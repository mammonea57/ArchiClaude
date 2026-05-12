#!/usr/bin/env bash
# Restore ArchiClaude DB from a backup dump.
#
# Usage:
#   ./scripts/restore_db.sh                    # list available dumps
#   ./scripts/restore_db.sh <dump-file>        # restore specified dump
#
# WARNING: restore overwrites the current DB. Take a safety dump first.

set -euo pipefail

REPO_ROOT="/Users/anthonymammone/Desktop/ArchiClaude"
BACKUP_DIR="$REPO_ROOT/backups"

if [[ $# -eq 0 ]]; then
    echo "Available dumps (newest first):"
    echo "--- hourly ---"
    ls -1t "$BACKUP_DIR/hourly"/*.dump 2>/dev/null | head -10
    echo "--- daily ---"
    ls -1t "$BACKUP_DIR/daily"/*.dump 2>/dev/null | head -10
    echo ""
    echo "Usage: $0 <dump-file>"
    exit 0
fi

DUMP="$1"
if [[ ! -f "$DUMP" ]]; then
    echo "ERROR: dump file not found: $DUMP"
    exit 1
fi

echo "About to restore: $DUMP"
echo "This will DROP existing objects and recreate from the dump."
read -p "Type 'yes' to continue: " CONFIRM
if [[ "$CONFIRM" != "yes" ]]; then
    echo "aborted"
    exit 1
fi

# Safety dump before restore
SAFETY="$BACKUP_DIR/hourly/pre_restore_$(date '+%Y%m%d_%H%M%S').dump"
echo "Taking safety dump → $SAFETY"
docker exec archiclaude-postgres pg_dump -U archiclaude -d archiclaude -F c -Z 6 > "$SAFETY"

# Restore: copy file into container, then pg_restore
echo "Copying dump into container..."
docker cp "$DUMP" archiclaude-postgres:/tmp/restore.dump

echo "Running pg_restore..."
docker exec archiclaude-postgres pg_restore \
    -U archiclaude \
    -d archiclaude \
    -c \
    --if-exists \
    --no-owner \
    --role=archiclaude \
    /tmp/restore.dump || {
    echo "pg_restore reported errors — check if they're just 'does not exist' on initial DROP (safe to ignore)"
}

docker exec archiclaude-postgres rm -f /tmp/restore.dump

echo "Restore complete. Pre-restore safety dump: $SAFETY"
