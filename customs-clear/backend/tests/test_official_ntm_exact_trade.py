from __future__ import annotations

from app.services.official_ntm_exact_trade import (
    CURATED_ALLOWLIST_FLAG,
    evaluate_exact_trade_measures,
    is_exact_trade_curated_allowlist_enabled,
)


def _rows(hs_code: str, description: str = "", **facts: object) -> list[dict]:
    return evaluate_exact_trade_measures(hs_code, description, facts)["rows"]


def test_curated_allowlist_is_default_off(monkeypatch) -> None:
    monkeypatch.delenv(CURATED_ALLOWLIST_FLAG, raising=False)
    assert is_exact_trade_curated_allowlist_enabled() is False
    result = evaluate_exact_trade_measures("0101210000", "лошадь", {})
    assert result["curated_allowlist"] == {
        "flag": CURATED_ALLOWLIST_FLAG,
        "enabled": False,
        "default": False,
        "broker_integrated": False,
        "used_for_missing_check": False,
    }


def test_380894_is_an_explicit_section_2_2_exclusion() -> None:
    result = evaluate_exact_trade_measures(
        "3808941000",
        "дезинфицирующий пестицид",
        {"direction": "import", "intended_use": "средство защиты растений"},
    )
    assert not any(row.get("section") == "2.2" for row in result["rows"])
    exclusion = next(
        diagnostic
        for diagnostic in result["diagnostics"]
        if diagnostic.get("rule_id") == "D30-2.2-PESTICIDES-FROM-3808"
    )
    assert exclusion["kind"] == "rule_exclusion"
    assert "3808 94" in exclusion["reason"]
    assert exclusion["source_url"].startswith("https://eec.eaeunion.org/")


def test_generic_7204_scrap_is_never_definite() -> None:
    rows = _rows("7204100000", "лом черных металлов", direction="import")
    waste_rows = [row for row in rows if row.get("section") in {"1.2", "2.3"}]
    assert {row["section"] for row in waste_rows} == {"1.2", "2.3"}
    assert all(row["match_precision"] == "prefix_from" for row in waste_rows)
    assert all(row["applicability"] == "needs_clarification" for row in waste_rows)
    assert all(
        row["shadow_applicability"] == "needs_clarification" for row in waste_rows
    )
    assert all("is_waste" in row["missing_facts"] for row in waste_rows)


def test_even_fully_described_7204_stays_prefix_clarification() -> None:
    rows = _rows(
        "7204100000",
        "опасный лом черных металлов, загрязненный мышьяком",
        direction="import",
        is_waste=True,
        hazardous_waste=True,
        contamination=["arsenic"],
        waste_class="A1030",
    )
    waste_rows = [row for row in rows if row.get("section") in {"1.2", "2.3"}]
    assert waste_rows
    assert all(row["missing_facts"] == [] for row in waste_rows)
    assert all(row["applicability"] == "needs_clarification" for row in waste_rows)
    assert all(row["curated_allowlist_eligible"] is False for row in waste_rows)


def test_section_2_30_exact_match_is_shadow_definite_by_default() -> None:
    result = evaluate_exact_trade_measures(
        "2903920000",
        "гексахлорбензол (HCB), лабораторный стандарт",
        {
            "direction": "import",
            "cas_numbers": ["118-74-1"],
            "composition": {"name": "hexachlorobenzene"},
            "intended_use": "reference standard for laboratory research",
            "technical_parameters_confirmed": True,
            "product_name_matches_official_row": True,
            "manufacturer_documents_verified": True,
            "sealed_container": True,
            "package_volume_ml": 5,
            "origin_country": "DE",
        },
    )
    row = next(row for row in result["rows"] if row.get("section") == "2.30")
    assert row["match_precision"] == "exact"
    assert row["missing_facts"] == []
    assert row["shadow_applicability"] == "definite"
    assert row["applicability"] == "needs_clarification"
    assert row["curated_allowlist_eligible"] is True
    assert row["used_for_missing_check"] is False
    assert row["enforcement_enabled"] is False


def test_section_2_30_flag_can_expose_definite_without_broker(monkeypatch) -> None:
    monkeypatch.setenv(CURATED_ALLOWLIST_FLAG, "true")
    result = evaluate_exact_trade_measures(
        "2903920000",
        "hexachlorobenzene HCB reference standard",
        {
            "direction": "import",
            "cas_numbers": "118-74-1",
            "intended_use": "laboratory research",
            "technical_parameters_confirmed": True,
            "product_name_matches_official_row": True,
            "manufacturer_documents_verified": True,
            "sealed_container": True,
            "package_mass_g": 10,
        },
    )
    row = next(row for row in result["rows"] if row.get("section") == "2.30")
    assert row["applicability"] == "definite"
    assert row["used_for_missing_check"] is False
    assert row["enforcement_enabled"] is False


def test_section_2_30_is_import_only() -> None:
    result = evaluate_exact_trade_measures(
        "2903920000",
        "гексахлорбензол CAS 118-74-1",
        {
            "direction": "export",
            "cas_numbers": ["118-74-1"],
            "intended_use": "laboratory",
            "technical_parameters_confirmed": True,
        },
    )
    assert not any(row.get("section") == "2.30" for row in result["rows"])
    mismatch = next(
        diagnostic
        for diagnostic in result["diagnostics"]
        if diagnostic.get("rule_id") == "D30-2.30-HCB-2903920000"
    )
    assert mismatch["kind"] == "direction_exclusion"
    assert mismatch["required_direction"] == "import"


def test_exact_code_without_identity_facts_stays_clarification() -> None:
    row = next(
        row
        for row in _rows("2903920000", "химическое вещество", direction="import")
        if row.get("section") == "2.30"
    )
    assert row["applicability"] == "needs_clarification"
    assert row["shadow_applicability"] == "needs_clarification"
    assert "description:hexachlorobenzene" in row["missing_facts"]
    assert "cas_numbers:118-74-1" in row["missing_facts"]


def test_export_hs_dataset_remains_candidate_only() -> None:
    row = next(
        row
        for row in _rows(
            "8517620009",
            "сетевое оборудование",
            direction="export",
            destination_country="CN",
        )
        if row["family"] == "export_control_dual_use"
    )
    assert row["rule_id"] == "RF-EXPORT-HS-CANDIDATE"
    assert row["candidate_only"] is True
    assert row["applicability"] == "needs_clarification"
    assert row["shadow_applicability"] == "needs_clarification"
    assert row["source_documents"]


def test_curated_export_item_requires_exact_identification(monkeypatch) -> None:
    monkeypatch.setenv(CURATED_ALLOWLIST_FLAG, "on")
    result = evaluate_exact_trade_measures(
        "2930909508",
        "амитон, O,O-диэтил-S соединение",
        {
            "direction": "export",
            "destination_country": "CN",
            "cas_numbers": ["78-53-5"],
            "composition": {"chemical": "amiton", "CAS": "78-53-5"},
            "export_control_list_item": {
                "source_number": 1284,
                "item_id": "2.1.1",
            },
            "technical_parameters_confirmed": True,
            "end_user": {"name": "civil laboratory"},
            "product_name_matches_official_row": True,
            "manufacturer_documents_verified": True,
        },
    )
    row = next(
        row for row in result["rows"] if row["rule_id"] == "RF-PP1284-2.1.1-AMITON"
    )
    assert row["match_precision"] == "exact"
    assert row["missing_facts"] == []
    assert row["applicability"] == "definite"
    assert row["source_url"].startswith("https://publication.pravo.gov.ru/")
    assert row["used_for_missing_check"] is False


def test_wrong_export_list_item_cannot_become_definite() -> None:
    row = next(
        row
        for row in _rows(
            "2930909508",
            "амитон CAS 78-53-5",
            direction="export",
            destination_country="CN",
            cas_numbers=["78-53-5"],
            export_control_list_item="PP-1299:2.1.1",
            technical_parameters_confirmed=True,
        )
        if row["rule_id"] == "RF-PP1284-2.1.1-AMITON"
    )
    assert row["shadow_applicability"] == "needs_clarification"
    assert "export_control_list_item:PP-1284:2.1.1" in row["missing_facts"]


def test_retired_export_codes_are_explicitly_excluded() -> None:
    for old_code, replacement in (
        ("3910000002", "3910000006"),
        ("3910000008", "3910000009"),
    ):
        result = evaluate_exact_trade_measures(
            old_code,
            "силикон в первичной форме",
            {"direction": "export"},
        )
        assert not any(
            row["family"] == "export_control_dual_use" for row in result["rows"]
        )
        retired = next(
            diagnostic
            for diagnostic in result["diagnostics"]
            if diagnostic["kind"] == "retired_export_control_code"
        )
        assert retired["replacement_code"] == replacement
        assert retired["catalog_revision"] == "ett:2026-06-18"
        assert retired["source_url"].startswith("https://publication.pravo.gov.ru/")


def test_catch_all_is_transaction_level_not_an_hs_document() -> None:
    result = evaluate_exact_trade_measures(
        "0101210000",
        "лошадь",
        {
            "direction": "export",
            "destination_country": "XY",
            "end_user": {"name": "foreign research centre"},
            "wmd_end_use": True,
        },
    )
    assert not any(row["family"] == "export_control_dual_use" for row in result["rows"])
    catch_all = result["catch_all"]
    assert catch_all["scope"] == "transaction"
    assert catch_all["status"] == "prohibited_transaction_risk"
    assert catch_all["applicability"] == "transaction_risk"
    assert catch_all["automatic_document_requirement"] is False
    assert catch_all["document_type"] is None
    assert catch_all["used_for_missing_check"] is False


def test_catch_all_review_does_not_depend_on_candidate_code() -> None:
    result = evaluate_exact_trade_measures(
        "0101210000",
        "товар не в HS-кандидатах",
        {
            "direction": "export",
            "catch_all_risk": "high",
            "military_end_use": True,
            "sanctioned_end_user": True,
        },
    )
    assert result["rows"] == []
    assert result["catch_all"]["status"] == "permission_review_required"
    assert result["catch_all"]["permit_type"] is None
    assert result["catch_all"]["automatic_document_requirement"] is False


def test_api_indicator_enum_triggers_transaction_review() -> None:
    result = evaluate_exact_trade_measures(
        "0101210000",
        "товар не в HS-кандидатах",
        {"direction": "export", "catch_all_risk": "indicators_present"},
    )
    assert result["catch_all"]["status"] == "permission_review_required"


def test_catch_all_is_not_applied_to_import_direction() -> None:
    result = evaluate_exact_trade_measures(
        "0101210000",
        "лошадь",
        {"direction": "import", "catch_all_risk": True},
    )
    assert result["catch_all"]["status"] == "not_applicable_direction"
    assert result["catch_all"]["applicability"] == "not_applicable"


def test_transit_is_known_and_outside_export_catch_all_scope() -> None:
    result = evaluate_exact_trade_measures(
        "0101210000",
        "лошадь",
        {"direction": "transit", "catch_all_risk": True},
    )
    assert result["direction"] == "transit"
    assert result["catch_all"]["status"] == "not_applicable_direction"
    assert not any(row["kind"] == "invalid_direction" for row in result["diagnostics"])


def test_every_result_exposes_source_revision_and_exact_rule_evidence() -> None:
    result = evaluate_exact_trade_measures(
        "2903920000",
        "гексахлорбензол",
        {"direction": "import"},
    )
    row = next(row for row in result["rows"] if row.get("section") == "2.30")
    assert row["source_url"].startswith("https://eec.eaeunion.org/")
    assert row["source_revision"]
    assert row["matched_rule"]["rule_id"] == row["rule_id"]
    assert row["matched_rule"]["hs"]["mode"] == "exact"
    assert result["catch_all"]["source_revision"]
    assert "decision_30_exact_rule_ids" in result["coverage"]
