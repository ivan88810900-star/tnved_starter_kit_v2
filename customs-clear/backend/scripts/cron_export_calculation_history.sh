#!/usr/bin/env bash
# Пример cron: выгрузка журнала расчётов (см. docs/RUNBOOK.md).
# Переменные: API_BASE (по умолчанию http://127.0.0.1:8001), OUT_DIR, ADMIN_TOKEN (если задан ADMIN_API_TOKEN на API).

set -euo pipefail
API_BASE="${API_BASE:-http://127.0.0.1:8001}"
OUT_DIR="${OUT_DIR:-.}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUT_DIR"

HDR=()
if [[ -n "${ADMIN_TOKEN:-}" ]]; then
  HDR=(-H "X-Admin-Token: ${ADMIN_TOKEN}")
fi

curl -sS "${HDR[@]}" \
  "${API_BASE}/api/calculator/history/export?format=csv&limit=10000" \
  -o "${OUT_DIR}/calculation_history_${STAMP}.csv"

echo "Written ${OUT_DIR}/calculation_history_${STAMP}.csv"
