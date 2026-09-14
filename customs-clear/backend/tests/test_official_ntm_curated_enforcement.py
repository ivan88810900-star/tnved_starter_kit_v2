from __future__ import annotations

from app.services.official_ntm_curated_enforcement import (
    CURATED_ENFORCEMENT_FLAG,
    apply_curated_official_enforcement,
    is_official_curated_enforcement_enabled,
)


def _exact_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "rule_id": "D30-2.30-HCB-2903920000",
        "family": "licensing",
        "permit_type": "ЛЗ/заключение",
        "applicability": "definite",
        "requirement_applicable": True,
        "candidate_only": False,
        "missing_facts": [],
        "enforcement_eligible": True,
        "curated_allowlist_eligible": True,
        "source": "official_ntm_exact_trade",
        "source_url": "https://eec.eaeunion.org/example",
        "rule_name": "Exact HCB row",
        "evidence_trust": "caller_supplied_structured_facts",
        "trusted_source_verified": False,
    }
    row.update(overrides)
    return row


def test_curated_enforcement_is_default_off(monkeypatch) -> None:
    monkeypatch.delenv(CURATED_ENFORCEMENT_FLAG, raising=False)
    assert is_official_curated_enforcement_enabled() is False
    broker, audit = apply_curated_official_enforcement([], [_exact_row()])
    assert broker == []
    assert audit["eligible_rule_ids"] == []
    assert audit["shadow_candidate_rule_ids"] == ["D30-2.30-HCB-2903920000"]
    assert audit["applied_rule_ids"] == []
    assert audit["broker_changed"] is False


def test_explicit_flag_cannot_enforce_caller_supplied_self_attestation() -> None:
    broker, audit = apply_curated_official_enforcement(
        [],
        [_exact_row()],
        enabled=True,
    )
    assert broker == []
    assert audit["applied_rule_ids"] == []
    assert audit["rejected"] == [{
        "rule_id": "D30-2.30-HCB-2903920000",
        "reason": "untrusted_caller_supplied_evidence",
    }]


def test_explicit_flag_applies_only_trusted_exact_allowlisted_positive_row() -> None:
    broker, audit = apply_curated_official_enforcement(
        [],
        [_exact_row(
            enforcement_eligible=True,
            curated_allowlist_eligible=True,
            evidence_trust="trusted_document_adapter",
            trusted_source_verified=True,
        )],
        enabled=True,
    )
    assert [row["permit_type"] for row in broker] == ["ЛЗ/заключение"]
    assert broker[0]["applicability"] == "definite"
    assert broker[0]["used_for_missing_check"] is True
    assert audit["applied_rule_ids"] == ["D30-2.30-HCB-2903920000"]


def test_missing_eligibility_flags_are_rejected_fail_closed() -> None:
    missing_source_policy = _exact_row()
    missing_source_policy.pop("enforcement_eligible")
    missing_allowlist_policy = _exact_row()
    missing_allowlist_policy.pop("curated_allowlist_eligible")

    broker, audit = apply_curated_official_enforcement(
        [],
        [missing_source_policy, missing_allowlist_policy],
        enabled=True,
    )

    assert broker == []
    assert {row["reason"] for row in audit["rejected"]} == {
        "source_policy_disallows_enforcement",
        "exact_rule_not_allowlist_eligible",
    }


def test_prefix_candidate_and_incomplete_exact_row_never_enter_broker() -> None:
    broker, audit = apply_curated_official_enforcement(
        [],
        [
            _exact_row(candidate_only=True),
            _exact_row(
                rule_id="RF-PP1284-2.1.1-AMITON",
                family="export_control_dual_use",
                permit_type="ЛЗ/разрешение ФСТЭК",
                missing_facts=["destination_country"],
            ),
        ],
        enabled=True,
    )
    assert broker == []
    assert {row["reason"] for row in audit["rejected"]} == {
        "candidate_only_result",
        "structured_facts_incomplete",
    }


def test_exact_exclusion_and_source_policy_negative_are_never_enforced() -> None:
    broker, audit = apply_curated_official_enforcement(
        [],
        [
            _exact_row(requirement_applicable=False),
            _exact_row(enforcement_eligible=False),
        ],
        enabled=True,
    )
    assert broker == []
    assert {row["reason"] for row in audit["rejected"]} == {
        "negative_or_excluded_result",
        "source_policy_disallows_enforcement",
    }


def test_existing_broker_document_is_not_duplicated() -> None:
    existing = [{"permit_type": "ЛЗ/заключение", "tr_ts": None, "source": "legacy"}]
    broker, audit = apply_curated_official_enforcement(
        existing,
        [_exact_row(
            enforcement_eligible=True,
            curated_allowlist_eligible=True,
            evidence_trust="trusted_document_adapter",
            trusted_source_verified=True,
        )],
        enabled=True,
    )
    assert broker == existing
    assert audit["duplicate_rule_ids"] == ["D30-2.30-HCB-2903920000"]
    assert audit["broker_changed"] is False
