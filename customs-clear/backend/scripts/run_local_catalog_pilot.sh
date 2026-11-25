#!/bin/bash
# Run this explicit preview on the prepared Mac, in the foreground.
set -euo pipefail
backend_dir="$(cd "$(dirname "$0")/.." && pwd)"
frontend_dir="$(cd "$backend_dir/../frontend" && pwd)"
project_dir="$(cd "$backend_dir/../../.." && pwd)"
runtime_dir="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies"
data_dir="$project_dir/evidence/2026-11-19-integration/r466/data"
public_libs="$project_dir/evidence/2026-11-19-integration/r466/runtime-libs"
if [[ ! -f "$frontend_dir/dist/index.html" ]]; then
  echo "Сначала соберите локальный интерфейс с VITE_TARIFF_LOCAL_PILOT=1." >&2
  exit 1
fi
exec env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 \
  PYTHONPATH="$public_libs:$runtime_dir/python/lib/python3.12/site-packages" \
  TARIFF_PILOT_PARTITIONED_CHAPTERS=38,39,40,41,42,43,44,45 \
  TARIFF_PILOT_PARTITIONED_RATES="$project_dir/evidence/2026-11-25-parallel/r482/ett/data" \
  TARIFF_PILOT_ADDITIONAL_RATES="$project_dir/evidence/2026-11-23-ch37-pilot/r471/data" \
  TARIFF_PILOT_DATA="$data_dir" TNVED_RECOVERY_FRONTEND="$frontend_dir/dist" \
  "$project_dir/.venv-tariff/bin/python" -m uvicorn app.local_pilot:create_app \
  --factory --app-dir "$backend_dir" --host 127.0.0.1 --port "${1:-18016}" --no-access-log
