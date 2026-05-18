#!/bin/bash
# Полная загрузка всех баз: ТН ВЭД, ЕТТ, OData
# Запуск: cd customs-clear/backend && ./scripts/load_full_databases.sh

set -e
cd "$(dirname "$0")/.."

echo "=== Полная загрузка баз ==="
echo "ЕТТ PDF: все группы (10–30 мин)"
echo "OData: льготы и преференции"
echo ""

export ETT_PDF_MAX_GROUPS=0
export PYTHONPATH=.

python3 scripts/load_full_tariff.py

echo ""
echo "=== Готово ==="
echo "Перезапустите backend для применения данных."
