.PHONY: start stop restart upgrade backup logs status setup-nsoric help

.DEFAULT_GOAL := help

# ─── Spustenie / zastavenie ───────────────────────────────────────────

start:
	docker compose up -d --build

stop:
	docker compose down

restart: stop start

# ─── Upgrade ──────────────────────────────────────────────────────────

upgrade: backup
	git pull nsoric main
	docker compose down
	docker compose up -d --build

# ─── Pomocné príkazy ─────────────────────────────────────────────────

backup:
	bash backup.sh

logs:
	docker compose logs -f --tail=100

status:
	docker compose ps

# ─── Jednorazové nastavenie NSORIC remote ────────────────────────────

setup-nsoric:
	@echo "=== Nastavenie NSORIC remote ==="
	@if [ ! -f ~/.ssh/id_ed25519 ]; then \
		echo ""; \
		echo "Generujem SSH kľúč..."; \
		ssh-keygen -t ed25519 -C "code-review-bot" -f ~/.ssh/id_ed25519 -N ""; \
		echo ""; \
		echo "=============================================================="; \
		echo "  !!! SKOPÍRUJ TENTO VEREJNÝ KĽÚČ DO GITLABU:"; \
		echo "      nsoric.mtf.stuba.sk → Settings → SSH Keys"; \
		echo "=============================================================="; \
		echo ""; \
		cat ~/.ssh/id_ed25519.pub; \
		echo ""; \
		echo "=============================================================="; \
	else \
		echo "SSH kľúč už existuje: ~/.ssh/id_ed25519"; \
	fi
	@echo ""
	@if git remote get-url nsoric >/dev/null 2>&1; then \
		echo "nsoric remote už existuje."; \
	else \
		git remote add nsoric git@nsoric.mtf.stuba.sk:mtf/web/code-review-bot.git; \
		echo "nsoric remote pridaný."; \
	fi
	@ssh-keyscan -H nsoric.mtf.stuba.sk >> ~/.ssh/known_hosts 2>/dev/null || true
	@echo ""
	@echo "=== Hotovo. Po pridaní SSH kľúča do GitLabu spusti: make upgrade ==="

# ─── Pomocník ─────────────────────────────────────────────────────────

help:
	@echo "Code Review Bot – Makefile"
	@echo ""
	@echo "  make start          Spusti aplikaciu"
	@echo "  make stop           Zastavi aplikaciu"
	@echo "  make restart        Restartuje aplikaciu"
	@echo "  make upgrade        Aktualizuje kod z NSORIC + rebuild"
	@echo "  make backup         Zalohuje databazu"
	@echo "  make logs           Zobrazi logy (follow)"
	@echo "  make status         Stav kontajnera"
	@echo "  make setup-nsoric   Jednorazove nastavenie NSORIC remote"
