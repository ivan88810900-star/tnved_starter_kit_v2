from __future__ import annotations

from app.services.official_ntm_exact_applicability import (
    evaluate_official_ntm_exact_applicability,
)


def test_no_structured_facts_preserves_existing_broad_contract() -> None:
    broad = [
        {
            "source": "official_ntm_contours",
            "family": "licensing",
            "permit_type": "ЛЗ",
            "section": "2.30",
            "applicability": "needs_clarification",
            "rule_name": "broad",
        }
    ]
    result = evaluate_official_ntm_exact_applicability(
        "2903920000",
        "гексахлорбензол",
        {},
        broad_requirements=broad,
    )
    assert result["requirements"] == broad
    assert result["exact_requirements"] == []
    assert result["summary"]["mode"] == "broad_candidate_only"


def test_complete_high_risk_phyto_facts_replace_broad_candidate_advisory_only() -> None:
    broad = [
        {
            "source": "official_ntm_contours",
            "family": "phytosanitary_control",
            "permit_type": "ФСС",
            "applicability": "needs_clarification",
            "rule_name": "broad phyto",
        }
    ]
    result = evaluate_official_ntm_exact_applicability(
        "0712901100",
        "Кукуруза сахарная гибридная для посева",
        {
            "direction": "import",
            "origin_country": "CN",
            "destination_country": "RU",
            "intended_use": "для посева",
            "processing_method": "семена сушеные, необработанные",
            "packaging": "коммерческая партия в мешках",
            "phytosanitary_risk_tier": "high",
        },
        broad_requirements=broad,
    )
    rows = [
        row
        for row in result["requirements"]
        if row["family"] == "phytosanitary_control"
    ]
    assert len(rows) == 1
    assert rows[0]["applicability"] == "definite"
    assert rows[0]["outcome"] == "certificate_required"
    assert rows[0]["certificate_required"] is True
    assert rows[0]["used_for_missing_check"] is False
    assert rows[0]["requires_manual_review"] is True
    assert rows[0]["reason"].startswith("По введённым данным:")


def test_radio_exact_exclusion_is_visible_and_never_enforcement_eligible() -> None:
    result = evaluate_official_ntm_exact_applicability(
        "9403609009",
        "шкаф со встроенным Wi-Fi радиомодулем",
        {
            "direction": "import",
            "embedded_radio": True,
            "radio_technology": ["wifi"],
            "frequency_mhz": [2400],
            "transmitter_power_mw": 50,
        },
    )
    radio = next(
        row for row in result["requirements"] if row["family"] == "radio_frequency"
    )
    assert radio["applicability"] == "excluded"
    assert radio["requirement_applicable"] is False
    assert radio["exclusion_reason"]
    assert radio["enforcement_eligible"] is False
    assert radio["used_for_missing_check"] is False


def test_hcb_exact_shadow_is_definite_advisory_and_allowlist_ready() -> None:
    result = evaluate_official_ntm_exact_applicability(
        "2903920000",
        "гексахлорбензол HCB, лабораторный стандарт",
        {
            "direction": "import",
            "cas_numbers": ["118-74-1"],
            "intended_use": "laboratory reference standard",
            "technical_parameters_confirmed": True,
            "product_name_matches_official_row": True,
            "manufacturer_documents_verified": True,
            "sealed_container": True,
            "package_volume_ml": 5,
        },
    )
    row = next(
        row
        for row in result["requirements"]
        if row.get("rule_id") == "D30-2.30-HCB-2903920000"
    )
    assert row["applicability"] == "definite"
    assert row["requirement_applicable"] is True
    assert row["curated_enforcement_key"] == "D30-2.30-HCB-2903920000"
    assert row["used_for_missing_check"] is False
    assert row["reason"].startswith("По введённым данным")
    assert "сервис доказательства не проверял" in row["reason"].lower()
    assert result["summary"]["curated_shadow_candidate_rule_ids"] == [
        "D30-2.30-HCB-2903920000"
    ]
    assert result["summary"]["curated_enforcement_ready_rule_ids"] == []


def test_ready_summary_uses_the_same_fail_closed_bridge_gates(monkeypatch) -> None:
    synthetic = {
        "source": "trusted_test_adapter",
        "family": "licensing",
        "permit_type": "ЛЗ/заключение",
        "applicability": "definite",
        "outcome": "required",
        "requirement_applicable": True,
        "candidate_only": False,
        "missing_facts": [],
        "rule_id": "D30-2.30-HCB-2903920000",
        "curated_enforcement_key": "D30-2.30-HCB-2903920000",
        "evidence_trust": "trusted_document_adapter",
        "trusted_source_verified": True,
    }
    monkeypatch.setattr(
        "app.services.official_ntm_exact_applicability._normalize_trade_rows",
        lambda _rows: [dict(synthetic)],
    )

    def ready_ids() -> list[str]:
        result = evaluate_official_ntm_exact_applicability(
            "2903920000",
            "гексахлорбензол",
            {"direction": "import"},
        )
        return result["summary"]["curated_enforcement_ready_rule_ids"]

    assert ready_ids() == []
    synthetic["enforcement_eligible"] = True
    assert ready_ids() == []
    synthetic["curated_allowlist_eligible"] = True
    assert ready_ids() == ["D30-2.30-HCB-2903920000"]


def test_generic_crypto_markers_never_become_definite() -> None:
    result = evaluate_official_ntm_exact_applicability(
        "8517620009",
        "маршрутизатор с AES TLS VPN",
        {
            "direction": "import",
            "cryptography_present": True,
            "crypto_functions": ["AES", "TLS", "VPN"],
            "mass_market": True,
        },
    )
    row = next(row for row in result["requirements"] if row["family"] == "cryptography")
    assert row["applicability"] == "needs_clarification"
    assert "notification_or_exact_legal_exemption" in row["missing_facts"]
    assert row["used_for_missing_check"] is False


def test_registry_claim_is_explicitly_caller_supplied_not_service_verified() -> None:
    result = evaluate_official_ntm_exact_applicability(
        "8517130000",
        "смартфон с шифрованием",
        {
            "direction": "import",
            "cryptography_present": True,
            "notification_registry_number": "RU0000051973",
            "notification_registry_verified": True,
            "registry_evidence_url": "https://portal.eaeunion.org/notification/51973",
        },
    )
    row = next(
        row for row in result["requirements"] if row["family"] == "cryptography"
    )

    assert row["applicability"] == "definite"
    assert "По введённым данным" in row["reason"]
    assert "сервис реестр не проверял" in row["reason"]
    assert row["evidence_trust"] == "caller_supplied_structured_facts"
    assert row["trusted_source_verified"] is False


def test_export_catch_all_is_a_transaction_check_not_a_document() -> None:
    result = evaluate_official_ntm_exact_applicability(
        "0101210000",
        "товар вне HS-кандидатного списка",
        {
            "direction": "export",
            "destination_country": "CN",
            "end_user": "foreign research centre",
            "wmd_end_use": True,
        },
    )
    card = next(row for row in result["requirements"] if row.get("transaction_level"))
    assert card["permit_type"] == "ПРОВЕРКА СДЕЛКИ"
    assert card["automatic_document_requirement"] is False
    assert card["used_for_missing_check"] is False
    assert result["catch_all"]["status"] == "prohibited_transaction_risk"


def test_catch_all_risk_without_direction_never_becomes_definite() -> None:
    result = evaluate_official_ntm_exact_applicability(
        "0101210000",
        "товар вне HS-кандидатного списка",
        {"wmd_end_use": True},
    )
    card = next(row for row in result["requirements"] if row.get("transaction_level"))
    assert card["applicability"] == "needs_clarification"
    assert card["missing_facts"] == ["direction"]


def test_exact_trade_direction_and_retired_code_exclusions_are_explainable() -> None:
    direction = evaluate_official_ntm_exact_applicability(
        "2903920000",
        "гексахлорбензол",
        {"direction": "export"},
    )
    assert any(
        row.get("rule_id") == "D30-2.30-HCB-2903920000"
        and row.get("applicability") == "excluded"
        for row in direction["requirements"]
    )

    retired = evaluate_official_ntm_exact_applicability(
        "3910000002",
        "силикон в первичной форме",
        {"direction": "export"},
    )
    diagnostic = next(
        row
        for row in retired["resolved_exclusions"]
        if row.get("kind") == "retired_export_control_code"
    )
    assert diagnostic["replacement_code"] == "3910000006"
