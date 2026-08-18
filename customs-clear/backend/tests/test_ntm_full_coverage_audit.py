from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError

from app.services import ntm_full_coverage_audit as audit_mod
from app.services.ntm_full_coverage_audit import audit_ntm_full_coverage


def test_structural_coverage_for_representative_codes() -> None:
    report = audit_ntm_full_coverage([
        ("0101210000", "лошадь племенная"),
        ("3004900000", "лекарственное средство"),
        ("6110209100", "джемпер хлопчатобумажный"),
        ("6912002300", "керамическая тарелка для взрослых"),
        ("8517620009", "маршрутизатор Wi-Fi с AES шифрованием"),
        ("9701100000", "старинная картина"),
    ])
    assert report["ok"] is True
    assert report["positions_evaluated"] == 6
    assert report["families_per_position"] == 9
    assert report["decision_299_sgr_ranges"] >= 90
    assert report["export_control_hs_candidates"] == 1087
    assert report["export_control_hs_candidates_raw"] == 1087
    assert report["export_control_hs_candidates_effective"] == 1085
    assert report["export_control_retired_exact_codes"] == 2
    assert report["export_control_identification_scope"] == "hs_candidates_only"
    assert report["export_control_technical_parameters_covered"] is False
    assert report["decision_30_sections_indexed"] == 30
    assert report["decision_30_sections_without_primary_filter"] == []
    assert report["enforcement_leak_count"] == 0
    assert report["official_contour_enforcement_leak_count"] == 0
    assert report["technical_regulations_registered"] == 53
    assert report["technical_regulations_unexpected_gaps"] == []
    assert report["technical_regulations_without_hs_filter"] == [
        "047/2018", "048/2019", "049/2020", "053/2026",
    ]
    assert report["requirements_evaluated"] > 0


def test_empty_position_set_is_not_a_successful_structural_audit(monkeypatch) -> None:
    monkeypatch.setattr(
        audit_mod,
        "load_export_control_dataset",
        lambda: {"hs_candidates": []},
    )
    assert audit_ntm_full_coverage([])["ok"] is False


def _complete_metadata() -> dict[str, Any]:
    baseline = audit_mod.load_catalog_baseline()
    return {
        "catalog_sections": 21,
        "catalog_chapters": 96,
        "catalog_rows": 17_809,
        "catalog_unique_codes": 17_809,
        "catalog_duplicate_rows": 0,
        "catalog_invalid_code_rows": 0,
        "description_rows": 17_774,
        "positions_loaded": 17_809,
        "active_ett_reference_available": True,
        "active_ett_reference_codes": 13_290,
        "active_ett_codes_present": 13_290,
        "active_ett_codes_described": 13_290,
        "active_ett_codes_missing": 0,
        "active_ett_codes_without_description": 0,
        "catalog_section_codes": baseline["catalog"]["section_codes"],
        "catalog_chapter_codes": baseline["catalog"]["chapter_codes"],
        "blank_description_codes": baseline["catalog"]["blank_description_codes"],
        "blank_codes_in_active_ett_snapshot": [],
        "blank_codes_not_in_active_ett_snapshot": baseline["catalog"]["blank_description_codes"],
        "overall_description_coverage_pct": 99.8035,
        "active_description_coverage_pct": 100.0,
        "catalog_baseline_available": True,
        "pdf_source_manifest_match": True,
        "active_ett_snapshot_match": True,
        "catalog_parser_match": True,
        "catalog_baseline_section_set_match": True,
        "catalog_baseline_chapter_set_match": True,
        "catalog_baseline_code_set_match": True,
        "catalog_baseline_code_description_match": True,
    }


def test_full_scope_exposes_reference_and_actual_counts() -> None:
    scope = audit_mod._catalog_scope(
        source="explicit_sqlite_tnved_commodities",
        positions_loaded=17_809,
        metadata=_complete_metadata(),
        limit=None,
    )
    assert scope["kind"] == "full_commodity_catalog"
    assert scope["full_catalog_verified"] is True
    assert scope["code_catalog_verified"] is True
    assert scope["reference_minimums"] == {
        "tnved_sections": 21,
        "tnved_chapters": 96,
        "tnved_commodities": 17_809,
        "commodity_descriptions": 17_774,
    }
    assert scope["actual_counts"]["positions_loaded"] == 17_809
    assert scope["actual_counts"]["blank_description_rows"] == 35
    assert scope["active_ett_description_complete"] is True
    assert scope["overall_description_coverage_pct"] == 99.8035
    assert scope["active_description_coverage_pct"] == 100.0


@pytest.mark.parametrize(
    ("metadata_key", "expected_reason"),
    [
        ("catalog_sections", "tnved_sections_not_equal_21"),
        ("catalog_chapters", "tnved_chapters_not_equal_96"),
        ("catalog_unique_codes", "tnved_commodities_not_equal_17809"),
        ("description_rows", "commodity_descriptions_below_17774"),
    ],
)
def test_full_scope_fails_each_reference_minimum(
    metadata_key: str,
    expected_reason: str,
) -> None:
    metadata = _complete_metadata()
    metadata[metadata_key] -= 1
    scope = audit_mod._catalog_scope(
        source="tnved_commodities",
        positions_loaded=17_809,
        metadata=metadata,
        limit=None,
    )
    assert scope["full_catalog_verified"] is False
    assert expected_reason in scope["full_catalog_gate_failures"]


def test_full_scope_rejects_an_extra_catalog_row() -> None:
    metadata = _complete_metadata()
    metadata["catalog_rows"] += 1
    metadata["catalog_unique_codes"] += 1
    scope = audit_mod._catalog_scope(
        source="tnved_commodities",
        positions_loaded=17_810,
        metadata=metadata,
        limit=None,
    )
    assert scope["full_catalog_verified"] is False
    assert "tnved_commodities_not_equal_17809" in scope["full_catalog_gate_failures"]
    assert "catalog_rows_not_equal_17809" in scope["full_catalog_gate_failures"]
    assert "positions_loaded_not_equal_17809" in scope["full_catalog_gate_failures"]


def test_full_scope_allows_fewer_blank_rows_after_reviewed_baseline_update() -> None:
    metadata = _complete_metadata()
    metadata["description_rows"] = 17_775
    metadata["blank_description_codes"] = metadata["blank_description_codes"][:-1]
    metadata["blank_codes_not_in_active_ett_snapshot"] = metadata["blank_description_codes"]
    scope = audit_mod._catalog_scope(
        source="tnved_commodities",
        positions_loaded=17_809,
        metadata=metadata,
        limit=None,
    )
    assert scope["full_catalog_verified"] is True
    assert scope["actual_counts"]["blank_description_rows"] == 34


def test_limited_and_code_only_scopes_cannot_claim_full_catalog() -> None:
    limited = audit_mod._catalog_scope(
        source="tnved_commodities",
        positions_loaded=100,
        metadata=_complete_metadata(),
        limit=100,
    )
    assert limited["kind"] == "limited_catalog_sample"
    assert limited["full_catalog_verified"] is False
    assert limited["code_catalog_verified"] is False

    code_only = audit_mod._catalog_scope(
        source="official_ett_rate_codes",
        positions_loaded=13_290,
        metadata={
            "catalog_sections": 0,
            "catalog_chapters": 0,
            "catalog_unique_codes": 13_290,
            "description_rows": 0,
            "active_ett_reference_available": True,
            "active_ett_reference_codes": 13_290,
            "active_ett_codes_present": 13_290,
            "active_ett_codes_described": 0,
        },
        limit=None,
    )
    assert code_only["kind"] == "code_only_catalog"
    assert code_only["code_catalog_verified"] is True
    assert code_only["full_catalog_verified"] is False


def test_full_scope_requires_every_active_ett_code_and_description() -> None:
    missing = _complete_metadata()
    missing["active_ett_codes_present"] -= 1
    missing["active_ett_codes_missing"] = 1
    missing_scope = audit_mod._catalog_scope(
        source="tnved_commodities",
        positions_loaded=17_809,
        metadata=missing,
        limit=None,
    )
    assert missing_scope["full_catalog_verified"] is False
    assert "active_ett_codes_missing_from_catalog" in missing_scope["full_catalog_gate_failures"]

    undescribed = _complete_metadata()
    undescribed["active_ett_codes_described"] -= 1
    undescribed["active_ett_codes_without_description"] = 1
    undescribed_scope = audit_mod._catalog_scope(
        source="tnved_commodities",
        positions_loaded=17_809,
        metadata=undescribed,
        limit=None,
    )
    assert undescribed_scope["full_catalog_verified"] is False
    assert "active_ett_codes_without_description" in undescribed_scope["full_catalog_gate_failures"]

    overlapping_blank = _complete_metadata()
    overlapping_blank["blank_codes_in_active_ett_snapshot"] = ["0101210000"]
    overlapping_scope = audit_mod._catalog_scope(
        source="tnved_commodities",
        positions_loaded=17_809,
        metadata=overlapping_blank,
        limit=None,
    )
    assert overlapping_scope["full_catalog_verified"] is False
    assert "blank_codes_overlap_active_ett_snapshot" in overlapping_scope["full_catalog_gate_failures"]


def _stub_audit(positions: Any) -> dict[str, Any]:
    count = len(list(positions))
    return {
        "positions_evaluated": count,
        "ok": count > 0,
        "requirement_family_counts": {
            row["family"]: 1 for row in audit_mod.OFFICIAL_NTM_FAMILIES
        },
        "decision_30_sections_observed": [
            row["section"] for row in audit_mod.DECISION_30_SECTIONS
        ],
        "decision_30_sections_not_observed": [],
    }


def test_build_defaults_to_fail_closed_but_allow_partial_is_explicit(monkeypatch) -> None:
    positions = [("0101210000", "")] * 13_290
    metadata = {
        "catalog_sections": 0,
        "catalog_chapters": 0,
        "catalog_rows": 13_319,
        "catalog_unique_codes": 13_290,
        "catalog_duplicate_rows": 27,
        "catalog_invalid_code_rows": 2,
        "description_rows": 0,
        "positions_loaded": 13_290,
    }
    monkeypatch.setattr(
        audit_mod,
        "load_catalog_positions",
        lambda *args, **kwargs: (positions, "official_ett_rate_codes", metadata),
    )
    monkeypatch.setattr(audit_mod, "audit_ntm_full_coverage", _stub_audit)
    monkeypatch.setattr(
        audit_mod,
        "_synthetic_positions",
        lambda: [("0101210000", "probe")],
    )

    report = audit_mod.build_ntm_full_coverage_report()
    assert report["ok"] is False
    assert report["structural_ok"] is True
    assert report["full_catalog_required"] is True
    assert report["catalog_complete"] is False
    assert report["audit_scope"] == "code_only_catalog"
    assert report["audit_claim"] == "official_advisory_structure_and_pinned_catalog_coverage"
    assert report["legal_applicability_proven_for_every_position"] is False
    assert report["rule_probe_family_gaps"] == []
    assert report["rule_probe_decision_30_sections_not_observed"] == []
    assert "full commodity catalog required" in report["catalog_error"]

    partial = audit_mod.build_ntm_full_coverage_report(
        require_full_catalog=False,
        require_code_catalog=True,
    )
    assert partial["ok"] is True
    assert partial["catalog_complete"] is False
    assert partial["audit_scope"] == "code_only_catalog"
    # Explicit partial success is never promoted to full-catalog success.
    assert partial["code_catalog_complete"] is True


def test_explicit_sqlite_loader_reports_full_counts_before_limit(tmp_path: Path) -> None:
    database = tmp_path / "catalog.db"
    connection = sqlite3.connect(database)
    try:
        connection.executescript(
            """
            CREATE TABLE tnved_sections (id INTEGER PRIMARY KEY, roman_number TEXT);
            CREATE TABLE tnved_chapters (id INTEGER PRIMARY KEY, code TEXT);
            CREATE TABLE tnved_commodities (code TEXT, description TEXT);
            INSERT INTO tnved_sections VALUES (1, 'I'), (2, 'II');
            INSERT INTO tnved_chapters VALUES (1, '01'), (2, '02'), (3, '03');
            INSERT INTO tnved_commodities VALUES
                ('0101', 'Живые лошади'),
                ('0101210000', 'Лошади чистопородные'),
                ('0101210000', 'Лошади');
            """
        )
        connection.commit()
    finally:
        connection.close()

    rows, metadata = audit_mod._load_sqlite_catalog_positions(database, limit=1)
    assert len(rows) == 1
    assert metadata["positions_loaded"] == 1
    assert metadata["catalog_rows"] == 3
    assert metadata["catalog_unique_codes"] == 2
    assert metadata["catalog_duplicate_rows"] == 1
    assert metadata["catalog_sections"] == 2
    assert metadata["catalog_chapters"] == 3
    assert metadata["description_rows"] == 2
    assert metadata["catalog_section_codes"] == ["I", "II"]
    assert metadata["catalog_chapter_codes"] == ["01", "02", "03"]


def test_missing_application_database_falls_back_to_code_only_ett(monkeypatch) -> None:
    ett_rows = [("0101210000", ""), ("0101299000", "")]
    ett_metadata = {
        "catalog_revision": "ett:test",
        "catalog_rows": 2,
        "catalog_unique_codes": 2,
        "catalog_duplicate_rows": 0,
        "catalog_invalid_code_rows": 0,
        "catalog_sections": 0,
        "catalog_chapters": 0,
        "description_rows": 0,
        "positions_loaded": 2,
    }

    monkeypatch.setattr(
        audit_mod,
        "_load_official_ett_positions",
        lambda *args, **kwargs: (ett_rows, ett_metadata),
    )

    def _missing_application_catalog(*args, **kwargs):
        raise OperationalError("SELECT code FROM tnved_commodities", {}, Exception("missing"))

    monkeypatch.setattr(
        audit_mod,
        "_load_application_catalog_positions",
        _missing_application_catalog,
    )
    monkeypatch.setattr(audit_mod, "_catalog_baseline_metadata", lambda *args, **kwargs: {})

    rows, source, metadata = audit_mod.load_catalog_positions()

    assert rows == ett_rows
    assert source == "official_ett_rate_codes"
    assert metadata["lightweight_db_rows_ignored"] == 0
    assert "cannot read application catalog" in metadata["application_catalog_error"]
