# Production Setup Guide (Ubuntu)

## Architecture

```
┌─────────────────────────────┐          ┌─────────────────────────────────┐
│   PC 1: GitLab              │          │   PC 2: Code Review Bot         │
│   IP: 192.168.1.10          │          │   IP: 192.168.1.20              │
│                             │          │                                 │
│   GitLab :8088              │ webhook  │   Docker: review-bot :8888      │
│                             │─────────►│       │                         │
│                             │◄─────────│       │ API calls               │
│                             │          │       ▼                         │
│                             │          │   Ollama :11434                 │
└─────────────────────────────┘          └─────────────────────────────────┘
                                                        ▲
        ▲                                               │
        │              ┌──────────────┐                 │
        └──────────────│   Browser    │─────────────────┘
                       │  (any PC)    │
                       └──────────────┘

Prístup z browsera:
  - Homepage:  http://192.168.1.20:8888/
  - Admin:     http://192.168.1.20:8888/code-review-bot/
  - GitLab:    http://192.168.1.10:8088/
```

---

## Prerequisites

- PC 1: GitLab already running and accessible
- PC 2: Ubuntu with min. 16GB RAM (for 14B model), ideally GPU
- Both PCs on the same network
- Ports open between them (see firewall section)

---

## Step 1: Prepare PC 2 (Bot Server)

### 1.1 Install Docker

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Add your user to docker group (logout/login required after)
sudo usermod -aG docker $USER
```

### 1.2 Install Ollama

```bash
curl -fsSL https://ollama.ai/install.sh | sh

# Pull the model (this will download ~8-9GB)
ollama pull qwen2.5-coder:14b

# Verify it works
ollama run qwen2.5-coder:14b "Say hello" --verbose
```

### 1.3 Configure Ollama to listen on all interfaces

By default Ollama only listens on localhost. For Docker to reach it via `host.docker.internal`:

```bash
sudo systemctl edit ollama
```

Add:
```ini
[Service]
Environment="OLLAMA_HOST=0.0.0.0"
```

Then restart:
```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

### 1.4 Clone the project

```bash
cd /opt
sudo mkdir code-review-bot && sudo chown $USER:$USER code-review-bot
git clone <your-repo-url> code-review-bot
cd code-review-bot
```

### 1.5 Create the data directory

```bash
mkdir -p data
```

---

## Step 2: Configure GitLab (PC 1)

### 2.1 Create a Personal Access Token

1. Go to GitLab → User Settings → Access Tokens
2. Create token:
   - Name: `code-review-bot`
   - Scopes: `api`
   - Expiration: set as needed
3. Copy the token (starts with `glpat-`)

### 2.2 Create an OAuth Application

1. Go to GitLab → User Settings → Applications
   (or Admin Area → Applications for instance-wide)
2. Create:
   - **Name:** Code Review Bot
   - **Redirect URI:** `http://192.168.1.20:8888/code-review-bot/callback`
   - **Confidential:** Yes
   - **Scopes:** `read_user`
3. Save. Copy the **Application ID** and **Secret**.

### 2.3 Configure Webhook on project(s)

For each GitLab project you want reviewed:

1. Go to Project → Settings → Webhooks
2. Add webhook:
   - **URL:** `http://192.168.1.20:8888/webhook`
   - **Secret Token:** (same value you'll put in `GITLAB_WEBHOOK_SECRET`)
   - **Trigger:** Merge request events
   - **SSL verification:** Disable (since we use HTTP)
3. Save

---

## Step 3: Configure the Bot (PC 2)

### 3.1 Create .env file

```bash
cd /opt/code-review-bot
cp .env.prod.example .env
```

### 3.2 Generate secrets

```bash
# Generate GITLAB_WEBHOOK_SECRET
python3 -c "import secrets; print(secrets.token_hex(32))"

# Generate SESSION_SECRET
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 3.3 Fill in .env

Edit `.env` and replace all placeholders:

```bash
nano .env
```

Example with real values:
```env
GITLAB_URL=http://192.168.1.10:8088
GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx
GITLAB_WEBHOOK_SECRET=<generated-secret>
OLLAMA_URL=http://host.docker.internal:11434
OLLAMA_MODEL=qwen2.5-coder:14b
OLLAMA_NUM_CTX=32768
OLLAMA_TEMPERATURE=0.2
OLLAMA_TIMEOUT_S=1800
MAX_CHUNK_CHARS=80000
DB_PATH=/data/reviews.db
LOG_LEVEL=INFO
GITLAB_OAUTH_APP_ID=<from-step-2.2>
GITLAB_OAUTH_APP_SECRET=<from-step-2.2>
SESSION_SECRET=<generated-secret>
ADMIN_BASE_URL=http://192.168.1.20:8888
GITLAB_OAUTH_BASE_URL=http://192.168.1.10:8088
```

---

## Step 4: Open Firewall Ports

### PC 2 (Bot Server)

```bash
# Allow access to the bot from the network
sudo ufw allow 8888/tcp comment "Code Review Bot"

# If Ollama needs to be accessed from other machines (optional)
# sudo ufw allow 11434/tcp comment "Ollama"

sudo ufw enable
sudo ufw status
```

### PC 1 (GitLab Server)

```bash
# GitLab must be reachable from PC 2 (API calls) and from browsers (OAuth)
sudo ufw allow 8088/tcp comment "GitLab"
sudo ufw enable
```

---

## Step 5: Start the Bot

```bash
cd /opt/code-review-bot
docker compose up -d --build
```

### Verify it's running:

```bash
# Check container status
docker compose ps

# Check logs
docker compose logs -f

# Test health endpoint
curl http://localhost:8888/health

# Test full health (checks all connections)
curl http://localhost:8888/health/full | python3 -m json.tool
```

### Expected output from /health/full:
```json
{
    "model": "qwen2.5-coder:14b",
    "ollama": {"status": "ok", ...},
    "gitlab": {"status": "ok", ...},
    "db": {"status": "ok", ...},
    "google_chat": {"status": "not configured"},
    "healthy": true
}
```

---

## Step 6: Verify End-to-End

1. **Open browser** on any PC on the network
2. Go to `http://192.168.1.20:8888/`
3. Verify all status indicators are green
4. Click "Open Admin Dashboard"
5. You should be redirected to GitLab OAuth login
6. After login, you see the dashboard
7. **Create a test MR** on a GitLab project with a webhook configured
8. Check bot logs: `docker compose logs -f`
9. The bot should post review comments on the MR within minutes

---

## Troubleshooting

### Bot can't reach GitLab
```bash
# From PC 2, test connectivity to GitLab
curl http://192.168.1.10:8088/api/v4/version
```
If fails: check firewall on PC 1, check GitLab is bound to 0.0.0.0 not 127.0.0.1.

### Bot can't reach Ollama
```bash
# Test Ollama from inside Docker
docker exec review-bot curl http://host.docker.internal:11434/api/tags
```
If fails: check Ollama is running with `OLLAMA_HOST=0.0.0.0`.

### OAuth callback fails
- Verify Redirect URI in GitLab OAuth app matches EXACTLY: `http://192.168.1.20:8888/code-review-bot/callback`
- Verify `ADMIN_BASE_URL` in .env matches: `http://192.168.1.20:8888`
- Verify `GITLAB_OAUTH_BASE_URL` is reachable from the browser

### Webhook not triggering
```bash
# Check GitLab webhook delivery history
# Go to: Project → Settings → Webhooks → Edit → Recent deliveries
```
Common issues: wrong URL, wrong secret token, firewall blocking PC1 → PC2.

### Large MR timeout
Increase `OLLAMA_TIMEOUT_S` or switch to a smaller model:
```env
OLLAMA_MODEL=qwen2.5-coder:7b
```

---

## Maintenance

### Update the bot
```bash
cd /opt/code-review-bot
git pull
docker compose up -d --build
```

### View logs
```bash
docker compose logs -f --tail=100
```

### Backup database
```bash
cp data/reviews.db data/reviews.db.backup-$(date +%Y%m%d)
```

### Change model
```bash
# Pull new model
ollama pull codellama:34b

# Update .env
sed -i 's/OLLAMA_MODEL=.*/OLLAMA_MODEL=codellama:34b/' .env

# Restart bot
docker compose up -d
```

---

## Network Access Summary

| From | To | What they see |
|------|----|---------------|
| Any PC on network | `http://<BOT_IP>:8888/` | Homepage with live status |
| Any PC on network | `http://<BOT_IP>:8888/code-review-bot/` | Admin (requires GitLab login) |
| GitLab server | `http://<BOT_IP>:8888/webhook` | Receives MR events |
| Bot server | `http://<GITLAB_IP>:<PORT>/api/v4/` | Posts review comments |
