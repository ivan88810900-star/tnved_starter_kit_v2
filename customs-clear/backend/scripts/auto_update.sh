#!/usr/bin/env bash
set -euo pipefail

# Базовый PATH для cron (macOS часто запускает cron с урезанным окружением).
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="${PROJECT_ROOT}/logs"
LOG_FILE="${LOG_DIR}/auto_update.log"

mkdir -p "${LOG_DIR}"

timestamp() {
  date "+%Y-%m-%d %H:%M:%S"
}

log() {
  printf "[%s] %s\n" "$(timestamp)" "$*" | tee -a "${LOG_FILE}"
}

run_step() {
  local name="$1"
  shift

  log "START: ${name}"

  set +e
  "$@" 2>&1 | while IFS= read -r line; do
    log "${line}"
  done
  local status=${PIPESTATUS[0]}
  set -e

  if [[ ${status} -ne 0 ]]; then
    log "FAIL: ${name} (exit_code=${status})"
    return "${status}"
  fi

  log "DONE: ${name}"
}

cd "${PROJECT_ROOT}"
log "Auto update started. project_root=${PROJECT_ROOT}"

run_step "initial_sync" env PYTHONPATH=. python3 scripts/initial_sync.py
run_step "generate_embeddings (only missing: regulatory_ai_extracts + declaration_examples)" \
  env PYTHONPATH=. python3 scripts/generate_embeddings.py \
    --source regulatory_ai_extracts \
    --source declaration_examples \
    --only-missing

log "Auto update finished successfully."
