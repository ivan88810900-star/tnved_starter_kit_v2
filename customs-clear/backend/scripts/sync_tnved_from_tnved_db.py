#!/usr/bin/env python3
"""
Копирует таблицы tnved_sections / tnved_chapters / tnved_commodities
из БД парсера PDF (backend/tnved.db) в БД CustomsClear (customs.db).

Парсер: backend/app/services/source_sync/pdf_parser.py пишет в sqlite по DB_URL бэкенда TN VED Pro.

Запуск (из customs-clear/backend):
  PYTHONPATH=. python scripts/sync_tnved_from_tnved_db.py

Переменные окружения:
  TNVED_SOURCE_DB — путь к sqlite-источнику (по умолчанию ../../backend/tnved.db относительно customs-clear/backend)
  DATABASE_URL — как в приложении (по умолчанию sqlite:///./customs.db)
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
from pathlib import Path

# корень customs-clear/backend
_HERE = Path(__file__).resolve().parent.parent


def _sqlite_path_from_url(url: str) -> Path:
    if url.startswith("sqlite:///"):
        raw = url.replace("sqlite:///", "", 1)
        p = Path(raw)
        if not p.is_absolute():
            p = (_HERE / p).resolve()
        return p
    raise SystemExit(f"Ожидается sqlite:///..., получено: {url[:80]}")


def _configure_sqlite_conn(conn: sqlite3.Connection, *, enable_wal: bool) -> None:
    cur = conn.cursor()
    try:
        cur.execute("PRAGMA busy_timeout = 30000")
        if enable_wal:
            cur.execute("PRAGMA journal_mode = WAL")
            cur.execute("PRAGMA synchronous = NORMAL")
        cur.execute("PRAGMA foreign_keys = ON")
    finally:
        cur.close()


def main() -> int:
    # Парсер пишет в sqlite из backend/db.py (часто tnved.db в корне репозитория)
    _root = _HERE.parent.parent
    _candidates = [_root / "tnved.db", _root / "backend" / "tnved.db"]
    default_src = next((p for p in _candidates if p.is_file()), _candidates[0])
    src = Path(os.environ.get("TNVED_SOURCE_DB", str(default_src))).resolve()
    db_url = os.environ.get("DATABASE_URL", "sqlite:///./customs.db")
    dst = _sqlite_path_from_url(db_url)

    if not src.is_file():
        print(f"[sync] Нет файла источника: {src}", file=sys.stderr)
        print("[sync] Сначала выполните импорт PDF:", file=sys.stderr)
        print("  cd ../../backend && python app/services/source_sync/pdf_parser.py --clear", file=sys.stderr)
        return 1

    if not dst.is_file():
        print(f"[sync] Нет целевой БД: {dst} — выполните alembic upgrade и init_db.", file=sys.stderr)
        return 1

    print(f"[sync] Источник: {src}")
    print(f"[sync] Назначение: {dst}")

    s = sqlite3.connect(str(src), timeout=30)
    d = sqlite3.connect(str(dst), timeout=30)
    _configure_sqlite_conn(s, enable_wal=False)
    _configure_sqlite_conn(d, enable_wal=True)
    d.execute("PRAGMA foreign_keys = OFF")
    try:
        cur = d.cursor()
        cur.execute("DELETE FROM tnved_commodities")
        cur.execute("DELETE FROM tnved_chapters")
        cur.execute("DELETE FROM tnved_sections")

        n_sec = s.execute("SELECT COUNT(*) FROM tnved_sections").fetchone()[0]
        n_ch = s.execute("SELECT COUNT(*) FROM tnved_chapters").fetchone()[0]
        n_co = s.execute("SELECT COUNT(*) FROM tnved_commodities").fetchone()[0]
        print(f"[sync] В источнике: разделов={n_sec}, групп={n_ch}, позиций={n_co}")

        cur.executemany(
            "INSERT INTO tnved_sections (id, roman_number, title, notes) VALUES (?,?,?,?)",
            s.execute("SELECT id, roman_number, title, notes FROM tnved_sections").fetchall(),
        )
        cur.executemany(
            "INSERT INTO tnved_chapters (id, section_id, code, title, notes) VALUES (?,?,?,?,?)",
            s.execute("SELECT id, section_id, code, title, notes FROM tnved_chapters").fetchall(),
        )
        cur.executemany(
            "INSERT INTO tnved_commodities (id, chapter_id, code, description, unit, import_duty) VALUES (?,?,?,?,?,?)",
            s.execute(
                "SELECT id, chapter_id, code, description, unit, import_duty FROM tnved_commodities"
            ).fetchall(),
        )
        d.commit()

        def _set_seq(table: str) -> None:
            mx = cur.execute(f"SELECT MAX(id) FROM {table}").fetchone()[0]
            if mx is None:
                return
            has_seq = cur.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'"
            ).fetchone()
            if not has_seq:
                return
            cur.execute(
                "INSERT OR REPLACE INTO sqlite_sequence(name,seq) VALUES (?,?)",
                (table, mx),
            )

        for t in ("tnved_sections", "tnved_chapters", "tnved_commodities"):
            _set_seq(t)
        d.commit()

        d.execute("PRAGMA foreign_keys = ON")
        print(
            f"[sync] Готово. В {dst.name}: "
            f"разделов={d.execute('SELECT COUNT(*) FROM tnved_sections').fetchone()[0]}, "
            f"групп={d.execute('SELECT COUNT(*) FROM tnved_chapters').fetchone()[0]}, "
            f"позиций={d.execute('SELECT COUNT(*) FROM tnved_commodities').fetchone()[0]}"
        )
    finally:
        s.close()
        d.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
