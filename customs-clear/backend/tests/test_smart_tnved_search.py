"""Deterministic quality checks for the product-facing TN VED hybrid search."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.services import tnved_fts
from app.services.normative_store import _expand_query_terms


@pytest.fixture()
def search_engine(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    engine = create_engine(f"sqlite:///{tmp_path / 'smart-search.db'}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE tnved_commodities ("
                "id INTEGER PRIMARY KEY, code TEXT NOT NULL, description TEXT NOT NULL)"
            )
        )
        rows = [
            (1, "8471", "Вычислительные машины и их блоки"),
            (2, "8471300000", "машины вычислительные портативные"),
            (3, "9022120000", "компьютерные томографы"),
            (4, "8516", "Электрические водонагреватели и электротермические приборы"),
            (5, "8516710000", "приборы для приготовления кофе или чая"),
            (6, "0902", "Чай со вкусо-ароматическими добавками или без них"),
            (7, "8508", "Пылесосы"),
            (8, "8508600000", "пылесосы прочие"),
            (9, "8517", "Аппараты телефонные, включая аппараты для сетей связи"),
            (10, "8517130000", "смартфоны"),
            (11, "8509400000", "измельчители пищевых продуктов"),
        ]
        conn.execute(
            text("INSERT INTO tnved_commodities(id, code, description) VALUES (:id, :code, :description)"),
            [{"id": row[0], "code": row[1], "description": row[2]} for row in rows],
        )

    monkeypatch.setattr(tnved_fts, "engine", engine)
    monkeypatch.setattr(tnved_fts, "_fts_ready", None)
    assert tnved_fts.ensure_fts_index(rebuild=True)
    yield engine
    engine.dispose()


def test_laptop_prefers_domain_family_over_computer_tomography(search_engine: Engine) -> None:
    outcome = tnved_fts.search_commodities_smart("ноутбук", limit=6)

    assert outcome["results"]
    assert outcome["results"][0]["code"] == "8471"
    codes = [row["code"] for row in outcome["results"]]
    assert codes.index("8471300000") < codes.index("9022120000")


def test_electric_kettle_does_not_match_tea_chapter_by_substring(search_engine: Engine) -> None:
    outcome = tnved_fts.search_commodities_smart("электрический чайник", limit=8)

    assert outcome["results"]
    assert outcome["results"][0]["code"] == "8516"
    assert not any(row["code"].startswith("0902") for row in outcome["results"])
    assert "8516" in _expand_query_terms("электрический чайник")
    assert "0902" not in _expand_query_terms("электрический чайник")
    assert "0902" in _expand_query_terms("зеленый чай")


@pytest.mark.parametrize(
    ("query", "correction", "expected_prefix"),
    [
        ("смартфн", "смартфон", "8517"),
        ("пылесосс", "пылесос", "8508"),
    ],
)
def test_common_typo_is_corrected_only_after_empty_original_search(
    search_engine: Engine,
    query: str,
    correction: str,
    expected_prefix: str,
) -> None:
    outcome = tnved_fts.search_commodities_smart(query, limit=8)

    assert outcome["corrected_query"] == correction
    assert outcome["strategy"] == "hybrid_fts_typo"
    assert outcome["results"]
    assert outcome["results"][0]["code"].startswith(expected_prefix)
    assert outcome["results"][0]["match_reason"] == "typo_correction"


def test_exact_code_remains_first_and_special_syntax_is_safe(search_engine: Engine) -> None:
    rows = tnved_fts.search_commodities_fts("8509 40 0000", limit=5)
    assert rows and rows[0]["code"] == "8509400000"

    for query in ('NOT OR AND', 'чайник* (электрический)', '"смартфон"'):
        outcome = tnved_fts.search_commodities_smart(query, limit=5)
        assert outcome["results"] is None or isinstance(outcome["results"], list)
