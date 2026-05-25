import logging
import time

from .. import config, llm_client, prompts
from ..gitlab_client import GitLabClient
from ._common import notify_and_save

log = logging.getLogger(__name__)

MAX_LOG_CHARS_PER_JOB = 15000


async def handle_pipeline(payload: dict) -> None:
    t_start = time.monotonic()
    attrs = payload.get("object_attributes") or {}
    status = attrs.get("status")

    if status != "failed":
        log.info("Pipeline ignored: status=%s (only analyzing failures)", status)
        return

    project = payload.get("project") or {}
    project_id = project.get("id")
    project_name = project.get("path_with_namespace") or project.get("name") or "unknown"
    pipeline_id = attrs.get("id")
    ref = attrs.get("ref", "unknown")
    mr_info = payload.get("merge_request")

    if not project_id or not pipeline_id:
        log.info("Pipeline ignored: missing project_id or pipeline_id")
        return

    log.info("========== PIPELINE ANALYSIS START ==========")
    log.info("Project: %s | Pipeline: #%s | Ref: %s | Status: %s", project_name, pipeline_id, ref, status)

    async with GitLabClient() as gl:
        builds = payload.get("builds") or []
        failed_jobs = [b for b in builds if b.get("status") == "failed"]

        if not failed_jobs:
            try:
                all_jobs = await gl.get_pipeline_jobs(project_id, pipeline_id)
                failed_jobs = [j for j in all_jobs if j.get("status") == "failed"]
            except Exception:
                log.exception("  Failed to fetch pipeline jobs")
                return

        if not failed_jobs:
            log.info("  No failed jobs found, nothing to analyze")
            return

        log.info("  Found %d failed job(s), fetching logs...", len(failed_jobs))

        jobs_block_parts: list[str] = []
        for job in failed_jobs:
            job_id = job.get("id")
            job_name = job.get("name", "unknown")
            stage = job.get("stage", "unknown")
            log.info("    Fetching log for job '%s' (id=%s, stage=%s)...", job_name, job_id, stage)
            try:
                job_log = await gl.get_job_log(project_id, job_id, tail_chars=MAX_LOG_CHARS_PER_JOB)
            except Exception:
                log.exception("    Failed to fetch log for job %s", job_id)
                job_log = "(log unavailable)"

            jobs_block_parts.append(
                f"### Job: `{job_name}` (stage: `{stage}`, id: {job_id})\n"
                f"```\n{job_log}\n```"
            )

        jobs_block = "\n\n".join(jobs_block_parts)

        log.info("  Analyzing with LLM...")
        t_llm = time.monotonic()
        try:
            analysis = await llm_client.chat([
                {"role": "system", "content": prompts.PIPELINE_ANALYSIS_SYSTEM},
                {"role": "user", "content": prompts.PIPELINE_ANALYSIS_PROMPT.format(
                    project_name=project_name,
                    ref=ref,
                    pipeline_id=pipeline_id,
                    jobs_block=jobs_block,
                )},
            ])
        except Exception:
            log.exception("  LLM analysis failed")
            return
        log.info("  LLM responded in %.1fs", time.monotonic() - t_llm)

        comment = (
            f"## Pipeline Failure Analysis — #{pipeline_id}\n\n"
            f"{analysis}\n\n"
            f"---\n"
            f"_Analyzed by `{config.OLLAMA_MODEL}`._"
        )

        if mr_info and mr_info.get("iid"):
            try:
                await gl.post_note(project_id, mr_info["iid"], comment)
                log.info("  Posted analysis to MR !%s", mr_info["iid"])
            except Exception:
                log.exception("  Failed to post analysis to MR")
        else:
            sha = attrs.get("sha", "")
            if sha:
                try:
                    await gl.post_commit_comment(project_id, sha, comment)
                    log.info("  Posted analysis on commit %s", sha[:8])
                except Exception:
                    log.exception("  Failed to post commit comment")

    pipeline_url = f"{(project.get('web_url') or '')}/pipelines/{pipeline_id}"
    await notify_and_save(
        event_type="pipeline_analysis", project_id=project_id, project_name=project_name,
        title=f"Pipeline #{pipeline_id} failed on {ref}",
        url=pipeline_url, result_text=analysis, ref_id=str(pipeline_id),
    )

    log.info("========== PIPELINE ANALYSIS DONE in %.1fs ==========", time.monotonic() - t_start)
