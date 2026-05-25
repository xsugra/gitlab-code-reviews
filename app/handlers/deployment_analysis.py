import logging
import time

from .. import config, db, google_chat, llm_client, prompts
from ..gitlab_client import GitLabClient

log = logging.getLogger(__name__)


async def handle_deployment(payload: dict) -> None:
    t_start = time.monotonic()
    status = payload.get("status")

    if status not in ("failed", "success"):
        log.info("Deployment ignored: status=%s (only analyzing failed/success)", status)
        return

    project = payload.get("project") or {}
    project_id = project.get("id")
    project_name = project.get("path_with_namespace") or project.get("name") or "unknown"
    deployment_id = payload.get("deployment_id")
    environment = payload.get("environment") or "unknown"
    ref = payload.get("ref") or "unknown"
    short_sha = payload.get("short_sha") or ""
    commit_title = payload.get("commit_title") or ""
    user = (payload.get("user") or {}).get("username") or payload.get("user_url") or "unknown"
    deployable_id = payload.get("deployable_id")

    if not project_id:
        log.info("Deployment ignored: missing project_id")
        return

    log.info("========== DEPLOYMENT ANALYSIS START ==========")
    log.info("Project: %s | Env: %s | Status: %s | Ref: %s | Commit: %s",
             project_name, environment, status, ref, short_sha)

    gl = GitLabClient()

    job_log_section = ""
    if status == "failed" and deployable_id:
        log.info("  Fetching deployment job log (job_id=%s)...", deployable_id)
        try:
            job_log = await gl.get_job_log(project_id, deployable_id, tail_chars=15000)
            job_log_section = f"Deployment job log (last lines):\n```\n{job_log}\n```"
        except Exception:
            log.exception("  Failed to fetch job log")
            job_log_section = "Deployment job log: (unavailable)"

    failure_instruction = ""
    if status == "failed":
        failure_instruction = "- **Root cause:** what went wrong.\n- **Fix:** concrete steps to resolve."

    log.info("  Analyzing deployment with LLM...")
    t_llm = time.monotonic()
    try:
        analysis = await llm_client.chat([
            {"role": "system", "content": prompts.DEPLOYMENT_ANALYSIS_SYSTEM},
            {"role": "user", "content": prompts.DEPLOYMENT_ANALYSIS_PROMPT.format(
                status=status,
                project_name=project_name,
                environment=environment,
                ref=ref,
                short_sha=short_sha,
                commit_title=commit_title,
                user=user,
                job_log_section=job_log_section,
                failure_instruction=failure_instruction,
            )},
        ])
    except Exception:
        log.exception("  LLM analysis failed")
        return
    log.info("  LLM responded in %.1fs", time.monotonic() - t_llm)

    comment = (
        f"## Deployment Report — `{environment}`\n\n"
        f"{analysis}\n\n"
        f"---\n"
        f"_Analyzed by `{config.OLLAMA_MODEL}`._"
    )

    if short_sha:
        try:
            await gl.post_commit_comment(project_id, short_sha, comment)
            log.info("  Posted deployment report on commit %s", short_sha)
        except Exception:
            log.exception("  Failed to post commit comment")

    deployable_url = payload.get("deployable_url") or ""

    try:
        webhook_config = await db.get_webhook_config(project_id)
        if webhook_config and webhook_config.get("enabled"):
            status_emoji = "Failed" if status == "failed" else "Success"
            await google_chat.send_event(
                event_type="deployment_analysis", body=analysis,
                title=f"Deploy to {environment} — {status_emoji}",
                url=deployable_url, project_name=project_name,
                webhook_url=webhook_config["webhook_url"],
            )
            log.info("  Sent Google Chat notification")
    except Exception:
        log.exception("  Failed to send Google Chat notification")

    try:
        await db.save_event(
            event_type="deployment_analysis",
            project_id=project_id,
            project_name=project_name,
            ref_id=str(deployment_id or short_sha),
            ref_url=deployable_url,
            model=config.OLLAMA_MODEL,
            result_text=analysis,
        )
    except Exception:
        log.exception("  Failed to save event to DB")

    log.info("========== DEPLOYMENT ANALYSIS DONE in %.1fs ==========", time.monotonic() - t_start)
