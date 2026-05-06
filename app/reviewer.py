import logging
import time

from . import config, db, google_chat, llm_client, prompts
from .gitlab_client import GitLabClient

log = logging.getLogger(__name__)


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


async def _review_chunk(title: str, diff_block: str) -> str:
    return await llm_client.chat(
        [
            {"role": "system", "content": prompts.SYSTEM_PROMPT},
            {"role": "user", "content": prompts.CHUNK_PROMPT.format(title=title, diff_block=diff_block)},
        ]
    )


async def _single_pass(title: str, description: str, diff_block: str) -> str:
    return await llm_client.chat(
        [
            {"role": "system", "content": prompts.SYSTEM_PROMPT},
            {
                "role": "user",
                "content": prompts.SINGLE_PASS_PROMPT.format(
                    title=title, description=description or "(none)", diff_block=diff_block
                ),
            },
        ]
    )


async def _summarize(title: str, description: str, findings: list[str]) -> str:
    joined = "\n\n---\n\n".join(f"Chunk {i + 1}:\n{f}" for i, f in enumerate(findings))
    return await llm_client.chat(
        [
            {"role": "system", "content": prompts.SYSTEM_PROMPT},
            {
                "role": "user",
                "content": prompts.SUMMARY_PROMPT.format(
                    title=title,
                    description=description or "(none)",
                    n_chunks=len(findings),
                    findings=joined,
                ),
            },
        ]
    )


async def run_review(project_id: int, mr_iid: int, project_name: str) -> None:
    t_start = time.monotonic()
    log.info("========== REVIEW START ==========")
    log.info("Project: %s (id=%s) | MR: !%s", project_name, project_id, mr_iid)

    gl = GitLabClient()

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

    if not diffs:
        log.info("  No diffs found, nothing to review. Done.")
        return

    title = mr.get("title") or f"MR !{mr_iid}"
    description = mr.get("description") or ""
    web_url = mr.get("web_url") or ""

    # --- Chunk and review ---
    chunks = split_diffs(diffs, config.MAX_CHUNK_CHARS)
    log.info("[3/5] Reviewing with LLM (%s)...", config.OLLAMA_MODEL)
    log.info("  Split into %d chunk(s)", len(chunks))

    try:
        if len(chunks) == 1:
            log.info("  Single-pass review (1 chunk)...")
            t_llm = time.monotonic()
            summary = await _single_pass(title, description, chunks[0])
            log.info("  LLM responded in %.1fs", time.monotonic() - t_llm)
        else:
            findings: list[str] = []
            for i, chunk in enumerate(chunks, start=1):
                log.info("  Reviewing chunk %d/%d (%d chars)...", i, len(chunks), len(chunk))
                t_llm = time.monotonic()
                content = await _review_chunk(title, chunk)
                elapsed = time.monotonic() - t_llm
                if content.strip().upper() != "NO_FINDINGS":
                    findings.append(content)
                    log.info("  Chunk %d done in %.1fs — findings detected", i, elapsed)
                else:
                    log.info("  Chunk %d done in %.1fs — no findings", i, elapsed)
            if not findings:
                summary = "**Overall:** No issues found.\n\n**Verdict:** Looks good."
                log.info("  No findings in any chunk.")
            else:
                log.info("  Aggregating %d chunk findings into summary...", len(findings))
                t_llm = time.monotonic()
                summary = await _summarize(title, description, findings)
                log.info("  Summary generated in %.1fs", time.monotonic() - t_llm)
    except Exception:
        log.exception("[3/5] FAILED — LLM review error")
        return

    log.info("  Review text length: %d chars", len(summary))

    # --- Save to DB ---
    log.info("[4/5] Saving review to database...")
    try:
        review_id = await db.save_review(
            project_id=project_id,
            project_name=project_name,
            mr_iid=mr_iid,
            mr_title=title,
            mr_url=web_url,
            model=config.OLLAMA_MODEL,
            chunks_count=len(chunks),
            review_text=summary,
        )
        log.info("  Saved as review id=%s", review_id)
    except Exception:
        log.exception("[4/5] FAILED to save review to DB")

    # --- Post to GitLab + Google Chat ---
    comment = (
        f"## Automated Code Review\n\n"
        f"{summary}\n\n"
        f"---\n"
        f"_Reviewed by `{config.OLLAMA_MODEL}` across {len(chunks)} chunk(s)._"
    )

    log.info("[5/5] Posting results...")
    try:
        await gl.post_note(project_id, mr_iid, comment)
        log.info("  Posted comment to GitLab MR !%s", mr_iid)
    except Exception:
        log.exception("  FAILED to post comment to GitLab")

    try:
        await google_chat.send(summary, title, web_url, project_name)
        if config.GOOGLE_CHAT_WEBHOOK_URL:
            log.info("  Sent notification to Google Chat")
    except Exception:
        log.exception("  FAILED to send Google Chat notification")

    elapsed_total = time.monotonic() - t_start
    log.info("========== REVIEW DONE in %.1fs ==========", elapsed_total)
