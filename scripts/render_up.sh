#!/usr/bin/env bash
# Start the render service (SP2-v2b SDXL Lightning) on port 8001.
# Run this from YOUR own Terminal (not from Claude chat).
# Idempotent : if already running, leaves it alone.

set -u
ROOT="/Users/anthonymammone/Desktop/ArchiClaude"
RS="$ROOT/apps/render-service"

if pgrep -f "uvicorn src.main:app.*8001" >/dev/null; then
    echo "✓ render service already running (pid $(pgrep -f 'uvicorn src.main:app.*8001' | head -1)) on :8001"
    exit 0
fi

if [ ! -d "$RS/.venv" ]; then
    echo "✗ venv missing at $RS/.venv — run setup first :"
    echo "    cd $RS && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi

echo "→ starting render service (SDXL Lightning, MPS)"
cd "$RS"
nohup .venv/bin/uvicorn src.main:app --host 127.0.0.1 --port 8001 \
    > /tmp/render-service.log 2>&1 < /dev/null &
disown
sleep 1
PID=$(pgrep -f "uvicorn src.main:app.*8001" | head -1)
if [ -n "$PID" ]; then
    echo "  pid $PID — log /tmp/render-service.log"
    echo "  waiting for /health endpoint (model loads in ~30s on cold start)…"
    for i in $(seq 1 60); do
        if curl -s --max-time 2 http://127.0.0.1:8001/health >/dev/null 2>&1; then
            echo "✓ render service ready on :8001"
            curl -s http://127.0.0.1:8001/health | python3 -m json.tool 2>/dev/null
            exit 0
        fi
        sleep 1
    done
    echo "⚠ /health not responding after 60s — check /tmp/render-service.log"
    exit 2
else
    echo "✗ failed to start — check /tmp/render-service.log"
    exit 1
fi
