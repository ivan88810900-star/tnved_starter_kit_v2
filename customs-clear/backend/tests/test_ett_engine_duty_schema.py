"""Engine-basis expressions remain bounded candidates with stable old digests."""
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.services.ett_manifest import ETTDuty, canonical_manifest_bytes, manifest_sha256, validate_manifest
from app.services.ett_resolver import resolve_rate
from tests.ett_fixtures import synthetic_manifest_data


def _capped():
    return {"kind": "capped_combined_max", "ad_valorem_cap_percent": "15", "ad_valorem_percent": "12.5",
            "specific_amount": "0.6", "currency": "EUR", "unit": "engine_displacement_cm3", "unit_quantity": "1"}


def test_schema_v2_previous_manifest_digest_and_duty_wire_shape_are_unchanged():
    # Captured before this additive expression extension. Old immutable
    # candidates must remain readable with their exact previously retained SHA.
    assert manifest_sha256(synthetic_manifest_data()) == "dfc7093f5fe87bd39a3bebee633808f725a725c84e8b009a705d8687e5580af3"
    duty = ETTDuty(kind="ad_valorem", ad_valorem_percent="5")
    assert duty.model_dump_json() == '{"kind":"ad_valorem","ad_valorem_percent":"5","specific_amount":null,"currency":null,"unit":null,"unit_quantity":null}'
    assert "ad_valorem_cap_percent" not in duty.model_dump()


@pytest.mark.parametrize("kind", ["specific", "combined_max", "combined_sum"])
def test_uncapped_old_shapes_have_no_added_null_field(kind):
    data = {"kind": kind, "specific_amount": "0.25", "currency": "EUR", "unit": "kg", "unit_quantity": "100"}
    if kind != "specific": data["ad_valorem_percent"] = "5"
    duty = ETTDuty.model_validate(data)
    assert "ad_valorem_cap_percent" not in duty.model_dump()
    assert ETTDuty.model_validate(duty.model_dump()) == duty


def test_capped_engine_rule_roundtrips_through_manifest_and_readonly_resolver():
    data = synthetic_manifest_data()
    data["rate_rules"][0]["duty"] = _capped()
    manifest = validate_manifest(data)
    body = canonical_manifest_bytes(manifest)
    assert validate_manifest(body) == manifest
    assert b'"ad_valorem_cap_percent":"15"' in body
    resolved = resolve_rate(manifest, "0101210000", date(2026, 9, 1), "RU")
    assert resolved.status == "resolved"  # Expression selection, not a monetary calculation.
    assert resolved.mode == "candidate_preview"
    assert resolved.duty == manifest.rate_rules[0].duty
    assert resolved.duty.ad_valorem_cap_percent == Decimal("15")
    assert resolved.duty.unit == "engine_displacement_cm3"
    original_digest = manifest_sha256(manifest)
    data["rate_rules"][0]["duty"]["ad_valorem_cap_percent"] = "16"
    assert manifest_sha256(data) != original_digest


@pytest.mark.parametrize("missing", ["ad_valorem_cap_percent", "ad_valorem_percent", "specific_amount", "currency", "unit", "unit_quantity"])
def test_all_components_of_the_nested_expression_are_required(missing):
    data = _capped()
    del data[missing]
    with pytest.raises(ValidationError): ETTDuty.model_validate(data)


@pytest.mark.parametrize("change", [
    {"unit": "m3"}, {"unit": "kg"}, {"unit": "cm3"}, {"unit_quantity": "0"},
    {"ad_valorem_cap_percent": "-1"}, {"ad_valorem_cap_percent": "12"},
    {"ad_valorem_cap_percent": 15.0}, {"ad_valorem_cap_percent": True},
    {"ad_valorem_cap_percent": "NaN"}, {"ad_valorem_cap_percent": "1e2"},
    {"ad_valorem_cap_percent": Decimal("Infinity")}, {"ad_valorem_cap_percent": 10 ** 100},
    {"cap_amount": "15"}, {"vat_rate": "22"}, {"kind": "combined_min"},
])
def test_invalid_basis_cap_and_extraneous_fields_fail_closed(change):
    data = _capped()
    data.update(change)
    with pytest.raises(ValidationError): ETTDuty.model_validate(data)


@pytest.mark.parametrize("kind", ["ad_valorem", "specific", "combined_max", "combined_sum"])
def test_a_cap_cannot_silently_change_an_existing_kind(kind):
    data = _capped()
    data["kind"] = kind
    if kind == "ad_valorem":
        for key in ("specific_amount", "currency", "unit", "unit_quantity"): del data[key]
    elif kind == "specific":
        del data["ad_valorem_percent"]
    with pytest.raises(ValidationError, match="cap"): ETTDuty.model_validate(data)


def test_model_copy_cannot_bypass_cap_validation_when_revalidated():
    valid = ETTDuty.model_validate(_capped())
    forged = valid.model_copy(update={"ad_valorem_cap_percent": Decimal("-1")})
    with pytest.raises(ValidationError): ETTDuty.model_validate(forged)
