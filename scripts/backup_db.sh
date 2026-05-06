#!/usr/bin/env bash
# Online backup SQLite БД бота с ротацией.
#
# Запускать из cron на VPS:
#   17 3 * * * /opt/notes-bot/scripts/backup_db.sh >> /var/log/notes-bot-backup.log 2>&1
#
# Использует `sqlite3 .backup` — безопасно при работающем боте (WAL-режим).
# Восстановление: gunzip -c notes-YYYYMMDD-HHMMSS.db.gz > data/notes.db
# (при остановленном контейнере: docker compose stop bot).
#
# Конфиг через env vars:
#   APP_DIR     — корень репо на VPS (default: /opt/notes-bot)
#   BACKUP_DIR  — куда складывать (default: /var/backups/notes-bot)
#   KEEP_DAYS   — сколько дней хранить (default: 14)
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/notes-bot}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/notes-bot}"
KEEP_DAYS="${KEEP_DAYS:-14}"

DB_PATH="$APP_DIR/data/notes.db"
TS=$(date +%Y%m%d-%H%M%S)

if [[ ! -f "$DB_PATH" ]]; then
    echo "[$(date -Is)] backup: ERROR — $DB_PATH not found" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"

OUT="$BACKUP_DIR/notes-$TS.db"
sqlite3 "$DB_PATH" ".backup '$OUT'"
gzip "$OUT"

find "$BACKUP_DIR" -name 'notes-*.db.gz' -mtime "+$KEEP_DAYS" -delete

echo "[$(date -Is)] backup: ok → $OUT.gz"
