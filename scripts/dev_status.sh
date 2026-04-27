#!/usr/bin/env bash
# Show whether backend, frontend, Postgres, Redis are up.
fmt() { printf "%-12s %-8s %s\n" "$1" "$2" "$3"; }
fmt "service" "status" "detail"
fmt "--------" "------" "------"

bp=$(pgrep -f "uvicorn api.main" | head -1)
if [ -n "$bp" ]; then
    code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/openapi.json)
    fmt "backend" "UP" "pid $bp · http $code"
else
    fmt "backend" "DOWN" "-"
fi

fp=$(pgrep -f "next dev -p 3010" | head -1)
if [ -n "$fp" ]; then
    code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:3010/)
    fmt "frontend" "UP" "pid $fp · http $code"
else
    fmt "frontend" "DOWN" "-"
fi

for c in archiclaude-postgres archiclaude-redis; do
    state=$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null || echo "missing")
    [ "$state" = "running" ] && fmt "$c" "UP" "-" || fmt "$c" "DOWN" "$state"
done
