"""Подбор примеров СС/ДС под запрос (справочник + фильтр ТРОИС).

Полноценный поиск «любой действующий сертификат на товар» в открытом виде
через pub.fsa.gov.ru без парсинга/коммерческого API недоступен (часто 403).
Здесь — локальный **справочный** набор для UX и демонстрации фильтра по ТРОИС;
номера нужно **проверить** через «Проверка в реестре».
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from .trois_service import trouis_conflicts_in_text

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "permit_suggestions.json"
_SUGGESTIONS: Optional[List[Dict[str, Any]]] = None

DISCLAIMER_RU = (
    "Подбор выполняется по **внутреннему справочнику примеров**, а не полной выгрузке ФСА. "
    "Номера носят иллюстративный характер: перед использованием обязательно проверьте "
    "действительность в pub.fsa.gov.ru и соответствие вашей партии (ТН ВЭД, изготовитель, ТМ). "
    "Исключение брендов из локального кэша ТРОИС не заменяет официальную проверку реестра ФТС."
)


def _load_rows() -> List[Dict[str, Any]]:
    global _SUGGESTIONS
    if _SUGGESTIONS is not None:
        return _SUGGESTIONS
    if not _DATA_PATH.is_file():
        logger.warning(f"Нет файла подсказок: {_DATA_PATH}")
        _SUGGESTIONS = []
        return _SUGGESTIONS
    with open(_DATA_PATH, "r", encoding="utf-8") as f:
        _SUGGESTIONS = json.load(f)
    if not isinstance(_SUGGESTIONS, list):
        _SUGGESTIONS = []
    return _SUGGESTIONS


def _score_row(row: Dict[str, Any], q_low: str, hs_digits: str) -> int:
    score = 0
    if q_low:
        for kw in row.get("keywords") or []:
            kl = str(kw).lower()
            if kl and kl in q_low:
                score += 4
            if len(q_low) >= 4 and q_low in kl:
                score += 2
        for field in ("product_ru", "applicant_ru", "manufacturer", "trademark_note"):
            val = (row.get(field) or "").lower()
            if len(q_low) >= 4 and q_low in val:
                score += 1
    if hs_digits:
        for h in row.get("hs_suggest") or []:
            hd = re.sub(r"\D", "", str(h))[:10]
            if not hd:
                continue
            if hs_digits.startswith(hd) or hd.startswith(hs_digits[: min(6, len(hs_digits))]):
                score += 6
            elif len(hs_digits) >= 4 and len(hd) >= 4 and hs_digits[:4] == hd[:4]:
                score += 2
    return score


def _row_search_blob(row: Dict[str, Any]) -> str:
    parts = [
        row.get("product_ru"),
        row.get("applicant_ru"),
        row.get("manufacturer"),
        row.get("trademark_note"),
        row.get("number"),
    ]
    return " ".join(str(p) for p in parts if p)


async def suggest_permits(
    query: str,
    *,
    hs_code: str = "",
    doc_types: Optional[List[str]] = None,
    exclude_trois: bool = True,
    country_hint: str = "",
    limit: int = 25,
) -> Dict[str, Any]:
    """Возвращает отсортированные варианты из справочника."""
    q = (query or "").strip()
    q_low = q.lower()
    hs_digits = re.sub(r"\D", "", hs_code or "")[:10]

    types_filter = None
    if doc_types:
        types_filter = {t.strip().upper() for t in doc_types if t and str(t).strip()}

    rows = _load_rows()
    scored: List[tuple[int, Dict[str, Any]]] = []
    excluded_trois = 0

    ch = (country_hint or "").strip().upper()
    for row in rows:
        dt = (row.get("doc_type") or "").strip().upper()
        if types_filter and dt and dt not in types_filter:
            continue
        if ch == "CN":
            co = (row.get("country_of_origin") or "").upper()
            if co and co != "CN" and not row.get("is_public_registry_example"):
                continue

        blob = _row_search_blob(row)
        if exclude_trois and trouis_conflicts_in_text(blob):
            excluded_trois += 1
            continue

        sc = _score_row(row, q_low, hs_digits)
        if not q_low and not hs_digits:
            sc = 1
        if sc > 0 or (not q_low and not hs_digits):
            scored.append((sc, row))

    scored.sort(key=lambda x: (-x[0], x[1].get("id", "")))
    top = [dict(r) for _, r in scored[: max(1, min(limit, 100))]]

    return {
        "status": "OK",
        "query": q,
        "hs_code": hs_digits,
        "exclude_trois": exclude_trois,
        "excluded_trois_count": excluded_trois,
        "data_quality": "reference_only",
        "disclaimer": DISCLAIMER_RU,
        "items": top,
        "meta": {
            "source": str(_DATA_PATH.name),
            "matched": len(top),
            "hint": "Нажмите «Проверить в ФСА» у выбранной строки или используйте раздел «Документы».",
        },
    }
