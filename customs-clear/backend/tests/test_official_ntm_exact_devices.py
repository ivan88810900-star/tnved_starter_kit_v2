from __future__ import annotations

from app.services.official_ntm_exact_devices import (
    DECISION_30_CRYPTO_PROCEDURE_URL,
    DECISION_30_RADIO_PROCEDURE_URL,
    evaluate_exact_crypto_requirement,
    evaluate_exact_device_requirements,
    evaluate_exact_radio_requirement,
)

OFFICIAL_NOTIFICATION_URL = (
    "https://portal.eaeunion.org/sites/odata/_layouts/15/"
    "portal.eec.registry.ui/displayform.aspx?itemid=89654"
)
OFFICIAL_RADIO_REGISTRY_URL = (
    "https://portal.eaeunion.org/sites/odata/official-radio-entry"
)


def _row(rows: list[dict], family: str) -> dict:
    return next(row for row in rows if row["family"] == family)


def test_embedded_radio_is_detected_outside_section_hs_ranges() -> None:
    row = evaluate_exact_radio_requirement(
        "9403609009",
        "шкаф со встроенным радиомодулем",
        {"direction": "import", "embedded_radio": True},
    )

    assert row is not None
    assert row["hs_scope"] is False
    assert row["applicability"] == "needs_clarification"
    assert row["used_for_missing_check"] is False
    assert "verified_current_radio_registry_result" in row["missing_facts"]


def test_exact_wifi_24_specs_match_curated_appendix_2_exclusion() -> None:
    row = evaluate_exact_radio_requirement(
        "9403609009",
        "умный шкаф со встроенным Wi-Fi",
        {
            "direction": "import",
            "embedded_radio": True,
            "radio_technology": "IEEE 802.11",
            "frequency_mhz": {"min": 2400, "max": 2483.5},
            "transmitter_power_mw": 100,
            "radio_registry_exemption": False,
        },
    )

    assert row is not None
    assert row["applicability"] == "definite"
    assert row["decision"] == "excluded_by_exact_rule"
    assert row["requirement_applicable"] is False
    assert row["exclusion"]["rule_id"] == "radio.app15.annex2.3.6_7.ieee_802_11"
    assert row["shadow_ready"] is True
    assert row["enforcement_eligible"] is False


def test_wifi_over_power_limit_never_becomes_definite() -> None:
    row = evaluate_exact_radio_requirement(
        "8517620009",
        "Wi-Fi access point",
        {
            "direction": "import",
            "embedded_radio": True,
            "radio_technology": "wifi",
            "frequency_mhz": [2400, 2483.5],
            "transmitter_power_mw": 101,
        },
    )

    assert row is not None
    assert row["applicability"] == "needs_clarification"
    assert row["exclusion"] is None


def test_json_frequency_list_is_points_not_an_invented_continuous_range() -> None:
    row = evaluate_exact_radio_requirement(
        "8517620009",
        "Wi-Fi access point",
        {
            "direction": "import",
            "radio_technology": "wifi",
            "frequency_mhz": [2400, 5150],
            "transmitter_power_mw": 100,
        },
    )

    assert row is not None
    frequency = next(
        evidence
        for evidence in row["evidence"]
        if evidence.get("field") == "frequency_mhz"
    )
    assert frequency["value"] == [[2400.0, 2400.0], [5150.0, 5150.0]]


def test_receive_only_category_is_an_exact_exclusion_without_power_guessing() -> None:
    row = evaluate_exact_radio_requirement(
        "8527990000",
        "радиоприемник без передатчика",
        {
            "direction": "import",
            "radio_technology": "receiver_without_transmitter",
        },
    )

    assert row is not None
    assert row["applicability"] == "definite"
    assert row["exclusion"]["rule_id"] == "radio.app15.annex2.3.9.receive_only"


def test_verified_radio_registry_match_is_exact_only_with_official_url() -> None:
    exact = evaluate_exact_radio_requirement(
        "8517620009",
        "радиомодуль Model X",
        {
            "direction": "import",
            "radio_registry_exemption": True,
            "radio_registry_evidence_url": OFFICIAL_RADIO_REGISTRY_URL,
        },
    )
    unproved = evaluate_exact_radio_requirement(
        "8517620009",
        "радиомодуль Model X",
        {
            "direction": "import",
            "radio_registry_exemption": True,
            "radio_registry_evidence_url": "https://example.com/row",
        },
    )

    assert exact is not None and unproved is not None
    assert exact["decision"] == "excluded_by_registry"
    assert exact["applicability"] == "definite"
    assert unproved["applicability"] == "needs_clarification"
    assert "radio_registry_evidence_url" in unproved["missing_facts"]


def test_radio_registry_mapping_requires_active_exact_model_match() -> None:
    row = evaluate_exact_radio_requirement(
        "8517620009",
        "радиомодуль",
        {
            "direction": "import",
            "radio_registry_exemption": {
                "verified": True,
                "active": True,
                "exact_model_match": False,
                "registration_number": "RU0000000001",
                "source_url": OFFICIAL_RADIO_REGISTRY_URL,
            },
        },
    )

    assert row is not None
    assert row["applicability"] == "needs_clarification"


def test_radio_section_is_an_exact_negative_for_export_direction() -> None:
    row = evaluate_exact_radio_requirement(
        "8517620009",
        "радиомодуль",
        {"direction": "export", "embedded_radio": True},
    )

    assert row is not None
    assert row["applicability"] == "definite"
    assert row["decision"] == "not_applicable"
    assert row["requirement_applicable"] is False


def test_generic_transit_is_radio_negative_but_crypto_route_stays_unresolved() -> None:
    radio = evaluate_exact_radio_requirement(
        "8517620009",
        "радиомодуль",
        {"direction": "transit", "embedded_radio": True},
    )
    crypto = evaluate_exact_crypto_requirement(
        "8517130000",
        "смартфон с шифрованием",
        {"direction": "transit", "cryptography_present": True},
    )

    assert radio is not None and crypto is not None
    assert radio["decision"] == "not_applicable"
    assert radio["requirement_applicable"] is False
    assert "direction" not in radio["missing_facts"]
    assert crypto["applicability"] == "needs_clarification"
    assert crypto["requirement_applicable"] is None
    assert crypto["missing_facts"] == ["transit_route"]


def test_crypto_through_transit_exclusion_requires_exact_border_route() -> None:
    through = evaluate_exact_crypto_requirement(
        "8517130000",
        "смартфон с шифрованием",
        {
            "direction": "transit",
            "transit_route": "border_to_border",
            "cryptography_present": True,
        },
    )
    internal = evaluate_exact_crypto_requirement(
        "8517130000",
        "смартфон с шифрованием",
        {
            "direction": "transit",
            "transit_route": "arrival_to_internal",
            "cryptography_present": True,
        },
    )

    assert through is not None and internal is not None
    assert through["applicability"] == "definite"
    assert through["decision"] == "not_applicable"
    assert through["requirement_applicable"] is False
    assert through["exclusion"]["rule_id"] == (
        "crypto.app9.p8.through_transit_no_documents"
    )
    assert internal["applicability"] == "needs_clarification"
    assert internal["requirement_applicable"] is None
    assert internal["missing_facts"] == [
        "crypto_transit_authorization_or_notification"
    ]


def test_exact_active_notification_proves_notification_route() -> None:
    row = evaluate_exact_crypto_requirement(
        "8517620009",
        "Wi-Fi module model SID300 with cryptography",
        {
            "direction": "import",
            "cryptography_present": True,
            "crypto_functions": ["AES", "TLS"],
            "notification_registry_number": "RU0000060047",
            "notification_registry_verified": True,
            "registry_evidence_url": OFFICIAL_NOTIFICATION_URL,
        },
    )

    assert row is not None
    assert row["applicability"] == "definite"
    assert row["decision"] == "covered_by_verified_notification"
    assert row["permit_type"] == "НФ"
    assert row["requirement_applicable"] is True
    assert row["required_document"] == "Сведения о нотификации RU0000060047"
    assert row["used_for_missing_check"] is False


def test_notification_mapping_form_is_supported() -> None:
    row = evaluate_exact_crypto_requirement(
        "8517130000",
        "смартфон",
        {
            "direction": "import",
            "notification_registry_verified": {
                "verified": True,
                "active": True,
                "exact_model_match": True,
                "number": "RU0000051973",
                "source_url": OFFICIAL_NOTIFICATION_URL,
            },
        },
    )

    assert row is not None
    assert row["applicability"] == "definite"
    assert row["required_document"].endswith("RU0000051973")


def test_verified_notification_without_number_or_official_url_is_not_exact() -> None:
    missing_number = evaluate_exact_crypto_requirement(
        "8517130000",
        "смартфон с шифрованием",
        {
            "direction": "import",
            "cryptography_present": True,
            "notification_registry_verified": True,
            "registry_evidence_url": OFFICIAL_NOTIFICATION_URL,
        },
    )
    nonofficial = evaluate_exact_crypto_requirement(
        "8517130000",
        "смартфон с шифрованием",
        {
            "direction": "import",
            "cryptography_present": True,
            "notification_registry_number": "RU0000051973",
            "notification_registry_verified": True,
            "registry_evidence_url": "https://example.com/notification",
        },
    )

    assert missing_number is not None and nonofficial is not None
    assert missing_number["applicability"] == "needs_clarification"
    assert "notification_registry_number" in missing_number["missing_facts"]
    assert nonofficial["applicability"] == "needs_clarification"
    assert (
        "official_active_notification_registry_evidence" in nonofficial["missing_facts"]
    )


def test_generic_aes_tls_vpn_words_never_create_definite_crypto_result() -> None:
    for marker in ("AES-256", "TLS 1.3", "VPN client"):
        row = evaluate_exact_crypto_requirement(
            "8471300000",
            f"ноутбук с {marker}",
            {
                "direction": "import",
                "cryptography_present": True,
                "crypto_functions": [marker],
            },
        )
        assert row is not None
        assert row["applicability"] == "needs_clarification"
        assert "notification_or_exact_legal_exemption" in row["missing_facts"]


def test_mass_market_is_notification_category_not_general_exemption() -> None:
    row = evaluate_exact_crypto_requirement(
        "8471300000",
        "массовый ноутбук с TLS",
        {
            "direction": "import",
            "cryptography_present": True,
            "crypto_functions": ["TLS"],
            "mass_market": True,
        },
    )

    assert row is not None
    assert row["applicability"] == "needs_clarification"
    mass_market = next(
        evidence
        for evidence in row["evidence"]
        if evidence.get("field") == "mass_market"
    )
    assert "not a general exemption" in mass_market["note"]


def test_bare_crypto_exemption_boolean_is_not_accepted_as_exact() -> None:
    row = evaluate_exact_crypto_requirement(
        "8471300000",
        "ноутбук с шифрованием",
        {
            "direction": "import",
            "cryptography_present": True,
            "crypto_exemption": True,
            "registry_evidence_url": OFFICIAL_NOTIFICATION_URL,
        },
    )

    assert row is not None
    assert row["applicability"] == "needs_clarification"
    assert "crypto_exemption.rule_id" in row["missing_facts"]


def test_test_sim_card_exception_requires_all_exact_point_6_facts() -> None:
    exact = evaluate_exact_crypto_requirement(
        "8523520000",
        "тестовые SIM-карты",
        {
            "direction": "import",
            "cryptography_present": True,
            "crypto_exemption": {
                "rule_id": "test_sim_cards",
                "verified": True,
                "quantity": 20,
                "importer_role": "cellular_operator",
                "purpose": "international_exchange",
                "source_url": DECISION_30_CRYPTO_PROCEDURE_URL,
            },
        },
    )
    too_many = evaluate_exact_crypto_requirement(
        "8523520000",
        "тестовые SIM-карты",
        {
            "direction": "import",
            "cryptography_present": True,
            "crypto_exemption": {
                "rule_id": "test_sim_cards",
                "verified": True,
                "quantity": 21,
                "importer_role": "cellular_operator",
                "purpose": "international_exchange",
                "source_url": DECISION_30_CRYPTO_PROCEDURE_URL,
            },
        },
    )

    assert exact is not None and too_many is not None
    assert exact["decision"] == "excluded_by_exact_rule"
    assert exact["applicability"] == "definite"
    assert too_many["applicability"] == "needs_clarification"
    assert "crypto_exemption.quantity_at_most_20" in too_many["missing_facts"]


def test_test_sim_card_exception_rejects_non_positive_or_non_integer_quantities() -> None:
    for quantity in (0, -1, 0.5, 20.0, "20"):
        row = evaluate_exact_crypto_requirement(
            "8523520000",
            "тестовые SIM-карты",
            {
                "direction": "import",
                "cryptography_present": True,
                "crypto_exemption": {
                    "rule_id": "test_sim_cards",
                    "verified": True,
                    "quantity": quantity,
                    "importer_role": "cellular_operator",
                    "purpose": "international_exchange",
                    "source_url": DECISION_30_CRYPTO_PROCEDURE_URL,
                },
            },
        )

        assert row is not None
        assert row["applicability"] == "needs_clarification"
        assert "crypto_exemption.quantity_at_most_20" in row["missing_facts"]


def test_personal_use_appendix_5_requires_natural_person_and_exact_category() -> None:
    row = evaluate_exact_crypto_requirement(
        "8517130000",
        "смартфон для личного пользования",
        {
            "direction": "import",
            "cryptography_present": True,
            "crypto_exemption": {
                "rule_id": "personal_use_appendix_5",
                "verified": True,
                "personal_use": True,
                "natural_person": True,
                "category": "smartphone",
                "source_url": DECISION_30_CRYPTO_PROCEDURE_URL,
            },
        },
    )

    assert row is not None
    assert row["applicability"] == "definite"
    assert row["requirement_applicable"] is False
    assert row["exclusion"]["rule_id"] == "crypto.app9.annex5.personal_use"


def test_appendix_5_corporate_or_unknown_declarant_fails_closed() -> None:
    for natural_person in (None, False):
        exemption = {
            "rule_id": "personal_use_appendix_5",
            "verified": True,
            "personal_use": True,
            "category": "smartphone",
            "source_url": DECISION_30_CRYPTO_PROCEDURE_URL,
        }
        if natural_person is not None:
            exemption["natural_person"] = natural_person
        row = evaluate_exact_crypto_requirement(
            "8517130000",
            "смартфон для личного пользования",
            {
                "direction": "import",
                "cryptography_present": True,
                "crypto_exemption": exemption,
            },
        )

        assert row is not None
        assert row["applicability"] == "needs_clarification"
        assert row["requirement_applicable"] is None
        assert "crypto_exemption.natural_person" in row["missing_facts"]


def test_crypto_signal_outside_section_code_stays_needs_clarification() -> None:
    row = evaluate_exact_crypto_requirement(
        "9403609009",
        "шкаф с VPN-модулем",
        {
            "direction": "import",
            "cryptography_present": True,
            "crypto_functions": ["VPN"],
        },
    )

    assert row is not None
    assert row["applicability"] == "needs_clarification"
    assert "section_2_19_hs_scope" in row["missing_facts"]


def test_conflicting_crypto_absence_and_registry_evidence_fails_closed() -> None:
    row = evaluate_exact_crypto_requirement(
        "8517130000",
        "смартфон",
        {
            "direction": "import",
            "cryptography_present": False,
            "notification_registry_number": "RU0000051973",
            "notification_registry_verified": True,
            "registry_evidence_url": OFFICIAL_NOTIFICATION_URL,
        },
    )

    assert row is not None
    assert row["applicability"] == "needs_clarification"
    assert "resolve_conflicting_crypto_facts" in row["missing_facts"]


def test_combined_evaluator_returns_no_rows_without_device_signals() -> None:
    assert (
        evaluate_exact_device_requirements(
            "6110209100",
            "хлопчатобумажный джемпер",
            {"direction": "import"},
        )
        == []
    )


def test_combined_evaluator_returns_radio_then_crypto_and_only_shadow_rows() -> None:
    rows = evaluate_exact_device_requirements(
        "8517620009",
        "Wi-Fi router with AES/TLS",
        {
            "direction": "import",
            "embedded_radio": True,
            "radio_technology": "wifi",
            "frequency_mhz": (2400, 2483.5),
            "transmitter_power_mw": {"max": 0.1, "unit": "W"},
            "cryptography_present": True,
            "crypto_functions": ["AES", "TLS"],
        },
    )

    assert [row["family"] for row in rows] == ["radio_frequency", "cryptography"]
    assert _row(rows, "radio_frequency")["applicability"] == "definite"
    assert _row(rows, "cryptography")["applicability"] == "needs_clarification"
    assert all(row["used_for_missing_check"] is False for row in rows)
    assert DECISION_30_RADIO_PROCEDURE_URL in rows[0]["source_urls"]
