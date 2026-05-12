#!/usr/bin/env bash
# Hourly Postgres backup for ArchiClaude dev DB.
#
# Strategy:
# - Every hour: pg_dump full DB (custom format, compressed) into backups/hourly/
# - Keep last 48 hourly dumps (2 days rolling)
# - After 24h: promote one dump per day into backups/daily/, keep 30 daily
#
# Restore: pg_restore -h localhost -U archiclaude -d archiclaude -c <file>
#   (-c drops objects first; use --no-owner --role=archiclaude if needed)
#
# Dump is taken from inside the Docker container to avoid host psql deps.

set -euo pipefail

REPO_ROOT="/Users/anthonymammone/Desktop/ArchiClaude"
BACKUP_DIR="$REPO_ROOT/backups"
HOURLY_DIR="$BACKUP_DIR/hourly"
DAILY_DIR="$BACKUP_DIR/daily"
LOG_FILE="$BACKUP_DIR/backup.log"

mkdir -p "$HOURLY_DIR" "$DAILY_DIR"

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(ts)] $*" | tee -a "$LOG_FILE"; }

# 1. Hourly dump
STAMP=$(date '+%Y%m%d_%H%M%S')
OUT="$HOURLY_DIR/archiclaude_${STAMP}.dump"

log "starting hourly dump → $OUT"

if ! docker exec archiclaude-postgres pg_dump \
    -U archiclaude \
    -d archiclaude \
    -F c \
    -Z 6 \
    > "$OUT"; then
    log "ERROR: pg_dump failed (container down?)"
    rm -f "$OUT"
    exit 1
fi

SIZE=$(du -h "$OUT" | cut -f1)
log "hourly OK ($SIZE)"

# 2. Rotate hourly: keep last 48
ls -1t "$HOURLY_DIR"/archiclaude_*.dump 2>/dev/null | tail -n +49 | xargs -I {} rm -f {}

# 3. Promote one-per-day: if no daily dump exists for today yet, copy this hourly
TODAY=$(date '+%Y%m%d')
if ! ls "$DAILY_DIR"/archiclaude_${TODAY}_*.dump >/dev/null 2>&1; then
    cp "$OUT" "$DAILY_DIR/archiclaude_${TODAY}_$(date '+%H%M%S').dump"
    log "promoted to daily"
fi

# 4. Rotate daily: keep last 30
ls -1t "$DAILY_DIR"/archiclaude_*.dump 2>/dev/null | tail -n +31 | xargs -I {} rm -f {}

log "done. hourly=$(ls "$HOURLY_DIR" | wc -l | tr -d ' ') daily=$(ls "$DAILY_DIR" | wc -l | tr -d ' ')"
