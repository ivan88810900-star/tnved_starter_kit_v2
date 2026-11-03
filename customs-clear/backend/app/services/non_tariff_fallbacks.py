"""Database-free fallback product scopes for non-tariff requirements."""
from __future__ import annotations

from typing import Any


FALLBACK_RULES: list[dict[str, Any]] = [
    {
        "name": "Бытовая электроника",
        "hs_prefixes": ["8509", "8516", "8517", "8471", "8472"],
        "tr_ts": ["004/2011", "020/2011", "037/2016"],
        "required_permits": ["СС", "ДС"],
    },
    {
        "name": "Косметика и парфюмерия",
        "hs_prefixes": ["3304", "3305", "3307"],
        "tr_ts": ["009/2011", "021/2011"],
        "required_permits": ["ДС"],
    },
    {
        "name": "Одежда 1-й слой",
        "hs_prefixes": ["6101", "6102", "6201", "6202", "6109", "6209"],
        "tr_ts": ["017/2011"],
        "required_permits": ["СС"],
    },
    {
        "name": "Одежда 2–3 слой",
        "hs_prefixes": ["6103", "6104", "6203", "6204", "6110", "6210"],
        "tr_ts": ["017/2011"],
        "required_permits": ["ДС"],
    },
    {
        "name": "Ткани хлопковые",
        "hs_prefixes": ["5208", "5209", "5210", "5211", "5212"],
        "tr_ts": ["017/2011"],
        "required_permits": ["ДС"],
    },
    {
        "name": "Детские товары",
        "hs_prefixes": ["9503", "9403", "6307", "9619", "6209"],
        "tr_ts": ["007/2011"],
        "required_permits": ["СС"],
    },
    {
        "name": "Посуда керамическая",
        "hs_prefixes": ["6911", "6912", "6913"],
        "tr_ts": ["021/2011"],
        "required_permits": ["ДС"],
    },
    {
        "name": "Игрушки",
        "hs_prefixes": ["9503"],
        "tr_ts": ["008/2011"],
        "required_permits": ["СС"],
    },
    {
        "name": "Лекарственные средства",
        "hs_prefixes": ["3004"],
        "tr_ts": ["061/2012"],
        "required_permits": ["РУ"],
    },
]


TR_TS_FALLBACK_PREFIXES: frozenset[str] = frozenset(
    prefix
    for rule in FALLBACK_RULES
    if rule.get("tr_ts")
    for prefix in rule.get("hs_prefixes", [])
)
