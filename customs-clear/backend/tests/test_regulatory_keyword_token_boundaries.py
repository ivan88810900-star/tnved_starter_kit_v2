"""Regression tests for bounded alcohol keywords in regulatory HS mapping."""
from __future__ import annotations

import pytest

from app.services.regulatory_ai_classifier import _extract_keyword_hs_codes


def _prefixes(text: str) -> set[str]:
    return {prefix for prefix, _keyword in _extract_keyword_hs_codes(text)}


@pytest.mark.parametrize(
    ("text", "unexpected_prefix"),
    [
        ("Контроль столового винограда", "2204"),
        ("Ответственность виновного лица", "2204"),
        ("Изделие крапивового цвета", "2203"),
        ("Анализ виноградного сырья", "2204"),
        ("Описание авинового образца", "2204"),
        ("Описание апивового образца", "2203"),
    ],
)
def test_unrelated_words_do_not_create_alcohol_hs_mapping(
    text: str,
    unexpected_prefix: str,
) -> None:
    assert unexpected_prefix not in _prefixes(text)


@pytest.mark.parametrize(
    ("text", "unexpected_prefix"),
    [
        ("вино\u0301", "2204"),
        ("вино\u200d", "2204"),
        ("вино＿", "2204"),
        ("＿вино", "2204"),
        ("\u200dвино", "2204"),
        ("пиво\u0301", "2203"),
        ("пиво\u200d", "2203"),
        ("пиво＿", "2203"),
        ("＿пиво", "2203"),
        ("\u200dпиво", "2203"),
    ],
)
def test_unicode_token_continuations_are_rejected(
    text: str,
    unexpected_prefix: str,
) -> None:
    assert unexpected_prefix not in _prefixes(text)


@pytest.mark.parametrize(
    ("text", "expected_prefix"),
    [
        ("Категория: вино", "2204"),
        ("Правила оборота вином", "2204"),
        ("Категория: пиво", "2203"),
        ("Правила торговли пивом", "2203"),
        ("вино, импорт", "2204"),
        ("пиво. импорт", "2203"),
        ("вино\u00a0импорт", "2204"),
        ("пиво\u2003импорт", "2203"),
    ],
)
def test_existing_bounded_forms_and_separators_still_match(
    text: str,
    expected_prefix: str,
) -> None:
    assert expected_prefix in _prefixes(text)


@pytest.mark.parametrize(
    ("text", "unexpected_prefix"),
    [
        ("Ввоз вина", "2204"),
        ("Ввоз пива", "2203"),
    ],
)
def test_change_does_not_expand_legacy_keyword_forms(
    text: str,
    unexpected_prefix: str,
) -> None:
    assert unexpected_prefix not in _prefixes(text)


def test_other_stem_keyword_matching_is_unchanged() -> None:
    assert "3004" in _prefixes("Контроль лекарственных средств")


def test_valid_later_occurrence_is_not_masked_by_false_prefix() -> None:
    assert "2204" in _prefixes("Виноград не относится к запросу; вино относится")
