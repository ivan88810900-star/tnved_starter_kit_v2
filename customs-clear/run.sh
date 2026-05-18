#!/bin/bash
# Запуск CustomsClear: backend + frontend
# Использование: ./run.sh [backend|frontend|all]

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${ROOT}/.venv"
BACKEND_DIR="${ROOT}/customs-clear/backend"
FRONTEND_DIR="${ROOT}/customs-clear/frontend"
PORT_BACKEND="${VITE_API_PORT:-8001}"
PORT_FRONTEND=3000

run_backend() {
  echo "Запуск backend на порту ${PORT_BACKEND}..."
  cd "$BACKEND_DIR"
  PYTHONPATH=. "${VENV}/bin/uvicorn" app.main:app --host 127.0.0.1 --port "$PORT_BACKEND"
}

run_frontend() {
  echo "Запуск frontend на порту ${PORT_FRONTEND}..."
  cd "$FRONTEND_DIR"
  npm install
  VITE_API_PORT="$PORT_BACKEND" npm run dev
}

case "${1:-all}" in
  backend)  run_backend ;;
  frontend) run_frontend ;;
  all)
    echo "Запустите в двух терминалах:"
    echo "  Терминал 1: ./run.sh backend"
    echo "  Терминал 2: ./run.sh frontend"
    echo ""
    echo "Или: ./run.sh backend &  sleep 3 && ./run.sh frontend"
    run_backend &
    sleep 3
    run_frontend
    ;;
  *) echo "Использование: $0 [backend|frontend|all]" ;;
esac
