"""Independent A5 stage-2 regressions; only a newly created in-memory SQL DB.

No legal sources are asserted: all data below are synthetic fault scenarios.
Real engine, repositories, quote builder and mounted ASGI routes are exercised.
"""
from decimal import Decimal
import json
import socket

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db as database_module
from app.models import core, tnved
from app.services import payment_engine as engine
from app.services import payment_quote_service as quotes
from app.services import normative_store, rate_display, compliance_resolver
from app.api import calculator, payments

HS = "8501100000"
MODELS = (core.HsRate, core.NonTariffRule, core.TnvedEntry, core.NormativeNote,
          core.TrTsAct, core.IngestedDocument, core.TnvedEntryEmbedding,
          core.CustomsCalculationHistory, core.CountryRisk, core.GeoSpecialDuty,
          core.SourceStatus, tnved.Section, tnved.Chapter, tnved.Commodity,
          tnved.HsDutyRule, tnved.SpecialDuty, tnved.VatPreference,
          tnved.CountryTariffPreference, tnved.RecyclingFee)


@pytest.fixture
def qa_database(monkeypatch):
    sql = create_engine("sqlite://", poolclass=StaticPool,
                        connect_args={"check_same_thread": False})
    database_module.Base.metadata.create_all(sql, tables=[m.__table__ for m in MODELS])
    factory = sessionmaker(bind=sql)
    for module in (database_module, engine, quotes, normative_store, rate_display, compliance_resolver):
        if hasattr(module, "SessionLocal"):
            monkeypatch.setattr(module, "SessionLocal", factory)
    # This additive display provider and FX acquisition are external boundaries,
    # not rate selection or calculation. No legal authority is added by stubs.
    monkeypatch.setattr(quotes, "canonical_anchor_for_hs", lambda *_: None)
    monkeypatch.setattr(quotes, "get_rates_map", lambda: {"RUB": 1.0})
    monkeypatch.setattr(calculator, "get_rates_map", lambda: {"RUB": 1.0})
    def forbidden_connect(*_args, **_kwargs):
        raise AssertionError("independent payment test attempted network access")
    monkeypatch.setattr(socket.socket, "connect", forbidden_connect)
    with factory() as session:
        section = tnved.Section(roman_number="XVI", title="Synthetic QA")
        chapter = tnved.Chapter(code="85", title="Synthetic QA", section=section)
        session.add(tnved.Commodity(code=HS, chapter=chapter, description="Synthetic motor"))
        session.add(core.TnvedEntry(hs_code=HS, title="Synthetic motor", level=10))
        session.add(core.HsRate(hs_code=HS, hs_prefix=HS, duty_rate="10%",
            vat_import_rate=22, valid_from="2000-01-01", valid_to="2100-01-01",
            source_revision="synthetic-a5-review-only", antidumping_type="none",
            antidumping_value=0, antidumping_countries=""))
        # A real but different-origin registry row avoids the unrelated
        # not_configured quote gate masking confirmed amounts in the scenarios.
        session.add(tnved.SpecialDuty(hs_code_prefix=HS, origin_country="DE",
            rate_percent=3, regulatory_act="Unrelated synthetic country row",
            effective_from="2000-01-01", effective_to="2100-01-01"))
        session.commit()
    yield factory
    sql.dispose()


def payload(**changes):
    return {"hs_code": HS, "country": "CN", "customs_value": 1_000_000,
            "insurance": 0, "quantity": 100, "net_weight_kg": 100,
            "extra_quantity": 100, **changes}


def seed(factory, case):
    with factory() as session:
        rate = session.query(core.HsRate).one()
        if case in {"preference", "geo_preference"}:
            session.add(tnved.CountryTariffPreference(country_code="CN",
                preference_type="synthetic", duty_coefficient=1.25, legal_ref="QA only"))
        if case in {"geo", "geo_preference"}:
            session.add(core.GeoSpecialDuty(hs_code_prefix=HS, country_iso="CN",
                duty_rate="35%", measure_type="increased_duty", document_basis="QA only"))
        if case in {"fixed_ad", "empty_ad_country", "overlap"}:
            rate.antidumping_type = "fixed" if case == "fixed_ad" else "percent"
            rate.antidumping_value = 7
            rate.antidumping_countries = "" if case == "empty_ad_country" else "CN"
        if case in {"special", "overlap"}:
            session.add(tnved.SpecialDuty(hs_code_prefix=HS, origin_country="CN",
                rate_percent=7, rate_specific=0, measure_type="anti_dumping",
                regulatory_act="Synthetic A5 only", effective_from="2000-01-01",
                effective_to="2100-01-01", needs_verification=False,
                source_code="EEC_ANTI_DUMPING", source_revision="anti-dumping:2026-01-01",
                source_url="https://eec.eaeunion.org/synthetic-test-only"))
        if case in {"specific_missing", "specific_fx", "specific_unit", "combined_missing", "combined_fx"}:
            session.add(tnved.HsDutyRule(commodity_code=HS,
                type="combined_max" if case.startswith("combined") else "specific",
                ad_valorem_pct=10 if case.startswith("combined") else None,
                specific_amount=None if case.endswith("missing") else 2,
                specific_currency="RUB" if case == "specific_unit" else "EUR",
                specific_uom="" if case == "specific_unit" else "kg"))
        if case == "expired":
            rate.valid_from, rate.valid_to = "2000-01-01", "2001-01-01"
        session.commit()


def observe(factory, case):
    seed(factory, case)
    request = payload()
    try:
        raw = engine.compute_payments(request)
        quote = quotes.build_payment_quote(request)
        return {"case": case, "raw_status": raw["status"],
                "review": raw.get("amounts_provisional"),
                "reasons": raw.get("payment_review_reasons"),
                "duty": raw["breakdown"]["duty"],
                "ad": raw["breakdown"]["antidumping"],
                "special": raw["breakdown"].get("special_duties_amount"),
                "total": raw["breakdown"]["total_payable"],
                "quote_status": quote.status, "quote_total": quote.total_payable_rub,
                "lines": {l.code: {"status": l.status, "amount": l.amount_rub} for l in quote.line_items},
                "geo": raw.get("geo"), "preference": raw.get("tariff_preference"),
                "special_rows": raw.get("special_duties")}
    except ValueError as exc:
        return {"case": case, "error": str(exc)}


@pytest.mark.parametrize("case", ["geo", "geo_preference", "fixed_ad", "empty_ad_country",
    "specific_missing", "specific_fx", "specific_unit", "combined_missing", "combined_fx", "expired"])
def test_unverified_inputs_never_become_confirmed_quote(qa_database, case):
    observation = observe(qa_database, case)
    print(json.dumps(observation, ensure_ascii=False, allow_nan=False))
    if "error" in observation:
        return  # Explicit fail-closed input rejection is safe; never accept a zero quote.
    assert observation["raw_status"] == "REVIEW_REQUIRED"
    assert observation["review"] is True
    assert observation["quote_total"] is None


def test_current_upward_preference_remains_unapplied(qa_database):
    observation = observe(qa_database, "preference")
    assert observation["duty"] == 100_000
    assert observation["preference"]["applied"] is False
    assert observation["quote_total"] is None


def test_cross_store_ad_does_not_double_count(qa_database):
    observation = observe(qa_database, "overlap")
    assert observation["ad"] in (None, 0)
    assert observation["special"] in (None, 0)
    assert observation["quote_total"] is None


def test_geo_candidate_does_not_suppress_preference_review(qa_database):
    observation = observe(qa_database, "geo_preference")
    assert observation["preference"].get("status") == "needs_review"
    assert observation["preference"]["applied"] is False
    assert observation["quote_total"] is None


def application():
    app = FastAPI()
    app.include_router(calculator.router, prefix="/api/calculator")
    app.include_router(payments.router, prefix="/api/payments")
    return app


def comparison(**changes):
    return {"shared": payload(), "scenarios": [{"hs_code": HS}, {"hs_code": HS}],
            "save_history": False, **changes}


def test_null_as_of_is_explicitly_equivalent_to_omitted(qa_database):
    # A0 contract: null carries no date; all non-null dates remain unsupported.
    assert engine.compute_payments(payload(as_of=None)) == engine.compute_payments(payload())
    assert quotes.build_payment_quote(payload(as_of=None)) == quotes.build_payment_quote(payload())
    expected = engine.compare_payment_scenarios(comparison())
    for supplied in (comparison(as_of=None), comparison(shared=payload(as_of=None)),
                     comparison(scenarios=[{"hs_code": HS, "as_of": None}, {"hs_code": HS}])):
        assert engine.compare_payment_scenarios(supplied) == expected


@pytest.mark.parametrize("endpoint", ["/api/calculator/compute", "/api/payments/quote", "/api/calculator/compare"])
def test_actual_asgi_null_as_of_is_equivalent(qa_database, endpoint):
    request = comparison() if endpoint.endswith("compare") else payload(save_history=False)
    with TestClient(application()) as client:
        omitted = client.post(endpoint, json=request)
        explicit_null = client.post(endpoint, json={**request, "as_of": None})
    assert explicit_null.status_code == omitted.status_code == 200
    assert explicit_null.json() == omitted.json()


@pytest.mark.parametrize("as_of", [False, 0, "", "2020-01-01"])
def test_non_null_as_of_is_always_rejected(qa_database, as_of):
    with pytest.raises(ValueError):
        engine.compute_payments(payload(as_of=as_of))


@pytest.mark.parametrize("case", ["geo", "fixed_ad", "empty_ad_country", "specific_missing", "specific_fx", "expired"])
def test_actual_asgi_calculator_and_quote_share_review_boundary(qa_database, case):
    seed(qa_database, case)
    application = FastAPI()
    application.include_router(calculator.router, prefix="/api/calculator")
    application.include_router(payments.router, prefix="/api/payments")
    with TestClient(application) as client:
        raw = client.post("/api/calculator/compute", json=payload(save_history=False))
        quote = client.post("/api/payments/quote", json=payload())
        assert raw.status_code in (200, 400) and quote.status_code in (200, 400)
        if raw.status_code == 200:
            assert raw.json()["status"] == "REVIEW_REQUIRED"
        if quote.status_code == 200:
            assert quote.json()["total_payable_rub"] is None


@pytest.mark.parametrize("as_of", [False, 0, "", "2020-01-01"])
def test_non_null_as_of_cannot_bypass_compare_or_asgi(qa_database, as_of):
    with pytest.raises(ValueError):
        quotes.build_payment_quote(payload(as_of=as_of))
    for supplied in (comparison(as_of=as_of), comparison(shared=payload(as_of=as_of)),
                     comparison(scenarios=[{"hs_code": HS, "as_of": as_of}, {"hs_code": HS}])):
        with pytest.raises(ValueError):
            engine.compare_payment_scenarios(supplied)
    with TestClient(application()) as client:
        for endpoint in ("/api/calculator/compute", "/api/payments/quote"):
            assert client.post(endpoint, json=payload(as_of=as_of)).status_code in (400, 422)
        assert client.post("/api/calculator/compare", json=comparison(as_of=as_of)).status_code in (400, 422)


def test_provisional_special_is_not_a_confirmed_payable_or_status_contradiction(qa_database):
    observation = observe(qa_database, "special")
    candidate = observation["special_rows"][0]
    assert candidate["applied"] is False
    assert candidate["legal_review_verified"] is False
    assert candidate["review_reasons"] == ["legal_review_unverified"]
    assert candidate["status"] == "provisional"
    assert observation["special"] == 70_000  # arithmetic preview is intentional
    assert observation["raw_status"] == "REVIEW_REQUIRED"
    assert observation["review"] is True
    assert observation["quote_total"] is None
    assert observation["lines"]["special_duty"]["amount"] is None
    assert observation["lines"]["vat"]["amount"] is None


@pytest.mark.parametrize("from_date,to_date", [("not-a-date", "2100-01-01"),
    ("2099-01-01", "2100-01-01"), ("2100-01-01", "2000-01-01")])
def test_invalid_or_future_source_window_cannot_confirm_dependent_lines(qa_database, from_date, to_date):
    with qa_database() as session:
        row = session.query(core.HsRate).one()
        row.valid_from, row.valid_to = from_date, to_date
        row.excise_type, row.excise_value = "percent", 3
        row.antidumping_type, row.antidumping_value, row.antidumping_countries = "percent", 7, "CN"
        session.commit()
    quote = quotes.build_payment_quote(payload())
    assert quote.total_payable_rub is None
    for line in quote.line_items:
        if line.code in {"duty", "vat", "excise", "antidumping"}:
            assert line.amount_rub is None
            assert line.status in {"manual_review_required", "unknown"}


def test_quote_visible_components_include_nonzero_recycling_fee(qa_database):
    code = "8703231910"
    with qa_database() as session:
        session.add(core.HsRate(hs_code=code, hs_prefix=code, duty_rate="10%",
            vat_import_rate=22, valid_from="2000-01-01", valid_to="2100-01-01",
            excise_type="percent", excise_value=0, antidumping_type="none"))
        session.add(tnved.SpecialDuty(hs_code_prefix=code, origin_country="DE",
            rate_percent=3, effective_from="2000-01-01", effective_to="2100-01-01"))
        session.add(tnved.RecyclingFee(hs_prefix="8703", vehicle_type="synthetic",
            is_new=True, base_rate=20_000, coefficient=1.5))
        session.commit()
    request = payload(hs_code=code, vehicle_is_new=True, engine_volume=1500)
    raw, quote = engine.compute_payments(request), quotes.build_payment_quote(request)
    assert raw["breakdown"]["recycling_fee"] == 30_000
    assert quote.total_payable_rub is not None
    visible = sum((Decimal(str(line.amount_rub)) for line in quote.line_items
                   if line.amount_rub is not None), Decimal(0))
    assert Decimal(str(quote.total_payable_rub)) == visible
    assert Decimal(str(quote.total_partial_rub)) == visible
    assert next(line.amount_rub for line in quote.line_items if line.code == "recycling_fee") == 30_000


@pytest.mark.parametrize("case", ["special", "specific_fx", "combined_fx"])
@pytest.mark.parametrize("value", [1.005, 1234.567, 99999.995])
def test_subcent_provisional_breakdown_reconciles_without_confirmed_quote(qa_database, case, value):
    seed(qa_database, case)
    request = payload(customs_value=value, quantity=1.333, net_weight_kg=1.333,
                      extra_quantity=1.333, _fx_rates={"EUR": 99.999})
    raw, quote = engine.compute_payments(request), quotes.build_payment_quote(request)
    b = raw["breakdown"]
    component_names = ("customs_fee", "duty", "excise", "antidumping", "special_duties_amount", "vat", "recycling_fee")
    displayed_sum = sum((Decimal(str(b[name])) for name in component_names), Decimal(0))
    assert Decimal(str(b["total_payable"])) == displayed_sum
    vat_base_sum = sum((Decimal(str(raw["customs_value"])), Decimal(str(b["duty"])),
        Decimal(str(b["excise"])), Decimal(str(b["antidumping"])), Decimal(str(b["special_duties_amount"]))))
    assert Decimal(str(b["vat_base"])) == vat_base_sum
    assert quote.total_payable_rub is None


def test_compute_quote_and_asgi_do_not_mutate_fixture_tables(qa_database):
    def rows():
        with qa_database() as session:
            return {model.__tablename__: [tuple(row) for row in session.execute(model.__table__.select()).all()]
                    for model in MODELS}
    before = rows()
    engine.compute_payments(payload())
    quotes.build_payment_quote(payload())
    with TestClient(application()) as client:
        assert client.post("/api/calculator/compute", json=payload(save_history=False)).status_code == 200
        assert client.post("/api/payments/quote", json=payload()).status_code == 200
    assert rows() == before
