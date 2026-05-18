#!/usr/bin/env bash
# Резервная копия SQLite БД (путь из первого аргумента или backend/customs.db).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="${ROOT}/backend"
DB_PATH="${1:-}"
if [[ -z "${DB_PATH}" ]]; then
  if [[ -f "${BACKEND}/customs.db" ]]; then
    DB_PATH="${BACKEND}/customs.db"
  elif [[ -f "${ROOT}/customs.db" ]]; then
    DB_PATH="${ROOT}/customs.db"
  else
    echo "Укажите путь к файлу БД: $0 /path/to/customs.db" >&2
    exit 1
  fi
fi
DEST_DIR="${BACKEND}/data/backups"
mkdir -p "${DEST_DIR}"
STAMP="$(date +%Y%m%d_%H%M%S)"
cp -f "${DB_PATH}" "${DEST_DIR}/customs_${STAMP}.db"
echo "OK: ${DEST_DIR}/customs_${STAMP}.db"
