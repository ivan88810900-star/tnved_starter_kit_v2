"""Единая нормализация и сопоставление кодов ТН ВЭД (HS) для нетарифного контура.

Контракт: после ``normalize_hs_code`` код — строка из цифр длиной до 10 знаков;
привязка правил/мер к префиксу — через ``match_hs_prefix`` (семантика ``startswith``).
"""
from __future__ import annotations

import re
from typing import Sequence

_MAX_HS_DIGITS = 10


def normalize_hs_code(code: str | None) -> str:
    """
    Убирает пробелы и прочие нецифровые символы, оставляет до 10 знаков (позиция ТН ВЭД ЕАЭС).

    Пустой/безцифровой ввод → ``\"\"`` (как в справочниках проекта: ``_digits_hs``).
    """
    if code is None:
        return ""
    return re.sub(r"\D", "", str(code))[:_MAX_HS_DIGITS]


def get_hs_prefixes(code: str, levels: Sequence[int] = (10, 8, 6, 4, 2)) -> list[str]:
    """
    Префиксы от более точного к более общему среди заданных длин (только если длина кода позволяет).

    Пример: ``8517620000`` при ``levels=(10, 8, 6, 4, 2)`` →
    ``[\"8517620000\", \"85176200\", \"851762\", \"8517\", \"85\"]``.
    """
    norm = normalize_hs_code(code)
    if not norm:
        return []
    out: list[str] = []
    for length in levels:
        if length <= 0:
            continue
        if len(norm) >= length:
            out.append(norm[:length])
    return out


def match_hs_prefix(code: str, prefix: str) -> bool:
    """``normalize_hs_code(code).startswith(normalize_hs_code(prefix))``."""
    c = normalize_hs_code(code)
    p = normalize_hs_code(prefix)
    if not p:
        return False
    return c.startswith(p)


def specificity(prefix: str) -> int:
    """Длина нормализованного префикса (для сортировки: больше — точнее)."""
    return len(normalize_hs_code(prefix))
