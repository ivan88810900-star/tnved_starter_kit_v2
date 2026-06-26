#!/usr/bin/env python3
"""
Синхронизация ставок ТН ВЭД из Excel tws.by → hs_rates (customs.db).

  cd customs-clear/backend
  python3 scripts/sync_tws_data.py
  python3 scripts/sync_tws_data.py --dry-run --limit 500

Источник: https://www.tws.by/tws/tnved/download (файл /download/excel).
Сервис: app.services.regulatory_sync

Ставка НДС в БД: если в Excel нет колонки НДС, в hs_rates подставляется DEFAULT_VAT_IMPORT_RATE = 22%
(см. regulatory_sync.parse_vat_cell / DEFAULT_VAT_IMPORT_RATE), в соответствии с базовой ставкой проекта.

-----------------------------------------------------------------------------
Планирование (crontab), например раз в неделю по воскресеньям в 03:15:

  # Редактировать расписание: crontab -e
  # Переменные окружения и путь к Python подставьте свои.
  15 3 * * 0 cd /ABS/PATH/customs-clear/backend && \\
    /ABS/PATH/venv/bin/python3 scripts/sync_tws_data.py >> logs/tws_sync.log 2>&1

  Либо с явным .env (если cron без окружения):

  15 3 * * 0 cd /ABS/PATH/customs-clear/backend && \\
    set -a && [ -f .env ] && . ./.env && set +a && \\
    /ABS/PATH/venv/bin/python3 scripts/sync_tws_data.py >> logs/tws_sync.log 2>&1

  Проверка записей в БД после прогона:
  sqlite3 customs.db "SELECT source_code,status,rows_affected,substr(note,1,80) FROM sync_log ORDER BY id DESC LIMIT 3;"
-----------------------------------------------------------------------------
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env")
load_dotenv()


def main() -> None:
    parser = argparse.ArgumentParser(description="Импорт тарифа tws.by в hs_rates")
    parser.add_argument("--dry-run", action="store_true", help="Скачать и разобрать, без записи в БД")
    parser.add_argument("--limit", type=int, default=None, help="Максимум строк для upsert (отладка)")
    args = parser.parse_args()

    from app.services.regulatory_sync import run_tws_tariff_sync

    out = run_tws_tariff_sync(dry_run=args.dry_run, limit=args.limit)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
