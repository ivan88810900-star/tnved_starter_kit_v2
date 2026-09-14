"""Fail-closed tests for legacy payment rows without source-bound identity."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.core import HsRate
from app.models.tnved import HsDutyRule, SpecialDuty
from app.services import normative_store
from app.services import payment_engine
from app.services import payment_quote_service


CODE = "8501100000"


@pytest.fixture
def payments(monkeypatch, tmp_path):
    database = create_engine(f"sqlite:///{tmp_path / 'payment-source-admission.db'}")
    for model in (HsRate, HsDutyRule, SpecialDuty):
        model.__table__.create(database)
    sessions = sessionmaker(bind=database)

    monkeypatch.setattr(payment_engine, "SessionLocal", sessions)
    monkeypatch.setattr(normative_store, "SessionLocal", sessions)
    monkeypatch.setattr(payment_engine, "find_rate_for_hs", normative_store.find_rate_for_hs)
    monkeypatch.setattr(payment_engine, "_find_vat_preference", lambda _: (None, 0))
    monkeypatch.setattr(payment_engine, "get_country_risk_by_iso", lambda _: None)
    monkeypatch.setattr(payment_engine, "find_geo_embargo_match", lambda *args, **kwargs: None)
    monkeypatch.setattr(payment_engine, "find_geo_duty_override_row", lambda *args, **kwargs: None)
    monkeypatch.setattr(payment_engine, "get_tariff_preference", lambda _: SimpleNamespace(
        duty_coefficient=1.0, preference_type="synthetic", legal_ref="Synthetic fixture"
    ))
    monkeypatch.setattr(payment_engine, "get_recycling_fee", lambda *args, **kwargs: [])
    monkeypatch.setattr(payment_engine, "calculate_customs_fee", lambda _: 4924.0)
    monkeypatch.setattr(payment_engine, "get_integrated_data_stats", lambda: {"hs_rates_count": 1})
    monkeypatch.setattr(payment_engine, "get_tnved_context_for_hs", lambda _: {"title": "Synthetic goods"})
    monkeypatch.setattr("app.services.rate_display.resolve_excise_for_hs", lambda _: ("none", 0.0, ""))
    monkeypatch.setattr(payment_quote_service, "compute_payments", payment_engine.compute_payments)
    monkeypatch.setattr(payment_quote_service, "get_rates_map", lambda: {"RUB": 1.0})
    monkeypatch.setattr(payment_quote_service, "canonical_anchor_for_hs", lambda _: None)
    monkeypatch.setattr(payment_quote_service, "_special_duties_configured_for_hs", lambda _: True)

    with sessions() as session:
        session.add(HsRate(
            hs_code=CODE,
            hs_prefix=CODE,
            duty_rate="10%",
            vat_import_rate=22,
            excise_type="none",
            excise_value=0,
            antidumping_type="none",
            antidumping_value=0,
            valid_from="2020-01-01",
            valid_to="2099-12-31",
            source_url="https://eec.eaeunion.org/synthetic-test-only",
            source_revision="ett:synthetic-test-only",
        ))
        session.commit()

    yield SimpleNamespace(sessions=sessions)
    database.dispose()


def _request(**changes):
    return {
        "hs_code": CODE,
        "customs_value": 1_000_000,
        "insurance": 0,
        "country": "CN",
        "quantity": 20,
        **changes,
    }


def _set_rate(payments, **changes):
    with payments.sessions() as session:
        row = session.query(HsRate).one()
        for field, value in changes.items():
            setattr(row, field, value)
        session.commit()


def _add_specific_rule(payments):
    with payments.sessions() as session:
        session.add(HsDutyRule(
            commodity_code=CODE,
            type="specific",
            ad_valorem_pct=None,
            specific_amount=2,
            specific_currency="RUB",
            specific_uom="kg",
        ))
        session.commit()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("valid_from", ""),
        ("valid_to", " "),
        ("source_url", ""),
        ("source_revision", ""),
        ("source_revision", "seed"),
    ],
)
def test_unbound_hs_rate_withholds_dependent_quote(payments, field, value):
    _set_rate(payments, **{field: value})

    raw = payment_engine.compute_payments(_request())
    quote = payment_quote_service.build_payment_quote(_request())
    lines = {line.code: line for line in quote.line_items}

    assert raw["status"] == quote.status == "REVIEW_REQUIRED"
    assert "hs_rate_source_binding_unverified" in raw["payment_review_reasons"]
    assert raw["hs_rate_source_candidate"]["source_evidence_verified"] is False
    assert lines["duty"].amount_rub is None
    assert lines["vat"].amount_rub is None
    assert quote.total_payable_rub is None


def test_spoofed_metadata_cannot_create_a_reviewed_source_binding(payments):
    _set_rate(
        payments,
        valid_from="2020-01-01",
        valid_to="2099-12-31",
        source_url="https://eec.eaeunion.org/plausible-but-unreviewed",
        source_revision="ett:plausible-but-unreviewed",
    )

    raw = payment_engine.compute_payments(_request())
    quote = payment_quote_service.build_payment_quote(_request())
    lines = {line.code: line for line in quote.line_items}

    assert raw["breakdown"]["duty"] == 100_000
    assert raw["status"] == quote.status == "REVIEW_REQUIRED"
    assert "hs_rate_source_binding_unverified" in raw["payment_review_reasons"]
    assert raw["hs_rate_source_candidate"]["source_evidence_verified"] is False
    assert lines["duty"].amount_rub is None
    assert lines["vat"].amount_rub is None
    assert quote.total_payable_rub is None


def test_structured_rule_without_source_binding_is_only_provisional(payments):
    _add_specific_rule(payments)

    raw = payment_engine.compute_payments(_request(net_weight_kg=100))
    quote = payment_quote_service.build_payment_quote(_request(net_weight_kg=100))
    lines = {line.code: line for line in quote.line_items}

    assert raw["breakdown"]["duty"] == 200
    assert raw["status"] == quote.status == "REVIEW_REQUIRED"
    assert "duty_rule_source_binding_unverified" in raw["payment_review_reasons"]
    assert raw["duty_rule_source_candidate"]["source_evidence_verified"] is False
    assert lines["duty"].amount_rub is None
    assert lines["vat"].amount_rub is None
    assert quote.total_payable_rub is None


def test_manual_duty_override_still_bypasses_unbound_structured_rule(payments):
    _add_specific_rule(payments)

    raw = payment_engine.compute_payments(_request(duty_rate=7))
    quote = payment_quote_service.build_payment_quote(_request(duty_rate=7))
    lines = {line.code: line for line in quote.line_items}

    assert raw["status"] == quote.status == "REVIEW_REQUIRED"
    assert "hs_rate_source_binding_unverified" in raw["payment_review_reasons"]
    assert "duty_rule_source_binding_unverified" not in raw["payment_review_reasons"]
    assert lines["duty"].status == "manual_override"
    assert lines["duty"].amount_rub == 70_000
    assert lines["vat"].amount_rub is None
    assert quote.total_payable_rub is None


def test_manual_duty_remains_visible_when_other_row_fields_need_review(payments):
    _add_specific_rule(payments)
    _set_rate(payments, source_url="", source_revision="seed", valid_from="", valid_to="")

    raw = payment_engine.compute_payments(_request(duty_rate=7))
    quote = payment_quote_service.build_payment_quote(_request(duty_rate=7))
    lines = {line.code: line for line in quote.line_items}

    assert raw["status"] == quote.status == "REVIEW_REQUIRED"
    assert "duty_rule_source_binding_unverified" not in raw["payment_review_reasons"]
    assert lines["duty"].status == "manual_override"
    assert lines["duty"].amount_rub == 70_000
    assert lines["vat"].amount_rub is None
    assert quote.total_payable_rub is None
