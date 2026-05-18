#!/usr/bin/env bash
# Cron: 0 3 * * * /path/to/scheduled_sync.sh
# Или вызывайте из systemd timer.
set -euo pipefail
BASE_URL="${CUSTOMS_CLEAR_API:-http://127.0.0.1:8001}"
curl -sf -X POST "${BASE_URL}/api/sources/sync" || exit 1
echo "OK $(date -u +%Y-%m-%dT%H:%M:%SZ)"
