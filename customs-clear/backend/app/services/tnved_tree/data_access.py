"""Доступ к данным БД для построения дерева ТН ВЭД (без FastAPI)."""

from __future__ import annotations

from sqlalchemy.orm import Session, joinedload

from ...models.tnved import Chapter, Commodity
from .helpers import OBSOLETE_RESERVED_DESC_PREFIX, digits


def exclude_obsolete_reserved(q):
    return q.filter(~Commodity.description.like(f"{OBSOLETE_RESERVED_DESC_PREFIX}%"))


def collect_chapter_notes(db: Session) -> dict[str, str]:
    """
    Собирает объединённые примечания (раздел + группа) для каждого кода главы.
    Ключ — 4-значный код группы (zfill(4)).
    """
    chs = db.query(Chapter).options(joinedload(Chapter.section)).all()
    result: dict[str, str] = {}
    for ch in chs:
        d = digits(ch.code or "")
        if not d:
            continue
        key = d.zfill(4)
        parts: list[str] = []
        sec = ch.section
        if sec and (sec.notes or "").strip():
            parts.append(f"Раздел {sec.roman_number}:\n{sec.notes.strip()}")
        if (ch.notes or "").strip():
            parts.append(f"Группа {ch.code}:\n{ch.notes.strip()}")
        result[key] = "\n\n".join(parts)
    return result
