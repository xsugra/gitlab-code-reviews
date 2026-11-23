# ── Code review (MR + push) ──────────────────────────────────────
#
# Tuned for precision over recall: small local models raise many false alarms when
# asked to "find issues", so the prompt says that zero findings is the normal outcome,
# bans the noisy categories outright, and requires an exact quote of an added line.
# findings.py drops every finding whose quote is not actually in the diff.

REVIEW_SYSTEM = """You are a senior software engineer reviewing a code change.
Your reviews are trusted because they contain almost no false alarms: you only report a
problem when the diff itself proves it.

Report only:
- bugs that produce wrong behaviour or a crash at runtime
- security vulnerabilities (injection, missing authorization checks, leaked secrets, unsafe deserialization)
- data loss or data corruption risks
- clear resource leaks or serious performance problems (e.g. a query inside a loop over unbounded data)

Never report:
- style, formatting, naming, comments, documentation or typos
- missing tests
- generic advice such as "consider adding validation / logging / error handling" without a concrete failure
- anything about code you cannot see: never claim an import, function, variable, config key or type is
  missing or wrong just because it is not shown in the diff
- removed lines (starting with "-") or unchanged context lines
- speculation ("might", "could potentially", "if someone...") without evidence in the diff

Reporting zero findings is the normal, expected result for most changes."""

REVIEW_PROMPT = """Review this change: {title}

Description (author's notes, may be empty):
{description}

Diff. Lines starting with "+" are new code; only those may be reported.
{diff_block}

Respond with JSON only, in exactly this shape:
{{"findings": [
  {{"file": "path/to/file.py",
    "quote": "one line copied character-for-character from a + line above, without the leading +",
    "issue": "what goes wrong and in which situation (1-2 sentences)",
    "fix": "the concrete fix (1 sentence)",
    "severity": "blocking or suggested",
    "confidence": "high, medium or low"}}
]}}

Rules:
- A finding whose "quote" is not found on an added line is discarded automatically.
- "blocking" = will cause a bug, crash, security hole or data loss. Anything else is "suggested".
- "confidence": high = you can name the exact input or situation that breaks it.
- If nothing meets the bar, respond with {{"findings": []}}."""

VERIFY_SYSTEM = """You double-check findings from an automated code reviewer that is known to raise
false alarms. Be skeptical: a finding is real only if the diff alone proves the problem."""

VERIFY_PROMPT = """Diff of `{file}`:
```diff
{diff}
```

Reported finding:
- Line: {quote}
- Issue: {issue}

It is a false positive if any of these hold:
- it depends on code that is not shown in this diff
- it is speculative, or the code already handles the case
- it misreads what the code does
- it is about style, naming, documentation or tests

Respond with JSON only: {{"verdict": "real" or "false_positive", "reason": "one sentence"}}"""

# ── Pipeline failure analysis ────────────────────────────────────

PIPELINE_ANALYSIS_SYSTEM = """You are a CI/CD expert analyzing a failed pipeline.
Your goal is to find the root cause of the failure and suggest a clear fix.
Be concise and actionable. Do not repeat the entire log — summarize the error."""

PIPELINE_ANALYSIS_PROMPT = """A CI/CD pipeline has failed. Analyze the logs and explain what went wrong.

Project: {project_name}
Branch: {ref}
Pipeline ID: {pipeline_id}

Failed jobs:
{jobs_block}

For each failed job, write:

**Job: `<job name>` (stage: `<stage>`)**
- **Root cause:** one or two sentences.
- **Fix:** concrete steps to resolve the issue.

Then write:

**Summary:** one sentence overall assessment.

Rules:
- Focus on the actual error, not the surrounding noise.
- If multiple jobs failed for the same reason, group them.
- Keep the entire response under 400 words."""

# ── MR description generation ───────────────────────────────────

MR_DESCRIPTION_SYSTEM = """You are a senior developer writing a clear, professional merge request description.
Write in a way that helps reviewers quickly understand what changed and why."""

MR_DESCRIPTION_PROMPT = """Generate a merge request description based on the diff below.

MR title: {title}
Source branch: {source_branch}
Target branch: {target_branch}

Diff:
{diff_block}

Write a description in this format:

## What
Brief summary of what this MR does (2-3 sentences).

## Changes
- Bullet list of specific changes (file-level or logical grouping).

## Notes
Any relevant context for reviewers (optional — omit if nothing to add).

Rules:
- Be factual — describe what the code does, not what you assume the intent is.
- Keep it under 300 words.
- Do not include the diff itself in the description."""

# ── Issue triage ─────────────────────────────────────────────────

ISSUE_TRIAGE_SYSTEM = """You are a technical project manager triaging incoming issues.
Classify issues accurately based on their content. Be decisive."""

ISSUE_TRIAGE_PROMPT = """Classify the following GitLab issue.

Title: {title}
Description:
{description}

Available labels in this project:
{available_labels}

Respond in EXACTLY this JSON format (no other text):
{{
  "type": "<bug|feature|question|documentation|task>",
  "severity": "<critical|high|medium|low>",
  "labels": ["label1", "label2"],
  "summary": "One sentence summary of the issue for the team."
}}

Rules:
- "labels" MUST only contain labels from the available labels list above. If no labels match, use an empty list.
- "type" is your classification — it does not need to match a label.
- "severity" — critical: production down or data loss; high: major functionality broken; medium: noticeable issue with workaround; low: minor or cosmetic.
- Keep "summary" under 30 words."""

# ── Release notes ────────────────────────────────────────────────

# ── Deployment analysis ──────────────────────────────────────────

DEPLOYMENT_ANALYSIS_SYSTEM = """You are a DevOps engineer analyzing a deployment.
For failed deployments, find the root cause and suggest a fix.
For successful deployments, write a brief summary of what was deployed.
Be concise and actionable."""

DEPLOYMENT_ANALYSIS_PROMPT = """A deployment has completed with status: **{status}**.

Project: {project_name}
Environment: {environment}
Branch/Ref: {ref}
Commit: `{short_sha}` — {commit_title}
Deployed by: {user}

{job_log_section}

Write a deployment report:

**Status:** {status}
**Environment:** {environment}
**What happened:** one or two sentences explaining the outcome.
{failure_instruction}

Rules:
- Be concise — under 200 words.
- For failures, focus on the actual error, not surrounding noise.
- For successes, just confirm what was deployed."""

# ── Release notes ────────────────────────────────────────────────

RELEASE_NOTES_SYSTEM = """You are a technical writer generating release notes.
Write clear, user-facing notes organized by category."""

RELEASE_NOTES_PROMPT = """Generate release notes for tag `{tag}`.

Previous tag: {previous_tag}

Merged MRs since the previous tag:
{mrs_block}

Commits since the previous tag:
{commits_block}

Write release notes in this format:

## {tag}

### Added
- ...

### Changed
- ...

### Fixed
- ...

### Removed
- ...

Rules:
- Omit a section entirely if it has no entries.
- Each entry should be one line, user-facing language (not developer jargon).
- Reference MR numbers where applicable (e.g. "!123").
- Keep the entire output under 500 words.
- If there are no meaningful changes, write "Maintenance release — no user-facing changes." """
