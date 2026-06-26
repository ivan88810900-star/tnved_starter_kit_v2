#!/usr/bin/env python3
"""Аудит SQLite БД: список таблиц и число строк в каждой."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _sqlite_path_from_database_url(url: str) -> Path:
    u = (url or "").strip()
    if not u.startswith("sqlite:///"):
        raise RuntimeError(f"Ожидался sqlite URL, получено: {u or '(пусто)'}")
    return Path(u.replace("sqlite:///", "", 1)).resolve()


def _resolve_db_path(cli_db: str) -> Path:
    if (cli_db or "").strip():
        return Path(cli_db).expanduser().resolve()
    from app.db import DATABASE_URL

    return _sqlite_path_from_database_url(DATABASE_URL)


def _read_table_counts(db_path: Path) -> list[tuple[str, int]]:
    rows: list[tuple[str, int]] = []
    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        )
        table_names = [str(r[0]) for r in cur.fetchall()]
        for table_name in table_names:
            safe_name = table_name.replace('"', '""')
            cur.execute(f'SELECT COUNT(*) FROM "{safe_name}"')
            count = int(cur.fetchone()[0])
            rows.append((table_name, count))
    rows.sort(key=lambda x: (-x[1], x[0]))
    return rows


def _print_table(rows: list[tuple[str, int]]) -> None:
    if not rows:
        print("Таблицы не найдены.")
        return

    header_1 = "Название таблицы"
    header_2 = "Количество строк"
    w1 = max(len(header_1), *(len(name) for name, _ in rows))
    w2 = max(len(header_2), *(len(str(cnt)) for _, cnt in rows))
    sep = f"+-{'-' * w1}-+-{'-' * w2}-+"

    print(sep)
    print(f"| {header_1.ljust(w1)} | {header_2.rjust(w2)} |")
    print(sep)
    for name, cnt in rows:
        print(f"| {name.ljust(w1)} | {str(cnt).rjust(w2)} |")
    print(sep)
    print(f"Всего таблиц: {len(rows)}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Показать таблицы SQLite и число строк в каждой")
    ap.add_argument(
        "--db",
        type=str,
        default="",
        help="Путь до customs.db (если не указан, берется из app.db.DATABASE_URL)",
    )
    args = ap.parse_args()

    db_path = _resolve_db_path(args.db)
    if not db_path.exists():
        print(f"БД не найдена: {db_path}", file=sys.stderr)
        return 1

    rows = _read_table_counts(db_path)
    _print_table(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
