#!/usr/bin/env bash
# Stop backend and frontend. Leaves Docker containers alone.
echo "→ stopping backend"
pkill -f "uvicorn api.main" 2>/dev/null && echo "  killed" || echo "  not running"
echo "→ stopping frontend"
pkill -f "next dev -p 3010" 2>/dev/null && echo "  killed" || echo "  not running"
