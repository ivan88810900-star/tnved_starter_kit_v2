"""A6 reconciliation: synthetic regressions, never legal source or rate approval."""
from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.services import payment_engine as engine
from app.services import payment_quote_service as quotes
from tests.test_payment_preference_eligibility import payment_data
from tests.test_payment_special_duty_applicability import remedies, payload, resolve, resolve_rows


@pytest.mark.parametrize("coefficient", [1.25, 2.0, 4.0])
def test_unreviewed_upward_coefficient_cannot_change_duty_or_confirm_quote(payment_data, coefficient):
    payment_data.coefficient = coefficient
    request = payload(country="ZZ", eligibility_verified=True, amounts_provisional=False)
    result = engine.compute_payments(request)
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["breakdown"]["duty"] == 10_000
    assert result["breakdown"]["vat_base"] == 110_000
    assert result["tariff_preference"]["applied"] is False
    assert result["tariff_preference"]["eligibility_verified"] is False
    assert result["tariff_preference"]["candidate_duty_coefficient"] == coefficient
    assert result["tariff_preference"]["duty_coefficient"] == 1
    quote = quotes.build_payment_quote(request)
    lines = {line.code: line for line in quote.line_items}
    assert lines["duty"].amount_rub is None
    assert lines["vat"].amount_rub is None
    assert quote.total_payable_rub is None


@pytest.mark.parametrize("coefficient", [None, True, "invalid", float("nan"), float("inf")])
def test_invalid_country_coefficient_remains_reviewable_and_json_safe(payment_data, coefficient):
    payment_data.coefficient = coefficient
    result = engine.compute_payments(payload(country="ZZ"))
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["breakdown"]["duty"] == 10_000
    assert result["tariff_preference"]["applied"] is False
    assert result["tariff_preference"]["candidate_duty_coefficient"] is None
    assert result["tariff_preference"]["eligibility_verified"] is False
    json.dumps(result, allow_nan=False)


def test_upward_coefficient_does_not_scale_specific_fixture_arithmetic(payment_data):
    payment_data.coefficient = 2
    payment_data.duty_rule = engine._FallbackDutyRule(
        commodity_code="8509400000", type="specific", ad_valorem_pct=None,
        specific_amount=2, specific_currency="EUR", specific_uom="kg",
    )
    result = engine.compute_payments(payload(country="ZZ", net_weight_kg=100, _fx_rates={"EUR": 100}))
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["breakdown"]["duty"] == result["breakdown"]["specific_amount_rub"] == 20_000


@pytest.mark.parametrize("legacy_value, candidate_value", [(5, 5), (18, 5)])
def test_legacy_and_structured_antidumping_are_not_assumed_cumulative(remedies, legacy_value, candidate_value):
    rate, _ = engine.find_rate_for_hs("8509400000")
    rate.antidumping_type = "percent"
    rate.antidumping_value = legacy_value
    rate.antidumping_countries = "CN"
    rate.antidumping_condition = ""
    remedies(rate_percent=candidate_value)
    result = resolve()
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["breakdown"]["antidumping"] == 0
    assert result["breakdown"]["special_duties_amount"] == 0
    assert result["breakdown"]["vat_base"] == 110_000
    assert result["data_quality"]["antidumping_status"] == "manual_review"
    candidate = result["special_duties"][0]
    assert candidate["amount"] is None and candidate["calculation_available"] is False
    assert candidate["status"] == "needs_clarification"
    assert "legacy_antidumping_overlap_unverified" in candidate["review_reasons"]
    assert candidate["rate_percent"] == candidate_value
    assert candidate["regulatory_act"] == "Synthetic remedy fixture"
    assert result["auto_detected"]["antidumping_value"] == legacy_value
    assert result["auto_detected"]["antidumping_countries"] == "CN"
    legacy = result["legacy_antidumping_candidate"]
    assert legacy["rate_value"] == legacy_value and legacy["origin_country_scope"] == "CN"
    assert legacy["source_revision"] == "test"
    assert legacy["amount"] is None and legacy["applied"] is False
    assert legacy["legal_review_verified"] is False
    assert legacy["status"] == "needs_clarification"
    quote = quotes.build_payment_quote(payload())
    lines = {line.code: line for line in quote.line_items}
    assert lines["antidumping"].amount_rub is None
    assert lines["special_duty"].amount_rub is None
    assert lines["vat"].amount_rub is None
    assert quote.total_payable_rub is None


def test_cross_store_overlap_preserves_other_distinct_family_estimate(remedies):
    rate, _ = engine.find_rate_for_hs("8509400000")
    rate.antidumping_type, rate.antidumping_value, rate.antidumping_countries = "percent", 5, "CN"
    remedies(rate_percent=5)
    remedies(rate_percent=3, measure_type="countervailing")
    result = resolve()
    assert result["breakdown"]["antidumping"] == 0
    assert result["special_duties_amount"] == 3_000
    assert result["breakdown"]["vat_base"] == 113_000
    by_family = {item["measure_family"]: item for item in result["special_duties"]}
    assert by_family["anti_dumping"]["amount"] is None
    assert by_family["countervailing"]["amount"] == 3_000
    assert result["amounts_provisional"] is True


def test_nonmatching_legacy_origin_does_not_block_structured_candidate(remedies):
    rate, _ = engine.find_rate_for_hs("8509400000")
    rate.antidumping_type, rate.antidumping_value, rate.antidumping_countries = "percent", 5, "MY"
    remedies(rate_percent=3)
    result = resolve()
    assert result["breakdown"]["antidumping"] == 0
    assert result["special_duties_amount"] == 3_000
    assert "legacy_antidumping_overlap_unverified" not in result["special_duties"][0]["review_reasons"]


@pytest.mark.parametrize("customs_value", [100.02, 100.07, 100.14])
def test_total_equals_sum_of_displayed_payable_components(payment_data, customs_value):
    result = engine.compute_payments(payload(customs_value=customs_value))
    part = result["breakdown"]
    displayed = sum(Decimal(str(part[key])) for key in (
        "customs_fee", "duty", "excise", "antidumping", "special_duties_amount", "vat", "recycling_fee",
    ))
    assert Decimal(str(part["total_payable"])) == displayed
    base = sum(Decimal(str(value)) for value in (
        result["customs_value"], part["duty"], part["excise"], part["antidumping"], part["special_duties_amount"],
    ))
    assert Decimal(str(part["vat_base"])) == base


def test_remedy_aggregate_equals_visible_candidate_cents(remedies):
    remedies(rate_percent=5)
    remedies(rate_percent=3, measure_type="countervailing")
    result = resolve(customs_value=100.07)
    visible = sum(Decimal(str(item["amount"])) for item in result["special_duties"]
                  if item["calculation_available"])
    assert Decimal(str(result["special_duties_amount"])) == visible
    assert result["status"] == "REVIEW_REQUIRED"


def test_provisional_arithmetic_is_not_an_applied_or_final_legal_grant(remedies):
    remedies(rate_percent=5)
    result = resolve()
    item = result["special_duties"][0]
    assert item["status"] == "provisional" and item["calculation_available"] is True
    assert item["applied"] is False and item["legal_review_verified"] is False
    assert item["review_reasons"] == ["legal_review_unverified"]
    assert item["amount"] == result["special_duties_amount"] == 5_000
    assert result["breakdown"]["vat_base"] == 115_000
    assert result["status"] == "REVIEW_REQUIRED" and result["amounts_provisional"] is True
    quote = quotes.build_payment_quote(payload())
    assert quote.total_payable_rub is None
    assert all(line.amount_rub is None for line in quote.line_items if line.code in {"special_duty", "vat"})


@pytest.mark.parametrize("origin", ["", "CN,MY", "China", "ALL"])
@pytest.mark.parametrize("country", ["CN", "DE"])
def test_unknown_origin_scope_remains_candidate_without_applied_money(remedies, origin, country):
    remedies(origin_country=origin)
    result = resolve(country=country, duty_rate=10)
    item = result["special_duties"][0]
    assert item["status"] == "needs_clarification"
    assert item["applied"] is False and item["amount"] is None
    assert item["calculation_available"] is False
    assert "origin_country_scope_unverified" in item["review_reasons"]
    assert result["special_duties_amount"] == 0 and result["amounts_provisional"] is True


def test_missing_specific_unit_is_review_and_never_confirmed_zero(remedies):
    remedies(rate_percent=0, rate_specific=2, currency_code="EUR")
    result = resolve(quantity=1_000, net_weight_kg=1_000, _fx_rates={"EUR": 100})
    item = result["special_duties"][0]
    assert item["status"] == "needs_clarification"
    assert item["amount"] is None and "specific_unit_basis_unverified" in item["review_reasons"]
    assert result["amounts_provisional"] is True


def test_date_aware_private_resolver_does_not_enable_unsupported_whole_quote_date(remedies):
    remedies()
    assert resolve_rows("2026-09-08")[0] == 5_000
    with pytest.raises(ValueError, match="as_of"):
        resolve(as_of="2026-09-08")
