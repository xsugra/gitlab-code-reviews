#!/usr/bin/env bash
set -euo pipefail

DB_FILE="${DB_PATH:-./data/reviews.db}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
KEEP_DAYS="${KEEP_DAYS:-30}"

# sqlite3 runs on the host (not in the container), so it must be installed here.
if ! command -v sqlite3 >/dev/null 2>&1; then
    echo "Error: 'sqlite3' is required for backups but is not installed on this host." >&2
    if command -v apt-get >/dev/null 2>&1; then
        echo "  Install it with:  sudo apt-get install -y sqlite3" >&2
    elif command -v dnf >/dev/null 2>&1; then
        echo "  Install it with:  sudo dnf install -y sqlite" >&2
    elif command -v yum >/dev/null 2>&1; then
        echo "  Install it with:  sudo yum install -y sqlite" >&2
    elif command -v apk >/dev/null 2>&1; then
        echo "  Install it with:  sudo apk add sqlite" >&2
    elif command -v brew >/dev/null 2>&1; then
        echo "  Install it with:  brew install sqlite" >&2
    else
        echo "  Install the 'sqlite3' package using your system's package manager." >&2
    fi
    exit 1
fi

if [ ! -f "$DB_FILE" ]; then
    echo "Database not found at $DB_FILE"
    exit 1
fi

mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/reviews_${TIMESTAMP}.db"

# sqlite3 .backup is safe during concurrent writes (uses WAL snapshot)
sqlite3 "$DB_FILE" ".backup '$BACKUP_FILE'"

echo "Backup created: $BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1))"

# Remove backups older than KEEP_DAYS
find "$BACKUP_DIR" -name "reviews_*.db" -mtime +"$KEEP_DAYS" -delete
echo "Cleaned backups older than ${KEEP_DAYS} days"
