#!/usr/bin/env python3
"""Обновление полных названий разделов ТН ВЭД в tnved_sections."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.data.tnved_section_titles import SECTION_TITLES
from app.db import SessionLocal
from app.models.tnved import Section


def repair_section_titles() -> int:
    updated = 0
    with SessionLocal() as db:
        for sec in db.query(Section).all():
            roman = (sec.roman_number or "").strip().upper()
            full = SECTION_TITLES.get(roman)
            if not full or sec.title == full:
                continue
            sec.title = full
            updated += 1
        db.commit()
    return updated


if __name__ == "__main__":
    n = repair_section_titles()
    print(f"Updated {n} section titles")
