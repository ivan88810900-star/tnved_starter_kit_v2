"""Заполняет колонку hs_codes.title_full полным «таможенным» текстом.

Алгоритм:
  1. Убеждаемся, что колонка title_full существует (SQLite: ALTER TABLE ADD COLUMN).
  2. Для каждого кода по возрастанию длины строим title_full:
     - для главы (2 цифры) берём из CHAPTER_TITLES или sanitize_title(title_ru);
     - для остальных — соединяем родителя и санированный собственный заголовок через « — ».
  3. Если у узла нет собственного заголовка — наследуем title_full родителя.
  4. Результат пакетно сохраняем в БД.

Запуск:
    cd backend
    python -m scripts.enrich_full_titles
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from sqlalchemy import text as sql_text

# Позволяем запускать как `python scripts/enrich_full_titles.py`
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import SessionLocal, engine  # noqa: E402
from app.routers.codes import (  # noqa: E402
    CHAPTER_TITLES,
    sanitize_title,
    is_garbage_code,
)


JOIN = " — "


def ensure_title_full_column() -> None:
    """Мягко добавляем колонку, если её нет (SQLite)."""
    with engine.begin() as conn:
        cols = conn.execute(sql_text("PRAGMA table_info(hs_codes)")).all()
        names = {row[1] for row in cols}
        if "title_full" not in names:
            print("[ETL] adding column hs_codes.title_full …")
            conn.execute(sql_text("ALTER TABLE hs_codes ADD COLUMN title_full TEXT"))
        else:
            print("[ETL] column hs_codes.title_full exists")


def sanitized_or_none(raw: str | None) -> str | None:
    s = sanitize_title(raw or "")
    if not s:
        return None
    if is_garbage_code("", s):
        return None
    return s


def base_chapter_title(code2: str, raw_title: str | None) -> str | None:
    """Официальное название главы: сначала фиксированный справочник, затем очищенный raw."""
    if code2 in CHAPTER_TITLES:
        return CHAPTER_TITLES[code2]
    return sanitized_or_none(raw_title)


def compute_title_full(
    code: str,
    raw_title: str | None,
    parent_full: str | None,
) -> str | None:
    """Главная функция: собираем полный текст по узлу.
    Возвращаем None, если совсем ничего не удалось нормализовать.
    """
    if len(code) == 2:
        return base_chapter_title(code, raw_title)

    own = sanitized_or_none(raw_title)
    if parent_full and own:
        pt = parent_full.rstrip(": ")
        ct = own.rstrip(": ")
        # Если свой текст начинается с родителя — не дублируем
        if ct.lower().startswith(pt.lower()):
            return ct
        return f"{pt}{JOIN}{ct}"
    if parent_full:
        return parent_full
    return own


def main() -> None:
    ensure_title_full_column()
    db = SessionLocal()
    try:
        rows = db.execute(
            sql_text("SELECT code, title_ru FROM hs_codes ORDER BY length(code), code")
        ).all()
        print(f"[ETL] rows to process: {len(rows)}")

        # Индексируем по коду для быстрого доступа к родителю
        raw_by_code: dict[str, str | None] = {r.code: r.title_ru for r in rows}
        full_by_code: dict[str, str | None] = {}

        def parent_of(c: str) -> str | None:
            if len(c) <= 2:
                return None
            # Ищем ближайшего существующего предка
            for prev_len in (8, 6, 4, 2):
                if prev_len >= len(c):
                    continue
                candidate = c[:prev_len]
                if candidate in raw_by_code:
                    return candidate
            return None

        updates: list[tuple[str | None, str]] = []
        for r in rows:
            code = r.code or ""
            if not code:
                continue
            parent_code = parent_of(code)
            parent_full = full_by_code.get(parent_code) if parent_code else None
            full = compute_title_full(code, r.title_ru, parent_full)
            full_by_code[code] = full
            updates.append((full, code))

        CHUNK = 500
        total = 0
        with engine.begin() as conn:
            for i in range(0, len(updates), CHUNK):
                batch = updates[i : i + CHUNK]
                conn.execute(
                    sql_text("UPDATE hs_codes SET title_full = :t WHERE code = :c"),
                    [{"t": t, "c": c} for t, c in batch],
                )
                total += len(batch)
                if i % (CHUNK * 10) == 0:
                    print(f"[ETL] updated {total}/{len(updates)}")
        print(f"[ETL] done, updated {total} rows")

        # Небольшой sanity-вывод
        sample_codes = ["10", "1001", "100110", "100119", "851713"]
        print("\n[ETL] samples:")
        for c in sample_codes:
            v = full_by_code.get(c) or "(нет данных)"
            print(f"  {c:>10}  →  {v}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
