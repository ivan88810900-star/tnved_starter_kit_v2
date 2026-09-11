"""Unresolved remedy candidates never become a known zero or final payment.

All rows are synthetic and confined to one in-memory SpecialDuty table. No legal
data is imported and no application database or external source is accessed.
"""
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.tnved import SpecialDuty
from app.services import payment_engine as engine
from app.services import payment_quote_service as quotes
from app.services.payment_result_status import payment_result_metadata
from tests.test_payment_preference_eligibility import payment_data


RESOLVE_SPECIAL = engine._resolve_special_duties


@pytest.fixture
def remedies(payment_data, monkeypatch):
    database = create_engine("sqlite:///:memory:")
    SpecialDuty.__table__.create(database)
    sessions = sessionmaker(bind=database)
    monkeypatch.setattr(engine, "SessionLocal", sessions)
    monkeypatch.setattr(engine, "_resolve_special_duties", lambda **kw: RESOLVE_SPECIAL(**kw, as_of="2026-09-08"))

    def add(**overrides):
        fields = dict(hs_code_prefix="850940", origin_country="CN", rate_percent=5.0,
                      rate_specific=0.0, currency_code="", regulatory_act="Synthetic remedy fixture",
                      measure_type="anti_dumping", manufacturer_exporter="", product_description="",
                      effective_from="2026-01-01", effective_to="2026-12-31", needs_verification=False,
                      source_code="EEC_ANTI_DUMPING", source_revision="anti-dumping:2026-01-01",
                      source_url="https://eec.eaeunion.org/synthetic-test-only",
                      safeguard_source_code="EEC_SPECIAL_SAFEGUARD", safeguard_source_revision="special-safeguard:2026-01-01",
                      safeguard_source_url="https://eec.eaeunion.org/synthetic-test-only",
                      countervailing_source_code="EEC_COUNTERVAILING", countervailing_source_revision="countervailing:2026-01-01",
                      countervailing_source_url="https://eec.eaeunion.org/synthetic-test-only")
        fields.update(overrides)
        with sessions() as db:
            row = SpecialDuty(**fields)
            db.add(row)
            db.commit()
            return row.id

    yield add
    database.dispose()


def payload(**overrides):
    return {"hs_code": "8509400000", "country": "CN",
            "customs_value": 100_000, "insurance": 0, **overrides}


def resolve(**overrides):
    return engine.compute_payments(payload(**overrides))


def resolve_rows(as_of):
    return RESOLVE_SPECIAL(hs_code="8509400000", country="CN", customs_value=100_000,
                           quantity=1, fx_rates={}, as_of=as_of)


@pytest.mark.parametrize("start,end,as_of,expected", [
    ("2026-09-09", "2027-01-01", "2026-09-08", 0),
    ("2025-01-01", "2026-09-07", "2026-09-08", 0),
    ("2026-09-08", "2026-09-08", "2026-09-08", 5_000),
    ("2025-01-01", "2025-12-31", "2025-06-01", 5_000),
])
def test_explicit_date_excludes_inactive_rows_and_keeps_existing_inclusive_end(remedies, start, end, as_of, expected):
    remedies(effective_from=start, effective_to=end)
    total, details = resolve_rows(as_of)
    assert total == expected
    if expected:
        assert details[0]["as_of"] == as_of and details[0]["status"] == "provisional"
    else:
        assert details == []


@pytest.mark.parametrize("as_of", ["20260908", "2026-9-8", "invalid", True, datetime(2026, 9, 8)])
def test_malformed_explicit_date_never_falls_back_to_today(remedies, as_of):
    remedies()
    with pytest.raises(ValueError):
        resolve_rows(as_of)


def test_calendar_date_object_is_explicit(remedies):
    remedies()
    assert resolve_rows(date(2026, 9, 8))[0] == 5_000


@pytest.mark.parametrize("row,reason", [
    ({"manufacturer_exporter": "Producer A"}, "manufacturer_exporter_condition_unverified"),
    ({"product_description": "Only goods with an unstructured characteristic"}, "product_characteristics_unverified"),
    ({"needs_verification": True}, "source_row_requires_verification"),
    ({"effective_from": ""}, "effective_period_unverified"),
    ({"effective_to": ""}, "effective_period_unverified"),
    ({"effective_from": "01.01.2026"}, "effective_period_unverified"),
    ({"effective_from": "2027-01-01", "effective_to": "2026-01-01"}, "effective_period_invalid"),
    ({"origin_country": ""}, "origin_country_scope_unverified"),
    ({"origin_country": "CN,MY"}, "origin_country_scope_unverified"),
    ({"measure_type": "unknown"}, "measure_type_unverified"),
    ({"rate_percent": -1}, "rate_expression_unverified"),
    ({"rate_percent": float("inf")}, "rate_expression_unverified"),
    ({"rate_specific": 10.0, "currency_code": "USD"}, "specific_unit_basis_unverified"),
    ({"source_code": "", "source_revision": "", "source_url": ""}, "source_provenance_unverified"),
    ({"source_code": "EEC_VAT", "source_revision": "vat:2026-01-01"}, "source_provenance_unverified"),
    ({"source_url": "https://example.test/unverified"}, "source_provenance_unverified"),
])
def test_unproved_rows_keep_evidence_and_block_money_and_dependent_vat(remedies, row, reason):
    candidate_id = remedies(**row)
    result = resolve(quantity=500, net_weight_kg=500, _fx_rates={"USD": 92},
                     manufacturer_exporter="Producer A", product_description=row.get("product_description", ""),
                     applicability_verified=True, amounts_provisional=False)
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["amounts_provisional"] is True
    assert result["payment_review_reasons"] == ["special_duty_applicability_unverified"]
    item = result["special_duties"][0]
    assert item["candidate_id"] == candidate_id
    assert item["status"] == "needs_clarification" and item["applied"] is False
    assert item["amount"] is None and reason in item["review_reasons"]
    assert item["regulatory_act"] == "Synthetic remedy fixture"
    assert item["source_url"] == row.get("source_url", "https://eec.eaeunion.org/synthetic-test-only")
    assert item["source_revision"] == row.get("source_revision", "anti-dumping:2026-01-01")
    assert result["special_duties_amount"] == 0
    assert result["breakdown"]["vat_base"] == 110_000  # Explicitly provisional subtotal.
    quote = quotes.build_payment_quote(payload(vat_rate=22))
    lines = {line.code: line for line in quote.line_items}
    assert lines["special_duty"].status == "manual_review_required"
    assert lines["special_duty"].amount_rub is None
    assert lines["vat"].status == "manual_review_required"
    assert lines["vat"].amount_rub is None and lines["vat"].basis_amount_rub is None
    assert lines["duty"].amount_rub == 10_000
    assert quote.total_payable_rub is None and quote.total_partial_rub == 11_000
    metadata = payment_result_metadata(result)
    assert metadata["payment_status"] == "REVIEW_REQUIRED" and metadata["amounts_provisional"] is True
    assert metadata["payment_review_reasons"] == ["special_duty_applicability_unverified"]


def test_missing_origin_is_review_while_a_known_other_origin_is_excluded(remedies):
    remedies()
    missing = resolve(country=None)
    assert missing["status"] == "REVIEW_REQUIRED"
    assert "origin_country_missing" in missing["special_duties"][0]["review_reasons"]
    assert missing["special_duties"][0]["warning"]
    other = resolve(country="MY", duty_rate=10)
    assert other["special_duties"] == [] and other["special_duties_amount"] == 0


@pytest.mark.parametrize("different_acts", [False, True])
def test_default_and_producer_alternatives_are_never_summed(remedies, different_acts):
    remedies(rate_percent=20)
    remedies(rate_percent=5, hs_code_prefix="8509400000", manufacturer_exporter="Producer A",
             regulatory_act="Other possibly amending act" if different_acts else "Synthetic remedy fixture")
    result = resolve(manufacturer_exporter="Producer A")
    assert result["special_duties_amount"] == 0
    assert len(result["special_duties"]) == 2
    assert all(item["amount"] is None and "overlapping_measure_candidates" in item["review_reasons"]
               for item in result["special_duties"])
    assert result["status"] == "REVIEW_REQUIRED"


def test_known_distinct_family_partial_is_retained_but_never_final(remedies):
    remedies(rate_percent=20, manufacturer_exporter="Producer A")
    remedies(rate_percent=3, measure_type="countervailing", regulatory_act="Synthetic separate-family fixture")
    result = resolve()
    assert result["special_duties_amount"] == 3_000
    assert result["breakdown"]["vat_base"] == 113_000
    assert result["status"] == "REVIEW_REQUIRED"
    quote = quotes.build_payment_quote(payload())
    lines = {line.code: line for line in quote.line_items}
    assert lines["special_duty"].amount_rub is None and lines["vat"].amount_rub is None
    assert quote.total_payable_rub is None and quote.total_partial_rub == 11_000
    assumption = next(item for item in quote.assumptions if item.key == "provisional_special_duties_rub")
    assert assumption.value == "3 000.00 RUB"


def test_unknown_specific_currency_and_quantity_cannot_guess_unit_or_use_fallback(remedies):
    remedies(rate_percent=0, rate_specific=2, currency_code="UNBOUND")
    result = resolve(quantity=1_000, net_weight_kg=20, extra_quantity=77,
                     specific_uom="kg", quantity_unit="kg", _fx_rates={"UNBOUND": 100})
    item = result["special_duties"][0]
    assert item["fx_rate"] is None and item["amount"] is None
    assert item["review_reasons"] == ["specific_unit_basis_unverified"]


def test_explicit_unconditional_zero_is_provisional_arithmetic_and_different_from_unknown(remedies):
    remedies(rate_percent=0)
    result = resolve()
    item = result["special_duties"][0]
    assert item["status"] == "provisional" and item["amount"] == 0
    assert item["review_reasons"] == ["legal_review_unverified"] and result["amounts_provisional"] is True
    assert item["official_source_marker_present"] is True and item["legal_review_verified"] is False
    quote = quotes.build_payment_quote(payload())
    assert quote.total_payable_rub is None


def test_nonmatching_producer_condition_does_not_make_future_row_block_current(remedies):
    remedies(manufacturer_exporter="Producer A", effective_from="2027-01-01", effective_to="2027-12-31")
    result = resolve()
    assert result["special_duties"] == [] and result["amounts_provisional"] is False


def test_safeguard_synonyms_do_not_bypass_overlapping_alternative_guard(remedies):
    remedies(measure_type="special_safeguard", rate_percent=10)
    remedies(measure_type="special_protective", rate_percent=20)
    result = resolve()
    assert result["special_duties_amount"] == 0
    assert all("overlapping_measure_candidates" in item["review_reasons"] for item in result["special_duties"])


@pytest.mark.parametrize("excise_type,value", [
    ("needs_review", 20), ("unsupported_positive_form", 20), ("none", 20),
    ("none", float("nan")), ("percent", float("inf")), ("fixed", -1),
])
def test_unknown_excise_propagates_to_dependent_vat_and_recorded_status(remedies, monkeypatch, excise_type, value):
    rate, _ = engine.find_rate_for_hs("8509400000")
    rate.excise_type = excise_type
    rate.excise_value = value
    result = resolve()
    assert result["payment_review_reasons"] == ["excise_applicability_unverified"]
    quote = quotes.build_payment_quote(payload())
    lines = {line.code: line for line in quote.line_items}
    assert lines["excise"].status == "manual_review_required" and lines["excise"].amount_rub is None
    assert lines["vat"].amount_rub is None and lines["vat"].basis_amount_rub is None
    assert quote.total_payable_rub is None and quote.total_partial_rub == 11_000


@pytest.mark.parametrize("ad_type,condition,country", [
    ("percent", "", None), ("percent", "Only a specified producer", "CN"),
    ("unsupported_positive_form", "", "CN"), ("none", "", "CN"),
])
def test_unresolved_legacy_antidumping_propagates_to_vat_and_review(remedies, ad_type, condition, country):
    rate, _ = engine.find_rate_for_hs("8509400000")
    rate.antidumping_type, rate.antidumping_value = ad_type, 20
    rate.antidumping_condition, rate.antidumping_countries = condition, "CN"
    result = resolve(country=country)
    assert result["payment_review_reasons"] == ["antidumping_applicability_unverified"]
    quote = quotes.build_payment_quote(payload(country=country))
    lines = {line.code: line for line in quote.line_items}
    assert lines["antidumping"].amount_rub is None and lines["vat"].amount_rub is None
    assert quote.total_payable_rub is None and quote.total_partial_rub == 11_000


@pytest.mark.parametrize("as_of", ["2026-09-08", "2020-01-01", "invalid", None])
def test_legacy_engine_explicitly_rejects_date_instead_of_partial_temporal_claim(remedies, as_of):
    with pytest.raises(ValueError, match="as_of"):
        resolve(as_of=as_of)


@pytest.mark.parametrize("target", ["top", "shared", "scenario"])
def test_direct_compare_rejects_date_at_every_supported_payload_level(remedies, target):
    data = {"shared": {"customs_value": 100_000},
            "scenarios": [{"hs_code": "8509400000"}, {"hs_code": "8509400001"}]}
    destination = data if target == "top" else data["shared"] if target == "shared" else data["scenarios"][0]
    destination["as_of"] = "2020-01-01"
    with pytest.raises(ValueError, match="as_of"):
        engine.compare_payment_scenarios(data)


@pytest.mark.parametrize("route,request_body", [
    ("/api/payments/quote", {"hs_code": "8509400000", "customs_value": 100}),
    ("/api/calculator/compute", {"hs_code": "8509400000", "customs_value": 100}),
    ("/api/calculator/compare", {"shared": {"customs_value": 100, "as_of": "2020-01-01"},
                                 "scenarios": [{"hs_code": "8509400000"}, {"hs_code": "8509400001"}]}),
    ("/api/calculator/compare", {"shared": {"customs_value": 100},
                                 "scenarios": [{"hs_code": "8509400000", "as_of": "2020-01-01"}, {"hs_code": "8509400001"}]}),
])
def test_actual_request_boundary_rejects_as_of_before_any_payment_or_history_work(remedies, monkeypatch, route, request_body):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import calculator, payments

    app = FastAPI()
    app.include_router(calculator.router, prefix="/api/calculator")
    app.include_router(payments.router, prefix="/api/payments")
    monkeypatch.setattr(payments, "build_payment_quote", lambda *a, **k: pytest.fail("Date was silently discarded"))
    monkeypatch.setattr(calculator, "compute_payments", lambda *a, **k: pytest.fail("Date was silently discarded"))
    data = dict(request_body)
    if route != "/api/calculator/compare":
        data["as_of"] = "2020-01-01"
    response = TestClient(app).post(route, json=data)
    assert response.status_code == 422
    assert "as_of" in response.text
