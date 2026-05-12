#!/usr/bin/env bash
# Stop the render service (frees ~7 GB RAM occupied by the loaded model).
# Multi-strategy kill — pkill regex sometimes fails depending on shell quoting,
# so we ALSO scan port 8001 and kill whoever is listening there.
echo "→ stopping render service"
killed=0
# Strategy 1 : port-based kill (most reliable)
PID=$(lsof -nP -iTCP:8001 -sTCP:LISTEN -t 2>/dev/null | head -1)
if [ -n "$PID" ]; then
    kill "$PID" 2>/dev/null && echo "  killed pid $PID (port 8001)" && killed=1
fi
# Strategy 2 : pattern-based (catches orphan workers / resource trackers)
for pat in "uvicorn.*src.main:app" "render-service/.venv"; do
    pids=$(pgrep -f "$pat" 2>/dev/null)
    if [ -n "$pids" ]; then
        echo "  killing extra : $pids ($pat)"
        echo "$pids" | xargs kill 2>/dev/null
        killed=1
    fi
done
sleep 1
# Verify
if lsof -nP -iTCP:8001 -sTCP:LISTEN >/dev/null 2>&1; then
    echo "  ⚠ port 8001 still listening — may need kill -9"
    lsof -nP -iTCP:8001 -sTCP:LISTEN -t | xargs kill -9 2>/dev/null
fi
if [ "$killed" = "0" ]; then
    echo "  not running"
else
    echo "✓ render service stopped"
fi
