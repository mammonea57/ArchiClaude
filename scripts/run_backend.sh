#!/usr/bin/env bash
# Backend supervisor entrypoint (run by launchd via com.archiclaude.backend).
# Use exec so launchd tracks the uvicorn PID directly.
set -e
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend
exec ./.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000 --workers 1
