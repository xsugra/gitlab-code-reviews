# GitLab Code Reviews Bot

Automated merge request reviewer for GitLab, powered by a local Ollama model and exposed through a FastAPI webhook service.

## What this project does

- Receives GitLab merge request webhook events (`open`, `reopen`, and `update` with new commits).
- Fetches MR metadata and diffs from GitLab API.
- Runs AI code review through Ollama (single-pass or chunked for large diffs).
- Posts the review back as an MR note.
- Stores review history in SQLite.
- Optionally sends a summary to Google Chat.

## Technical stack

- **Python** 3.12 (Docker image: `python:3.12-slim`)
- **FastAPI** + **Uvicorn**
- **HTTP client**: `httpx`
- **Database**: SQLite (`aiosqlite`)
- **Container runtime**: Docker Compose

## Repository layout

```text
app/
  main.py           # FastAPI app + webhook and health endpoints
  reviewer.py       # Review pipeline orchestration
  gitlab_client.py  # GitLab API calls
  llm_client.py     # Ollama chat calls
  google_chat.py    # Optional Google Chat notifications
  db.py             # SQLite schema and persistence
data/
  reviews.db        # Persistent SQLite DB (mounted volume)
backup.sh           # SQLite backup + retention script
docker-compose.yml  # Runtime configuration
```

## Configuration

Copy `.env.example` to `.env` and set values:

```bash
cp .env.example .env
```

| Variable | Required | Default | Purpose |
|---|---:|---|---|
| `GITLAB_URL` | Yes | — | Base URL of your GitLab instance |
| `GITLAB_TOKEN` | Yes | — | GitLab token with `api` scope |
| `GITLAB_WEBHOOK_SECRET` | No | empty | Validates `X-Gitlab-Token` |
| `OLLAMA_URL` | No | `http://ollama:11434` | Ollama API URL |
| `OLLAMA_MODEL` | No | `qwen2.5-coder:14b` | Review model name |
| `OLLAMA_NUM_CTX` | No | `32768` | Context window |
| `OLLAMA_TEMPERATURE` | No | `0.2` | Generation temperature |
| `OLLAMA_TIMEOUT_S` | No | `1800` | LLM request timeout |
| `GOOGLE_CHAT_WEBHOOK_URL` | No | empty | Google Chat notification webhook |
| `MAX_CHUNK_CHARS` | No | `80000` | Diff chunk size limit |
| `DB_PATH` | No | `/data/reviews.db` | SQLite DB path |
| `LOG_LEVEL` | No | `INFO` | Logging level |

> In `docker-compose.yml`, `OLLAMA_URL` is set to `http://host.docker.internal:11434` so the container can use Ollama running on your host machine.

## Run with Docker (recommended)

1. Ensure Ollama is running on your host and pull the configured model:
   ```bash
   ollama pull qwen2.5-coder:14b
   ```
2. Start the service:
   ```bash
   docker compose up -d --build
   ```
3. Check health:
   ```bash
   curl http://localhost:8888/health
   curl http://localhost:8888/health/full
   ```

Service mapping: **host `:8888` -> container `:8000`**.

## Webhook setup (GitLab)

In your GitLab project:

- **URL**: `http://<your-host>:8888/webhook`
- **Trigger**: Merge request events
- **Secret token**: set if you define `GITLAB_WEBHOOK_SECRET`

The bot ignores non-MR events and MR updates without new commits.

## API endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Liveness + active model |
| `/health/full` | GET | Checks Ollama, GitLab, DB, Google Chat config |
| `/webhook` | POST | GitLab MR webhook receiver |
| `/reviews` | GET | List stored reviews (`project_id`, `mr_iid`, `limit`) |

## Backups

Create a DB backup:

```bash
bash backup.sh
```

Optional env overrides for backup:

- `DB_PATH` (default `./data/reviews.db`)
- `BACKUP_DIR` (default `./backups`)
- `KEEP_DAYS` (default `30`)

## Git flow strategy for this repository

Use a lightweight **Git Flow (GitHub-hosted)** model:

### Branches

- `main`: production-ready, protected branch.
- `develop`: integration branch for next release.
- `feature/<short-name>`: new work (branch from `develop`).
- `fix/<short-name>`: non-urgent bug fixes (branch from `develop`).
- `release/<version>`: stabilization before release (branch from `develop`).
- `hotfix/<short-name>`: urgent production fixes (branch from `main`).

### Day-to-day workflow

1. Create branch from `develop`:
   ```bash
   git checkout develop
   git pull
   git checkout -b feature/webhook-hardening
   ```
2. Commit in small units (clear messages).
3. Open PR into `develop`.
4. Require review + passing checks before merge.

### Release workflow

1. Create `release/x.y.z` from `develop`.
2. Only stabilization fixes on release branch.
3. Merge release branch into `main` and tag (`vX.Y.Z`).
4. Merge same release branch back into `develop`.

### Hotfix workflow

1. Create `hotfix/<name>` from `main`.
2. Open PR to `main` and merge after review.
3. Merge hotfix back into `develop` to keep branches aligned.

### GitHub repository setup recommendations

For `xsugra/gitlab-code-reviews`:

- Protect `main` and `develop`.
- Require pull requests (no direct pushes).
- Require at least 1 approval.
- Require status checks before merging.
- Enable squash merge (clean history).

### Connect local project to your GitHub repo

```bash
git remote add origin git@github.com:xsugra/gitlab-code-reviews.git
# or
git remote add origin https://github.com/xsugra/gitlab-code-reviews.git
```
