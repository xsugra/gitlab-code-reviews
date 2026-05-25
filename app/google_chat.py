import html
import logging
import re

import httpx

log = logging.getLogger(__name__)

# Google Chat cards have a 4096 char limit per text widget; leave headroom.
MAX_BODY_CHARS = 3500
SECTION_ORDER = ("overall", "blocking", "suggested", "nits", "verdict")
CARD_ORDER = ("blocking", "overall", "suggested", "nits", "verdict")
SECTION_META = {
    "overall": {"title": "Overall", "icon": "✨"},
    "blocking": {"title": "Blocking", "icon": "⚠️"},
    "suggested": {"title": "Suggested", "icon": "🟡"},
    "nits": {"title": "Nits", "icon": "⚪3"},
    "verdict": {"title": "Verdict", "icon": "✅"},
}


def _escape(text: str) -> str:
    return html.escape(text, quote=False)


def _format_inline(text: str) -> str:
    """Convert the small Markdown subset used by the bot into safe HTML."""
    if not text:
        return ""

    text = _escape(text)

    def link_repl(match: re.Match[str]) -> str:
        label = match.group(1)
        url = html.escape(html.unescape(match.group(2)), quote=True)
        return f'<a href="{url}">{label}</a>'

    text = re.sub(r"\[([^]]+)\]\(([^)]+)\)", link_repl, text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"`([^`]+)`", r'<font color="#5f6368">\1</font>', text)
    return text


def _render_code_block(lines: list[str]) -> str:
    escaped_lines = [_escape(line) for line in lines]
    return '<font color="#5f6368">' + "<br>".join(escaped_lines) + "</font>"


def _render_review_section(text: str) -> str:
    lines = text.splitlines()
    rendered: list[str] = []
    code_block: list[str] = []
    in_code_block = False

    def flush_code_block() -> None:
        nonlocal code_block
        if code_block:
            rendered.append(_render_code_block(code_block))
            code_block = []

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code_block:
                flush_code_block()
                in_code_block = False
            else:
                in_code_block = True
            continue

        if in_code_block:
            code_block.append(raw_line)
            continue

        if not stripped:
            rendered.append("")
            continue

        bullet_match = re.match(r"^([*-])\s+(.*)$", stripped)
        if bullet_match:
            indent = len(line) - len(line.lstrip(" "))
            depth = max(0, indent // 2)
            bullet = "•" if depth == 0 else "◦"
            rendered.append(f"{'&nbsp;' * (depth * 2)}{bullet} {_format_inline(bullet_match.group(2))}")
            continue

        header_match = re.match(r"^#{1,6}\s+(.+)$", stripped)
        if header_match:
            rendered.append(f"<b>{_format_inline(header_match.group(1))}</b>")
            continue

        rendered.append(_format_inline(stripped))

    if in_code_block:
        flush_code_block()

    compacted: list[str] = []
    previous_blank = False
    for item in rendered:
        is_blank = item == ""
        if is_blank and previous_blank:
            continue
        compacted.append(item)
        previous_blank = is_blank

    return "<br>".join(compacted).strip()


def _split_review_sections(summary: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {name: [] for name in SECTION_ORDER}
    current = "overall"

    for raw_line in summary.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        match = re.match(r"^\*\*(Overall|Blocking|Suggested|Nits|Verdict):\*\*\s*(.*)$", stripped)
        if match:
            current = match.group(1).lower()
            tail = match.group(2).strip()
            if tail:
                sections[current].append(tail)
            continue

        sections[current].append(line)

    return {name: "\n".join(lines).strip() for name, lines in sections.items() if any(l.strip() for l in lines)}


def _build_button_widget(mr_title: str, mr_url: str) -> dict:
    return {
        "buttonList": {
            "buttons": [
                {
                    "text": mr_title,
                    "onClick": {
                        "openLink": {
                            "url": mr_url,
                        }
                    },
                }
            ]
        }
    }


def _build_card(section_name: str, body_html: str, project_name: str, mr_title: str, mr_url: str) -> dict:
    meta = SECTION_META[section_name]
    header_title = f"{meta['icon']} {meta['title']}"
    if section_name == "overall":
        header_title = f"{meta['icon']} Code Review — {project_name}"

    widgets = []
    if section_name == "overall":
        widgets.append(_build_button_widget(mr_title, mr_url))
    widgets.append({"textParagraph": {"text": body_html}})

    return {
        "cardId": f"code-review-{section_name}",
        "card": {
            "header": {
                "title": header_title,
                "subtitle": mr_title if section_name != "overall" else "GitLab Merge Request Review",
            },
            "sections": [{"widgets": widgets}],
        },
    }


def _truncate_with_formatting(text: str, max_chars: int) -> str:
    """Truncate text while preserving markdown/HTML structure."""
    if len(text) <= max_chars:
        return text

    truncated = text[:max_chars]
    last_newline = truncated.rfind("\n")
    if last_newline > max_chars * 0.8:
        truncated = truncated[:last_newline]

    return truncated.rstrip() + "\n\n(review truncated)"


def _create_card_payload(summary: str, mr_title: str, mr_url: str, project_name: str) -> dict:
    """Create a Google Chat Card (v2 format) for rich formatting."""

    body = summary if len(summary) <= MAX_BODY_CHARS else _truncate_with_formatting(summary, MAX_BODY_CHARS)
    sections = _split_review_sections(body)

    cards: list[dict] = []
    for section_name in CARD_ORDER:
        section_text = sections.get(section_name)
        if not section_text:
            continue

        section_html = _render_review_section(section_text)
        if not section_html:
            continue

        cards.append(_build_card(section_name, section_html, project_name, mr_title, mr_url))

    if not cards:
        cards.append(_build_card("overall", _render_review_section(body), project_name, mr_title, mr_url))

    return {
        "cardsV2": [
            *cards
        ]
    }


async def send(summary: str, mr_title: str, mr_url: str, project_name: str, webhook_url: str) -> None:
    payload = _create_card_payload(summary, mr_title, mr_url, project_name)

    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(webhook_url, json=payload)
        r.raise_for_status()


EVENT_META = {
    "push_review": {"icon": "🔀", "title": "Push Review"},
    "pipeline_analysis": {"icon": "🔴", "title": "Pipeline Failure"},
    "mr_description": {"icon": "📝", "title": "MR Description Generated"},
    "issue_triage": {"icon": "🏷️", "title": "Issue Triaged"},
    "release_notes": {"icon": "🚀", "title": "Release Notes"},
    "deployment_analysis": {"icon": "📦", "title": "Deployment Report"},
}


def _create_event_card_payload(
        event_type: str, body: str, title: str, url: str, project_name: str,
) -> dict:
    meta = EVENT_META.get(event_type, {"icon": "ℹ️", "title": event_type})
    header_title = f"{meta['icon']} {meta['title']} — {project_name}"

    body = body if len(body) <= MAX_BODY_CHARS else _truncate_with_formatting(body, MAX_BODY_CHARS)
    body_html = _render_review_section(body)

    widgets = []
    if url:
        widgets.append(_build_button_widget(title, url))
    widgets.append({"textParagraph": {"text": body_html}})

    card = {
        "cardId": f"event-{event_type}",
        "card": {
            "header": {
                "title": header_title,
                "subtitle": title,
            },
            "sections": [{"widgets": widgets}],
        },
    }
    return {"cardsV2": [card]}


async def send_event(
        event_type: str, body: str, title: str, url: str,
        project_name: str, webhook_url: str,
) -> None:
    payload = _create_event_card_payload(event_type, body, title, url, project_name)
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(webhook_url, json=payload)
        r.raise_for_status()


async def send_test(webhook_url: str, project_name: str = "Test") -> bool:
    payload = {"text": f"Test notification from Code Review Bot for project: {project_name}"}
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(webhook_url, json=payload)
        return r.status_code == 200
