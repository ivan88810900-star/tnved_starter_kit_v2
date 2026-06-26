"""Tests for regulatory_ai_classifier — HS extraction and keyword binding."""
from __future__ import annotations

import pytest

from app.services.regulatory_ai_classifier import (
    _extract_explicit_hs_codes,
    _extract_keyword_hs_codes,
)


class TestExtractExplicitHsCodes:
    def test_standalone_6digit(self) -> None:
        codes = _extract_explicit_hs_codes("товар 851712 подлежит декларированию")
        assert "851712" in codes

    def test_standalone_10digit(self) -> None:
        codes = _extract_explicit_hs_codes("код 8517120000 на импорт")
        assert "8517120000" in codes

    def test_tnved_context_4digit(self) -> None:
        codes = _extract_explicit_hs_codes("код ТН ВЭД 8517 включает телефоны")
        assert "8517" in codes

    def test_tnved_context_eaes_4digit(self) -> None:
        codes = _extract_explicit_hs_codes("позиция ТН ВЭД ЕАЭС 8528 — телевизоры")
        assert "8528" in codes

    def test_no_false_positive_random_number(self) -> None:
        codes = _extract_explicit_hs_codes("В 2023 году объём составил 993456 тонн")
        assert len(codes) == 0

    def test_rejects_chapter_above_97(self) -> None:
        codes = _extract_explicit_hs_codes("код ТН ВЭД 9901 — это не товар")
        assert len(codes) == 0

    def test_empty_text(self) -> None:
        assert _extract_explicit_hs_codes("") == []
        assert _extract_explicit_hs_codes(None) == []

    def test_multiple_codes_dedup(self) -> None:
        codes = _extract_explicit_hs_codes("ТН ВЭД 8517, товар 851712, код 8517120000")
        assert len(codes) == 3
        assert codes[0] == "8517"

    def test_subpoziciya_context(self) -> None:
        codes = _extract_explicit_hs_codes("субпозиция 0201 включает говядину")
        assert "0201" in codes

    def test_8digit_standalone(self) -> None:
        codes = _extract_explicit_hs_codes("код 85171200 подлежит контролю")
        assert "85171200" in codes


class TestExtractKeywordHsCodes:
    def test_smartphone(self) -> None:
        hits = _extract_keyword_hs_codes("Ввоз смартфонов из КНР")
        prefixes = [h[0] for h in hits]
        assert "851712" in prefixes

    def test_multiple_keywords(self) -> None:
        hits = _extract_keyword_hs_codes("Лекарства и косметика на импорт")
        prefixes = [h[0] for h in hits]
        assert "3004" in prefixes
        assert "3304" in prefixes

    def test_case_insensitive(self) -> None:
        hits = _extract_keyword_hs_codes("БЕНЗИН автомобильный")
        prefixes = [h[0] for h in hits]
        assert "2710" in prefixes

    def test_no_match(self) -> None:
        hits = _extract_keyword_hs_codes("О порядке заполнения деклараций")
        assert len(hits) == 0

    def test_empty(self) -> None:
        assert _extract_keyword_hs_codes("") == []
        assert _extract_keyword_hs_codes(None) == []

    def test_partial_match_lekars(self) -> None:
        hits = _extract_keyword_hs_codes("Контроль лекарственных средств")
        prefixes = [h[0] for h in hits]
        assert "3004" in prefixes

    def test_alcohol(self) -> None:
        hits = _extract_keyword_hs_codes("Контроль алкогольной продукции")
        prefixes = [h[0] for h in hits]
        assert "2208" in prefixes

    def test_dedup_prefixes(self) -> None:
        hits = _extract_keyword_hs_codes("телефон мобильный и мобильный телефон и смартфон")
        prefixes = [h[0] for h in hits]
        assert prefixes.count("851712") == 1

    def test_clothing_returns_multiple_chapters(self) -> None:
        hits = _extract_keyword_hs_codes("Маркировка одежды")
        prefixes = [h[0] for h in hits]
        assert "61" in prefixes
        assert "62" in prefixes

    def test_pesticide(self) -> None:
        hits = _extract_keyword_hs_codes("Регистрация пестицидов и гербицидов")
        prefixes = [h[0] for h in hits]
        assert "3808" in prefixes
