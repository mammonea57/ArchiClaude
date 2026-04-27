#!/usr/bin/env bash
# Wrapper: capture a plans-page tab as PNG for visual self-check.
# Usage: ./scripts/screenshot.sh <project_id> <tab>
set -e
PID="${1:-e9a960c8-081f-4c42-a65b-619610a61134}"
TAB="${2:-coupes}"
NODE_PATH="/Users/anthonymammone/Desktop/ArchiClaude/node_modules/.pnpm/playwright@1.59.1/node_modules" \
  node /Users/anthonymammone/Desktop/ArchiClaude/scripts/screenshot.cjs "$PID" "$TAB"
echo "  → $(/usr/bin/file /tmp/archiclaude-${TAB}.png | cut -d, -f2-)"
