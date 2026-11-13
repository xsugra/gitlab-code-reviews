"""Structured review findings: parse the LLM's JSON, check it against the diff, render Markdown.

The model must quote the exact added line each finding is about. A finding whose quote
does not appear on a "+" line of the diff is dropped. This removes the most common
false alarms from small local models: invented code, complaints about removed or
unchanged lines, and guesses about code outside the diff.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)

SEVERITY_ORDER = {"blocking": 0, "suggested": 1}
CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}
MIN_QUOTE_CHARS = 4
MAX_QUOTE_RENDER_CHARS = 160

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass
class Finding:
    file: str
    quote: str
    issue: str
    fix: str = ""
    severity: str = "suggested"
    confidence: str = "low"
    line: int | None = None


@dataclass
class AddedLine:
    number: int
    norm: str


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


# ── Diff indexing ────────────────────────────────────────────────

def index_added_lines(diffs: list[dict]) -> dict[str, list[AddedLine]]:
    """Map file path -> added lines (with their line number in the new file)."""
    index: dict[str, list[AddedLine]] = {}
    for d in diffs:
        path = d.get("new_path") or d.get("old_path")
        if not path:
            continue
        added = index.setdefault(path, [])
        new_no = 0
        in_hunk = False
        for raw in (d.get("diff") or "").split("\n"):
            m = _HUNK_RE.match(raw)
            if m:
                new_no = int(m.group(1))
                in_hunk = True
                continue
            if not in_hunk or raw.startswith("\\"):  # file headers / "\ No newline at end of file"
                continue
            if raw.startswith("+"):
                added.append(AddedLine(new_no, _norm(raw[1:])))
                new_no += 1
            elif raw.startswith("-"):
                continue
            else:
                new_no += 1
    return index


def file_diff_context(diffs: list[dict], finding: Finding, max_chars: int = 16000) -> str:
    """The finding's file diff, or only the hunk containing the quote if the file is large."""
    for d in diffs:
        if (d.get("new_path") or d.get("old_path")) != finding.file:
            continue
        text = d.get("diff") or ""
        if len(text) <= max_chars:
            return text
        target = _norm(_clean_quote(finding.quote).split("\n")[0])
        for hunk in re.split(r"\n(?=@@ )", text):
            if target and target in _norm(hunk):
                return hunk[:max_chars]
        return text[:max_chars]
    return ""


# ── LLM output parsing ───────────────────────────────────────────

def _load_json(raw: str):
    raw = (raw or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    if fenced:
        raw = fenced.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            pass
    return None


def parse_findings(raw: str) -> list[Finding]:
    data = _load_json(raw)
    if data is None:
        log.warning("  LLM returned non-JSON review output, ignoring it: %r", (raw or "")[:300])
        return []
    items = data.get("findings") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []

    out: list[Finding] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        issue = str(item.get("issue") or "").strip()
        if not issue:
            continue
        severity = str(item.get("severity") or "").strip().lower()
        confidence = str(item.get("confidence") or "").strip().lower()
        out.append(Finding(
            file=str(item.get("file") or "").strip(),
            quote=str(item.get("quote") or "").strip(),
            issue=issue,
            fix=str(item.get("fix") or "").strip(),
            severity="blocking" if severity.startswith("block") else "suggested",
            confidence=confidence if confidence in CONFIDENCE_ORDER else "low",
        ))
    return out


def parse_verdict(raw: str) -> tuple[bool | None, str]:
    """(is_real, reason). is_real is None when the answer can't be parsed."""
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None, ""
    verdict = str(data.get("verdict") or "").strip().lower().replace(" ", "_")
    reason = str(data.get("reason") or "").strip()
    if verdict == "real":
        return True, reason
    if verdict in ("false_positive", "false"):
        return False, reason
    return None, reason


# ── Grounding against the diff ───────────────────────────────────

def _clean_quote(quote: str) -> str:
    lines = []
    for line in quote.strip().strip("`").split("\n"):
        line = line.rstrip()
        if line.startswith("+"):
            line = line[1:]
        lines.append(line)
    return "\n".join(lines)


def _locate(quote: str, added: list[AddedLine]) -> int | None:
    """Line number of the quote among the added lines, or None if it isn't there."""
    quote_lines = [_norm(l) for l in _clean_quote(quote).split("\n")]
    quote_lines = [l for l in quote_lines if len(l) >= MIN_QUOTE_CHARS]
    if not quote_lines:
        return None
    first_match = None
    for ql in quote_lines:
        match = next((al for al in added if ql in al.norm), None)
        if match is None:
            return None
        if first_match is None:
            first_match = match.number
    return first_match


def _resolve_file(name: str, index: dict[str, list[AddedLine]]) -> str | None:
    name = name.strip().strip("`")
    for prefix in ("a/", "b/", "./"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    if name in index:
        return name
    candidates = [p for p in index if p.endswith("/" + name) or name.endswith("/" + p)]
    return candidates[0] if len(candidates) == 1 else None


def ground(findings: list[Finding], index: dict[str, list[AddedLine]], min_confidence: str) -> list[Finding]:
    """Keep only findings that quote a real added line and meet the confidence threshold."""
    threshold = CONFIDENCE_ORDER.get(min_confidence, CONFIDENCE_ORDER["medium"])
    kept: list[Finding] = []
    for f in findings:
        if CONFIDENCE_ORDER[f.confidence] > threshold:
            log.info("    drop (confidence=%s): %s — %s", f.confidence, f.file, f.issue[:80])
            continue

        path = _resolve_file(f.file, index)
        line = _locate(f.quote, index[path]) if path else None
        if line is None:
            # The model may have named the wrong file; accept if the quote is in exactly one file.
            hits = [(p, _locate(f.quote, added)) for p, added in index.items()]
            hits = [(p, n) for p, n in hits if n is not None]
            if len(hits) == 1:
                path, line = hits[0]

        if path is None or line is None:
            log.info("    drop (quote not on an added line): %s %r — %s", f.file, f.quote[:60], f.issue[:80])
            continue

        f.file, f.line = path, line
        kept.append(f)
    return kept


def _rank(f: Finding) -> tuple[int, int]:
    return SEVERITY_ORDER[f.severity], CONFIDENCE_ORDER[f.confidence]


def dedupe_and_rank(findings: list[Finding]) -> list[Finding]:
    best: dict[tuple, Finding] = {}
    for f in findings:
        key = (f.file, f.line)
        if key not in best or _rank(f) < _rank(best[key]):
            best[key] = f
    return sorted(best.values(), key=lambda f: (*_rank(f), f.file, f.line or 0))


# ── Rendering ────────────────────────────────────────────────────

def _code(text: str) -> str:
    text = _norm(text)
    if len(text) > MAX_QUOTE_RENDER_CHARS:
        text = text[:MAX_QUOTE_RENDER_CHARS - 1] + "…"
    return f"`` {text} ``" if "`" in text else f"`{text}`"


def _render_item(f: Finding) -> str:
    first_quote_line = _clean_quote(f.quote).split("\n")[0]
    lines = [f"- **`{f.file}:{f.line}`** — {f.issue}", f"  {_code(first_quote_line)}"]
    if f.fix:
        lines.append(f"  *Fix:* {f.fix}")
    return "\n".join(lines)


def render_markdown(findings: list[Finding]) -> str:
    if not findings:
        return ("**Overall:** No issues found in the changed code.\n\n"
                "**Verdict:** Looks good to merge.")

    blocking = [f for f in findings if f.severity == "blocking"]
    suggested = [f for f in findings if f.severity == "suggested"]

    counts = []
    if blocking:
        counts.append(f"{len(blocking)} blocking issue{'s' if len(blocking) != 1 else ''}")
    if suggested:
        counts.append(f"{len(suggested)} suggestion{'s' if len(suggested) != 1 else ''}")

    parts = [f"**Overall:** Found {' and '.join(counts)}."]
    if blocking:
        parts.append("**Blocking:**\n" + "\n".join(_render_item(f) for f in blocking))
    if suggested:
        parts.append("**Suggested:**\n" + "\n".join(_render_item(f) for f in suggested))
    verdict = ("Changes requested — fix the blocking issues before merging." if blocking
               else "Good to merge; the suggestions are optional.")
    parts.append(f"**Verdict:** {verdict}")
    return "\n\n".join(parts)
