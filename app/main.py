import logging
import os
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles

from . import config, db
from .admin import router as admin_router
from .reviewer import run_review

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("review-bot")


@asynccontextmanager
async def lifespan(application: FastAPI):
    log.info("=== Review Bot starting ===")
    log.info("GITLAB_URL = %s", config.GITLAB_URL)
    log.info("OLLAMA_URL = %s", config.OLLAMA_URL)
    log.info("OLLAMA_MODEL = %s", config.OLLAMA_MODEL)
    log.info("WEBHOOK_SECRET = %s", "set" if config.GITLAB_WEBHOOK_SECRET else "NOT set (accepting all)")
    log.info("MAX_CHUNK_CHARS = %s", config.MAX_CHUNK_CHARS)
    log.info("ADMIN_UI = %s", "enabled" if config.GITLAB_OAUTH_APP_ID else "disabled (set GITLAB_OAUTH_APP_ID to enable)")
    await db.init()
    log.info("=== Review Bot ready ===")
    yield
    log.info("=== Review Bot shutting down ===")


app = FastAPI(title="GitLab LLM Code Reviewer", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")
app.include_router(admin_router)


@app.get("/health")
async def health() -> dict:
    """Basic liveness check."""
    return {"ok": True, "model": config.OLLAMA_MODEL}


@app.get("/health/full")
async def health_full() -> dict:
    """Deep health check: verify Ollama, GitLab, and DB connectivity."""
    results: dict = {
        "model": config.OLLAMA_MODEL,
        "ollama": {"status": "unknown"},
        "gitlab": {"status": "unknown"},
        "db": {"status": "unknown"},
        "google_chat": {"status": "not configured"},
    }

    # Check Ollama
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{config.OLLAMA_URL}/api/tags")
            r.raise_for_status()
            models = [m["name"] for m in r.json().get("models", [])]
            model_found = any(config.OLLAMA_MODEL in m for m in models)
            results["ollama"] = {
                "status": "ok" if model_found else "warning",
                "url": config.OLLAMA_URL,
                "models_available": models,
                "target_model_loaded": model_found,
            }
            if not model_found:
                results["ollama"]["warning"] = f"Model '{config.OLLAMA_MODEL}' not found. Run: ollama pull {config.OLLAMA_MODEL}"
    except Exception as e:
        results["ollama"] = {"status": "error", "url": config.OLLAMA_URL, "error": str(e)}

    # Check GitLab
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                f"{config.GITLAB_URL.rstrip('/')}/api/v4/version",
                headers={"PRIVATE-TOKEN": config.GITLAB_TOKEN},
            )
            r.raise_for_status()
            results["gitlab"] = {"status": "ok", "url": config.GITLAB_URL, "version": r.json()}
    except httpx.HTTPStatusError as e:
        results["gitlab"] = {"status": "error", "url": config.GITLAB_URL, "http_code": e.response.status_code, "error": "Authentication failed — check GITLAB_TOKEN"}
    except Exception as e:
        results["gitlab"] = {"status": "error", "url": config.GITLAB_URL, "error": str(e)}

    # Check DB
    try:
        reviews = await db.get_reviews(limit=1)
        results["db"] = {"status": "ok", "path": db.DB_PATH, "total_reviews_sampled": len(reviews)}
    except Exception as e:
        results["db"] = {"status": "error", "path": db.DB_PATH, "error": str(e)}

    # Check Google Chat webhooks
    try:
        webhooks = await db.get_all_webhook_configs()
        active = sum(1 for w in webhooks if w.get("enabled"))
        results["google_chat"] = {
            "status": "configured" if active > 0 else "not configured",
            "webhooks_total": len(webhooks),
            "webhooks_active": active,
        }
    except Exception as e:
        results["google_chat"] = {"status": "error", "error": str(e)}

    all_ok = all(
        results[k].get("status") in ("ok", "configured", "not configured")
        for k in ("ollama", "gitlab", "db", "google_chat")
    )
    results["healthy"] = all_ok

    return results


@app.get("/reviews")
async def list_reviews(
    project_id: int | None = Query(default=None),
    mr_iid: int | None = Query(default=None),
    limit: int = Query(default=50, le=200),
) -> list[dict]:
    return await db.get_reviews(project_id=project_id, mr_iid=mr_iid, limit=limit)


@app.post("/webhook")
async def webhook(
    request: Request,
    background: BackgroundTasks,
    x_gitlab_token: str | None = Header(default=None),
    x_gitlab_event: str | None = Header(default=None),
) -> dict:
    log.info("Webhook received: event=%s", x_gitlab_event)

    if config.GITLAB_WEBHOOK_SECRET:
        if x_gitlab_token != config.GITLAB_WEBHOOK_SECRET:
            log.warning("Webhook rejected: invalid secret token")
            raise HTTPException(status_code=401, detail="invalid webhook token")

    payload = await request.json()

    if payload.get("object_kind") != "merge_request":
        log.info("Webhook ignored: object_kind=%s", payload.get("object_kind"))
        return {"ignored": f"object_kind={payload.get('object_kind')}"}

    attrs = payload.get("object_attributes") or {}
    action = attrs.get("action")

    if action in ("open", "reopen"):
        pass
    elif action == "update":
        if not attrs.get("oldrev"):
            log.info("Webhook ignored: MR update without new commits (label/assignee change)")
            return {"ignored": "update without new commits"}
    else:
        log.info("Webhook ignored: action=%s", action)
        return {"ignored": f"action={action}"}

    project = payload.get("project") or {}
    project_id = project.get("id")
    mr_iid = attrs.get("iid")
    mr_title = attrs.get("title", "")
    project_name = project.get("path_with_namespace") or project.get("name") or "unknown"
    author = (payload.get("user") or {}).get("username", "unknown")

    if not project_id or not mr_iid:
        log.error("Webhook rejected: missing project_id or mr_iid in payload")
        raise HTTPException(status_code=400, detail="missing project id or mr iid")

    log.info(
        ">>> Review queued: project=%s mr=!%s title='%s' action=%s author=%s",
        project_name, mr_iid, mr_title, action, author,
    )
    background.add_task(run_review, project_id, mr_iid, project_name)
    return {"queued": True, "project_id": project_id, "mr_iid": mr_iid}
