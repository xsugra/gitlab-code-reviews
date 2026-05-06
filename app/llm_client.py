import logging

import httpx

from . import config

log = logging.getLogger(__name__)


async def chat(messages: list[dict], num_ctx: int | None = None) -> str:
    payload = {
        "model": config.OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": config.OLLAMA_TEMPERATURE,
            "num_ctx": num_ctx or config.OLLAMA_NUM_CTX,
        },
    }
    log.debug("LLM request: model=%s, messages=%d, num_ctx=%s", config.OLLAMA_MODEL, len(messages), num_ctx or config.OLLAMA_NUM_CTX)
    try:
        async with httpx.AsyncClient(timeout=config.OLLAMA_TIMEOUT_S) as c:
            r = await c.post(f"{config.OLLAMA_URL}/api/chat", json=payload)
            r.raise_for_status()
            data = r.json()
    except httpx.ConnectError:
        log.error("Cannot connect to Ollama at %s — is it running?", config.OLLAMA_URL)
        raise
    except httpx.HTTPStatusError as e:
        log.error("Ollama returned HTTP %s: %s", e.response.status_code, e.response.text[:500])
        raise
    except httpx.ReadTimeout:
        log.error("Ollama request timed out after %ss — diff may be too large or model too slow", config.OLLAMA_TIMEOUT_S)
        raise

    content = data["message"]["content"].strip()
    tokens_eval = data.get("eval_count", "?")
    tokens_prompt = data.get("prompt_eval_count", "?")
    duration_s = data.get("total_duration", 0) / 1e9
    log.debug("LLM response: %s prompt tokens, %s eval tokens, %.1fs", tokens_prompt, tokens_eval, duration_s)
    return content
