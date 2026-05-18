#!/usr/bin/env python3
"""
Сводка по наполнению таблиц compliance / нормативки / госсреестров выданных документов.
Запуск из каталога customs-clear/backend: python3 scripts/audit_compliance_db.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import inspect, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal, engine  # noqa: E402


def _count_table(table_name: str) -> int | None:
    inspector = inspect(engine)
    if not inspector.has_table(table_name):
        return None
    with SessionLocal() as db:
        row = db.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one()
    return int(row or 0)


def _fmt(value: int | None) -> str:
    return "N/A (table not found)" if value is None else str(value)


def main() -> int:
    targets: list[tuple[str, list[str]]] = [
        ("Техрегламенты", ["tr_ts_acts"]),
        ("Меры нетарифки", ["non_tariff_rules", "non_tariff_measures"]),
        ("ИИ-выжимки нормативки", ["regulatory_ai_extracts"]),
        ("ТРОИС / ИС", ["trois_registry", "intellectual_properties"]),
        ("Санкции и страновые риски", ["sanction_import_risks", "country_risks"]),
        (
            "Государственные реестры выданных документов",
            [
                "fss_notifications",
                "reo_registry",
                "sgr_certificates",
            ],
        ),
    ]

    print("=== Compliance/TROIS DB Audit ===")
    print(f"DB URL: {engine.url}")
    print("")

    for section, tables in targets:
        print(f"[{section}]")
        section_total = 0
        found_any = False
        for table in tables:
            count = _count_table(table)
            if count is not None:
                section_total += count
                found_any = True
            print(f"  - {table}: {_fmt(count)}")
        print(f"  => section_total: {section_total if found_any else 'N/A'}")
        print("")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
