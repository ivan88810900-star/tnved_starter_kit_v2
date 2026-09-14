#!/usr/bin/env python3
"""Retired tariff loader: report the reviewed-snapshot boundary without writes.

Запуск:
  cd customs-clear/backend
  PYTHONPATH=. ETT_PDF_MAX_GROUPS=0 python scripts/load_full_tariff.py

The legacy path exits nonzero with REVIEW_REQUIRED. Acquisition, review and
promotion now belong to the versioned ETT pipeline (Decision #188).
"""
from __future__ import annotations

import asyncio
import os
import sys

# Добавляем корень backend в path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

async def main() -> int:
    from app.services.ett_pdf_parser import sync_ett_from_pdfs
    ett = await sync_ett_from_pdfs(max_groups=0)
    print(f"ETT PDF: {ett['status']}. {ett['note']}")
    return 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
