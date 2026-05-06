#!/usr/bin/env bash
set -euo pipefail

DB_FILE="${DB_PATH:-./data/reviews.db}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
KEEP_DAYS="${KEEP_DAYS:-30}"

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
