"""Adversarial contract tests; synthetic records do not prove legal coverage."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError

from app.services.ett_manifest import (
    ETTCondition, ETTDuty, ETTManifest, canonical_manifest_bytes,
    conditions_provably_disjoint, manifest_sha256, validate_manifest,
)
from tests.ett_fixtures import evidence_for, synthetic_manifest, synthetic_manifest_data


def test_roundtrip_is_complete_stable_and_explicitly_not_an_approval():
    manifest = synthetic_manifest()
    body = canonical_manifest_bytes(manifest)
    assert len(manifest.artifacts) == 100
    assert manifest_sha256(manifest) == hashlib.sha256(body).hexdigest()
    assert canonical_manifest_bytes(body) == body
    assert validate_manifest(body) == manifest
    altered = json.loads(body)
    altered["approved"] = True
    with pytest.raises(ValidationError, match="Extra inputs"):
        validate_manifest(altered)


def test_nested_aliases_cannot_mutate_the_manifest():
    data = synthetic_manifest_data()
    manifest = validate_manifest(data)
    digest = manifest_sha256(manifest)
    data["rate_rules"][0]["destinations"].clear()
    data["codes"][0]["evidence"][0]["raw_text"] = "tampered"
    assert manifest_sha256(manifest) == digest
    with pytest.raises(ValidationError, match="frozen"):
        manifest.rate_rules[0].duty.ad_valorem_percent = Decimal("99")
    assert isinstance(manifest.rate_rules, tuple)
    assert isinstance(manifest.rate_rules[0].evidence, tuple)


@pytest.mark.parametrize("change", [
    lambda d: d.update(snapshot_id="another-snapshot"),
    lambda d: d["parser"].update(sha256="b" * 64),
    lambda d: d["codes"][0].update(description="Different synthetic description"),
    lambda d: d["rate_rules"][0]["duty"].update(ad_valorem_percent="6"),
    lambda d: d.update(coverage_to="2026-12-01"),
    lambda d: d["rate_rules"][0].update(destinations=["RU"]),
    lambda d: d["artifacts"][0].update(sha256="b" * 64),
    lambda d: d["artifacts"][0].update(url="https://docs.eaeunion.org/synthetic-other-index"),
])
def test_all_normalized_content_is_bound(change):
    data = synthetic_manifest_data()
    before = manifest_sha256(data)
    change(data)
    assert manifest_sha256(data) != before


def test_decimal_hashing_preserves_digits_independently_of_context():
    data = synthetic_manifest_data()
    data["rate_rules"][0]["duty"]["ad_valorem_percent"] = "123456789012345678901234.123456789012"
    expected = manifest_sha256(data)
    with localcontext() as ctx:
        ctx.prec = 3
        assert manifest_sha256(data) == expected
    data["rate_rules"][0]["duty"]["ad_valorem_percent"] = "123456789012345678901234.123456789013"
    assert manifest_sha256(data) != expected
    data["rate_rules"][0]["duty"]["ad_valorem_percent"] = "5.000"
    assert manifest_sha256(data) == manifest_sha256(synthetic_manifest_data())


@pytest.mark.parametrize("value", [5.0, float("nan"), float("inf"), True, "NaN", "1e2", "+5", " 5", "5 ", "５", Decimal("Infinity"), Decimal("1e999999999"), Decimal("1e-999999999"), 10**100])
def test_duty_rejects_lossy_or_unbounded_quantities(value):
    with pytest.raises(ValidationError):
        ETTDuty(kind="ad_valorem", ad_valorem_percent=value)


@pytest.mark.parametrize("duty", [
    {"kind": "ad_valorem"},
    {"kind": "ad_valorem", "ad_valorem_percent": "-1"},
    {"kind": "ad_valorem", "ad_valorem_percent": "5", "vat_rate": "22"},
    {"kind": "specific", "specific_amount": "1"},
    {"kind": "specific", "specific_amount": "1", "currency": "EUR", "unit": "kg", "unit_quantity": "0"},
    {"kind": "combined_max", "ad_valorem_percent": "5"},
    {"kind": "raw_formula", "ad_valorem_percent": "5"},
])
def test_incomplete_or_unsupported_duty_never_defaults_to_zero(duty):
    with pytest.raises(ValidationError):
        ETTDuty.model_validate(duty)


@pytest.mark.parametrize("kind", ["specific", "combined_max", "combined_sum"])
def test_explicit_specific_and_combined_duties(kind):
    fields = {"kind": kind, "specific_amount": "0.25", "currency": "EUR", "unit": "kg", "unit_quantity": "100"}
    if kind != "specific":
        fields["ad_valorem_percent"] = "5"
    assert ETTDuty.model_validate(fields).specific_amount == Decimal("0.25")


@pytest.mark.parametrize("value", ["2026-01-01T00:00:00Z", datetime(2026, 1, 1), datetime(2026, 1, 1, tzinfo=timezone.utc), True, 20260101, "2026-1-1", "２０２６-01-01"])
def test_dates_are_explicit_not_coerced(value):
    data = synthetic_manifest_data()
    data["coverage_from"] = value
    with pytest.raises(ValidationError):
        validate_manifest(data)


@pytest.mark.parametrize("value", ["2026-09-01", "2026-09-01T01:00:00", "2026-09-01T01:00:00+03:00", 1234, True])
def test_creation_time_requires_utc(value):
    data = synthetic_manifest_data()
    data["created_at"] = value
    with pytest.raises(ValidationError):
        validate_manifest(data)


@pytest.mark.parametrize("url", [
    "http://eec.eaeunion.org/a.pdf", "https://evil.example/a.pdf",
    "https://eec.eaeunion.org.evil.example/a.pdf", "https://user:secret@eec.eaeunion.org/a.pdf",
    "https://eec.eaeunion.org:443/a.pdf", "https://eec.eaeunion.org/a.pdf?",
    "https://eec.eaeunion.org/a.pdf#", "https://eec.eaeunion.org/a.pdf?key=secret",
    "https://eec.eaeunion.org/a.pdf#page=1", "https://eec.eaeunion.org\\evil/a.pdf",
    "https://eec.eaeunion.org/a\n.pdf", "https://eec.eaeunion.org/%0dabc.pdf",
])
def test_only_exact_clean_official_urls_are_accepted(url):
    data = synthetic_manifest_data()
    data["artifacts"][0]["url"] = url
    with pytest.raises(ValidationError):
        validate_manifest(data)


@pytest.mark.parametrize("change", [
    lambda d: d["artifacts"].pop(),
    lambda d: d["artifacts"].append(copy.deepcopy(d["artifacts"][-1])),
    lambda d: d["artifacts"][-1].update(chapter="77"),
    lambda d: d["artifacts"][-1].update(chapter="96"),
    lambda d: d["artifacts"][0].update(role="amendment"),
    lambda d: d["artifacts"][0].update(url=d["artifacts"][1]["url"]),
    lambda d: d["artifacts"][0].update(retrieved_at="2026-09-02T00:00:00Z"),
    lambda d: d["artifacts"][-1].update(media_type="text/html"),
    lambda d: d.update(coverage_from=d["coverage_to"]),
    lambda d: d.update(schema_version=2.0),
    lambda d: d["codes"][0].update(code="０１０１２１００００"),
    lambda d: d["codes"][0].update(code="7712110000"),
    lambda d: d["codes"].append(copy.deepcopy(d["codes"][0])),
    lambda d: d["codes"][0].update(description=" "),
    lambda d: d["rate_rules"][0].update(code="0101290000"),
    lambda d: d["rate_rules"][0].update(valid_to="2027-02-01"),
    lambda d: d["rate_rules"][0].update(destinations=[]),
    lambda d: d["rate_rules"][0].update(destinations=["RU", "RU"]),
    lambda d: d["rate_rules"][0].update(destinations=["DE"]),
    lambda d: d["rate_rules"][0].update(footnote_ids=["missing-footnote"]),
    lambda d: d["rate_rules"][0].update(effective_evidence=[]),
    lambda d: d["rate_rules"][0]["evidence"][0].update(page=True),
    lambda d: d["rate_rules"][0]["evidence"][0].update(raw_text="Modified but old hash"),
    lambda d: d["rate_rules"][0]["evidence"][0].update(artifact_sha256="0" * 64),
    lambda d: d["rate_rules"][0]["evidence"][0].update(artifact_id="absent"),
    lambda d: d["rate_rules"][0].update(evidence=[evidence_for(d["artifacts"][0])]),
    lambda d: d["rate_rules"][0].update(evidence=[evidence_for(d["artifacts"][-1])]),
])
def test_incomplete_duplicate_or_unbound_candidate_fails_closed(change):
    data = synthetic_manifest_data()
    change(data)
    with pytest.raises(ValidationError):
        validate_manifest(data)


def test_code_without_explicit_rate_is_not_a_zero_duty():
    data = synthetic_manifest_data()
    another = copy.deepcopy(data["codes"][0])
    another["code"] = "0101290000"
    data["codes"].append(another)
    with pytest.raises(ValidationError, match="explicit rate"):
        validate_manifest(data)


def _two_rules() -> dict:
    data = synthetic_manifest_data()
    second = copy.deepcopy(data["rate_rules"][0])
    second["rule_id"] = "test-rule-2"
    second["duty"]["ad_valorem_percent"] = "7"
    data["rate_rules"].append(second)
    return data


def test_overlapping_rates_rejected_even_when_the_amounts_agree():
    data = _two_rules()
    with pytest.raises(ValidationError, match="overlapping rate"):
        validate_manifest(data)
    data["rate_rules"][1]["duty"] = copy.deepcopy(data["rate_rules"][0]["duty"])
    with pytest.raises(ValidationError, match="overlapping rate"):
        validate_manifest(data)


@pytest.mark.parametrize("separation", ["date", "destination", "fact", "numeric"])
def test_disjoint_rate_applicability_is_permitted(separation):
    data = _two_rules()
    left, right = data["rate_rules"]
    if separation == "date":
        left["valid_to"] = right["valid_from"] = "2026-07-01"
    elif separation == "destination":
        left["destinations"], right["destinations"] = ["RU"], ["AM", "BY", "KG", "KZ"]
    elif separation == "fact":
        left["conditions"] = [{"field": "purpose", "op": "eq", "value": "adult"}]
        right["conditions"] = [{"field": "purpose", "op": "eq", "value": "child"}]
    else:
        left["conditions"] = [{"field": "mass_kg", "op": "numeric_interval", "maximum": "10", "maximum_inclusive": False}]
        right["conditions"] = [{"field": "mass_kg", "op": "numeric_interval", "minimum": "10"}]
    assert len(validate_manifest(data).rate_rules) == 2


def test_touching_inclusive_numeric_bounds_still_overlap():
    data = _two_rules()
    data["rate_rules"][0]["conditions"] = [{"field": "mass_kg", "op": "numeric_interval", "maximum": "10"}]
    data["rate_rules"][1]["conditions"] = [{"field": "mass_kg", "op": "numeric_interval", "minimum": "10"}]
    with pytest.raises(ValidationError, match="overlapping rate"):
        validate_manifest(data)


@pytest.mark.parametrize("condition", [
    {"field": "unknown", "op": "eq", "value": "x"},
    {"field": "purpose", "op": "regex", "value": ".*"},
    {"field": "purpose", "op": "eq", "value": True},
    {"field": "is_used", "op": "eq", "value": "true"},
    {"field": "purpose", "op": "eq", "value": ""},
    {"field": "mass_kg", "op": "eq", "value": "1"},
    {"field": "mass_kg", "op": "numeric_interval"},
    {"field": "purpose", "op": "numeric_interval", "minimum": "1"},
    {"field": "mass_kg", "op": "numeric_interval", "minimum": "2", "maximum": "1"},
    {"field": "mass_kg", "op": "numeric_interval", "minimum": "1", "maximum": "1", "minimum_inclusive": False},
    {"field": "mass_kg", "op": "numeric_interval", "minimum": "-1"},
    {"field": "mass_kg", "op": "numeric_interval", "minimum": 1.0},
])
def test_unknown_empty_or_contradictory_condition_is_rejected(condition):
    with pytest.raises(ValidationError):
        ETTCondition.model_validate(condition)


def test_unrelated_facts_cannot_prove_disjointness():
    a = ETTCondition(field="purpose", op="eq", value="adult")
    b = ETTCondition(field="material", op="eq", value="steel")
    assert not conditions_provably_disjoint((a,), (b,))


def _footnoted() -> dict:
    data = synthetic_manifest_data()
    data["footnotes"] = [{"footnote_id": "note-1", "text": "Synthetic note effect",
                          "evidence": copy.deepcopy(data["rate_rules"][0]["effective_evidence"]),
                          "resolution": "rate_rule", "rule_ids": ["test-rule-1"],
                          "rationale": "Synthetic footnote translated to this exact test rule"}]
    data["rate_rules"][0]["footnote_ids"] = ["note-1"]
    return data


def test_footnotes_are_included_in_digest_and_bind_both_ways():
    data = _footnoted()
    before = manifest_sha256(data)
    data["footnotes"][0]["rationale"] += "; revised explanation"
    assert manifest_sha256(data) != before
    data["footnotes"][0]["rule_ids"] = []
    with pytest.raises(ValidationError):
        validate_manifest(data)


@pytest.mark.parametrize("change", [
    lambda d: d["footnotes"][0].update(resolution="unresolved"),
    lambda d: d["footnotes"][0].update(rule_ids=["absent-rule"]),
    lambda d: d["rate_rules"][0].update(footnote_ids=[]),
    lambda d: d["footnotes"][0].update(rationale=" "),
])
def test_unresolved_footnotes_cannot_enter_valid_candidates(change):
    data = _footnoted()
    change(data)
    with pytest.raises(ValidationError):
        validate_manifest(data)


def test_duplicate_json_keys_and_nonfinite_json_are_rejected_before_validation():
    body = canonical_manifest_bytes(synthetic_manifest()).decode()
    with pytest.raises(ValueError, match="duplicate JSON key"):
        validate_manifest(body.replace('"schema_version":2', '"schema_version":1,"schema_version":2'))
    with pytest.raises(ValueError, match="non-finite"):
        validate_manifest(body.replace('"schema_version":2', '"schema_version":NaN'))


def test_model_construct_cannot_bypass_validation_at_digest_boundary():
    valid = synthetic_manifest()
    invalid = ETTManifest.model_construct(**{**valid.model_dump(), "coverage_from": valid.coverage_to})
    with pytest.raises(ValidationError):
        manifest_sha256(invalid)


def test_unvalidated_nested_model_copy_is_also_revalidated():
    valid = synthetic_manifest()
    duty = valid.rate_rules[0].duty.model_copy(update={"ad_valorem_percent": Decimal("-1")})
    rule = valid.rate_rules[0].model_copy(update={"duty": duty})
    copied = valid.model_copy(update={"rate_rules": (rule,)})
    with pytest.raises(ValidationError, match="cannot be negative"):
        manifest_sha256(copied)


def test_per_code_bound_prevents_unbounded_overlap_comparison():
    data = synthetic_manifest_data()
    template = data["rate_rules"][0]
    data["rate_rules"] = []
    for index in range(257):
        rule = copy.deepcopy(template)
        rule["rule_id"] = f"bounded-test-{index}"
        rule["conditions"] = [{"field": "purpose", "op": "eq", "value": f"distinct-{index}"}]
        data["rate_rules"].append(rule)
    with pytest.raises(ValidationError, match="at most 256 rules"):
        validate_manifest(data)
