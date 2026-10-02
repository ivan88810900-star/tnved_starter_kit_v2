"""Fail-closed helpers for matching NTM description hints."""

from __future__ import annotations

import unicodedata
from collections.abc import Collection, Sequence


def _continues_unicode_word(value: str, index: int) -> bool:
    if index < 0 or index >= len(value):
        return False
    char = value[index]
    category = unicodedata.category(char)
    return char.isalnum() or category.startswith("M") or category in {"Pc", "Cf"}


def _contains_whole_token(value: str, token: str) -> bool:
    start = 0
    while True:
        index = value.find(token, start)
        if index < 0:
            return False
        end = index + len(token)
        if not _continues_unicode_word(value, index - 1) and not _continues_unicode_word(value, end):
            return True
        start = index + 1


def first_description_match(
    description: str,
    triggers: Sequence[str],
    *,
    whole_tokens: Collection[str] = (),
) -> str | None:
    """Return the first trigger, requiring Unicode token bounds for selected hints."""
    value = (description or "").casefold()
    bounded = {str(token).casefold() for token in whole_tokens if str(token)}
    for trigger in triggers:
        needle = str(trigger).casefold()
        if not needle:
            continue
        if needle in bounded:
            if _contains_whole_token(value, needle):
                return str(trigger)
        elif needle in value:
            return str(trigger)
    return None
