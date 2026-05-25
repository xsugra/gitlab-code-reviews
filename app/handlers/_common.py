import logging

from .. import config, db, google_chat

log = logging.getLogger(__name__)


async def notify_and_save(
        *,
        event_type: str,
        project_id: int,
        project_name: str,
        title: str,
        url: str,
        result_text: str,
        ref_id: str,
) -> None:
    try:
        webhook_config = await db.get_webhook_config(project_id)
        if webhook_config and webhook_config.get("enabled"):
            await google_chat.send_event(
                event_type=event_type, body=result_text,
                title=title, url=url, project_name=project_name,
                webhook_url=webhook_config["webhook_url"],
            )
            log.info("  Sent Google Chat notification")
    except Exception:
        log.exception("  Failed to send Google Chat notification")

    try:
        await db.save_event(
            event_type=event_type,
            project_id=project_id,
            project_name=project_name,
            ref_id=ref_id,
            ref_url=url,
            model=config.OLLAMA_MODEL,
            result_text=result_text,
        )
    except Exception:
        log.exception("  Failed to save event to DB")
