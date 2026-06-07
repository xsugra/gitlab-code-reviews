import logging

import httpx

from . import db, settings

log = logging.getLogger(__name__)


async def model_for_project(project_id: int) -> str:
    """Per-project model override if set on the webhook config, else the global default."""
    cfg = await db.get_webhook_config(project_id)
    return (cfg or {}).get("model") or settings.get("OLLAMA_MODEL")


async def chat(messages: list[dict], num_ctx: int | None = None, model: str | None = None) -> str:
    model = model or settings.get("OLLAMA_MODEL")
    ollama_url = settings.get("OLLAMA_URL")
    timeout_s = settings.get("OLLAMA_TIMEOUT_S")
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": settings.get("OLLAMA_TEMPERATURE"),
            "num_ctx": num_ctx or settings.get("OLLAMA_NUM_CTX"),
        },
    }
    log.debug("LLM request: model=%s, messages=%d, num_ctx=%s", model, len(messages),
              num_ctx or settings.get("OLLAMA_NUM_CTX"))
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as c:
            r = await c.post(f"{ollama_url}/api/chat", json=payload)
            r.raise_for_status()
            data = r.json()
    except httpx.ConnectError:
        log.error("Cannot connect to Ollama at %s — is it running?", ollama_url)
        raise
    except httpx.HTTPStatusError as e:
        log.error("Ollama returned HTTP %s: %s", e.response.status_code, e.response.text[:500])
        raise
    except httpx.ReadTimeout:
        log.error("Ollama request timed out after %ss — diff may be too large or model too slow",
                  timeout_s)
        raise

    content = data["message"]["content"].strip()
    tokens_eval = data.get("eval_count", "?")
    tokens_prompt = data.get("prompt_eval_count", "?")
    duration_s = data.get("total_duration", 0) / 1e9
    log.debug("LLM response: %s prompt tokens, %s eval tokens, %.1fs", tokens_prompt, tokens_eval, duration_s)
    return content
