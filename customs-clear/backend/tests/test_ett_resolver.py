"""Temporal/conditional selection tests over explicitly synthetic ETT candidates."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone
from decimal import Decimal, localcontext

import pytest

from app.services.ett_manifest import manifest_sha256, validate_manifest
from app.services.ett_resolver import resolve_rate
from tests.ett_fixtures import evidence_for, synthetic_manifest, synthetic_manifest_data


CODE = "0101210000"
DAY = date(2026, 9, 8)


def _manifest_with_rules(*overrides):
    data = synthetic_manifest_data()
    template = data["rate_rules"][0]
    data["rate_rules"] = [dict(deepcopy(template), rule_id=f"rule-{index}", **override)
                          for index, override in enumerate(overrides)]
    return validate_manifest(data)


def _numeric_manifest():
    return _manifest_with_rules(
        {"conditions": [{"field": "alcohol_percent", "op": "numeric_interval",
                         "maximum": "10.11", "maximum_inclusive": True}]},
        {"conditions": [{"field": "alcohol_percent", "op": "numeric_interval",
                         "minimum": "10.11", "minimum_inclusive": False}],
         "duty": {"kind": "ad_valorem", "ad_valorem_percent": "8"}},
    )


def test_resolved_candidate_is_explicitly_not_an_approved_rate():
    manifest = synthetic_manifest()
    result = resolve_rate(manifest, CODE, DAY, "RU")
    assert result.status == "resolved"
    assert result.mode == "candidate_preview"
    assert result.code == CODE
    assert result.as_of == DAY
    assert result.destination == "RU"
    assert result.snapshot_id == manifest.snapshot_id
    assert result.manifest_sha256 == manifest_sha256(manifest)
    assert result.rule_ids == ("test-rule-1",)
    assert result.duty.ad_valorem_percent == Decimal("5")
    assert result.evidence == manifest.rate_rules[0].evidence
    assert result.effective_evidence == manifest.rate_rules[0].effective_evidence
    assert result.missing_facts == ()
    with pytest.raises(FrozenInstanceError):
        result.mode = "approved"


@pytest.mark.parametrize("day,expected", [
    (date(2025, 12, 31), "unavailable"),
    (date(2026, 1, 1), "resolved"),
    (date(2026, 12, 31), "resolved"),
    (date(2027, 1, 1), "unavailable"),
])
def test_snapshot_coverage_is_finite_and_half_open(day, expected):
    manifest = synthetic_manifest()
    result = resolve_rate(manifest, CODE, day, "RU")
    assert result.status == expected
    assert result.as_of == day
    assert result.manifest_sha256 == manifest_sha256(manifest)
    if expected == "unavailable":
        assert result.reason == "outside_snapshot_coverage"
        assert result.duty is None


def test_temporal_rate_boundary_selects_exact_day_without_inheriting_old_duty():
    manifest = _manifest_with_rules(
        {"valid_to": "2026-07-01"},
        {"valid_from": "2026-07-01", "duty": {"kind": "ad_valorem", "ad_valorem_percent": "0"}},
    )
    before = resolve_rate(manifest, CODE, date(2026, 6, 30), "RU")
    after = resolve_rate(manifest, CODE, date(2026, 7, 1), "RU")
    assert before.rule_ids == ("rule-0",)
    assert before.duty.ad_valorem_percent == 5
    assert after.rule_ids == ("rule-1",)
    assert after.duty.ad_valorem_percent == 0  # An explicit source expression, never fallback.


def test_gap_in_rate_validity_returns_unavailable_not_a_zero_or_previous_rate():
    manifest = _manifest_with_rules({"valid_to": "2026-07-01"})
    result = resolve_rate(manifest, CODE, DAY, "RU")
    assert result.status == "unavailable"
    assert result.reason == "no_applicable_rate"
    assert result.duty is None


def test_code_validity_is_checked_even_when_snapshot_coverage_is_broader():
    data = synthetic_manifest_data()
    data["codes"][0]["valid_to"] = "2026-07-01"
    data["rate_rules"][0]["valid_to"] = "2026-07-01"
    result = resolve_rate(validate_manifest(data), CODE, DAY, "RU")
    assert result.status == "unavailable"
    assert result.reason == "code_not_effective"
    assert result.duty is None


def test_code_description_versions_follow_their_own_intervals():
    data = synthetic_manifest_data()
    first = data["codes"][0]
    first["valid_to"] = "2026-07-01"
    data["codes"].append(dict(deepcopy(first), description="Second synthetic version",
                              valid_from="2026-07-01", valid_to="2027-01-01"))
    initial = data["rate_rules"][0]
    initial["valid_to"] = "2026-07-01"
    data["rate_rules"].append(dict(deepcopy(initial), rule_id="new-version",
                                   valid_from="2026-07-01", valid_to="2027-01-01"))
    result = resolve_rate(validate_manifest(data), CODE, DAY, "RU")
    assert result.status == "resolved"
    assert result.rule_ids == ("new-version",)


def test_destination_is_not_inferred_from_origin_country():
    manifest = _manifest_with_rules(
        {"destinations": ["RU"]},
        {"destinations": ["KZ"], "duty": {"kind": "ad_valorem", "ad_valorem_percent": "7"}},
    )
    result = resolve_rate(manifest, CODE, DAY, "KZ", {"origin_country": "RU"})
    assert result.rule_ids == ("rule-1",)
    assert result.duty.ad_valorem_percent == 7
    assert resolve_rate(manifest, CODE, DAY, "AM").reason == "no_applicable_rate"


@pytest.mark.parametrize("destination", ["AM", "BY", "KZ", "KG", "RU"])
def test_all_explicit_member_destinations_are_supported(destination):
    assert resolve_rate(synthetic_manifest(), CODE, DAY, destination).status == "resolved"


@pytest.mark.parametrize("value,rule", [
    ("10.11", "rule-0"),
    (Decimal("10.110000000000"), "rule-0"),
    ("10.110000000001", "rule-1"),
    (Decimal("10.109999999999"), "rule-0"),
    (11, "rule-1"),
    (0, "rule-0"),
])
def test_thresholds_are_exact_and_do_not_depend_on_decimal_context(value, rule):
    manifest = _numeric_manifest()
    with localcontext() as context:
        context.prec = 2
        result = resolve_rate(manifest, CODE, DAY, "RU", {"alcohol_percent": value})
    assert result.status == "resolved"
    assert result.rule_ids == (rule,)


@pytest.mark.parametrize("value", [
    True, False, 10.11, float("nan"), float("inf"),
    Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"),
    Decimal("1e999999999"), Decimal("1e-999999999"),
    "1e1", "+10", " 10", "10 ", "01", "10.", ".1", "10,11", "１０", "NaN",
    "1" * 25, "0." + "1" * 13, 10**1000, -1, "-0.1", Decimal("-0.1"), [], {},
])
def test_malformed_numeric_facts_cannot_be_used_as_threshold_evidence(value):
    with pytest.raises(ValueError):
        resolve_rate(_numeric_manifest(), CODE, DAY, "RU", {"alcohol_percent": value})


def test_missing_numeric_fact_retains_both_candidates_and_their_sources():
    manifest = _numeric_manifest()
    result = resolve_rate(manifest, CODE, DAY, "RU")
    assert result.status == "needs_clarification"
    assert result.rule_ids == ("rule-0", "rule-1")
    assert result.missing_facts == ("alcohol_percent",)
    assert result.duty is None
    assert result.evidence == manifest.rate_rules[0].evidence  # Shared source is deduplicated.


def test_missing_facts_are_sorted_unique_and_only_asked_for_possible_rules():
    manifest = _manifest_with_rules(
        {"conditions": [
            {"field": "purpose", "op": "eq", "value": "industrial"},
            {"field": "material", "op": "eq", "value": "steel"},
            {"field": "origin_country", "op": "eq", "value": "CN"},
        ]},
        {"conditions": [
            {"field": "purpose", "op": "eq", "value": "household"},
            {"field": "packaging", "op": "eq", "value": "retail"},
        ]},
    )
    result = resolve_rate(manifest, CODE, DAY, "RU", {"purpose": "industrial", "material": None})
    assert result.status == "needs_clarification"
    assert result.rule_ids == ("rule-0",)
    assert result.missing_facts == ("material", "origin_country")


def test_exact_string_condition_is_not_substring_or_casefolded():
    manifest = _manifest_with_rules({"conditions": [
        {"field": "purpose", "op": "eq", "value": "industrial"},
    ]})
    for value in ("not industrial", "Industrial", "industrial "):
        result = resolve_rate(manifest, CODE, DAY, "RU", {"purpose": value})
        assert result.status == "unavailable"
        assert result.duty is None
    assert resolve_rate(manifest, CODE, DAY, "RU", {"purpose": "industrial"}).status == "resolved"


def test_boolean_conditions_never_treat_integer_or_string_as_boolean():
    manifest = _manifest_with_rules({"conditions": [
        {"field": "is_used", "op": "eq", "value": True},
    ]})
    assert resolve_rate(manifest, CODE, DAY, "RU", {"is_used": True}).status == "resolved"
    assert resolve_rate(manifest, CODE, DAY, "RU", {"is_used": False}).status == "unavailable"
    for value in (1, 0, "true", "false", Decimal(1)):
        with pytest.raises(ValueError):
            resolve_rate(manifest, CODE, DAY, "RU", {"is_used": value})


@pytest.mark.parametrize("code", ["0101", "101210000", CODE + "0", " " + CODE, CODE + "\n",
                                  "０１０１２１００００", 101210000, None, True])
def test_codes_are_exact_ten_ascii_digits_with_no_padding_or_prefix_fallback(code):
    with pytest.raises(ValueError):
        resolve_rate(synthetic_manifest(), code, DAY, "RU")


def test_absent_ten_digit_code_has_no_prefix_or_zero_fallback():
    result = resolve_rate(synthetic_manifest(), "0101210001", DAY, "RU")
    assert result.status == "unavailable"
    assert result.reason == "code_not_present"
    assert result.duty is None


@pytest.mark.parametrize("as_of", [None, "2026-09-08", 20260908, True,
                                   datetime(2026, 9, 8), datetime(2026, 9, 8, tzinfo=timezone.utc)])
def test_date_is_required_without_clock_or_datetime_coercion(as_of):
    with pytest.raises(ValueError):
        resolve_rate(synthetic_manifest(), CODE, as_of, "RU")


@pytest.mark.parametrize("destination", [None, "", "ru", "RUS", "RU ", "DE", True])
def test_destination_is_required_without_default_country(destination):
    with pytest.raises(ValueError):
        resolve_rate(synthetic_manifest(), CODE, DAY, destination)


@pytest.mark.parametrize("facts", [[], "purpose=industrial", {1: "industrial"},
                                   {str(index): True for index in range(257)}])
def test_facts_are_a_bounded_mapping_with_string_keys(facts):
    with pytest.raises(ValueError):
        resolve_rate(synthetic_manifest(), CODE, DAY, "RU", facts)


def test_tampered_overlapping_rules_are_revalidated_not_selected_last():
    manifest = synthetic_manifest()
    original = manifest.rate_rules[0]
    conflict = original.model_copy(update={"rule_id": "other"})
    unvalidated = manifest.model_copy(update={"rate_rules": (original, conflict)})
    with pytest.raises(ValueError, match="overlapping rate rules"):
        resolve_rate(unvalidated, CODE, DAY, "RU")


def test_resolution_uses_the_same_revalidated_representation_as_the_digest():
    manifest = synthetic_manifest()
    copied_rule = manifest.rate_rules[0].model_copy(update={"valid_from": "2026-01-01"})
    copied_manifest = manifest.model_copy(update={"rate_rules": (copied_rule,)})
    result = resolve_rate(copied_manifest, CODE, DAY, "RU")
    assert result.status == "resolved"
    assert result.manifest_sha256 == manifest_sha256(manifest)
    assert copied_rule.valid_from == "2026-01-01"  # The caller's object remains untouched.


def test_evidence_and_footnote_resolution_remain_attached_to_selected_expression():
    data = synthetic_manifest_data()
    source = next(item for item in data["artifacts"] if item["role"] == "tariff_notes")
    data["rate_rules"][0]["footnote_ids"] = ["note-1"]
    data["footnotes"] = [{"footnote_id": "note-1", "text": "Synthetic rate footnote",
                          "evidence": [evidence_for(source)], "resolution": "rate_rule",
                          "rule_ids": ["test-rule-1"], "rationale": "Synthetic normalized expression"}]
    manifest = validate_manifest(data)
    result = resolve_rate(manifest, CODE, DAY, "RU")
    assert result.footnotes == manifest.footnotes
    assert result.footnotes[0].evidence[0].artifact_sha256 == source["sha256"]
    assert result.manifest_sha256 == manifest_sha256(manifest)


@pytest.mark.parametrize("kind", ["specific", "combined_max", "combined_sum"])
def test_structured_specific_and_combined_expressions_are_preserved(kind):
    duty = {"kind": kind, "specific_amount": "0.123456789012", "currency": "EUR",
            "unit": "kg", "unit_quantity": "100"}
    if kind != "specific":
        duty["ad_valorem_percent"] = "12.5"
    manifest = _manifest_with_rules({"duty": duty})
    result = resolve_rate(manifest, CODE, DAY, "RU")
    assert result.status == "resolved"
    assert result.duty == manifest.rate_rules[0].duty
    assert result.duty.unit_quantity == 100
    assert result.duty.specific_amount == Decimal("0.123456789012")


def test_preview_is_deterministic_without_mutating_inputs():
    manifest = _numeric_manifest()
    facts = {"alcohol_percent": "11", "purpose": "unchanged"}
    original_facts = dict(facts)
    original_manifest = manifest.model_dump_json()
    first = resolve_rate(manifest, CODE, DAY, "RU", facts)
    second = resolve_rate(manifest, CODE, DAY, "RU", facts)
    assert first == second
    assert facts == original_facts
    assert manifest.model_dump_json() == original_manifest
