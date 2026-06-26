"""Диагностика сравнения режимов префиксов для non_tariff_measures (без изменения production)."""

from __future__ import annotations

from unittest.mock import patch

from app.services.non_tariff_rules import diagnose_measures_prefix_strategies


def test_diagnose_counts_and_only_cumulative() -> None:
    cur = [
        {
            "commodity_code": "8517620001",
            "measure_type": "certificate",
            "description": "",
            "document_required": "",
            "legal_ref": "",
            "permit_type": "СС",
            "tr_ts_code": None,
            "match_prefix_len": 10,
            "source_level": "exact",
            "direction": "import",
        }
    ]
    cum = cur + [
        {
            "commodity_code": "8517000000",
            "measure_type": "declaration",
            "description": "",
            "document_required": "",
            "legal_ref": "",
            "permit_type": "ДС",
            "tr_ts_code": None,
            "match_prefix_len": 4,
            "source_level": "4_digit",
            "direction": "import",
        }
    ]
    with (
        patch("app.services.non_tariff_rules.find_measures_for_code", return_value=cur),
        patch(
            "app.services.non_tariff_rules._find_measures_cumulative_all_levels",
            return_value=cum,
        ),
    ):
        d = diagnose_measures_prefix_strategies("8517620000", direction="import")

    assert d["counts"] == {"current": 1, "cumulative": 2}
    assert len(d["only_in_cumulative"]) == 1
    assert d["only_in_cumulative"][0]["commodity_code"] == "8517000000"
    assert d["only_in_current"] == []
    assert "recommended_future_sort" in d


def test_diagnose_semantic_duplicate_grouping() -> None:
    """Две строки cumulative с одним compact_key (разные товары) — в отчёте группа."""
    cur: list[dict] = []
    cum = [
        {
            "commodity_code": "8517111111",
            "measure_type": "certificate",
            "description": "a",
            "document_required": "",
            "legal_ref": "L",
            "permit_type": "СС",
            "tr_ts_code": None,
            "match_prefix_len": 6,
            "source_level": "6_digit",
            "direction": "import",
        },
        {
            "commodity_code": "8517222222",
            "measure_type": "certificate",
            "description": "b",
            "document_required": "",
            "legal_ref": "L",
            "permit_type": "СС",
            "tr_ts_code": None,
            "match_prefix_len": 4,
            "source_level": "4_digit",
            "direction": "import",
        },
    ]
    with (
        patch("app.services.non_tariff_rules.find_measures_for_code", return_value=cur),
        patch(
            "app.services.non_tariff_rules._find_measures_cumulative_all_levels",
            return_value=cum,
        ),
    ):
        d = diagnose_measures_prefix_strategies("8517620000")

    dup = d["cumulative_semantic_duplicate_commodities"]
    assert dup
