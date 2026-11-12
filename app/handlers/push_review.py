import logging
import time

from .. import db, findings as fnd, settings
from ..gitlab_client import GitLabClient
from ..reviewer import filter_ignored_diffs, review_diffs
from ._common import notify_and_save

log = logging.getLogger(__name__)

NULL_SHA = "0" * 40


async def _push_diffs(gl: GitLabClient, project_id: int, payload: dict, commits: list[dict]) -> list[dict]:
    """Net diff of the push; per-commit diffs when the branch is new (no `before`)."""
    before, after = payload.get("before") or "", payload.get("after") or ""
    if before and before != NULL_SHA and after and after != NULL_SHA:
        return (await gl.compare(project_id, before, after)).get("diffs") or []

    diffs: list[dict] = []
    for c in commits:
        sha = c.get("id", "")
        try:
            diffs.extend(await gl.get_commit_diff(project_id, sha))
        except Exception:
            log.exception("  Failed to fetch diff for commit %s", sha[:8])
    return diffs


async def handle_push(payload: dict) -> None:
    t_start = time.monotonic()
    project = payload.get("project") or {}
    project_id = project.get("id")
    project_name = project.get("path_with_namespace") or project.get("name") or "unknown"
    branch = payload.get("ref", "").replace("refs/heads/", "")
    commits = payload.get("commits") or []
    user = payload.get("user_name") or payload.get("user_username") or "unknown"

    if not project_id or not commits:
        log.info("Push ignored: no project_id or no commits")
        return

    async with GitLabClient() as gl:
        # A push to a branch with an open MR is already reviewed by the MR review
        # (merge_request "update" webhook). Reviewing it here too doubled the work
        # and the notifications.
        try:
            open_mr = await gl.find_open_mr_for_branch(project_id, branch)
        except Exception:
            log.exception("  Could not check for an open MR on %s, reviewing the push anyway", branch)
            open_mr = None
        if open_mr:
            log.info("Push review skipped: %s has open MR !%s, the MR review covers it",
                     branch, open_mr.get("iid"))
            return

        log.info("========== PUSH REVIEW START ==========")
        log.info("Project: %s | Branch: %s | Commits: %d | By: %s", project_name, branch, len(commits), user)

        webhook_config = await db.get_webhook_config(project_id)
        model = (webhook_config or {}).get("model") or settings.get("OLLAMA_MODEL")
        try:
            diffs = await _push_diffs(gl, project_id, payload, commits)
        except Exception:
            log.exception("  Failed to fetch push diff")
            return
        diffs = filter_ignored_diffs(diffs, (webhook_config or {}).get("ignore_patterns", ""))
        if not diffs:
            log.info("  No diffs to review (empty or all ignored). Done.")
            return

        commit_messages = "\n".join(f"- {(c.get('title') or c.get('message') or '').strip()}" for c in commits)
        try:
            findings, _ = await review_diffs(diffs, f"Push to {branch}", commit_messages, model)
        except Exception:
            log.exception("  LLM review failed")
            return
        review = fnd.render_markdown(findings)

        last_sha = commits[-1].get("id", "")
        if settings.gitlab_comments("other") and last_sha:
            comment = (
                f"## Push Review — `{branch}`\n\n"
                f"{review}\n\n"
                f"---\n"
                f"_Reviewed by `{model}` — {len(commits)} commit(s)._"
            )
            try:
                await gl.post_commit_comment(project_id, last_sha, comment)
                log.info("  Posted review comment on commit %s", last_sha[:8])
            except Exception:
                log.exception("  Failed to post commit comment")
        else:
            log.info("  GitLab commit comment skipped (GITLAB_COMMENTS=%s)", settings.get("GITLAB_COMMENTS"))

    await notify_and_save(
        event_type="push_review", project_id=project_id, project_name=project_name,
        title=f"Push to {branch} ({len(commits)} commit(s))",
        url=commits[-1].get("url", ""), result_text=review, ref_id=last_sha[:8], model=model,
    )

    log.info("========== PUSH REVIEW DONE in %.1fs ==========", time.monotonic() - t_start)
