"""Runtime configuration backed by the database.

Unlike `config.py` (bootstrap-only env vars read once at import), these settings
live in the `app_settings` table and are editable from the admin UI. Values are
cached in memory and refreshed on save, so changes apply live without a restart.
"""
import logging
import os

from . import db

log = logging.getLogger(__name__)

# Each field: key, label, group, type, default, input kind, help text (inline guide).
SETTINGS_SCHEMA: list[dict] = [
    # ── GitLab ───────────────────────────────────────────────────
    {
        "key": "GITLAB_URL", "label": "GitLab URL", "group": "GitLab",
        "type": "str", "default": "", "input": "text",
        "help": "Base URL of your GitLab instance, e.g. https://gitlab.example.com. "
                "Inside Docker use http://host.docker.internal:<port> to reach GitLab on the host.",
    },
    {
        "key": "GITLAB_TOKEN", "label": "GitLab Access Token", "group": "GitLab",
        "type": "str", "default": "", "input": "password",
        "help": "GitLab → User Settings → Access Tokens → create one with the `api` scope. "
                "Personal Access Tokens start with `glpat-`.",
    },
    {
        "key": "GITLAB_WEBHOOK_SECRET", "label": "Webhook Secret", "group": "GitLab",
        "type": "str", "default": "", "input": "password",
        "help": "Optional. If set, it must match the \"Secret Token\" on the GitLab webhook "
                "(Project → Settings → Webhooks). Leave empty to accept all webhook calls.",
    },
    # ── Ollama / LLM ─────────────────────────────────────────────
    {
        "key": "OLLAMA_URL", "label": "Ollama URL", "group": "Ollama",
        "type": "str", "default": "http://host.docker.internal:11434", "input": "text",
        "help": "Where Ollama is reachable. Inside Docker that is usually "
                "http://host.docker.internal:11434.",
    },
    {
        "key": "OLLAMA_MODEL", "label": "Model", "group": "Ollama",
        "type": "str", "default": "qwen2.5-coder:14b-instruct-q8_0", "input": "select",
        "help": "Pick an installed model, or type a custom name. Pull new ones with "
                "`docker compose exec ollama ollama pull <model>`.",
    },
    {
        "key": "OLLAMA_NUM_CTX", "label": "Context window (tokens)", "group": "Ollama",
        "type": "int", "default": 32768, "input": "number",
        "help": "Match the model's context size. Coder models typically support 32768.",
    },
    {
        "key": "OLLAMA_TEMPERATURE", "label": "Temperature", "group": "Ollama",
        "type": "float", "default": 0.2, "input": "number",
        "help": "Lower = more deterministic. 0.2 is a good default for code review.",
    },
    {
        "key": "OLLAMA_TIMEOUT_S", "label": "Request timeout (seconds)", "group": "Ollama",
        "type": "int", "default": 1800, "input": "number",
        "help": "Per-request timeout to Ollama. Large diffs on CPU can take a long time.",
    },
    # ── Review behaviour ─────────────────────────────────────────
    {
        "key": "MAX_CHUNK_CHARS", "label": "Max chunk size (chars)", "group": "Review",
        "type": "int", "default": 80000, "input": "number",
        "help": "Max characters per LLM input chunk (~4 chars/token). 80000 ≈ 20k tokens of diff.",
    },
    {
        "key": "REVIEW_RETRIGGER_EMOJI", "label": "Re-trigger emoji", "group": "Review",
        "type": "str", "default": "repeat", "input": "text",
        "help": "GitLab emoji name (no colons) that re-triggers a review when added to an MR. "
                "e.g. `repeat` = 🔄. Requires \"Emoji events\" enabled on the webhook.",
    },
]

_BY_KEY: dict[str, dict] = {f["key"]: f for f in SETTINGS_SCHEMA}

_cache: dict[str, str] = {}


def _coerce(field: dict, raw: str):
    """Convert a stored string into the field's typed value, falling back to default."""
    if raw is None or raw == "":
        return field["default"]
    try:
        if field["type"] == "int":
            return int(raw)
        if field["type"] == "float":
            return float(raw)
    except (TypeError, ValueError):
        return field["default"]
    return raw


async def load() -> None:
    """Refresh the in-memory cache from the database."""
    global _cache
    _cache = await db.get_all_settings()
    log.info("Settings loaded (%d keys from DB)", len(_cache))


def get(key: str):
    """Return the typed value for a setting (DB value, else schema default)."""
    field = _BY_KEY[key]
    return _coerce(field, _cache.get(key, ""))


def get_raw(key: str) -> str:
    """Return the raw string value (for pre-filling form fields)."""
    field = _BY_KEY[key]
    raw = _cache.get(key, "")
    if raw == "" and field["default"] != "":
        return str(field["default"])
    return raw


async def save(values: dict[str, str]) -> None:
    """Persist settings and reload the cache so changes apply immediately."""
    clean = {k: v for k, v in values.items() if k in _BY_KEY}
    await db.set_settings(clean)
    await load()


async def seed_from_env_if_empty() -> None:
    """First boot / migration: copy current env values into the DB so an existing
    deployment keeps working. After this the DB owns the settings."""
    existing = await db.get_all_settings()
    if existing:
        return
    seed = {f["key"]: os.getenv(f["key"], str(f["default"])) for f in SETTINGS_SCHEMA}
    await db.set_settings(seed)
    log.info("Seeded %d settings from environment into DB", len(seed))
