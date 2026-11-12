import fnmatch
import logging
import time
from datetime import datetime, timezone

from . import db, findings as fnd, google_chat, llm_client, prompts, settings
from .gitlab_client import GitLabClient

log = logging.getLogger(__name__)

# Hidden marker that identifies the bot's single review comment on an MR.
REVIEW_NOTE_MARKER = "<!-- code-review-bot:mr-review -->"
LEGACY_REVIEW_HEADER = "## Automated Code Review"
MAX_DESCRIPTION_CHARS = 1500


def _split_diff_by_hunks(diff_text: str) -> list[str]:
    if "@@" not in diff_text:
        return [diff_text]
    parts: list[str] = []
    current: list[str] = []
    for line in diff_text.split("\n"):
        if line.startswith("@@") and current:
            parts.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        parts.append("\n".join(current))
    return parts


def _format_file_block(path: str, diff_text: str) -> str:
    return f"### {path}\n```diff\n{diff_text}\n```\n"


def filter_ignored_diffs(diffs: list[dict], patterns: str) -> list[dict]:
    if not patterns.strip():
        return diffs
    rules = [p.strip() for p in patterns.splitlines() if p.strip() and not p.strip().startswith("#")]
    return [d for d in diffs if
            not any(fnmatch.fnmatch(d.get("new_path") or d.get("old_path") or "", rule) for rule in rules)]


def split_diffs(diffs: list[dict], max_chars: int) -> list[str]:
    chunks: list[str] = []
    current_parts: list[str] = []
    current_size = 0

    def flush() -> None:
        nonlocal current_parts, current_size
        if current_parts:
            chunks.append("".join(current_parts))
            current_parts = []
            current_size = 0

    for d in diffs:
        path = d.get("new_path") or d.get("old_path") or "<unknown>"
        diff_text = d.get("diff") or ""
        if not diff_text.strip():
            continue
        block = _format_file_block(path, diff_text)
        if len(block) <= max_chars:
            if current_size + len(block) > max_chars:
                flush()
            current_parts.append(block)
            current_size += len(block)
            continue

        flush()
        hunks = _split_diff_by_hunks(diff_text)
        sub_parts: list[str] = []
        sub_size = 0
        header = f"### {path} (part {{i}})\n```diff\n"
        footer = "\n```\n"
        part_idx = 1
        for h in hunks:
            piece = h + "\n"
            if sub_size + len(piece) + len(header) + len(footer) > max_chars and sub_parts:
                chunks.append(header.format(i=part_idx) + "".join(sub_parts) + footer)
                part_idx += 1
                sub_parts = []
                sub_size = 0
            sub_parts.append(piece)
            sub_size += len(piece)
        if sub_parts:
            chunks.append(header.format(i=part_idx) + "".join(sub_parts) + footer)

    flush()
    return chunks


async def _llm_findings(title: str, description: str, diff_block: str, model: str) -> list[fnd.Finding]:
    raw = await llm_client.chat(
        [
            {"role": "system", "content": prompts.REVIEW_SYSTEM},
            {"role": "user", "content": prompts.REVIEW_PROMPT.format(
                title=title,
                description=(description or "(none)")[:MAX_DESCRIPTION_CHARS],
                diff_block=diff_block,
            )},
        ],
        model=model,
        json_mode=True,
    )
    return fnd.parse_findings(raw)


async def _confirmed(finding: fnd.Finding, diffs: list[dict], model: str) -> bool:
    """Second, skeptical LLM pass. Keeps the finding if the answer can't be parsed."""
    try:
        raw = await llm_client.chat(
            [
                {"role": "system", "content": prompts.VERIFY_SYSTEM},
                {"role": "user", "content": prompts.VERIFY_PROMPT.format(
                    file=finding.file,
                    diff=fnd.file_diff_context(diffs, finding),
                    quote=finding.quote,
                    issue=finding.issue,
                )},
            ],
            model=model,
            json_mode=True,
        )
    except Exception:
        log.exception("    verify call failed, keeping finding %s:%s", finding.file, finding.line)
        return True
    is_real, reason = fnd.parse_verdict(raw)
    if is_real is False:
        log.info("    drop (verifier: %s): %s:%s — %s", reason or "false positive",
                 finding.file, finding.line, finding.issue[:80])
        return False
    return True


async def review_diffs(diffs: list[dict], title: str, description: str, model: str) -> tuple[list[fnd.Finding], int]:
    """Review a set of GitLab diff entries. Returns (confirmed findings, number of chunks)."""
    chunks = split_diffs(diffs, settings.get("MAX_CHUNK_CHARS"))
    if not chunks:
        return [], 0

    proposed: list[fnd.Finding] = []
    for i, chunk in enumerate(chunks, start=1):
        log.info("  Reviewing chunk %d/%d (%d chars)...", i, len(chunks), len(chunk))
        t_llm = time.monotonic()
        chunk_findings = await _llm_findings(title, description, chunk, model)
        log.info("  Chunk %d done in %.1fs — %d finding(s) proposed", i, time.monotonic() - t_llm,
                 len(chunk_findings))
        proposed.extend(chunk_findings)

    grounded = fnd.ground(proposed, fnd.index_added_lines(diffs), settings.get("REVIEW_MIN_CONFIDENCE"))
    ranked = fnd.dedupe_and_rank(grounded)
    max_findings = settings.get("REVIEW_MAX_FINDINGS")

    if settings.get("REVIEW_VERIFY") == "on" and ranked:
        # Verify at most 2x the cap so a noisy model can't trigger dozens of extra calls.
        candidates = ranked[:max_findings * 2]
        log.info("  Double-checking %d finding(s)...", len(candidates))
        confirmed = [f for f in candidates if await _confirmed(f, diffs, model)]
    else:
        confirmed = ranked

    result = confirmed[:max_findings]
    log.info("  Findings: %d proposed → %d grounded in diff → %d reported",
             len(proposed), len(grounded), len(result))
    return result, len(chunks)


async def _find_review_note(gl: GitLabClient, project_id: int, mr_iid: int) -> dict | None:
    """The bot's existing review comment on this MR, if any."""
    me = await gl.get_current_user()
    for note in await gl.list_mr_notes(project_id, mr_iid):
        if note.get("system") or (note.get("author") or {}).get("id") != me.get("id"):
            continue
        body = note.get("body") or ""
        if REVIEW_NOTE_MARKER in body or body.startswith(LEGACY_REVIEW_HEADER):
            return note
    return None


async def _publish_mr_review(gl: GitLabClient, project_id: int, mr_iid: int, comment: str,
                             has_findings: bool) -> None:
    """Keep a single bot comment per MR. New comments email every participant, edits don't."""
    if not settings.gitlab_comments("mr_review"):
        log.info("  GitLab comment skipped (GITLAB_COMMENTS=%s)", settings.get("GITLAB_COMMENTS"))
        return

    existing = None
    try:
        existing = await _find_review_note(gl, project_id, mr_iid)
    except Exception:
        log.exception("  Could not look up an existing review comment")

    if existing:
        try:
            await gl.update_note(project_id, mr_iid, existing["id"], comment)
            log.info("  Updated existing review comment (note %s) on MR !%s", existing["id"], mr_iid)
            return
        except Exception:
            log.exception("  Failed to update review comment %s, posting a new one", existing["id"])

    if not has_findings:
        log.info("  No findings and no earlier comment — not posting to GitLab (avoids an email)")
        return
    await gl.post_note(project_id, mr_iid, comment)
    log.info("  Posted review comment to GitLab MR !%s", mr_iid)


async def run_review(project_id: int, mr_iid: int, project_name: str) -> None:
    t_start = time.monotonic()
    log.info("========== REVIEW START ==========")
    log.info("Project: %s (id=%s) | MR: !%s", project_name, project_id, mr_iid)

    async with GitLabClient() as gl:
        # --- Fetch MR metadata ---
        log.info("[1/5] Fetching MR metadata from GitLab...")
        try:
            mr = await gl.get_mr(project_id, mr_iid)
            log.info("  MR title: '%s'", mr.get("title"))
            log.info("  MR author: %s", mr.get("author", {}).get("username", "unknown"))
            log.info("  MR state: %s", mr.get("state"))
            log.info("  MR URL: %s", mr.get("web_url"))
        except Exception:
            log.exception("[1/5] FAILED to fetch MR metadata from GitLab")
            return

        # --- Fetch diffs ---
        log.info("[2/5] Fetching diffs from GitLab...")
        try:
            diffs = await gl.get_diffs(project_id, mr_iid)
            log.info("  Files changed: %d", len(diffs))
            total_diff_chars = sum(len(d.get("diff") or "") for d in diffs)
            log.info("  Total diff size: %d chars (~%d tokens)", total_diff_chars, total_diff_chars // 4)
            for d in diffs:
                path = d.get("new_path") or d.get("old_path") or "?"
                size = len(d.get("diff") or "")
                log.info("    %s (%d chars)", path, size)
        except Exception:
            log.exception("[2/5] FAILED to fetch diffs from GitLab")
            return

        webhook_config = await db.get_webhook_config(project_id)
        diffs = filter_ignored_diffs(diffs, (webhook_config or {}).get("ignore_patterns", ""))
        if not diffs:
            log.info("  No diffs to review (empty or all ignored). Done.")
            return

        title = mr.get("title") or f"MR !{mr_iid}"
        description = mr.get("description") or ""
        web_url = mr.get("web_url") or ""
        head_sha = (mr.get("sha") or "")[:8]

        # --- Review ---
        model = (webhook_config or {}).get("model") or settings.get("OLLAMA_MODEL")
        log.info("[3/5] Reviewing with LLM (%s)...", model)
        try:
            findings, chunks_count = await review_diffs(diffs, title, description, model)
        except Exception:
            log.exception("[3/5] FAILED — LLM review error")
            return
        summary = fnd.render_markdown(findings)

        # --- Save to DB ---
        log.info("[4/5] Saving review to database...")
        try:
            review_id = await db.save_review(
                project_id=project_id,
                project_name=project_name,
                mr_iid=mr_iid,
                mr_title=title,
                mr_url=web_url,
                model=model,
                chunks_count=chunks_count,
                review_text=summary,
            )
            log.info("  Saved as review id=%s", review_id)
        except Exception:
            log.exception("[4/5] FAILED to save review to DB")

        # --- Post to GitLab ---
        reviewed_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        comment = (
            f"{REVIEW_NOTE_MARKER}\n"
            f"{LEGACY_REVIEW_HEADER}\n\n"
            f"{summary}\n\n"
            f"---\n"
            f"_Reviewed by `{model}` at commit `{head_sha}` · {reviewed_at}. "
            f"This comment is updated on every push._"
        )
        log.info("[5/5] Posting results...")
        try:
            await _publish_mr_review(gl, project_id, mr_iid, comment, has_findings=bool(findings))
        except Exception:
            log.exception("  FAILED to post comment to GitLab")

    try:
        webhook_config = await db.get_webhook_config(project_id)
        if webhook_config and webhook_config.get("enabled"):
            await google_chat.send(summary, title, web_url, project_name, webhook_url=webhook_config["webhook_url"])
            log.info("  Sent notification to Google Chat for %s", project_name)
        else:
            log.info("  No webhook configured for project %s, skipping chat notification", project_name)
    except Exception:
        log.exception("  FAILED to send Google Chat notification")

    elapsed_total = time.monotonic() - t_start
    log.info("========== REVIEW DONE in %.1fs ==========", elapsed_total)
