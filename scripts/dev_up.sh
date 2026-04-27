#!/usr/bin/env bash
# Start backend (uvicorn :8000) + frontend (next dev :3010) so they survive
# until you run dev_down.sh or reboot.
#
# RUN THIS FROM YOUR OWN TERMINAL — not from Claude's chat.
# Reason: macOS TCC blocks launchd-spawned processes from reading ~/Desktop.
# A user-Terminal-launched process inherits TCC permission and persists.
#
# Idempotent: if a service is already up, it's left alone.

set -u
ROOT="/Users/anthonymammone/Desktop/ArchiClaude"
cd "$ROOT"

# ---- Docker containers (Postgres + Redis) ----------------------------
if ! docker info >/dev/null 2>&1; then
    echo "→ Docker daemon not running, starting Docker.app…"
    open -a Docker
    until docker info >/dev/null 2>&1; do sleep 1; done
fi
for c in archiclaude-postgres archiclaude-redis; do
    state=$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null || echo "missing")
    case "$state" in
        running)  echo "✓ $c already running" ;;
        missing)  echo "✗ $c container missing — create it first" ;;
        *)        echo "→ starting $c"; docker start "$c" >/dev/null ;;
    esac
done

# ---- Backend (uvicorn) -----------------------------------------------
if pgrep -f "uvicorn api.main" >/dev/null; then
    echo "✓ backend already running (pid $(pgrep -f 'uvicorn api.main' | head -1))"
else
    echo "→ starting backend (uvicorn :8000)"
    cd "$ROOT/apps/backend"
    nohup .venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000 --workers 1 \
        > /tmp/uvicorn.log 2>&1 < /dev/null &
    disown
    cd "$ROOT"
    sleep 1
    echo "  pid $(pgrep -f 'uvicorn api.main' | head -1) — log /tmp/uvicorn.log"
fi

# ---- Frontend (next dev) ---------------------------------------------
if pgrep -f "next dev -p 3010" >/dev/null; then
    echo "✓ frontend already running (pid $(pgrep -f 'next dev -p 3010' | head -1))"
else
    echo "→ starting frontend (next dev :3010)"
    cd "$ROOT/apps/frontend"
    nohup /usr/local/bin/npm run dev > /tmp/frontend.log 2>&1 < /dev/null &
    disown
    cd "$ROOT"
    sleep 1
    echo "  pid $(pgrep -f 'next dev -p 3010' | head -1) — log /tmp/frontend.log"
fi

echo
echo "Run ./scripts/dev_status.sh to verify, ./scripts/dev_down.sh to stop."
