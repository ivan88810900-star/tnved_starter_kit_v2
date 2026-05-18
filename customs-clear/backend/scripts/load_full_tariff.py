#!/usr/bin/env python3
"""Полная загрузка ТН ВЭД и тарифа из официальных источников.

Запуск:
  cd customs-clear/backend
  PYTHONPATH=. ETT_PDF_MAX_GROUPS=0 python scripts/load_full_tariff.py

Или через API после запуска сервера:
  curl -X POST http://localhost:8001/api/sources/sync/ett
"""
from __future__ import annotations

import asyncio
import os
import sys

# Добавляем корень backend в path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Полная загрузка: все группы PDF
os.environ.setdefault("ETT_PDF_MAX_GROUPS", "0")


async def main() -> None:
    from app.services.normative_store import init_db
    from app.services.ett_pdf_parser import sync_ett_from_pdfs
    from app.services.ett_odata_parser import sync_all_odata
    from app.services.preview_cache_revision import bump_preview_cache_revision

    print("Инициализация БД и сидов...")
    init_db()

    print("Загрузка OData (классификатор льгот)...")
    odata = await sync_all_odata()
    print(f"  OData: {odata}")

    print("Загрузка ЕТТ из PDF (все группы, может занять 10–30 мин)...")
    ett = await sync_ett_from_pdfs(max_groups=0)
    print(f"  ETT PDF: {ett}")
    bump_preview_cache_revision("load_full_tariff")

    print("Готово.")


if __name__ == "__main__":
    asyncio.run(main())
