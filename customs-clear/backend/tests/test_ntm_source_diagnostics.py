"""Тесты диагностики источников NTM (без изменения production check)."""

from __future__ import annotations

from unittest.mock import patch

from app.services.ntm_source_diagnostics import (
    compare_ntm_requirement_sources,
    run_ntm_source_matrix,
    _rules_to_keys,
    _rows_to_keys,
)


def test_rules_to_keys_cartesian() -> None:
    rules = [
        {
            "name": "x",
            "required_permits": ["СС", "ДС"],
            "tr_ts": ["004/2011"],
        }
    ]
    k = _rules_to_keys(rules)
    assert k == {("СС", "004/2011"), ("ДС", "004/2011")}


def test_rows_to_keys_none_tr_ts() -> None:
    rows = [{"permit_type": "ВС", "tr_ts": None}]
    assert _rows_to_keys(rows) == {("ВС", "")}


def test_compare_overlap_mocked() -> None:
    fake_rules = [
        {
            "name": "seed",
            "hs_prefix": "9999",
            "required_permits": ["СС", "ДС"],
            "tr_ts": ["004/2011"],
            "tr_ts_edition": "",
            "exception_note": "",
            "priority": 0,
            "source_url": "",
            "source_revision": "t",
        }
    ]
    fake_catalog = [{"permit_type": "СС", "tr_ts": "004/2011", "matched_prefix": "9999"}]
    fake_layers: list[dict] = []
    fake_measures: list[dict] = []

    with (
        patch(
            "app.services.ntm_source_diagnostics.find_rules_for_code",
            return_value=fake_rules,
        ),
        patch(
            "app.services.non_tariff_service._sanitize_ntm_rules_for_position",
            side_effect=lambda hs, d, rs: rs,
        ),
        patch(
            "app.services.ntm_source_diagnostics.get_tr_ts_requirements",
            return_value=fake_catalog,
        ),
        patch(
            "app.services.ntm_source_diagnostics.get_all_layer_requirements",
            return_value=fake_layers,
        ),
        patch(
            "app.services.ntm_source_diagnostics.find_measures_for_code",
            return_value=fake_measures,
        ),
        patch(
            "app.services.ntm_source_diagnostics.get_sensitive_override",
            return_value=None,
        ),
        patch(
            "app.services.ntm_source_diagnostics.find_measures_by_description",
            return_value=[],
        ),
    ):
        out = compare_ntm_requirement_sources("9999999999", "", include_triggers=False)

    assert "ДС|004/2011" in out["only_in_rules"]
    assert "СС|004/2011" in out["rules_and_catalog_overlap"]
    assert out["only_in_catalog"] == []
    assert out["only_in_layers"] == []
    assert out["suspected_duplicates"] == ["СС|004/2011"]


def test_measures_only_when_measure_has_unique_permit() -> None:
    fake_rules: list = []
    fake_catalog: list = []
    fake_layers: list = []
    fake_measures = [
        {
            "commodity_code": "9999999999",
            "measure_type": "other",
            "description": "",
            "document_required": "",
            "legal_ref": "",
            "permit_type": "КВ",
            "tr_ts_code": "",
            "match_prefix_len": 10,
            "source_level": "exact",
            "direction": "import",
        }
    ]
    with (
        patch("app.services.ntm_source_diagnostics.find_rules_for_code", return_value=[]),
        patch(
            "app.services.non_tariff_service._sanitize_ntm_rules_for_position",
            side_effect=lambda hs, d, rs: rs,
        ),
        patch("app.services.ntm_source_diagnostics.get_tr_ts_requirements", return_value=[]),
        patch("app.services.ntm_source_diagnostics.get_all_layer_requirements", return_value=[]),
        patch(
            "app.services.ntm_source_diagnostics.find_measures_for_code",
            return_value=fake_measures,
        ),
        patch("app.services.ntm_source_diagnostics.get_sensitive_override", return_value=None),
        patch(
            "app.services.ntm_source_diagnostics.find_measures_by_description",
            return_value=[],
        ),
    ):
        out = compare_ntm_requirement_sources("9999999999", "", include_triggers=False)
    assert "КВ|" in out["measures_only"]


def test_run_matrix_smoke() -> None:
    cases = [
        ("8471300000", "Ноутбук"),
        ("3304990000", "Косметика"),
    ]
    rows = run_ntm_source_matrix(cases, include_triggers=False)
    assert len(rows) == 2
    for r in rows:
        assert "counts" in r
        assert "only_in_rules" in r


def test_compare_does_not_mutate_production_check_contract() -> None:
    """Проверка: импорт диагностики не ломает check_position_non_tariff."""
    from app.services.non_tariff_service import check_position_non_tariff

    assert callable(check_position_non_tariff)
