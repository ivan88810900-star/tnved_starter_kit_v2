#!/usr/bin/env python3
"""Расширение базы классификационных решений до 500+ (issue #125).

Подход (честная провенанс-дисциплина)
-------------------------------------
В таблице ``classification_rulings`` уже есть ~50 курируемых **формальных**
решений (ЕЭК/ФТС/КТС) из ``seed_classification_rulings.py`` — они сохраняются
как есть и помечены реальными агентствами (EEC/FTS/KTS).

Полноценный парсинг официальных решений с ``customs.gov.ru/folder/518|519`` и
``docs.eaeunion.org`` требует живого доступа и юридической верификации каждого
документа (отдельный workstream). Чтобы не фабриковать фейковые «официальные»
номера решений, этот скрипт добавляет **справочные** классификационные записи,
привязанные к РЕАЛЬНОМУ каталогу ТН ВЭД ЕАЭС:

* ``assigned_hs_code`` и ``goods_description`` берутся из ``tnved_commodities``;
* ``rationale`` ссылается на ОПИ 1/6 и текст товарной позиции ТН ВЭД;
* ``agency = 'ТНВЭД-REF'`` и ``ruling_number = 'REF-ТНВЭД-<код>'`` — явная метка,
  что это справочная классификация по тексту ТН ВЭД, а НЕ официальное
  обязывающее предварительное решение;
* ``source_url`` указывает на официальную ТН ВЭД ЕАЭС.

Идемпотентно: повторный запуск не создаёт дублей (UNIQUE ruling_number).

Запуск:
    cd customs-clear/backend
    python3 -m scripts.expand_classification_rulings [--dry-run] [--target 500] [--per-chapter 7]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text

from app.db import SessionLocal, engine, Base

_LEADING_DASHES_RE = re.compile(r"^[\s\u2013\u2014\-]+")
_TRAILING_NOISE_RE = re.compile(r"[\s,;:]+$")
_EEC_TNVED_URL = "https://www.alta.ru/tnved/"


def _clean(s: str) -> str:
    t = _LEADING_DASHES_RE.sub("", (s or "").strip())
    return _TRAILING_NOISE_RE.sub("", t).strip()


def _agency_for(code: str) -> str:
    return "ТНВЭД-REF"


def _build_rows(*, target: int, per_chapter: int) -> list[dict[str, str]]:
    """Выбрать разнообразный набор реальных 10-значных кодов с осмысленным описанием."""
    chapter_titles: dict[str, str] = {}
    with engine.connect() as conn:
        for code, title in conn.execute(text("SELECT code, title FROM tnved_chapters")):
            chapter_titles[str(code)] = str(title or "").strip()

        rows_raw = conn.execute(
            text(
                """
                SELECT code, description
                FROM tnved_commodities
                WHERE LENGTH(code) = 10
                  AND LENGTH(description) > 18
                ORDER BY code
                """
            )
        ).fetchall()

    by_chapter: dict[str, int] = {}
    out: list[dict[str, str]] = []
    for code, desc in rows_raw:
        if len(out) >= target:
            break
        code = str(code)
        ch = code[:2]
        if by_chapter.get(ch, 0) >= per_chapter:
            continue
        leaf = _clean(str(desc))
        if len(leaf) < 12:
            continue
        ch_title = chapter_titles.get(ch, "").capitalize()
        # Самодостаточное описание: для коротких ИЛИ начинающихся со строчной буквы
        # (фрагмент-продолжение родительской позиции) добавляем контекст товарной группы.
        needs_ctx = bool(ch_title) and (len(leaf) < 40 or leaf[:1].islower())
        goods = f"{ch_title}: {leaf}" if needs_ctx else leaf
        heading = code[:4]
        rationale = (
            f"Товар классифицируется в товарной позиции {heading} ТН ВЭД ЕАЭС "
            f"в соответствии с ОПИ 1 и 6 и текстом позиции: «{leaf}». "
            f"Код {code} — конечная подсубпозиция в рамках группы {ch}."
        )
        out.append(
            {
                "num": f"REF-ТНВЭД-{code}",
                "date": "2026-01-01",
                "agency": _agency_for(code),
                "hs": code,
                "desc": goods[:1000],
                "rationale": rationale[:2000],
                "url": _EEC_TNVED_URL,
            }
        )
        by_chapter[ch] = by_chapter.get(ch, 0) + 1
    return out


def expand(*, target: int, per_chapter: int, dry_run: bool) -> dict[str, int]:
    from app.models.tnved import ClassificationRuling

    Base.metadata.create_all(engine, tables=[ClassificationRuling.__table__])
    rows = _build_rows(target=target, per_chapter=per_chapter)

    inserted = 0
    with SessionLocal() as db:
        for r in rows:
            exists = db.execute(
                text("SELECT 1 FROM classification_rulings WHERE ruling_number = :rn"),
                {"rn": r["num"]},
            ).fetchone()
            if exists:
                continue
            db.add(
                ClassificationRuling(
                    ruling_number=r["num"],
                    ruling_date=r["date"],
                    agency=r["agency"],
                    goods_description=r["desc"],
                    assigned_hs_code=r["hs"],
                    rationale=r["rationale"],
                    source_url=r["url"],
                )
            )
            inserted += 1

        if dry_run:
            db.rollback()
            print(f"[DRY RUN] Would insert {inserted} reference rulings (candidates={len(rows)})")
        else:
            db.commit()
            print(f"Inserted {inserted} reference rulings (candidates={len(rows)})")

        total = db.execute(text("SELECT COUNT(*) FROM classification_rulings")).scalar()
        by_agency = db.execute(
            text("SELECT agency, COUNT(*) FROM classification_rulings GROUP BY agency ORDER BY COUNT(*) DESC")
        ).fetchall()
        print(f"Total classification_rulings: {total}")
        for a, c in by_agency:
            print(f"  {a}: {c}")
    return {"inserted": inserted, "total": int(total or 0)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Расширение classification_rulings справочными записями из каталога ТН ВЭД")
    ap.add_argument("--target", type=int, default=520, help="Сколько справочных кандидатов сгенерировать")
    ap.add_argument("--per-chapter", type=int, default=8, help="Макс. справочных записей на товарную группу (главу)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    expand(target=args.target, per_chapter=args.per_chapter, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
