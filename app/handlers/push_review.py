import logging
import time

from .. import config, llm_client, prompts
from ..gitlab_client import GitLabClient
from ..reviewer import split_diffs
from ._common import notify_and_save

log = logging.getLogger(__name__)


def _format_commit_block(commit: dict, diffs: list[dict]) -> str:
    sha = commit.get("id", "")[:8]
    message = commit.get("message") or commit.get("title") or ""
    chunks = split_diffs(diffs, config.MAX_CHUNK_CHARS)
    diff_text = "\n\n".join(chunks) if chunks else "(no diff)"
    return f"#### Commit `{sha}`: {message.strip()}\n{diff_text}"


async def handle_push(payload: dict) -> None:
    t_start = time.monotonic()
    project = payload.get("project") or {}
    project_id = project.get("id")
    project_name = project.get("path_with_namespace") or project.get("name") or "unknown"
    ref = payload.get("ref", "")
    branch = ref.replace("refs/heads/", "")
    commits = payload.get("commits") or []
    user = payload.get("user_name") or payload.get("user_username") or "unknown"

    if not project_id or not commits:
        log.info("Push ignored: no project_id or no commits")
        return

    log.info("========== PUSH REVIEW START ==========")
    log.info("Project: %s | Branch: %s | Commits: %d | By: %s", project_name, branch, len(commits), user)

    async with GitLabClient() as gl:
        commit_blocks: list[str] = []
        for c in commits:
            sha = c.get("id", "")
            log.info("  Fetching diff for commit %s...", sha[:8])
            try:
                diffs = await gl.get_commit_diff(project_id, sha)
                commit_blocks.append(_format_commit_block(c, diffs))
            except Exception:
                log.exception("  Failed to fetch diff for commit %s", sha[:8])
                commit_blocks.append(f"#### Commit `{sha[:8]}`: {c.get('title', '?')}\n(diff unavailable)")

        commits_block = "\n\n---\n\n".join(commit_blocks)

        log.info("  Reviewing %d commit(s) with LLM...", len(commits))
        t_llm = time.monotonic()
        try:
            review = await llm_client.chat([
                {"role": "system", "content": prompts.PUSH_REVIEW_SYSTEM},
                {"role": "user", "content": prompts.PUSH_REVIEW_PROMPT.format(
                    branch=branch, commits_block=commits_block,
                )},
            ])
        except Exception:
            log.exception("  LLM review failed")
            return
        log.info("  LLM responded in %.1fs", time.monotonic() - t_llm)

        comment = (
            f"## Push Review — `{branch}`\n\n"
            f"{review}\n\n"
            f"---\n"
            f"_Reviewed by `{config.OLLAMA_MODEL}` — {len(commits)} commit(s)._"
        )

        last_sha = commits[-1].get("id", "")
        if last_sha:
            try:
                await gl.post_commit_comment(project_id, last_sha, comment)
                log.info("  Posted review comment on commit %s", last_sha[:8])
            except Exception:
                log.exception("  Failed to post commit comment")

    ref_url = commits[-1].get("url", "")
    await notify_and_save(
        event_type="push_review", project_id=project_id, project_name=project_name,
        title=f"Push to {branch} ({len(commits)} commit(s))",
        url=ref_url, result_text=review, ref_id=last_sha[:8],
    )

    log.info("========== PUSH REVIEW DONE in %.1fs ==========", time.monotonic() - t_start)
