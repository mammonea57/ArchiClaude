#!/usr/bin/env bash
# Frontend supervisor entrypoint (run by launchd via com.archiclaude.frontend).
# Use exec so launchd tracks the next/node PID directly.
set -e
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/frontend
exec /usr/local/bin/npm run dev
