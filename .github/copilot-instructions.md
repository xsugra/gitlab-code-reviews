# Copilot Instructions — GitLab Code Reviews Bot

## Project Overview

This is an automated merge request reviewer for GitLab. The bot:
- Receives webhook events from GitLab (MR open, reopen, update)
- Fetches the MR diff from GitLab API
- Runs an AI code review through a local Ollama model (single-pass or chunked for large diffs)
- Posts the review as an MR note
- Saves review history to SQLite
- Optionally notifies via Google Chat with rich formatting (Cards v2)

**Tech stack:** Python 3.12, FastAPI, Uvicorn, httpx (async), aiosqlite, Docker Compose

## Architecture

### Core Review Pipeline (`app/reviewer.py`)

The pipeline is orchestrated in `run_review()` with 5 phases:

1. **Fetch MR metadata** — Get title, description, author, URL from GitLab API
2. **Fetch diffs** — Get file diffs from GitLab, log file names and sizes
3. **Chunk & review** — Split diffs intelligently, send to Ollama:
   - If ≤ `MAX_CHUNK_CHARS`: single-pass review (one LLM call)
   - If > `MAX_CHUNK_CHARS`: review each chunk independently, then aggregate
4. **Save to DB** — Persist review metadata and findings
5. **Post results** — Post comment to GitLab MR + send Google Chat notification

### Diff Chunking Strategy (`split_diffs()`)

Large diffs are split to respect Ollama's context window:
- Split by file first
- If a single file is too large, split by hunk (`@@` markers)
- Each chunk is capped at `MAX_CHUNK_CHARS` (default 80,000 chars)
- If a chunk review returns `NO_FINDINGS`, it's skipped in aggregation

### LLM Integration (`app/llm_client.py`)

- Sends chat messages to Ollama API (`/api/chat` endpoint)
- Uses `OLLAMA_MODEL` (default: `qwen2.5-coder:14b`)
- Configurable context window, temperature, timeout

### Google Chat Notifications (`app/google_chat.py`)

Messages are sent as **Google Chat Cards (v2)** with:
- Header (project name)
- Clickable button linking to MR
- Review body with converted markdown → HTML (bold, italic, code, links, headers as bold, lists with bullets)
- Graceful truncation if summary exceeds 3500 chars

## Configuration & Deployment

### Environment Variables

All config via `.env` (copy from `.env.example`):

| Variable | Required | Default | Notes |
|---|---|---|---|
| `GITLAB_URL` | ✓ | — | Base URL of GitLab instance |
| `GITLAB_TOKEN` | ✓ | — | GitLab token with `api` scope |
| `GITLAB_WEBHOOK_SECRET` | — | empty | Validates webhook secret; leave empty to skip |
| `OLLAMA_URL` | — | `http://ollama:11434` | Docker-compose overrides this to `http://host.docker.internal:11434` |
| `OLLAMA_MODEL` | — | `qwen2.5-coder:14b` | Model name (pull manually on host before running) |
| `OLLAMA_NUM_CTX` | — | `32768` | LLM context window |
| `OLLAMA_TEMPERATURE` | — | `0.2` | Generation temperature (lower = deterministic) |
| `OLLAMA_TIMEOUT_S` | — | `1800` | LLM request timeout in seconds |
| `GOOGLE_CHAT_WEBHOOK_URL` | — | empty | Google Chat webhook URL; omit to disable notifications |
| `MAX_CHUNK_CHARS` | — | `80000` | Diff chunk size limit |
| `LOG_LEVEL` | — | `INFO` | Logging level |

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env with your GitLab token, instance URL, etc.

# Run service
uvicorn app.main:app --reload --port 8000

# Health check
curl http://localhost:8000/health
curl http://localhost:8000/health/full
```

### Docker Deployment

```bash
# Ensure Ollama is running on host
ollama pull qwen2.5-coder:14b

# Start service
docker compose up -d --build

# Health check
curl http://localhost:8888/health

# View logs
docker compose logs -f review-bot

# Stop service
docker compose down
```

Service runs on **container port 8000**, mapped to **host port 8888**.

## Code Conventions

### Async-First

All I/O (GitLab API, Ollama, database) is async using `httpx.AsyncClient` and `aiosqlite`. Use `await` throughout the pipeline.

### Configuration

Use `config._env()` helper for all environment variables:
```python
from . import config
url = config.GITLAB_URL  # raises RuntimeError if required and missing
```

Required vars should pass `required=True`. Defaults are applied automatically.

### Logging

Use structured logging with `%s` formatting (not f-strings in log calls):
```python
log.info("Processing MR !%s in project %s", mr_iid, project_name)
log.exception("Failed to fetch diffs")  # includes traceback
```

Log at 5 key stages: fetch → chunk → review → save → post. Use `[X/5]` markers for clarity.

### Error Handling

- Catch specific exceptions where possible (e.g., `httpx.HTTPStatusError`)
- Use `log.exception()` to include tracebacks
- Return gracefully rather than raising (webhook must not fail the GitLab webhook delivery)
- If a phase fails, log and return; don't attempt downstream phases

### Diff & Markdown Formatting

- Diffs are formatted as markdown code blocks with file paths as headers
- Review comments use markdown; Google Chat converts this to HTML (see `google_chat._parse_markdown_to_html()`)
- Prompts use f-string template injection (see `prompts.py`)

### Database

SQLite schema is managed in `db.py`. All queries are async. Review records are immutable after save (no updates).

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Liveness check (returns active model) |
| `/health/full` | GET | Deep health check (Ollama, GitLab, DB, Google Chat connectivity) |
| `/webhook` | POST | GitLab webhook receiver (MR events) |
| `/reviews` | GET | List stored reviews (query params: `project_id`, `mr_iid`, `limit`) |

## Git Flow

See `gitflow.md` for the branching strategy. In brief:
- `main`: production-ready (protected)
- `develop`: integration branch
- `feature/<name>` / `fix/<name>`: branch from `develop`, PR to `develop`
- `hotfix/<name>`: branch from `main`, PR to `main`, backport to `develop`

Commit messages follow Conventional Commits format: `type(scope): description`

## Common Tasks

### Adding a new LLM Provider

1. Create `app/new_provider_client.py` mirroring `llm_client.py` interface
2. Update `app/config.py` with new env vars
3. Modify `app/reviewer.py` to conditionally use provider based on config
4. Test with `/health/full` endpoint

### Modifying the Review Prompt

1. Edit `app/prompts.py` — change `SYSTEM_PROMPT`, `SINGLE_PASS_PROMPT`, `CHUNK_PROMPT`, or `SUMMARY_PROMPT`
2. Test locally: `curl http://localhost:8000/reviews` to inspect past reviews
3. Adjust chunking strategy if needed (see `split_diffs()` in `reviewer.py`)

### Adding a New Notification Channel

1. Create `app/new_channel.py` mirroring `google_chat.py` interface (async `send()` function)
2. Add config vars in `config.py`
3. Call from `run_review()` phase 5 (post results)
4. Add health check in `main.py` health endpoints

### Debugging a Failed Review

1. Check container logs: `docker compose logs -f review-bot`
2. Check `data/reviews.db` for stored reviews: `sqlite3 data/reviews.db "SELECT * FROM reviews ORDER BY created_at DESC LIMIT 1;"`
3. Cross-reference with GitLab webhook delivery logs (GitLab → project settings → webhooks)
4. Verify `.env` vars are set: `docker compose exec review-bot env | grep GITLAB`

## Testing

**No test suite currently exists in this repo.** When adding tests:
- Use `pytest` + `pytest-asyncio` for async tests
- Mock `httpx.AsyncClient` and `aiosqlite` to avoid external dependencies
- Test diff chunking with edge cases (binary files, large single-hunk changes)
- Test prompt injection (malicious MR titles/descriptions)

## Performance Considerations

- Diff chunking is I/O bound (GitLab API) and CPU bound (LLM inference)
- Large MRs (>1MB diff) may timeout; adjust `OLLAMA_TIMEOUT_S` if needed
- SQLite concurrent writes are serialized; for high volume, consider PostgreSQL
- Google Chat Card rendering is client-side (no performance impact on bot)

## References

- **GitLab API:** https://docs.gitlab.com/ee/api/
- **Ollama API:** https://github.com/ollama/ollama/blob/main/docs/api.md
- **Google Chat Webhook:** https://developers.google.com/chat/api/guides/message-formats/cards
- **FastAPI:** https://fastapi.tiangolo.com/
