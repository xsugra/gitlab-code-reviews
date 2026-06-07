import json
import logging
import time

from .. import llm_client, prompts
from ..gitlab_client import GitLabClient
from ._common import notify_and_save

log = logging.getLogger(__name__)


def _parse_triage_response(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
    log.warning("  Could not parse LLM triage response as JSON")
    return None


async def handle_issue_triage(payload: dict) -> None:
    t_start = time.monotonic()
    attrs = payload.get("object_attributes") or {}
    action = attrs.get("action")

    if action != "open":
        log.info("Issue triage ignored: action=%s (only triaging new issues)", action)
        return

    project = payload.get("project") or {}
    project_id = project.get("id")
    project_name = project.get("path_with_namespace") or project.get("name") or "unknown"
    issue_iid = attrs.get("iid")
    title = attrs.get("title") or ""
    description = attrs.get("description") or ""

    if not project_id or not issue_iid:
        log.info("Issue triage ignored: missing project_id or issue_iid")
        return

    model = await llm_client.model_for_project(project_id)

    existing_labels = attrs.get("labels") or []
    if existing_labels:
        log.info("Issue #%s already has labels, skipping triage", issue_iid)
        return

    log.info("========== ISSUE TRIAGE START ==========")
    log.info("Project: %s | Issue: #%s | Title: %s", project_name, issue_iid, title)

    async with GitLabClient() as gl:
        try:
            available_labels = await gl.get_project_labels(project_id)
        except Exception:
            log.exception("  Failed to fetch project labels")
            available_labels = []

        labels_str = ", ".join(available_labels) if available_labels else "(no labels configured in project)"

        log.info("  Triaging with LLM...")
        t_llm = time.monotonic()
        try:
            response = await llm_client.chat([
                {"role": "system", "content": prompts.ISSUE_TRIAGE_SYSTEM},
                {"role": "user", "content": prompts.ISSUE_TRIAGE_PROMPT.format(
                    title=title,
                    description=description or "(no description)",
                    available_labels=labels_str,
                )},
            ], model=model)
        except Exception:
            log.exception("  LLM triage failed")
            return
        log.info("  LLM responded in %.1fs", time.monotonic() - t_llm)

        triage = _parse_triage_response(response)
        if not triage:
            log.warning("  Could not parse triage response, posting raw response as comment")
            try:
                await gl.post_issue_note(project_id, issue_iid,
                                         f"## Auto-Triage\n\n{response}\n\n---\n_Triaged by `{model}`._")
            except Exception:
                log.exception("  Failed to post issue comment")
            return

        labels_to_add = triage.get("labels", [])
        if isinstance(labels_to_add, list) and labels_to_add:
            valid_labels = [l for l in labels_to_add if l in available_labels]
            if valid_labels:
                try:
                    await gl.update_issue(project_id, issue_iid, add_labels=",".join(valid_labels))
                    log.info("  Applied labels: %s", valid_labels)
                except Exception:
                    log.exception("  Failed to apply labels")

        summary = triage.get("summary", "")
        issue_type = triage.get("type", "unknown")
        severity = triage.get("severity", "unknown")

        triage_comment = (
            f"## Auto-Triage\n\n"
            f"**Type:** {issue_type}\n"
            f"**Severity:** {severity}\n"
            f"**Summary:** {summary}\n\n"
            f"---\n"
            f"_Triaged by `{model}`._"
        )

        try:
            await gl.post_issue_note(project_id, issue_iid, triage_comment)
            log.info("  Posted triage comment on issue #%s", issue_iid)
        except Exception:
            log.exception("  Failed to post triage comment")

    issue_url = attrs.get("url") or ""
    await notify_and_save(
        event_type="issue_triage", project_id=project_id, project_name=project_name,
        title=f"Issue #{issue_iid} — {title}",
        url=issue_url, result_text=triage_comment, ref_id=str(issue_iid), model=model,
    )

    log.info("========== ISSUE TRIAGE DONE in %.1fs ==========", time.monotonic() - t_start)
