"""Fuzzy-нормализация брендов для поиска в ТРОИС (#151)."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

# Распространённые кириллические написания латинских брендов
CYRILLIC_ALIASES: dict[str, str] = {
    "найк": "nike",
    "найкe": "nike",
    "эппл": "apple",
    "эпл": "apple",
    "самсунг": "samsung",
    "сяоми": "xiaomi",
    "шанель": "chanel",
    "шанел": "chanel",
    "адidas": "adidas",
    "адидас": "adidas",
    "гуcci": "gucci",
    "гуччи": "gucci",
    "лего": "lego",
    "айфон": "apple",
    "iphone": "apple",
}

_LEET_MAP = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t"})


def normalize_brand_key(raw: str) -> str:
    """Базовая нормализация ключа бренда для поиска."""
    s = (raw or "").strip().lower()
    s = s.translate(_LEET_MAP)
    s = re.sub(r"[^\w\sа-яё-]", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()
    if s in CYRILLIC_ALIASES:
        s = CYRILLIC_ALIASES[s]
    for cyr, lat in CYRILLIC_ALIASES.items():
        if cyr in s and len(cyr) >= 4:
            s = s.replace(cyr, lat)
    return s


def fuzzy_variants(query: str) -> list[str]:
    """Варианты запроса для поиска: оригинал, без пробелов, leet, алиасы."""
    base = normalize_brand_key(query)
    if not base:
        return []
    out: list[str] = [base]
    compact = base.replace(" ", "").replace("-", "")
    if compact and compact not in out:
        out.append(compact)
    # Первое слово (Apple MacBook → apple)
    first = base.split()[0] if base.split() else base
    if first and first not in out:
        out.append(first)
    return list(dict.fromkeys(out))


def fuzzy_match_score(query: str, candidate: str) -> float:
    """Оценка похожести 0..1 между запросом и кандидатом."""
    q = normalize_brand_key(query)
    c = normalize_brand_key(candidate)
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0
    if q in c or c in q:
        return 0.85 + 0.1 * (len(q) / max(len(c), 1))
    return SequenceMatcher(None, q, c).ratio()
