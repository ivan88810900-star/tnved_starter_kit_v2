#!/usr/bin/env bash
# Запуск CustomsClear: API (uvicorn) + React (Vite) параллельно.
# Бэкенд: customs-clear/backend → http://127.0.0.1:8001
# Фронт:  customs-clear/frontend → http://127.0.0.1:3000 (прокси /api → бэкенд)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="${BACKEND_DIR:-$ROOT/customs-clear/backend}"
FRONTEND_DIR="${FRONTEND_DIR:-$ROOT/customs-clear/frontend}"

if [[ ! -d "$BACKEND_DIR" ]] || [[ ! -f "$BACKEND_DIR/app/main.py" ]]; then
  echo "Ожидается бэкенд: $BACKEND_DIR (app/main.py)" >&2
  exit 1
fi
if [[ ! -d "$FRONTEND_DIR" ]] || [[ ! -f "$FRONTEND_DIR/package.json" ]]; then
  echo "Ожидается фронтенд: $FRONTEND_DIR (package.json)" >&2
  exit 1
fi

cleanup() {
  [[ -n "${BACK_PID:-}" ]] && kill "$BACK_PID" 2>/dev/null || true
  [[ -n "${FRONT_PID:-}" ]] && kill "$FRONT_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

(
  cd "$BACKEND_DIR"
  exec uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
) &
BACK_PID=$!

(
  cd "$FRONTEND_DIR"
  exec npm run dev
) &
FRONT_PID=$!

echo "Бэкенд:  http://127.0.0.1:8001"
echo "Фронт:   http://127.0.0.1:3000"
echo "Остановка: Ctrl+C"
wait
