import logging
import time

from .. import llm_client, prompts
from ..gitlab_client import GitLabClient
from ._common import notify_and_save

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
    user = (payload.get("user") or {}).get("username") or "unknown"
    deployable_id = payload.get("deployable_id")

    if not project_id:
        log.info("Deployment ignored: missing project_id")
        return

    model = await llm_client.model_for_project(project_id)

    log.info("========== DEPLOYMENT ANALYSIS START ==========")
    log.info("Project: %s | Env: %s | Status: %s | Ref: %s | Commit: %s",
             project_name, environment, status, ref, short_sha)

    async with GitLabClient() as gl:
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
            ], model=model)
        except Exception:
            log.exception("  LLM analysis failed")
            return
        log.info("  LLM responded in %.1fs", time.monotonic() - t_llm)

        comment = (
            f"## Deployment Report — `{environment}`\n\n"
            f"{analysis}\n\n"
            f"---\n"
            f"_Analyzed by `{model}`._"
        )

        if short_sha:
            try:
                await gl.post_commit_comment(project_id, short_sha, comment)
                log.info("  Posted deployment report on commit %s", short_sha)
            except Exception:
                log.exception("  Failed to post commit comment")

    deployable_url = payload.get("deployable_url") or ""
    status_label = "Failed" if status == "failed" else "Success"
    await notify_and_save(
        event_type="deployment_analysis", project_id=project_id, project_name=project_name,
        title=f"Deploy to {environment} — {status_label}",
        url=deployable_url, result_text=analysis,
        ref_id=str(deployment_id or short_sha or "unknown"), model=model,
    )

    log.info("========== DEPLOYMENT ANALYSIS DONE in %.1fs ==========", time.monotonic() - t_start)
