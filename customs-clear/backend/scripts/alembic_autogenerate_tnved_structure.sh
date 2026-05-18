#!/usr/bin/env bash
# Генерация миграции Alembic по текущим моделям (в т.ч. app/models/tnved.py).
# Перед запуском задайте DATABASE_URL на целевую БД (PostgreSQL рекомендуется для прода).
#
#   cd customs-clear/backend
#   chmod +x scripts/alembic_autogenerate_tnved_structure.sh
#   export DATABASE_URL="postgresql+psycopg2://user:pass@127.0.0.1:5432/customs"
#   ./scripts/alembic_autogenerate_tnved_structure.sh
#
# В репозитории уже есть ручная миграция d1e2f3a4b5c6_*; autogenerate нужен,
# если вы меняли модели и хотите дополнительный revision без ручного SQL.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "DATABASE_URL не задан. Пример:" >&2
  echo "  export DATABASE_URL=postgresql+psycopg2://customs:customs@127.0.0.1:5432/customs" >&2
  exit 1
fi

exec alembic revision --autogenerate -m "tnved structure: sections, chapters, commodities"
