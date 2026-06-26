"""Permit-типы (ДС/СС) для legacy /api/codes/* по главам ТН ВЭД.

Синхронизировано с customs-clear/app/services/tr_ts_catalog.py (укрупнённо).
"""

from __future__ import annotations

import re

# Главы → permit-типы (без ложных срабатываний для 84/85/86–89)
_CHAPTER_PERMIT_TYPES: dict[str, frozenset[str]] = {
    **{f"{i:02d}": frozenset({"ДС"}) for i in range(50, 64)},  # 017/2011
    "33": frozenset({"ДС"}),
    "64": frozenset({"ДС"}),
    "94": frozenset({"ДС"}),
    "95": frozenset({"ДС", "СС"}),
    **{f"{i:02d}": frozenset({"ДС"}) for i in (2, 3, 4, 7, 8, 9, 10, 11, 12, 15, 16, 17, 18, 19, 20, 21, 22, 23)},
    "39": frozenset({"ДС"}),
    "48": frozenset({"ДС"}),
}

# Явные исключения: префиксы без ДС (037/2016 для телефонов и т.п.)
_NO_DS_PREFIXES: frozenset[str] = frozenset(
    {
        "8517",
        "851713",
        "8401",
    }
)


def permit_measures_for_code(code: str) -> list[dict[str, str]]:
    """Возвращает [{type, document, description}] для 10-значного кода."""
    d = re.sub(r"\D", "", code or "")
    if len(d) < 10:
        return []
    if any(d.startswith(p) for p in _NO_DS_PREFIXES):
        return []
    ch = d[:2]
    types = _CHAPTER_PERMIT_TYPES.get(ch)
    if not types:
        return []
    doc_by_type = {
        "ДС": "ТР ТС (декларация соответствия)",
        "СС": "ТР ТС (сертификат соответствия)",
    }
    return [{"type": pt, "document": doc_by_type.get(pt, pt), "description": ""} for pt in sorted(types)]


def is_codeless_title(title: str | None) -> bool:
    t = (title or "").strip()
    return bool(t) and t.rstrip().endswith(":")
