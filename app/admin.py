import base64
import hashlib
import hmac
import html as html_mod
import json
import logging
import os
import re
import secrets
import time

import httpx
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from . import config, db, google_chat

log = logging.getLogger(__name__)

router = APIRouter(prefix="/code-review-bot")
templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates")
)


def _md_to_html(text: str) -> Markup:
    lines = text.splitlines()
    out: list[str] = []
    in_code = False
    code_buf: list[str] = []

    for raw in lines:
        stripped = raw.strip()

        if stripped.startswith("```"):
            if in_code:
                out.append(
                    '<pre style="background:var(--pico-card-background-color);padding:0.75rem;border-radius:var(--pico-border-radius);overflow-x:auto;font-size:0.85rem">'
                    + html_mod.escape("\n".join(code_buf)) + "</pre>")
                code_buf = []
                in_code = False
            else:
                in_code = True
            continue

        if in_code:
            code_buf.append(raw)
            continue

        if not stripped:
            out.append("")
            continue

        line = html_mod.escape(stripped)
        line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
        line = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", line)
        line = re.sub(r"`([^`]+)`", r"<code>\1</code>", line)

        hm = re.match(r"^#{1,6}\s+(.+)$", stripped)
        if hm:
            line = f"<strong>{html_mod.escape(hm.group(1))}</strong>"
            line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)

        bm = re.match(r"^[*\-]\s+(.+)$", stripped)
        if bm:
            content = html_mod.escape(bm.group(1))
            content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", content)
            content = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", content)
            content = re.sub(r"`([^`]+)`", r"<code>\1</code>", content)
            line = f"&bull; {content}"

        out.append(line)

    if in_code and code_buf:
        out.append(
            '<pre style="background:var(--pico-card-background-color);padding:0.75rem;border-radius:var(--pico-border-radius);overflow-x:auto;font-size:0.85rem">'
            + html_mod.escape("\n".join(code_buf)) + "</pre>")

    return Markup("<br>".join(out))


templates.env.filters["md"] = _md_to_html

SESSION_COOKIE = "session"
SESSION_MAX_AGE = 28800


def _admin_enabled() -> bool:
    return bool(
        config.GITLAB_OAUTH_APP_ID
        and config.GITLAB_OAUTH_APP_SECRET
        and config.SESSION_SECRET
        and config.ADMIN_BASE_URL
    )


def _sign(payload: bytes) -> str:
    return hmac.new(
        config.SESSION_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()


def _create_session(data: dict) -> str:
    data["exp"] = int(time.time()) + SESSION_MAX_AGE
    if "csrf" not in data:
        data["csrf"] = secrets.token_hex(32)
    payload = base64.urlsafe_b64encode(json.dumps(data).encode())
    sig = _sign(payload)
    return payload.decode() + "." + sig


def _verify_session(token: str) -> dict | None:
    if "." not in token:
        return None
    payload_b64, sig = token.rsplit(".", 1)
    expected = _sign(payload_b64.encode())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:
        return None
    if data.get("exp", 0) < time.time():
        return None
    return data


def _get_session(request: Request) -> dict | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return _verify_session(token)


def _require_session(request: Request) -> dict:
    session = _get_session(request)
    if not session:
        raise _redirect_login()
    return session


def _redirect_login():
    return HTTPException(
        status_code=303,
        headers={"Location": "/code-review-bot/login"},
    )


def _validate_csrf(request_token: str, session: dict) -> None:
    if not hmac.compare_digest(request_token, session.get("csrf", "")):
        raise HTTPException(status_code=403, detail="CSRF validation failed")


def _mask_url(url: str) -> str:
    if len(url) <= 35:
        return url
    return url[:20] + "..." + url[-12:]


def _oauth_authorize_url(state: str) -> str:
    base = config.GITLAB_OAUTH_BASE_URL.rstrip("/")
    redirect_uri = f"{config.ADMIN_BASE_URL.rstrip('/')}/code-review-bot/callback"
    return (
        f"{base}/oauth/authorize"
        f"?client_id={config.GITLAB_OAUTH_APP_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope=read_user"
        f"&state={state}"
    )


async def _exchange_code(code: str) -> dict:
    base = config.GITLAB_URL.rstrip("/")
    redirect_uri = f"{config.ADMIN_BASE_URL.rstrip('/')}/code-review-bot/callback"
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            f"{base}/oauth/token",
            data={
                "client_id": config.GITLAB_OAUTH_APP_ID,
                "client_secret": config.GITLAB_OAUTH_APP_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
        r.raise_for_status()
        return r.json()


async def _get_gitlab_user(access_token: str) -> dict:
    base = config.GITLAB_URL.rstrip("/")
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            f"{base}/api/v4/user",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        r.raise_for_status()
        return r.json()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if not _admin_enabled():
        raise HTTPException(
            status_code=503,
            detail="Admin UI is not configured. Set GITLAB_OAUTH_APP_ID, GITLAB_OAUTH_APP_SECRET, SESSION_SECRET, and ADMIN_BASE_URL.",
        )
    session = _get_session(request)
    if session:
        return RedirectResponse("/code-review-bot/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/callback")
async def oauth_callback(request: Request, code: str = "", state: str = "", error: str = "",
                         error_description: str = ""):
    if error:
        log.warning("OAuth error from GitLab: %s — %s", error, error_description)
        raise HTTPException(status_code=400, detail=f"GitLab OAuth error: {error} — {error_description}")
    if not code:
        params = dict(request.query_params)
        log.warning("OAuth callback without code. Query params: %s", params)
        raise HTTPException(status_code=400, detail=f"Missing authorization code. GitLab returned: {params}")

    expected_state = request.cookies.get("oauth_state", "")
    if not state or not expected_state or not hmac.compare_digest(state, expected_state):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    try:
        token_data = await _exchange_code(code)
        access_token = token_data["access_token"]
        user = await _get_gitlab_user(access_token)
    except httpx.HTTPStatusError:
        log.exception("OAuth token exchange failed")
        raise HTTPException(status_code=401, detail="GitLab authentication failed")
    except Exception:
        log.exception("OAuth callback error")
        raise HTTPException(status_code=500, detail="Authentication error")

    session_data = {
        "username": user.get("username", "unknown"),
        "name": user.get("name", ""),
        "avatar_url": user.get("avatar_url", ""),
    }
    session_token = _create_session(session_data)

    response = RedirectResponse("/code-review-bot/", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie("oauth_state")
    log.info("User '%s' logged in", session_data["username"])
    return response


@router.get("/start-oauth")
async def start_oauth(request: Request):
    state = secrets.token_hex(32)
    url = _oauth_authorize_url(state)
    log.info("OAuth redirect URL: %s", url)
    response = RedirectResponse(url, status_code=303)
    response.set_cookie("oauth_state", state, max_age=600, httponly=True, samesite="lax")
    return response


@router.post("/logout")
async def logout():
    response = RedirectResponse("/code-review-bot/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    session = _require_session(request)

    reviews = await db.get_reviews(limit=10)
    webhooks = await db.get_all_webhook_configs()

    health = {"status": "unknown"}
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get("http://127.0.0.1:8000/health/full")
            if r.status_code == 200:
                health = r.json()
    except Exception:
        health = {"healthy": False, "error": "Could not reach health endpoint"}

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "session": session,
        "reviews": reviews,
        "webhooks": webhooks,
        "health": health,
        "model": config.OLLAMA_MODEL,
    })


@router.get("/webhooks", response_class=HTMLResponse)
async def list_webhooks(request: Request):
    session = _require_session(request)
    configs = await db.get_all_webhook_configs()
    return templates.TemplateResponse("webhooks/list.html", {
        "request": request,
        "session": session,
        "configs": configs,
        "mask_url": _mask_url,
    })


@router.get("/webhooks/new", response_class=HTMLResponse)
async def new_webhook_form(request: Request):
    session = _require_session(request)
    return templates.TemplateResponse("webhooks/form.html", {
        "request": request,
        "session": session,
        "config": None,
        "error": None,
    })


@router.post("/webhooks", response_class=HTMLResponse)
async def create_webhook(
        request: Request,
        project_id: int = Form(...),
        project_name: str = Form(""),
        webhook_url: str = Form(...),
        enabled: bool = Form(False),
        csrf_token: str = Form(...),
):
    session = _require_session(request)
    _validate_csrf(csrf_token, session)

    if project_id < 1:
        return templates.TemplateResponse("webhooks/form.html", {
            "request": request,
            "session": session,
            "config": None,
            "error": "Project ID must be a positive integer.",
        })

    if not webhook_url.startswith("https://"):
        return templates.TemplateResponse("webhooks/form.html", {
            "request": request,
            "session": session,
            "config": None,
            "error": "Webhook URL must start with https://",
        })

    existing = await db.get_webhook_config(project_id)
    if existing:
        return templates.TemplateResponse("webhooks/form.html", {
            "request": request,
            "session": session,
            "config": None,
            "error": f"A webhook is already configured for project ID {project_id}. Edit it instead.",
        })

    await db.save_webhook_config(project_id, project_name, webhook_url, enabled)
    log.info("Webhook config created for project %s by %s", project_id, session.get("username"))
    return RedirectResponse("/code-review-bot/webhooks", status_code=303)


@router.get("/webhooks/{config_id:int}/edit", response_class=HTMLResponse)
async def edit_webhook_form(request: Request, config_id: int):
    session = _require_session(request)
    cfg = await db.get_webhook_config_by_id(config_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Webhook config not found")
    return templates.TemplateResponse("webhooks/form.html", {
        "request": request,
        "session": session,
        "config": cfg,
        "error": None,
    })


@router.post("/webhooks/{config_id:int}", response_class=HTMLResponse)
async def update_webhook(
        request: Request,
        config_id: int,
        project_name: str = Form(""),
        webhook_url: str = Form(...),
        enabled: bool = Form(False),
        csrf_token: str = Form(...),
):
    session = _require_session(request)
    _validate_csrf(csrf_token, session)

    cfg = await db.get_webhook_config_by_id(config_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Webhook config not found")

    if not webhook_url.startswith("https://"):
        return templates.TemplateResponse("webhooks/form.html", {
            "request": request,
            "session": session,
            "config": cfg,
            "error": "Webhook URL must start with https://",
        })

    await db.update_webhook_config(
        config_id,
        project_name=project_name,
        webhook_url=webhook_url,
        enabled=enabled,
    )
    log.info("Webhook config %s updated by %s", config_id, session.get("username"))
    return RedirectResponse("/code-review-bot/webhooks", status_code=303)


@router.post("/webhooks/{config_id:int}/delete")
async def delete_webhook(
        request: Request,
        config_id: int,
        csrf_token: str = Form(...),
):
    session = _require_session(request)
    _validate_csrf(csrf_token, session)
    await db.delete_webhook_config(config_id)
    log.info("Webhook config %s deleted by %s", config_id, session.get("username"))
    return RedirectResponse("/code-review-bot/webhooks", status_code=303)


@router.post("/webhooks/{config_id:int}/toggle")
async def toggle_webhook(
        request: Request,
        config_id: int,
        csrf_token: str = Form(...),
):
    session = _require_session(request)
    _validate_csrf(csrf_token, session)
    cfg = await db.get_webhook_config_by_id(config_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Webhook config not found")
    await db.update_webhook_config(config_id, enabled=not cfg["enabled"])
    log.info("Webhook config %s toggled by %s", config_id, session.get("username"))
    return RedirectResponse("/code-review-bot/webhooks", status_code=303)


@router.post("/webhooks/{config_id:int}/test")
async def test_webhook(
        request: Request,
        config_id: int,
        csrf_token: str = Form(...),
):
    session = _require_session(request)
    _validate_csrf(csrf_token, session)
    cfg = await db.get_webhook_config_by_id(config_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Webhook config not found")

    try:
        ok = await google_chat.send_test(cfg["webhook_url"], cfg.get("project_name", "Test"))
    except Exception:
        log.exception("Webhook test failed for config %s", config_id)
        ok = False

    configs = await db.get_all_webhook_configs()
    return templates.TemplateResponse("webhooks/list.html", {
        "request": request,
        "session": session,
        "configs": configs,
        "mask_url": _mask_url,
        "flash": "Test message sent successfully!" if ok else "Test failed. Check the webhook URL.",
        "flash_type": "success" if ok else "error",
    })


@router.get("/reviews", response_class=HTMLResponse)
async def reviews_page(request: Request):
    session = _require_session(request)
    project_id = request.query_params.get("project_id")
    mr_iid = request.query_params.get("mr_iid")

    kwargs: dict = {"limit": 100}
    if project_id:
        try:
            kwargs["project_id"] = int(project_id)
        except ValueError:
            pass
    if mr_iid:
        try:
            kwargs["mr_iid"] = int(mr_iid)
        except ValueError:
            pass

    reviews = await db.get_reviews(**kwargs)
    return templates.TemplateResponse("reviews.html", {
        "request": request,
        "session": session,
        "reviews": reviews,
        "filter_project_id": project_id or "",
        "filter_mr_iid": mr_iid or "",
    })


@router.get("/health", response_class=HTMLResponse)
async def health_page(request: Request):
    session = _require_session(request)

    health = {}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("http://127.0.0.1:8000/health/full")
            if r.status_code == 200:
                health = r.json()
    except Exception:
        health = {"healthy": False, "error": "Could not reach health endpoint"}

    webhook_count = len(await db.get_all_webhook_configs())

    return templates.TemplateResponse("health.html", {
        "request": request,
        "session": session,
        "health": health,
        "webhook_count": webhook_count,
    })

def _get_session(request: Request) -> dict | None:
    token = request.cookies.get("session")
    if not token:
        return None
    return _verify_session(token)