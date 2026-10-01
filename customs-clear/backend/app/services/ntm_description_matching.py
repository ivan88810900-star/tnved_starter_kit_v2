"""Fail-closed helpers for matching NTM description hints."""

from __future__ import annotations

import unicodedata
from collections.abc import Collection, Sequence


_CHILD_TOKEN_PREFIXES = ("детск", "ребен", "младен", "baby")
_CHILD_TOKEN_FORMS = frozenset({"дети", "детей", "детям", "детьми", "детях"})
_DIRECT_NEGATIONS = frozenset({"не", "без", "кроме"})
_NEGATED_AUDIENCE_PREDICATES = (
    "предназнач",
    "подход",
    "рекоменд",
    "разработ",
    "использ",
)


def _normalize_audience_text(value: str) -> str:
    """Normalize compatibility characters/case and Russian diacritics."""
    return unicodedata.normalize("NFKC", value or "").casefold().replace("ё", "е")


def _unicode_tokens(value: str) -> list[str]:
    """Split on separators while keeping Unicode continuations in one token."""
    tokens: list[str] = []
    current: list[str] = []
    for char in _normalize_audience_text(value):
        category = unicodedata.category(char)
        if char.isalnum() or category.startswith("M") or category in {"Pc", "Cf"}:
            current.append(char)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return tokens


def _is_child_token(token: str) -> bool:
    return token in _CHILD_TOKEN_FORMS or token.startswith(_CHILD_TOKEN_PREFIXES)


def _is_fused_negated_child_token(token: str) -> bool:
    return token.startswith("не") and _is_child_token(token[2:])


def _child_token_is_negated(tokens: list[str], index: int) -> bool:
    if index and tokens[index - 1] in _DIRECT_NEGATIONS:
        return True
    if index >= 2 and tokens[index - 1] == "для" and tokens[index - 2] in _DIRECT_NEGATIONS:
        return True
    if index >= 3 and tokens[index - 1] == "для":
        predicate = tokens[index - 2]
        negator = tokens[index - 3]
        if negator == "не" and predicate.startswith(_NEGATED_AUDIENCE_PREDICATES):
            return True
        if predicate.startswith("не") and predicate[2:].startswith(_NEGATED_AUDIENCE_PREDICATES):
            return True
    return False


def is_child_product_description(description: str) -> bool:
    """Return true only for an explicit, non-negated child-audience token.

    Matching is Unicode-token aware: unrelated/fused words such as
    ``недетский`` and explicit phrases such as ``не детский`` fail closed,
    while a mixed audience (``для взрослых и детей``) remains a child audience.
    """
    tokens = _unicode_tokens(description)
    for index, token in enumerate(tokens):
        if _is_fused_negated_child_token(token):
            continue
        if _is_child_token(token) and not _child_token_is_negated(tokens, index):
            return True
    return False


def is_child_audience_marker(marker: str) -> bool:
    """Whether a configured description marker represents child audience."""
    tokens = _unicode_tokens(marker)
    # Curated rules may intentionally use the short stem ``дет``.  It is safe
    # for classifying configuration, but never accepted as a description token
    # by ``is_child_product_description`` (``деталь``/``детокс`` stay false).
    return any(token == "дет" or _is_child_token(token) for token in tokens)


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
