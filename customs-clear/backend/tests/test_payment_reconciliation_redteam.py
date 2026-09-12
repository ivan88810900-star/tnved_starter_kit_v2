"""Independent A6 arithmetic/availability checks using existing isolated fixtures.

Shared fixtures supply synthetic data and block external/application DB access.
These assertions independently test reconciliation and preserve the distinction
between a calculable provisional estimate and a legally usable final quote.
"""
from decimal import Decimal
import json

import pytest

from app.services import payment_engine as engine
from app.services import payment_quote_service as quotes
from tests.test_payment_preference_eligibility import payment_data
from tests.test_payment_special_duty_applicability import remedies, payload, resolve


@pytest.mark.parametrize("coefficient", [1.00001, 1.9999, 3.75, -0.5, None, False, "2.5"])
def test_unverified_coefficient_does_not_override_undiscounted_calculation(payment_data, coefficient):
    payment_data.coefficient = coefficient
    request = payload(country="BR", eligibility_verified=True, amounts_provisional=False)
    result = engine.compute_payments(request)
    assert result["breakdown"]["duty"] == 10000
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["amounts_provisional"] is True
    assert result["tariff_preference"]["applied"] is False
    assert result["tariff_preference"]["eligibility_verified"] is False
    assert result["tariff_preference"]["duty_coefficient"] == 1
    json.dumps(result, allow_nan=False)
    quote = quotes.build_payment_quote(request)
    lines = {line.code: line for line in quote.line_items}
    assert quote.total_payable_rub is None
    assert lines["duty"].amount_rub is lines["vat"].amount_rub is None


@pytest.mark.parametrize("legacy_percent,structured_percent", [(9, 3), (9, 9)])
def test_antidumping_overlap_stays_unavailable_without_erasing_other_family(
        remedies, legacy_percent, structured_percent):
    row, _ = engine.find_rate_for_hs("8509400000")
    row.antidumping_type = "percent"
    row.antidumping_value = legacy_percent
    row.antidumping_countries = "CN"
    row.antidumping_condition = ""
    remedies(rate_percent=structured_percent)
    remedies(rate_percent=2.25, measure_type="countervailing")
    result = resolve()
    assert result["status"] == "REVIEW_REQUIRED" and result["amounts_provisional"] is True
    candidates = {item["measure_family"]: item for item in result["special_duties"]}
    ad = candidates["anti_dumping"]
    assert ad["amount"] is None and ad["calculation_available"] is False
    assert ad["applied"] is False and ad["status"] == "needs_clarification"
    assert "legacy_antidumping_overlap_unverified" in ad["review_reasons"]
    assert ad["rate_percent"] == structured_percent
    assert result["auto_detected"]["antidumping_value"] == legacy_percent
    assert result["data_quality"]["antidumping_status"] == "manual_review"
    assert candidates["countervailing"]["amount"] == 2250
    assert result["breakdown"]["antidumping"] == 0
    assert result["special_duties_amount"] == 2250
    quote = quotes.build_payment_quote(payload())
    lines = {line.code: line for line in quote.line_items}
    assert lines["antidumping"].amount_rub is None
    assert lines["antidumping"].status == "manual_review_required"
    assert lines["special_duty"].amount_rub is None
    assert lines["vat"].amount_rub is None
    assert quote.total_payable_rub is None


@pytest.mark.parametrize("other_origin", ["MY", "DE"])
def test_nonmatching_structured_origin_does_not_remove_the_legacy_component(remedies, other_origin):
    row, _ = engine.find_rate_for_hs("8509400000")
    row.antidumping_type, row.antidumping_value, row.antidumping_countries = "percent", 9, "CN"
    remedies(rate_percent=3, origin_country=other_origin)
    result = resolve()
    assert result["special_duties"] == []
    assert result["breakdown"]["antidumping"] == 9000


@pytest.mark.parametrize("customs_value", [100.17, 100.23, 222.27, 333.33, 789.99, 1000.05])
def test_payable_displayed_cents_and_vat_basis_reconcile_exactly(payment_data, customs_value):
    result = engine.compute_payments(payload(customs_value=customs_value))
    part = result["breakdown"]
    amount = lambda value: Decimal(str(value))
    payable = sum(amount(part[key]) for key in (
        "customs_fee", "duty", "excise", "antidumping", "special_duties_amount", "vat", "recycling_fee",
    ))
    basis = sum(amount(value) for value in (
        result["customs_value"], part["duty"], part["excise"], part["antidumping"], part["special_duties_amount"],
    ))
    assert amount(part["total_payable"]) == payable
    assert amount(part["vat_base"]) == basis


@pytest.mark.parametrize("customs_value", [100.17, 222.27, 333.33])
def test_provisional_remedy_sum_equals_visible_cents_without_granting_legal_application(
        remedies, customs_value):
    remedies(rate_percent=7.25)
    remedies(rate_percent=2.75, measure_type="countervailing")
    result = resolve(customs_value=customs_value, legal_review_verified=True, amounts_provisional=False)
    rows = result["special_duties"]
    assert all(item["status"] == "provisional" for item in rows)
    assert all(item["applied"] is item["legal_review_verified"] is False for item in rows)
    assert all(item["review_reasons"] == ["legal_review_unverified"] for item in rows)
    displayed = sum(Decimal(str(item["amount"])) for item in rows)
    assert Decimal(str(result["special_duties_amount"])) == displayed
    assert result["status"] == "REVIEW_REQUIRED" and result["amounts_provisional"] is True
    quote = quotes.build_payment_quote(payload(customs_value=customs_value))
    assert quote.total_payable_rub is None
