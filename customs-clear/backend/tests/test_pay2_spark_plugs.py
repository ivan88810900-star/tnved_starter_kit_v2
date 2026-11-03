"""PAY-2 / AD-41: Decision No. 46 spark-plug destination scope."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.core import HsRate
from app.models.tnved import Commodity, HsDutyRule, SpecialDuty, VatPreference
from app.services.anti_dumping_ingestion import (
    _apply_anti_dumping_rows,
    _normalize_measure_row,
    _validate_bundle_for_ingest,
)
from app.services.payment_engine import compute_payments
from app.services.payment_profile_builder import build_compare_payment_profiles
from app.services.payment_quote_service import build_payment_quote


BACKEND_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_PATH = BACKEND_ROOT / "data/raw_normative/eec_anti_dumping.json"
ACT = "Решение Коллегии ЕЭК № 46 от 07.04.2026"


class _Clock(date):
    current = date(2026, 10, 15)

    @classmethod
    def today(cls) -> date:
        return cls.current


def _spark_plug_rows() -> list[dict]:
    payload = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    return [row for row in payload["measures"] if row.get("regulatory_act") == ACT]


@pytest.fixture()
def payment_db(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Commodity.__table__,
            HsDutyRule.__table__,
            HsRate.__table__,
            SpecialDuty.__table__,
            VatPreference.__table__,
        ],
    )
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr("app.services.payment_engine.SessionLocal", factory)
    monkeypatch.setattr("app.services.payment_quote_service.SessionLocal", factory)
    monkeypatch.setattr("app.services.payment_profile_builder.SessionLocal", factory)
    monkeypatch.setattr("app.services.anti_dumping_ingestion.SessionLocal", factory)
    monkeypatch.setattr("app.services.normative_store.SessionLocal", factory)
    monkeypatch.setattr("app.services.rate_display.SessionLocal", factory)
    monkeypatch.setattr("app.services.payment_engine.date", _Clock)
    monkeypatch.setattr("app.services.payment_engine.get_country_risk_by_iso", lambda _country: None)
    monkeypatch.setattr("app.services.payment_engine.find_geo_embargo_match", lambda *_a, **_k: None)
    monkeypatch.setattr("app.services.payment_engine.find_geo_duty_override_row", lambda *_a, **_k: None)
    monkeypatch.setattr("app.services.payment_engine.get_tariff_preference", lambda *_a, **_k: None)
    monkeypatch.setattr("app.services.payment_engine.get_recycling_fee", lambda *_a, **_k: [])
    monkeypatch.setattr("app.services.payment_engine.get_integrated_data_stats", lambda: {"hs_rates_count": 0})
    monkeypatch.setattr("app.services.payment_engine.get_tnved_context_for_hs", lambda _hs: {})
    monkeypatch.setattr("app.services.payment_quote_service.get_rates_map", lambda: {"RUB": 1.0})
    monkeypatch.setattr(
        "app.services.payment_profile_builder.build_compliance_document_items",
        lambda **_kwargs: {"documents": [], "blocking_issue": False},
    )

    normalized = [_normalize_measure_row(raw) for raw in _spark_plug_rows()]
    assert all(row is not None for row in normalized)
    counts = _apply_anti_dumping_rows(
        normalized, synced_at=datetime(2026, 10, 15, 9, 30, 0)
    )
    assert counts is not None
    assert counts.insert == 10
    try:
        yield factory
    finally:
        engine.dispose()


def _compute(
    day: date,
    *,
    hs_code: str = "8511100001",
    origin: str = "CN",
    destination: str | None = "RU",
) -> dict:
    _Clock.current = day
    payload = {
        "hs_code": hs_code,
        "country": origin,
        "customs_value": 100_000.0,
        "quantity": 1.0,
    }
    if destination is not None:
        payload["destination_country"] = destination
    return compute_payments(payload)


def test_bundle_encodes_exact_codes_dates_and_national_scope() -> None:
    rows = _spark_plug_rows()
    assert len(rows) == 10
    assert {row["hs_code"] for row in rows} == {"8511100001", "8511100009"}
    assert {row["destination_country"] for row in rows} == {"RU", "AM", "BY", "KZ", "KG"}
    assert all(row["origin_country"] == "CN" for row in rows)
    assert all(row["rate_percent"] == 17.23 for row in rows)
    assert all(row["effective_from"] == "2026-05-10" for row in rows)
    assert all(row["effective_to"] == "2031-05-09" for row in rows)
    assert all(row["source_url"] == "https://docs.eaeunion.org/documents/463/10611/" for row in rows)
    assert all(row["needs_verification"] is False for row in rows if row["destination_country"] == "RU")
    assert all(row["needs_verification"] is True for row in rows if row["destination_country"] != "RU")


def test_full_bundle_parser_preserves_destination_scope() -> None:
    _payload, parser_result, _revision, rows, blockers = _validate_bundle_for_ingest(
        "data/raw_normative/eec_anti_dumping.json"
    )
    assert parser_result["status"] == "parsed"
    assert blockers == []
    spark = [row for row in rows if row["regulatory_act"] == ACT]
    assert len(spark) == 10
    assert {row["destination_country"] for row in spark} == {"RU", "AM", "BY", "KZ", "KG"}


@pytest.mark.usefixtures("payment_db")
@pytest.mark.parametrize("hs_code", ["8511100001", "8511100009"])
@pytest.mark.parametrize("day", [date(2026, 5, 10), date(2031, 5, 9)])
def test_russian_destination_applies_on_both_legal_boundaries(day: date, hs_code: str) -> None:
    result = _compute(day, hs_code=hs_code)
    assert result["breakdown"]["special_duties_amount"] == 17_230.0
    assert len(result["special_duties"]) == 1
    assert result["special_duties"][0]["destination_country"] == "RU"
    assert result["special_duties"][0]["amount"] == 17_230.0


@pytest.mark.usefixtures("payment_db")
@pytest.mark.parametrize("day", [date(2026, 5, 9), date(2031, 5, 10)])
def test_measure_is_inactive_outside_legal_window(day: date) -> None:
    result = _compute(day)
    assert result["special_duties"] == []
    assert result["breakdown"]["special_duties_amount"] == 0.0


@pytest.mark.usefixtures("payment_db")
@pytest.mark.parametrize(
    ("hs_code", "origin"),
    [("8511100002", "CN"), ("8511100001", "JP")],
)
def test_neighboring_code_and_other_origin_do_not_match(hs_code: str, origin: str) -> None:
    result = _compute(date(2026, 10, 15), hs_code=hs_code, origin=origin)
    assert result["special_duties"] == []
    assert result["breakdown"]["special_duties_amount"] == 0.0


@pytest.mark.usefixtures("payment_db")
@pytest.mark.parametrize("destination", ["AM", "BY", "KZ", "KG"])
def test_national_exceptions_are_withheld_pending_transaction_facts(destination: str) -> None:
    result = _compute(date(2026, 10, 15), destination=destination)
    assert result["status"] == "MANUAL_REVIEW_REQUIRED"
    assert result["breakdown"]["total_payable"] is None
    assert result["breakdown"]["total_partial"] > 0
    assert result["breakdown"]["special_duties_amount"] == 0.0
    assert len(result["special_duties"]) == 1
    detail = result["special_duties"][0]
    assert detail["destination_country"] == destination
    assert detail["manual_review_required"] is True
    assert detail["amount"] is None


@pytest.mark.usefixtures("payment_db")
def test_missing_destination_fails_closed() -> None:
    result = _compute(date(2026, 10, 15), destination=None)
    assert result["status"] == "MANUAL_REVIEW_REQUIRED"
    assert result["breakdown"]["total_payable"] is None
    assert result["breakdown"]["special_duties_amount"] == 0.0
    assert len(result["special_duties"]) == 1
    assert result["special_duties"][0]["manual_review_required"] is True
    assert "Страна назначения" in result["special_duties"][0]["warning"]


@pytest.mark.usefixtures("payment_db")
def test_product_quote_applies_ru_and_withholds_kz() -> None:
    _Clock.current = date(2026, 10, 15)
    base = {
        "hs_code": "8511100009",
        "country": "CN",
        "customs_value": 100_000.0,
        "invoice_currency": "RUB",
        "quantity": 1.0,
    }
    ru = build_payment_quote({**base, "destination_country": "RU"})
    ru_special = next(item for item in ru.line_items if item.code == "special_duty")
    assert ru_special.status == "applied"
    assert ru_special.amount_rub == 17_230.0
    assert ru.destination_country == "RU"

    kz = build_payment_quote({**base, "destination_country": "KZ"})
    kz_special = next(item for item in kz.line_items if item.code == "special_duty")
    assert kz_special.status == "manual_review_required"
    assert kz_special.amount_rub is None
    assert kz.total_payable_rub is None


@pytest.mark.usefixtures("payment_db")
def test_compare_preserves_scenario_destination_and_withholds_unresolved_total() -> None:
    _Clock.current = date(2026, 10, 15)
    result = build_compare_payment_profiles(
        payload={
            "shared": {
                "customs_value": 100_000.0,
                "country": "CN",
                "quantity": 1.0,
                "_fx_rates": {"RUB": 1.0},
            },
            "scenarios": [
                {"label": "RU", "hs_code": "8511100001", "destination_country": "RU"},
                {"label": "KZ", "hs_code": "8511100001", "destination_country": "KZ"},
            ],
        }
    )
    assert result.status == "MANUAL_REVIEW_REQUIRED"
    ru, kz = result.scenarios
    assert ru.profile.destination_country == "RU"
    assert ru.profile.breakdown.anti_dumping == 17_230.0
    assert ru.profile.breakdown.total_payable is not None
    assert ru.profile.blocking_issue is False
    assert kz.profile.destination_country == "KZ"
    assert kz.profile.breakdown.anti_dumping is None
    assert kz.profile.breakdown.total_payable is None
    assert kz.profile.blocking_issue is True
