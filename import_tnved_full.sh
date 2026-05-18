#!/usr/bin/env bash
# Полный импорт PDF ЕТТ из backend/app/services/source_sync/data → tnved.db,
# затем копирование в customs-clear/backend/customs.db для UI CustomsClear.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT/backend"
echo "=== 1/2 Парсинг PDF → tnved.db (очистка и импорт) ==="
python3 app/services/source_sync/pdf_parser.py --clear --no-progress
cd "$ROOT/customs-clear/backend"
echo "=== 2/2 Синхронизация в customs.db ==="
PYTHONPATH=. python3 scripts/sync_tnved_from_tnved_db.py
echo "Готово. Запустите API из customs-clear/backend (uvicorn) и фронт."
