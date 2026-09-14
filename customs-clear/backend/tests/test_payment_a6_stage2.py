"""A6 stage 2: isolated executable cases, never an official rate dataset.

The same file can run against the base checkout with importlib mode/PYTHONPATH.
Only three fresh in-memory tables are created; application data and network
providers are never used. Diagnostic JSON exposes actual arithmetic/status.
"""
from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.core import HsRate
from app.models.tnved import HsDutyRule, SpecialDuty
from app.services import normative_store as store
from app.services import payment_engine as engine
from app.services import payment_quote_service as quotes


CODE = "8501100000"


@pytest.fixture
def isolated_payments(monkeypatch):
    database = create_engine("sqlite:///:memory:")
    for model in (HsRate, HsDutyRule, SpecialDuty):
        model.__table__.create(database)
    sessions = sessionmaker(bind=database)
    state = SimpleNamespace(coefficient=1.0, geo=None, fx={"RUB": 1.0}, sessions=sessions)
    monkeypatch.setattr(engine, "SessionLocal", sessions)
    monkeypatch.setattr(store, "SessionLocal", sessions)
    monkeypatch.setattr(engine, "find_rate_for_hs", store.find_rate_for_hs)
    monkeypatch.setattr(engine, "_find_vat_preference", lambda _: (None, 0))
    monkeypatch.setattr(engine, "get_country_risk_by_iso", lambda _: None)
    monkeypatch.setattr(engine, "find_geo_embargo_match", lambda *a, **k: None)
    monkeypatch.setattr(engine, "find_geo_duty_override_row", lambda *a, **k: state.geo)
    monkeypatch.setattr(engine, "get_tariff_preference", lambda _: SimpleNamespace(
        duty_coefficient=state.coefficient, preference_type="synthetic", legal_ref="Synthetic fixture"))
    monkeypatch.setattr(engine, "get_recycling_fee", lambda *a, **k: [])
    monkeypatch.setattr(engine, "calculate_customs_fee", lambda _: 4924.0)
    monkeypatch.setattr(engine, "get_integrated_data_stats", lambda: {"hs_rates_count": 1})
    monkeypatch.setattr(engine, "get_tnved_context_for_hs", lambda _: {"title": "Synthetic goods"})
    monkeypatch.setattr("app.services.rate_display.resolve_excise_for_hs", lambda _: ("none", 0.0, ""))
    monkeypatch.setattr(quotes, "compute_payments", engine.compute_payments)
    monkeypatch.setattr(quotes, "get_rates_map", lambda: dict(state.fx))
    monkeypatch.setattr(quotes, "canonical_anchor_for_hs", lambda _: None)
    # Isolate the reviewed arithmetic from the separate coverage-warning path.
    monkeypatch.setattr(quotes, "_special_duties_configured_for_hs", lambda _: True)

    def set_rate(**changes):
        with sessions() as session:
            row = session.query(HsRate).first()
            if row is None:
                row = HsRate(hs_code=CODE, hs_prefix=CODE, duty_rate="10%", vat_import_rate=22,
                             excise_type="none", excise_value=0, antidumping_type="none", antidumping_value=0,
                             antidumping_condition="", antidumping_countries="", vat_rule="none", vat_rule_basis="",
                             valid_from="2020-01-01", valid_to="2099-12-31", source_revision="synthetic")
                session.add(row)
            for key, value in changes.items():
                setattr(row, key, value)
            session.commit()

    def set_duty(**changes):
        with sessions() as session:
            row = session.query(HsDutyRule).first()
            if row is None:
                row = HsDutyRule(commodity_code=CODE, type="ad_valorem", ad_valorem_pct=10,
                                 specific_amount=None, specific_currency="", specific_uom="")
                session.add(row)
            for key, value in changes.items():
                setattr(row, key, value)
            session.commit()

    def add_remedy(**changes):
        fields = dict(hs_code_prefix=CODE[:6], origin_country="CN", rate_percent=5,
                      rate_specific=0, currency_code="", measure_type="anti_dumping",
                      regulatory_act="Synthetic special duty", manufacturer_exporter="", product_description="",
                      effective_from="2020-01-01", effective_to="2099-12-31", needs_verification=False,
                      source_code="EEC_ANTI_DUMPING", source_revision="anti-dumping:2026-01-01",
                      source_url="https://eec.eaeunion.org/synthetic-test-only",
                      countervailing_source_code="EEC_COUNTERVAILING", countervailing_source_revision="countervailing:2026-01-01",
                      countervailing_source_url="https://eec.eaeunion.org/synthetic-test-only")
        fields.update(changes)
        with sessions() as session:
            session.add(SpecialDuty(**fields))
            session.commit()

    state.set_rate, state.set_duty, state.add_remedy = set_rate, set_duty, add_remedy
    set_rate()
    set_duty()
    yield state
    database.dispose()


def request(**changes):
    return dict(hs_code=CODE, customs_value=1_000_000, insurance=0, country="CN", quantity=20, **changes)


def observe(label, payload=None):
    payload = request() if payload is None else payload
    raw = engine.compute_payments(payload)
    quote = quotes.build_payment_quote(payload)
    lines = {line.code: line for line in quote.line_items}
    print("A6_STAGE2 " + json.dumps({
        "case": label, "engine": engine.__file__, "raw_status": raw["status"],
        "raw_breakdown": raw["breakdown"], "review_reasons": raw.get("payment_review_reasons"),
        "quote_status": quote.status, "quote_total": quote.total_payable_rub,
        "lines": {key: {"status": line.status, "amount": line.amount_rub} for key, line in lines.items()},
        "geo": raw.get("geo"), "preference": raw.get("tariff_preference"),
    }, ensure_ascii=False, allow_nan=False))
    return raw, quote, lines


def needs_review(raw, quote, lines, component="duty"):
    assert raw["status"] == "REVIEW_REQUIRED"
    assert quote.status == "REVIEW_REQUIRED"
    assert lines[component].amount_rub is None
    assert lines["vat"].amount_rub is None
    assert quote.total_payable_rub is None


def test_special_provisional_arithmetic_keeps_legal_and_payable_guards(isolated_payments):
    isolated_payments.add_remedy()
    raw, quote, lines = observe("A1_A2_provisional_special")
    detail = raw["special_duties"][0]
    assert detail["applied"] is False and detail["legal_review_verified"] is False
    assert detail["status"] == "provisional"
    assert "legal_review_unverified" in detail["review_reasons"]
    assert raw["breakdown"]["special_duties_amount"] == 50_000
    needs_review(raw, quote, lines, "special_duty")


def test_increased_coefficient_does_not_become_approved_arithmetic(isolated_payments):
    isolated_payments.coefficient = 2
    raw, quote, lines = observe("A3_increased_coefficient")
    assert raw["breakdown"]["duty"] == 100_000
    needs_review(raw, quote, lines)


def test_legacy_and_structured_antidumping_overlap_remains_unresolved(isolated_payments):
    isolated_payments.set_rate(antidumping_type="percent", antidumping_value=5, antidumping_countries="CN")
    isolated_payments.add_remedy()
    raw, quote, lines = observe("A6_antidumping_overlap")
    assert raw["breakdown"]["antidumping"] == 0
    assert raw["breakdown"]["special_duties_amount"] == 0
    needs_review(raw, quote, lines, "antidumping")


@pytest.mark.parametrize("coefficient", [1.0, 0.75, 2.0])
def test_geo_candidate_never_confirms_duty_or_suppresses_preference_review(isolated_payments, coefficient):
    isolated_payments.geo = SimpleNamespace(duty_rate="35%", document_basis="Synthetic geo", document_link="")
    isolated_payments.coefficient = coefficient
    raw, quote, lines = observe(f"A9_geo_and_coefficient_{coefficient}")
    assert raw["breakdown"]["duty"] == 100_000
    needs_review(raw, quote, lines)
    if coefficient != 1:
        assert raw["tariff_preference"]["status"] == "needs_review"
        assert raw["tariff_preference"]["applied"] is False


@pytest.mark.parametrize("with_other_review", [False, True])
def test_fixed_antidumping_without_source_unit_never_uses_universal_quantity(isolated_payments, with_other_review):
    isolated_payments.set_rate(antidumping_type="fixed", antidumping_value=100, antidumping_countries="CN")
    if with_other_review:
        isolated_payments.add_remedy(measure_type="countervailing", rate_percent=3)
    raw, quote, lines = observe(f"A10_fixed_AD_other_review_{with_other_review}")
    needs_review(raw, quote, lines, "antidumping")
    assert raw["data_quality"]["antidumping_status"] == "manual_review"


@pytest.mark.parametrize("currency", ["EUR", "USD"])
@pytest.mark.parametrize("explicit_factor", [None, 123.45])
def test_specific_foreign_fx_map_or_fallback_never_proves_dated_source(isolated_payments, currency, explicit_factor):
    isolated_payments.set_duty(type="specific", ad_valorem_pct=None, specific_amount=2,
                               specific_currency=currency, specific_uom="kg")
    if explicit_factor is not None:
        isolated_payments.fx[currency] = explicit_factor
    payload = request(net_weight_kg=100, _fx_rates=dict(isolated_payments.fx))
    raw, quote, lines = observe(f"A13_specific_FX_{currency}_{explicit_factor}", payload)
    needs_review(raw, quote, lines)


def test_null_as_of_is_omission_not_an_unsupported_historical_request(isolated_payments):
    ordinary = engine.compute_payments(request())
    null_date = engine.compute_payments(request(as_of=None))
    assert null_date == ordinary
    print("A6_STAGE2 " + json.dumps({"case": "null_as_of", "equal_to_omission": True, "engine": engine.__file__}))


@pytest.mark.parametrize("rule_type", ["specific", "combined_max", "combined_min"])
def test_missing_specific_operand_never_means_zero_or_partial_rule_approval(isolated_payments, rule_type):
    isolated_payments.set_duty(type=rule_type, ad_valorem_pct=None if rule_type == "specific" else 10,
                               specific_amount=None, specific_currency="EUR", specific_uom="kg")
    raw, quote, lines = observe(f"A12_missing_specific_amount_{rule_type}", request(net_weight_kg=100))
    needs_review(raw, quote, lines)


@pytest.mark.parametrize("dates", [
    {"valid_from": "2019-01-01", "valid_to": "2020-12-31"},
    {"valid_from": "2098-01-01", "valid_to": "2099-12-31"},
    {"valid_from": "bad-date", "valid_to": "2099-12-31"},
])
def test_expired_future_or_bad_hs_rate_bounds_cannot_confirm_vat(isolated_payments, dates):
    isolated_payments.set_rate(**dates)
    raw, quote, lines = observe(f"HsRate_dates_{dates}")
    assert raw["status"] == quote.status == "REVIEW_REQUIRED"
    assert lines["vat"].amount_rub is None and quote.total_payable_rub is None


@pytest.mark.parametrize("countries", ["", "ALL", "CN,unknown"])
def test_unverified_antidumping_country_scope_never_applies_globally(isolated_payments, countries):
    isolated_payments.set_rate(antidumping_type="percent", antidumping_value=5, antidumping_countries=countries)
    raw, quote, lines = observe(f"A11_AD_countries_{countries}")
    needs_review(raw, quote, lines, "antidumping")


def test_displayed_components_still_reconcile_exactly(isolated_payments):
    raw, _, _ = observe("displayed_cents", {**request(), "customs_value": 100.02})
    part = raw["breakdown"]
    displayed = sum(Decimal(str(part[key])) for key in ("duty", "vat", "excise", "antidumping", "special_duties_amount", "customs_fee", "recycling_fee"))
    assert Decimal(str(part["total_payable"])) == displayed


@pytest.mark.parametrize("value", [0, -1, True, float("nan"), float("inf")])
def test_invalid_specific_fx_never_becomes_one_or_a_confirmed_amount(isolated_payments, value):
    isolated_payments.set_duty(type="specific", ad_valorem_pct=None, specific_amount=2,
                               specific_currency="EUR", specific_uom="kg")
    with pytest.raises(ValueError):
        engine.compute_payments(request(net_weight_kg=100, _fx_rates={"EUR": value}))


@pytest.mark.parametrize("value", [0, -1, True, float("nan"), float("inf")])
def test_invalid_invoice_fx_never_becomes_one(isolated_payments, value):
    isolated_payments.fx["EUR"] = value
    with pytest.raises(ValueError):
        quotes.build_payment_quote(request(invoice_currency="EUR"))


@pytest.mark.parametrize("changes", [
    {"specific_currency": ""}, {"specific_uom": ""}, {"specific_uom": "unknown"},
    {"specific_amount": -1}, {"specific_amount": float("inf")},
])
def test_missing_or_invalid_specific_basis_is_explicitly_unavailable(isolated_payments, changes):
    isolated_payments.set_duty(type="specific", ad_valorem_pct=None, specific_amount=2,
                               specific_currency="RUB", specific_uom="kg")
    isolated_payments.set_duty(**changes)
    raw, quote, lines = observe(f"incomplete_specific_{changes}", request(net_weight_kg=100))
    needs_review(raw, quote, lines)
    assert raw["duty_candidate"]["amount"] is None
    assert raw["duty_candidate"]["calculation_available"] is False


def test_rub_identity_is_not_taken_from_mutable_fx_map(isolated_payments):
    isolated_payments.fx["RUB"] = 17
    isolated_payments.set_duty(type="specific", ad_valorem_pct=None, specific_amount=2,
                               specific_currency="RUB", specific_uom="kg")
    raw, quote, lines = observe("RUB_identity", request(net_weight_kg=100, _fx_rates={"RUB": 17}))
    assert raw["breakdown"]["duty"] == 200
    assert quote.customs_value_rub == 1_000_000
    assert raw["breakdown"]["fx_rate"] == 1
    assert "duty_rule_source_binding_unverified" in raw["payment_review_reasons"]
    needs_review(raw, quote, lines)


def test_invoice_fx_also_withholds_fee_and_other_dependent_components(isolated_payments):
    isolated_payments.fx["EUR"] = 100
    quote = quotes.build_payment_quote(request(invoice_currency="EUR"))
    lines = {line.code: line for line in quote.line_items}
    for key in ("duty", "vat", "customs_fee", "excise", "antidumping", "special_duty"):
        assert lines[key].status == "manual_review_required"
        assert lines[key].amount_rub is None
    assert quote.total_payable_rub is None
    assert lines["customs_fee"].basis_amount_rub is None


def test_existing_recycling_amount_is_visible_and_reconciles_without_recalculation(isolated_payments, monkeypatch):
    monkeypatch.setattr(engine, "get_recycling_fee", lambda *a, **kw: [{
        "fee_amount": 30000.0, "vehicle_type": "synthetic", "is_new": True,
        "base_rate": 20000.0, "coefficient": 1.5, "description": "Synthetic recycling fixture", "legal_ref": "Synthetic source",
    }])
    raw, quote, lines = observe("existing_recycling_amount")
    line = lines["recycling_fee"]
    assert line.amount_rub == raw["breakdown"]["recycling_fee"] == 30000
    assert line.reason == "Synthetic source"
    assert line.basis_amount_rub == 20000 and line.rate_label == "1.5"
    shown = sum(Decimal(str(line.amount_rub)) for line in quote.line_items if line.amount_rub is not None)
    assert shown == Decimal(str(quote.total_partial_rub))
    assert quote.total_payable_rub is None
    needs_review(raw, quote, lines)


@pytest.mark.parametrize("currency,fx", [("USD", 90), ("RUB", 17)])
def test_extended_scenario_preserves_original_invoice_currency_review(isolated_payments, monkeypatch, currency, fx):
    from app.services import scenario_compare_service as scenarios
    monkeypatch.setattr(scenarios, "SessionLocal", isolated_payments.sessions)
    monkeypatch.setattr(scenarios, "get_rates_map", lambda: {currency: fx})
    monkeypatch.setattr(scenarios, "compute_payments", engine.compute_payments)
    result = scenarios.compare_scenarios_extended({
        "base": {"hs_code": CODE, "country": "CN", "customs_value": 1000, "currency": currency},
        "scenarios": [{"name": "A"}, {"name": "B"}],
    })
    if currency == "USD":
        assert result["status"] == "REVIEW_REQUIRED" and result["comparison_complete"] is False
        assert result["best_scenario"] is None and result["savings_vs_worst"] is None
        assert all("foreign_fx_source_unverified" in row["payment_review_reasons"] for row in result["scenarios"])
        assert result["base"]["customs_value_rub"] == 90000
    else:
        assert result["base"]["customs_value_rub"] == 1000


@pytest.mark.parametrize("fx", [None, 0, -1, True, float("nan"), float("inf")])
def test_extended_scenario_never_falls_back_to_one_for_bad_currency_factor(isolated_payments, monkeypatch, fx):
    from app.services import scenario_compare_service as scenarios
    monkeypatch.setattr(scenarios, "SessionLocal", isolated_payments.sessions)
    monkeypatch.setattr(scenarios, "get_rates_map", lambda: {} if fx is None else {"ZZZ": fx})
    with pytest.raises(ValueError):
        scenarios.compare_scenarios_extended({
            "base": {"hs_code": CODE, "country": "CN", "customs_value": 1000, "currency": "ZZZ"},
            "scenarios": [{"name": "A"}, {"name": "B"}],
        })
