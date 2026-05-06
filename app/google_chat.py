import logging

import httpx

from . import config

log = logging.getLogger(__name__)

# Google Chat text messages have a 4096 char limit; leave headroom for the header.
MAX_BODY_CHARS = 3500


async def send(summary: str, mr_title: str, mr_url: str, project_name: str) -> None:
    if not config.GOOGLE_CHAT_WEBHOOK_URL:
        log.info("Google Chat webhook not configured, skipping notification")
        return

    body = summary if len(summary) <= MAX_BODY_CHARS else summary[:MAX_BODY_CHARS] + "\n\n_(truncated)_"
    text = (
        f"*Code Review* — {project_name}\n"
        f"*<{mr_url}|{mr_title}>*\n\n"
        f"{body}"
    )

    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(config.GOOGLE_CHAT_WEBHOOK_URL, json={"text": text})
        r.raise_for_status()
