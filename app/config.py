import os


def _env(name: str, default: str | None = None, required: bool = False) -> str:
    val = os.getenv(name, default)
    if required and not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val or ""


# Bootstrap-only config: values needed before the DB/admin UI exist.
# Everything else (GitLab, Ollama, review behaviour) lives in the DB and is
# editable from the admin UI — see app/settings.py.

LOG_LEVEL = _env("LOG_LEVEL", "INFO")

# Admin UI auth: a single shared password gates the dashboard; the session
# secret signs the login cookie. Both must be set for the UI to be enabled.
SESSION_SECRET = _env("SESSION_SECRET")
ADMIN_PASSWORD = _env("ADMIN_PASSWORD")
