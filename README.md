<div align="center">
<p align="center">
  <img src="app/logo/code-reviews-bot-logo.png" alt="Code Reviews Bot" width="180">
</p>

<h1 align="center">GitLab Code Reviews Bot</h1>

<p align="center">
  AI-powered GitLab automation — code reviews, pipeline analysis, issue triage, and more.<br>
  All powered by a local LLM. No data leaves your network.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12-blue?logo=python&logoColor=white" alt="Python 3.12">
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/Ollama-local_LLM-black?logo=ollama" alt="Ollama">
  <img src="https://img.shields.io/badge/SQLite-WAL-003B57?logo=sqlite&logoColor=white" alt="SQLite">
  <img src="https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white" alt="Docker">
</p>
</div>

---

## Overview

```text
┌──────────────┐    webhooks       ┌──────────────────┐    LLM analysis   ┌─────────────┐
│   GitLab     │ ────────────────▸ │   Review Bot     │ ────────────────▸ │   Ollama    │
│  (events)    │                   │   (FastAPI)      │ ◂──────────────── │  (local AI) │
└──────────────┘                   │                  │                   └─────────────┘
                                   │  ┌────────────┐  │
┌──────────────┐   OAuth + UI      │  │  SQLite DB │  │     notification
│   Browser    │ ────────────────▸ │  │  reviews   │  │ ────────────────▸  Google Chat
│  (admin UI)  │ ◂──────────────── │  │  events    │  │                    (per-project)
└──────────────┘                   │  └────────────┘  │
                                   └──────────────────┘
```

The bot hooks into your GitLab instance and processes multiple event types:

1. **Receives** webhook events from GitLab (MR, push, pipeline, issues, deployments, releases, emoji).
2. **Analyzes** each event with a local Ollama model — reviews code, diagnoses failures, triages issues.
3. **Posts** findings back to GitLab (MR comments, commit comments, issue labels and notes).
4. **Saves** all events and reviews to SQLite for history and auditing.
5. **Notifies** the team via Google Chat (if configured for that project).

---

## Features

|                        | Feature                        | Description                                                                            |
|------------------------|--------------------------------|----------------------------------------------------------------------------------------|
| :robot:                | **AI Code Review**             | Single-pass or chunked review using a local Ollama model (no data leaves your network) |
| :pushpin:              | **Push Review**                | Review commits pushed directly to branches (outside MRs)                               |
| :red_circle:           | **Pipeline Failure Analysis**  | Analyze failed CI/CD job logs, find root cause, suggest fixes                          |
| :memo:                 | **MR Description Generation**  | Auto-fill empty MR descriptions from the diff                                          |
| :label:                | **Issue Triage**               | Auto-classify new issues — assign labels, severity, and summary                        |
| :rocket:               | **Release Notes**              | Generate changelogs from merged MRs when a tag or release is created                   |
| :package:              | **Deployment Analysis**        | Analyze failed/successful deployments, post reports on commits                         |
| :repeat:               | **Emoji Re-trigger**           | Re-run a review by adding an emoji (default: :repeat:) to a MR                        |
| :speech_balloon:       | **GitLab Integration**         | Posts findings as MR comments, commit comments, and issue notes                        |
| :bell:                 | **Google Chat Notifications**  | Rich Card notifications per-project for all event types                                |
| :globe_with_meridians: | **Admin Dashboard**            | Web UI for managing webhooks, browsing reviews, and monitoring health                  |
| :lock:                 | **GitLab OAuth**               | Authenticate via your existing GitLab accounts                                         |
| :whale:                | **Docker Deployment**          | Single `docker compose up` — no complex setup                                          |
| :floppy_disk:          | **Event History**              | All reviews and events stored in SQLite with search and filtering                      |

---

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Ollama running on the host machine
- A GitLab instance with API access

### 1. Clone and configure

```bash
git clone <repo-url> && cd code-reviews
cp .env.example .env
# Edit .env with your GitLab URL and token
```

### 2. Pull the LLM model and start

```bash
ollama pull qwen2.5-coder:14b
docker compose up -d --build
```

### 3. Verify

```bash
curl http://localhost:8888/health/full
```

### 4. Add a GitLab webhook

In your GitLab project under **Settings → Webhooks**:

| Field        | Value                                     |
|--------------|-------------------------------------------|
| URL          | `http://<your-host>:8888/webhook`         |
| Secret token | Value of `GITLAB_WEBHOOK_SECRET` (if set) |

Enable the triggers you need:

| Trigger               | What it does                                             |
|-----------------------|----------------------------------------------------------|
| Merge request events  | Code review + auto-fill empty MR descriptions            |
| Push events           | Review commits pushed directly to branches               |
| Pipeline events       | Analyze failed CI/CD pipelines                           |
| Work item events      | Auto-triage new issues (labels + severity)               |
| Deployment events     | Analyze failed/successful deployments                    |
| Releases events       | Generate release notes from merged MRs                   |
| Tag push events       | Generate release notes when a tag is pushed              |
| Emoji events          | Re-trigger review when :repeat: emoji is added to a MR  |

That's it — open a merge request and the bot will review it automatically.

> **Port mapping**: host `:8888` → container `:8000`

---

## Admin UI Setup

The admin panel lets any GitLab user configure per-project Google Chat notifications.

### Register an OAuth app on GitLab

1. Go to **User Settings → Applications** (or **Admin → Applications**).
2. Create an application:

| Field        | Value                                              |
|--------------|----------------------------------------------------|
| Name         | `Code Review Bot`                                  |
| Redirect URI | `http://<your-host>:8888/code-review-bot/callback` |
| Confidential | Yes                                                |
| Scopes       | `read_user`                                        |

3. Copy the **Application ID** and **Secret**.

### Add to `.env`

```bash
GITLAB_OAUTH_APP_ID=<Application ID>
GITLAB_OAUTH_APP_SECRET=<Secret>
SESSION_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
ADMIN_BASE_URL=http://<your-host>:8888
```

> If `GITLAB_URL` uses a Docker-internal address (e.g. `host.docker.internal`), also set `GITLAB_OAUTH_BASE_URL` to the
> browser-accessible GitLab URL.

Rebuild and open `http://<your-host>:8888/code-review-bot/`.

### Configure a project webhook

1. Sign in with your GitLab account.
2. Go to **Webhooks → Add New Webhook**.
3. Enter the **Project ID** (GitLab → project Settings → General).
4. Paste the **Google Chat Webhook URL** (Space settings → Manage webhooks).
5. Click **Create**, then **Test** to verify.

Projects without a webhook still get reviews on GitLab — they just don't get a chat notification.

---

## Configuration Reference

### Core

| Variable                | Required | Default               | Purpose                           |
|-------------------------|:--------:|-----------------------|-----------------------------------|
| `GITLAB_URL`            |   Yes    | —                     | GitLab instance base URL          |
| `GITLAB_TOKEN`          |   Yes    | —                     | GitLab token with `api` scope     |
| `GITLAB_WEBHOOK_SECRET` |    —     | empty                 | Validates `X-Gitlab-Token` header |
| `OLLAMA_URL`            |    —     | `http://ollama:11434` | Ollama API endpoint               |
| `OLLAMA_MODEL`          |    —     | `qwen2.5-coder:14b`   | LLM model name                    |
| `OLLAMA_NUM_CTX`        |    —     | `32768`               | Context window (tokens)           |
| `OLLAMA_TEMPERATURE`    |    —     | `0.2`                 | Generation temperature            |
| `OLLAMA_TIMEOUT_S`      |    —     | `1800`                | LLM request timeout (seconds)     |
| `MAX_CHUNK_CHARS`       |    —     | `80000`               | Diff chunk size limit             |
| `DB_PATH`               |    —     | `/data/reviews.db`    | SQLite database path              |
| `LOG_LEVEL`             |    —     | `INFO`                | Logging level                     |
| `REVIEW_RETRIGGER_EMOJI`|    —     | `repeat`              | Emoji name that re-triggers review|

### Admin UI (GitLab OAuth)

| Variable                  | Required | Default        | Purpose                       |
|---------------------------|:--------:|----------------|-------------------------------|
| `GITLAB_OAUTH_APP_ID`     |    —     | empty          | OAuth Application ID          |
| `GITLAB_OAUTH_APP_SECRET` |    —     | empty          | OAuth Application Secret      |
| `SESSION_SECRET`          |    —     | empty          | Cookie signing key            |
| `ADMIN_BASE_URL`          |    —     | empty          | This service's base URL       |
| `GITLAB_OAUTH_BASE_URL`   |    —     | = `GITLAB_URL` | Browser-accessible GitLab URL |

> Leave OAuth variables empty to disable the admin UI. The bot still processes webhooks normally.

---

## API Endpoints

### Public

| Method | Endpoint       | Description                                              |
|:------:|----------------|----------------------------------------------------------|
| `GET`  | `/`            | Homepage with live status                                |
| `GET`  | `/api-docs`    | API documentation page                                   |
| `GET`  | `/health`      | Liveness check + active model                            |
| `GET`  | `/health/full` | Deep health check (Ollama, GitLab, DB, webhooks)         |
| `POST` | `/webhook`     | GitLab webhook receiver (all event types)                |
| `GET`  | `/reviews`     | Review history (query: `project_id`, `mr_iid`, `limit`)  |
| `GET`  | `/events`      | Event history (query: `event_type`, `project_id`, `limit`) |

### Admin UI (GitLab OAuth required)

| Method | Endpoint                    | Description                 |
|:------:|-----------------------------|-----------------------------|
| `GET`  | `/code-review-bot/`         | Dashboard                   |
| `GET`  | `/code-review-bot/webhooks` | Webhook management          |
| `GET`  | `/code-review-bot/reviews`  | Review browser with filters |
| `GET`  | `/code-review-bot/health`   | System health dashboard     |

---

## Event Processing

All events follow a similar pipeline:

```text
Webhook ─▸ Parse event ─▸ Fetch context ─▸ LLM analysis ─▸ Save ─▸ Post
           (object_kind)   (GitLab API)    (Ollama)         (DB)   (GitLab + Chat)
```

**MR Code Review** uses a chunked pipeline for large diffs:

- Split by file first.
- If a single file exceeds `MAX_CHUNK_CHARS`, split by hunk (`@@` markers).
- Each chunk is reviewed independently, then findings are aggregated into a final summary.
- Chunks returning `NO_FINDINGS` are excluded from aggregation.

**Google Chat Cards v2** format:

- MR reviews: separate cards per section (Blocking, Overall, Suggested, Nits, Verdict).
- Other events: single card with event-specific icon and title.
- Markdown converted to safe HTML (bold, italic, code, links, bullets).
- Clickable button linking to the relevant GitLab resource.
- Graceful truncation at 3500 characters per section.

---

## Security

| Measure              | Implementation                                                |
|----------------------|---------------------------------------------------------------|
| **Authentication**   | GitLab OAuth2 with `read_user` scope                          |
| **Sessions**         | HMAC-SHA256 signed cookies, HttpOnly, SameSite=Lax, 8h expiry |
| **CSRF**             | Per-session token validated on every POST                     |
| **XSS**              | Jinja2 autoescaping on all templates                          |
| **URL masking**      | Webhook URLs shown truncated in list view                     |
| **Input validation** | Project ID > 0, webhook URLs must be HTTPS                    |
| **Logging**          | Webhook URLs and secrets are never logged                     |

> **HTTP note**: Without a TLS reverse proxy, OAuth tokens and cookies transit unencrypted. Acceptable on a trusted
> internal network; add HTTPS for internet-facing deployments.

---

## Database

SQLite with WAL journal mode. Three tables, managed via `CREATE TABLE IF NOT EXISTS` on every startup:

| Table             | Purpose                                                                 |
|-------------------|-------------------------------------------------------------------------|
| `reviews`         | MR review history (project, MR, model, chunks, review text, timestamp)  |
| `events`          | All other event results (type, project, ref, model, result, timestamp)  |
| `webhook_configs` | Per-project Google Chat webhooks (project ID, URL, enabled, timestamps) |

---

## Project Structure

```text
app/
├── main.py              FastAPI app, webhook router, health endpoints
├── admin.py             Admin UI: OAuth, sessions, CSRF, webhook CRUD
├── reviewer.py          MR code review pipeline (chunked)
├── gitlab_client.py     GitLab API client (shared httpx session)
├── llm_client.py        Ollama chat client
├── google_chat.py       Google Chat Cards v2 formatting
├── prompts.py           LLM prompt templates (all event types)
├── db.py                SQLite schema and queries
├── config.py            Environment variable parsing
├── handlers/
│   ├── __init__.py
│   ├── _common.py       Shared notify + save boilerplate
│   ├── push_review.py   Push commit review
│   ├── pipeline_analysis.py  Failed pipeline analysis
│   ├── mr_description.py     Auto-fill empty MR descriptions
│   ├── issue_triage.py       Issue classification and labeling
│   ├── release_notes.py      Changelog generation (release + tag push)
│   └── deployment_analysis.py  Deployment analysis
├── logo/
│   └── code-reviews-bot-logo.png
├── templates/
│   ├── base.html        Layout with nav and Pico CSS
│   ├── home.html        Public homepage
│   ├── api_docs.html    API documentation page
│   ├── login.html       GitLab OAuth login
│   ├── dashboard.html   Overview dashboard
│   ├── reviews.html     Review history browser
│   ├── health.html      System health
│   └── webhooks/
│       ├── list.html    Webhook table
│       └── form.html    Add/edit form
└── static/
    ├── logo.png         Bot logo for the admin UI
    ├── main.css         Custom styles
    └── pico.min.css     Bundled CSS (no CDN)
data/
└── reviews.db           Persistent database (Docker volume)
```

---

## Backups

```bash
bash backup.sh
```

| Variable     | Default             | Purpose                 |
|--------------|---------------------|-------------------------|
| `DB_PATH`    | `./data/reviews.db` | Database file path      |
| `BACKUP_DIR` | `./backups`         | Backup destination      |
| `KEEP_DAYS`  | `30`                | Retention period (days) |
