#!/usr/bin/env python3
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
    groups: list[tuple[str, list[str]]] = [
        ("Дерево ТН ВЭД", ["tnved_sections", "tnved_chapters", "tnved_commodities"]),
        ("Пошлины и налоги", ["hs_rates", "hs_duty_rules", "vat_preferences"]),
        ("Нетарифные меры", ["non_tariff_rules", "non_tariff_measures"]),
    ]

    print("=== DB Reference Tables Status ===")
    print(f"DB URL: {engine.url}")
    print("")

    for title, tables in groups:
        print(f"[{title}]")
        for table in tables:
            count = _count_table(table)
            print(f"  - {table}: {_fmt(count)}")
        print("")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

