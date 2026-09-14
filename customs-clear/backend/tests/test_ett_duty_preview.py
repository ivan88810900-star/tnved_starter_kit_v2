"""Synthetic arithmetic cases are not evidence of any legally applicable rate."""

from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime
from decimal import Decimal, Inexact, Rounded, localcontext
import hashlib

import pytest
from pydantic import ValidationError

from app.services.ett_duty_preview import ETTPreviewExchangeRate, preview_duty
from app.services.ett_manifest import ETTDuty, manifest_sha256
from tests.ett_fixtures import synthetic_manifest_data


DAY = date(2026, 9, 8)


def _duty(kind="specific", **changes):
    values = {"kind": kind}
    if kind != "ad_valorem":
        values.update(specific_amount="2.5", currency="EUR", unit="kg", unit_quantity="100")
    if kind != "specific":
        values["ad_valorem_percent"] = "5"
    if kind == "capped_combined_max":
        values.update(unit="engine_displacement_cm3", ad_valorem_cap_percent="15")
    values.update(changes)
    return ETTDuty.model_validate(values)


def _fx(**changes):
    # Deliberately synthetic and unverified; the URL is a reference, not a fetch.
    text = "SYNTHETIC EUR/RUB factor 100.25 for 2026-09-08"
    values = dict(
        from_currency="EUR", to_currency="RUB", as_of=DAY, multiplier="100.25",
        source_url="https://example.invalid/synthetic-rates", source_artifact_sha256="a" * 64,
        source_locator="synthetic row 1", source_text=text,
        source_text_sha256=hashlib.sha256(text.encode()).hexdigest(),
    )
    values.update(changes)
    return ETTPreviewExchangeRate(**values)


def _preview(duty=None, **inputs):
    values = dict(as_of=DAY, currency="EUR", quantity="200", quantity_unit="kg")
    values.update(inputs)
    return preview_duty(_duty() if duty is None else duty, **values)


def test_specific_per_100kg_and_directed_fx_keep_explicit_bases_and_provisional_trace():
    result = _preview(currency="RUB", exchange_rate=_fx())
    assert result.status == "calculated"
    assert result.amount == Decimal("501.25")
    assert result.specific_amount == result.amount
    assert result.ad_valorem_amount is None and result.cap_amount is None
    assert result.quantity == Decimal("200") and result.quantity_unit == "kg"
    assert result.duty.unit_quantity == Decimal("100")
    assert result.exchange_rate.multiplier == Decimal("100.25")
    assert result.trace[0].operation == "multiply_divide"
    assert result.trace[0].operands == (Decimal("2.5"), Decimal(200), Decimal("100.25"), Decimal(100))
    assert result.trace[0].result == Decimal("501.25")
    assert result.mode == "candidate_preview"
    assert not result.legally_approved and not result.final_payable
    assert not result.source_evidence_verified and not result.rounding_applied


@pytest.mark.parametrize("kind,customs_value,expected,operation", [
    ("ad_valorem", "1000", "50", "multiply_divide"),
    ("specific", None, "5", "multiply_divide"),
    ("combined_sum", "1000", "55", "sum"),
    ("combined_max", "1000", "50", "max"),
    ("combined_max", "10", "5", "max"),
    ("combined_max", "100", "5", "max"),
])
def test_all_uncapped_kinds_apply_the_declared_operation(kind, customs_value, expected, operation):
    result = _preview(_duty(kind), customs_value=customs_value)
    assert result.status == "calculated" and result.amount == Decimal(expected)
    assert result.trace[-1].operation == operation


@pytest.mark.parametrize("specific,expected", [("0.1", "50"), ("0.6", "60"), ("2", "150")])
def test_engine_cap_order_is_min_of_cap_and_max_of_components(specific, expected):
    result = _preview(
        _duty("capped_combined_max", specific_amount=specific, unit_quantity="1"),
        customs_value="1000", quantity="100", quantity_unit="engine_displacement_cm3",
    )
    assert result.amount == Decimal(expected)
    assert result.ad_valorem_amount == Decimal(50)
    assert result.specific_amount == Decimal(specific) * 100
    assert result.cap_amount == Decimal(150)
    assert [step.operation for step in result.trace] == ["multiply_divide"] * 3 + ["max", "min"]
    assert result.trace[-1].operands == (Decimal(150), result.trace[-2].result)


@pytest.mark.parametrize("unit", ["kg", "g", "tonne", "litre", "m3", "m2", "m", "unit", "pair", "kwh", "engine_displacement_cm3"])
def test_explicit_total_quantity_is_evaluated_in_the_exact_declared_unit(unit):
    result = _preview(_duty(unit=unit, specific_amount="7", unit_quantity="1000"), quantity="250", quantity_unit=unit)
    assert result.amount == Decimal("1.75")


@pytest.mark.parametrize("unit,supplied", [("kg", "g"), ("g", "kg"), ("tonne", "kg"), ("litre", "m3"), ("pair", "unit"), ("engine_displacement_cm3", "m3")])
def test_unit_mismatch_never_converts_or_confuses_cargo_volume_with_engine_displacement(unit, supplied):
    result = _preview(_duty(unit=unit), quantity_unit=supplied)
    assert result.status == "unavailable" and result.reason == "quantity_unit_mismatch"
    assert result.amount is None and result.trace == ()


def test_global_decimal_precision_exponents_rounding_and_traps_cannot_change_arithmetic():
    duty = _duty("combined_sum", ad_valorem_percent="12.123456789012", specific_amount="0.123456789012", unit_quantity="1000")
    inputs = dict(customs_value="999999999999999999999999.123456789012", quantity="999999999999999999999999.123456789012", currency="RUB", exchange_rate=_fx(multiplier="123.123456789012"))
    ordinary = _preview(duty, **inputs)
    with localcontext() as context:
        context.prec = 2
        context.Emax = 2
        context.Emin = -2
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        context.clear_flags()
        stressed = _preview(duty, **inputs)
        assert not any(context.flags.values())
    assert ordinary.status == stressed.status == "calculated"
    assert stressed == ordinary
    assert len(stressed.amount.as_tuple().digits) > 50


def test_exact_cancelled_scale_division_is_not_rounded_prematurely():
    result = _preview(_duty(specific_amount="1", unit_quantity="3"), quantity="1", currency="RUB", exchange_rate=_fx(multiplier="3"))
    assert result.status == "calculated" and result.amount == Decimal(1)
    assert not result.rounding_applied


def test_nonterminating_division_is_unavailable_without_any_guessed_payable_amount():
    result = _preview(_duty(specific_amount="1", unit_quantity="3"), quantity="1")
    assert result.status == "unavailable" and result.reason == "nonterminating_decimal"
    assert result.amount is None and result.specific_amount is None
    assert result.trace == () and not result.rounding_applied


def test_exact_sub_cent_amount_is_retained_without_assuming_a_statutory_rounding_rule():
    result = _preview(_duty(specific_amount="0.000001", unit_quantity="1000"), quantity="1")
    assert result.amount == Decimal("0.000000001")


@pytest.mark.parametrize("inputs,missing", [
    ({"quantity": None}, ("quantity",)),
    ({"quantity": "0"}, ("quantity",)),
    ({"quantity_unit": None}, ("quantity_unit",)),
    ({"currency": "RUB"}, ("exchange_rate",)),
    ({"quantity": None, "quantity_unit": None, "currency": "RUB"}, ("quantity", "quantity_unit", "exchange_rate")),
])
def test_missing_or_empty_specific_bases_do_not_become_zero(inputs, missing):
    result = _preview(**inputs)
    assert result.status == "needs_clarification" and result.missing_facts == missing
    assert result.amount is None


def test_ad_valorem_requires_an_explicit_value_even_for_an_explicit_zero_rate():
    duty = _duty("ad_valorem", ad_valorem_percent="0")
    absent = preview_duty(duty, as_of=DAY, currency="RUB")
    zero_rate = preview_duty(duty, as_of=DAY, currency="RUB", customs_value="100")
    zero_value = preview_duty(_duty("ad_valorem"), as_of=DAY, currency="RUB", customs_value=0)
    assert absent.status == "needs_clarification" and absent.amount is None
    assert absent.missing_facts == ("customs_value",)
    assert zero_rate.status == zero_value.status == "calculated"
    assert zero_rate.amount == zero_value.amount == Decimal(0)
    assert zero_rate.ad_valorem_amount == Decimal(0)


def test_specific_zero_still_requires_quantity_and_an_explicit_conversion_when_needed():
    duty = _duty(specific_amount="0")
    known = _preview(duty)
    missing_quantity = _preview(duty, quantity=None)
    missing_factor = _preview(duty, currency="RUB")
    assert known.status == "calculated" and known.amount == Decimal(0)
    assert missing_quantity.status == missing_factor.status == "needs_clarification"
    assert missing_quantity.amount is missing_factor.amount is None


@pytest.mark.parametrize("changes,reason", [
    ({"from_currency": "USD"}, "exchange_rate_pair_mismatch"),
    ({"from_currency": "RUB", "to_currency": "EUR"}, "exchange_rate_pair_mismatch"),
    ({"to_currency": "USD"}, "exchange_rate_pair_mismatch"),
    ({"as_of": date(2026, 9, 7)}, "exchange_rate_date_mismatch"),
    ({"as_of": date(2026, 9, 9)}, "exchange_rate_date_mismatch"),
])
def test_no_inverse_cross_rate_previous_day_or_future_day_fallback(changes, reason):
    result = _preview(currency="RUB", exchange_rate=_fx(**changes))
    assert result.status == "unavailable" and result.reason == reason
    assert result.amount is None


@pytest.mark.parametrize("kind", ["specific", "ad_valorem"])
def test_unneeded_currency_factor_is_not_silently_applied_or_ignored(kind):
    result = _preview(_duty(kind), customs_value="100", exchange_rate=_fx())
    assert result.status == "unavailable" and result.reason == "exchange_rate_pair_mismatch"


@pytest.mark.parametrize("value", [True, False, 1.5, -1, "-1", "-0", "1e2", "01", ".5", "1.", " 1", "1\n", "NaN", "Infinity", "1" * 25, "0." + "1" * 13, 10 ** 100, Decimal("NaN"), Decimal("Infinity"), Decimal("1e10000"), Decimal("1e-10000"), {}, []])
def test_binary_float_nonfinite_ambiguous_and_oversized_quantities_are_rejected(value):
    with pytest.raises(ValueError):
        _preview(quantity=value)


@pytest.mark.parametrize("field,value", [("customs_value", 12.5), ("quantity_unit", "cm3"), ("quantity_unit", "KG"), ("quantity_unit", True), ("currency", "rub"), ("currency", "CNY"), ("currency", []), ("as_of", "2026-09-08"), ("as_of", datetime(2026, 9, 8))])
def test_explicit_input_types_are_not_guessed(field, value):
    with pytest.raises(ValueError):
        _preview(**{field: value})


@pytest.mark.parametrize("changes", [
    {"multiplier": "0"}, {"multiplier": "-1"}, {"multiplier": 100.25},
    {"multiplier": True}, {"multiplier": Decimal("NaN")},
    {"as_of": "2026-09-08"}, {"as_of": datetime(2026, 9, 8)},
    {"from_currency": "eur"}, {"from_currency": "RUB"},
    {"source_url": "http://example.invalid/rates"},
    {"source_url": "https://user:secret@example.invalid/rates"},
    {"source_url": "https://example.invalid/rates#fragment"},
    {"source_url": "https://example.invalid/\nrates"},
    {"source_url": "https://example.invalid/\\rates"},
    {"source_artifact_sha256": "A" * 64}, {"source_artifact_sha256": ""},
    {"source_locator": ""}, {"source_locator": "x" * 513},
    {"source_text": "a different quote"}, {"source_text": ""},
    {"source_text_sha256": "b" * 64},
])
def test_currency_factor_evidence_shape_and_quote_digest_fail_closed(changes):
    with pytest.raises(ValueError):
        _preview(currency="RUB", exchange_rate=_fx(**changes))


def test_quote_reference_cannot_claim_original_bytes_or_factor_authenticity():
    result = _preview(currency="RUB", exchange_rate=_fx(multiplier="999"))
    # A supplied factor need not agree with this declared text: that requires a
    # separately supported source parser. Arithmetic must make no such claim.
    assert result.amount == Decimal("4995")
    assert not result.source_evidence_verified and not result.legally_approved
    assert "100.25" in result.exchange_rate.source_text
    assert result.exchange_rate.multiplier == Decimal(999)


def test_preview_does_not_rely_on_a_bypassed_duty_model_validation():
    forged = _duty().model_copy(update={"unit_quantity": Decimal(0)})
    with pytest.raises(ValidationError):
        _preview(forged)
    with pytest.raises(ValueError):
        _preview({"kind": "ad_valorem", "ad_valorem_percent": "0"})


def test_all_result_metadata_is_immutable_and_cannot_turn_on_approval():
    result = _preview(currency="RUB", exchange_rate=_fx())
    with pytest.raises(FrozenInstanceError):
        result.final_payable = True
    with pytest.raises(FrozenInstanceError):
        result.exchange_rate.multiplier = Decimal(1)
    with pytest.raises(FrozenInstanceError):
        result.trace[0].result = Decimal(0)
    with pytest.raises(ValueError):
        replace(result, legally_approved=True)


def test_candidate_manifest_serialization_and_identity_remain_unchanged():
    assert manifest_sha256(synthetic_manifest_data()) == "dfc7093f5fe87bd39a3bebee633808f725a725c84e8b009a705d8687e5580af3"
