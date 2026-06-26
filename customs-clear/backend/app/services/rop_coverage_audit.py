"""
Системный аудит покрытия РОП по 97 главам ТН ВЭД.

Основание: ФЗ №89, ПП №2414 (перечень), маппинг HS в rop_goods_rates.
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from ..models.rop import RopGoodsRate
from ..models.tnved import Chapter

# Главы, где типично нет готовых изделий из перечня РОП (навал/сырьё) — not_subject
_BULK_CHAPTER_HINTS: frozenset[str] = frozenset(
    {
        "01",  # живые животные
        "02",  # мясо (частично — но не в 16 группах как готовая продукция обычно)
        "05",  # шерсть/волос (сырьё)
        "26",  # руды
        "27",  # минеральное сырьё (нефтепродукты — частично в группе 4)
        "72",  # чугун/сталь навалом
        "73",  # прокат навалом
        "74",  # медь слитки
        "75",  # никель
        "76",  # алюминий слитки
        "78",  # свинец
        "79",  # цинк
        "80",  # олово
        "81",  # прочие металлы
    }
)


def _norm_prefix(raw: str) -> str:
    return re.sub(r"\D", "", (raw or "").strip())[:10]


def _parse_prefixes(row: RopGoodsRate) -> list[str]:
    try:
        data = json.loads(row.hs_prefixes_json or "[]")
        return [_norm_prefix(str(x)) for x in data if str(x).strip()]
    except json.JSONDecodeError:
        return []


def _chapter_matches_prefix(chapter_code: str, prefix: str) -> bool:
    ch = _norm_prefix(chapter_code)[:2]
    p = _norm_prefix(prefix)
    if not ch or not p:
        return False
    return ch.startswith(p) or p.startswith(ch)


def build_rop_chapter_coverage(session: Session, *, calendar_year: int = 2026) -> list[dict[str, Any]]:
    """Матрица покрытия для глав 01–97."""
    goods_rows = session.query(RopGoodsRate).filter(RopGoodsRate.calendar_year == calendar_year).all()
    chapters = session.query(Chapter).order_by(Chapter.code).all()

    # Если chapters пуст — синтетические 01..97
    if not chapters:
        chapter_codes = [f"{i:02d}" for i in range(1, 98)]
    else:
        chapter_codes = sorted({str(c.code).zfill(2)[:2] for c in chapters if c.code})

    matrix: list[dict[str, Any]] = []
    for ch in chapter_codes:
        matched_groups: list[dict[str, Any]] = []
        verified = True
        for row in goods_rows:
            for pfx in _parse_prefixes(row):
                if _chapter_matches_prefix(ch, pfx):
                    matched_groups.append(
                        {
                            "pp2414_group": row.pp2414_group,
                            "category_name": row.category_name,
                            "rate_per_ton": row.rate_per_ton,
                            "needs_verification": row.needs_verification,
                        }
                    )
                    if row.needs_verification:
                        verified = False
                    break

        if matched_groups:
            subject = "partial" if len(matched_groups) == 1 and ch in _BULK_CHAPTER_HINTS else "yes"
            verified = not any(g["needs_verification"] for g in matched_groups)
        elif ch in _BULK_CHAPTER_HINTS:
            subject = "no"
            verified = True
        else:
            subject = "no"
            verified = False  # не mapped — needs review

        matrix.append(
            {
                "chapter": ch,
                "subject_to_rop": subject,
                "rate_verified": verified and subject == "yes",
                "not_subject": subject == "no",
                "needs_verification": subject != "no" and not verified,
                "matched_groups": matched_groups,
                "legal_ref": "ФЗ №89; ПП №2414; ПП №1041",
                "coverage_note": (
                    f"{len(matched_groups)} групп(ы) ПП №2414"
                    if matched_groups
                    else ("сырьё/навал — вне перечня готовых изделий" if ch in _BULK_CHAPTER_HINTS else "маппинг не задан")
                ),
            }
        )
    return matrix


def coverage_summary(matrix: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total_chapters": len(matrix),
        "subject_yes": sum(1 for r in matrix if r["subject_to_rop"] == "yes"),
        "subject_partial": sum(1 for r in matrix if r["subject_to_rop"] == "partial"),
        "not_subject": sum(1 for r in matrix if r["not_subject"]),
        "needs_verification": sum(1 for r in matrix if r["needs_verification"]),
    }
