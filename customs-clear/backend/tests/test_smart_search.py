"""Tests for Issue #96: smart search with synonyms and fuzzy matching."""
import pytest
from app.services.normative_store import _expand_query_terms, get_search_suggestions


class TestExpandQueryTerms:
    def test_planshет_expands(self):
        terms = _expand_query_terms("планшет")
        assert "портативн" in terms or "8471" in terms

    def test_notebook_expands(self):
        terms = _expand_query_terms("ноутбук")
        assert "портативн" in terms
        assert "вычислительн" in terms
        assert "8471" in terms

    def test_phone_expands(self):
        terms = _expand_query_terms("телефон")
        assert "аппарат телефонн" in terms
        assert "8517" in terms

    def test_fridge_expands(self):
        terms = _expand_query_terms("холодильник")
        assert "8418" in terms

    def test_car_expands(self):
        terms = _expand_query_terms("автомобиль")
        assert "8703" in terms
        assert "моторн транспортн" in terms

    def test_shoes_expands(self):
        terms = _expand_query_terms("обувь")
        assert any(c.startswith("640") for c in terms)

    def test_jacket_expands(self):
        terms = _expand_query_terms("куртка")
        assert "6201" in terms or "6202" in terms

    def test_original_term_kept(self):
        terms = _expand_query_terms("стол")
        assert "стол" in terms

    def test_stem_trimming(self):
        terms = _expand_query_terms("яблоки")
        assert any("яблок" in t for t in terms)

    def test_empty_query(self):
        assert _expand_query_terms("") == []
        assert _expand_query_terms("  ") == []

    def test_digit_query_no_stem(self):
        terms = _expand_query_terms("8517")
        assert "8517" in terms

    def test_smartphone_expands(self):
        terms = _expand_query_terms("смартфон")
        assert "8517" in terms

    def test_tv_expands(self):
        terms = _expand_query_terms("телевизор")
        assert "8528" in terms


class TestSearchSuggestions:
    def test_returns_list(self):
        suggestions = get_search_suggestions()
        assert isinstance(suggestions, list)
        assert len(suggestions) >= 5

    def test_has_term_and_hint(self):
        for s in get_search_suggestions():
            assert "term" in s
            assert "hint" in s

    def test_includes_common_terms(self):
        terms = {s["term"] for s in get_search_suggestions()}
        assert "планшет" in terms
        assert "телефон" in terms
