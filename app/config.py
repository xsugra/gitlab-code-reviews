import os


def _env(name: str, default: str | None = None, required: bool = False) -> str:
    val = os.getenv(name, default)
    if required and not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val or ""


GITLAB_URL = _env("GITLAB_URL", required=True)
GITLAB_TOKEN = _env("GITLAB_TOKEN", required=True)
GITLAB_WEBHOOK_SECRET = _env("GITLAB_WEBHOOK_SECRET")

OLLAMA_URL = _env("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL = _env("OLLAMA_MODEL", "qwen2.5-coder:14b")
OLLAMA_NUM_CTX = int(_env("OLLAMA_NUM_CTX", "32768"))
OLLAMA_TEMPERATURE = float(_env("OLLAMA_TEMPERATURE", "0.2"))
OLLAMA_TIMEOUT_S = int(_env("OLLAMA_TIMEOUT_S", "1800"))

GOOGLE_CHAT_WEBHOOK_URL = _env("GOOGLE_CHAT_WEBHOOK_URL")

MAX_CHUNK_CHARS = int(_env("MAX_CHUNK_CHARS", "80000"))

LOG_LEVEL = _env("LOG_LEVEL", "INFO")
