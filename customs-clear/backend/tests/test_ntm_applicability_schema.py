from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.ntm_applicability import (
    NtmTransactionFacts,
    dump_ntm_transaction_facts,
)


def test_schema_accepts_structured_ui_and_exact_rule_facts() -> None:
    facts = NtmTransactionFacts.model_validate(
        {
            "direction": "import",
            "origin_country": "DE",
            "destination_country": "RU",
            "intended_use": "laboratory reference standard",
            "end_user": "quality-control laboratory",
            "composition": ["hexachlorobenzene"],
            "cas_numbers": ["118-74-1"],
            "product_name_matches_official_row": True,
            "manufacturer_documents_verified": True,
            "technical_parameters_confirmed": True,
            "sealed_container": True,
            "package_volume_ml": 5,
            "radio_technology": ["wifi"],
            "frequency_mhz": [2400, 2483.5],
            "notification_registry_number": "RU1234567890",
            "registry_evidence_url": "https://portal.eaeunion.org/example",
        }
    )
    dumped = dump_ntm_transaction_facts(facts)
    assert dumped["direction"] == "import"
    assert dumped["cas_numbers"] == ["118-74-1"]
    assert dumped["package_volume_ml"] == 5
    assert "feed_use" not in dumped


def test_empty_schema_dumps_to_empty_mapping() -> None:
    assert dump_ntm_transaction_facts(None) == {}
    assert dump_ntm_transaction_facts(NtmTransactionFacts()) == {}


def test_schema_preserves_exact_registry_and_crypto_exemption_evidence() -> None:
    facts = NtmTransactionFacts.model_validate(
        {
            "notification_registry_verified": {
                "verified": True,
                "active": True,
                "exact_model_match": True,
                "number": "RU0000051973",
                "source_url": "https://portal.eaeunion.org/notification/51973",
            },
            "crypto_exemption": {
                "rule_id": "personal_use_appendix_5",
                "verified": True,
                "personal_use": True,
                "natural_person": True,
                "category": "smartphone",
                "source_url": "https://eec.eaeunion.org/example",
            },
        }
    )

    dumped = dump_ntm_transaction_facts(facts)
    assert dumped["notification_registry_verified"]["active"] is True
    assert dumped["crypto_exemption"]["rule_id"] == "personal_use_appendix_5"
    assert dumped["crypto_exemption"]["natural_person"] is True


def test_schema_accepts_bounded_crypto_transit_routes() -> None:
    facts = NtmTransactionFacts.model_validate(
        {
            "direction": "transit",
            "transit_route": "border_to_border",
        }
    )

    assert dump_ntm_transaction_facts(facts) == {
        "direction": "transit",
        "transit_route": "border_to_border",
    }


def test_schema_normalizes_iso_country_codes_and_accepts_positive_sim_quantity() -> None:
    facts = NtmTransactionFacts.model_validate(
        {
            "origin_country": " cn ",
            "destination_country": "rus",
            "crypto_exemption": {
                "rule_id": "test_sim_cards",
                "quantity": 20,
            },
        }
    )

    dumped = dump_ntm_transaction_facts(facts)
    assert dumped["origin_country"] == "CN"
    assert dumped["destination_country"] == "RUS"
    assert dumped["crypto_exemption"]["quantity"] == 20


def test_schema_accepts_the_real_ui_frequency_range_payload() -> None:
    facts = NtmTransactionFacts.model_validate(
        {
            "frequency_mhz": [
                {"min": 2400, "max": 2483.5},
                {"min": 5150, "max": 5350},
            ]
        }
    )
    assert dump_ntm_transaction_facts(facts)["frequency_mhz"] == [
        {"min": 2400.0, "max": 2483.5},
        {"min": 5150.0, "max": 5350.0},
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"direction": "sideways"},
        {"transit_route": "warehouse_to_customer"},
        {"origin_country": "TOO-LONG"},
        {"origin_country": "1N"},
        {"crypto_exemption": {"rule_id": "test_sim_cards", "quantity": 0}},
        {"crypto_exemption": {"rule_id": "test_sim_cards", "quantity": 0.5}},
        {"crypto_exemption": {"rule_id": "test_sim_cards", "quantity": "20"}},
        {"substance_purity_percent": 101},
        {"frequency_mhz": list(range(101))},
        {"unknown_legal_conclusion": True},
    ],
)
def test_schema_rejects_unknown_or_invalid_legal_facts(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        NtmTransactionFacts.model_validate(payload)
