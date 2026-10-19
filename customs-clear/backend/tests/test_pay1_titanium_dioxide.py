"""PAY-1: exact titanium-dioxide scope and Decision No. 124 suspension."""

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
    _row_needs_update,
    _validate_bundle_for_ingest,
)
from app.services.payment_engine import compute_payments
from app.services.payment_quote_service import build_payment_quote
from app.services.payment_revision_utils import is_safe_official_anti_dumping_source_url


BACKEND_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_PATH = BACKEND_ROOT / "data/raw_normative/eec_anti_dumping.json"


class _Clock(date):
    current = date(2026, 10, 15)

    @classmethod
    def today(cls) -> date:
        return cls.current


def _titanium_rows() -> list[dict]:
    payload = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    return [
        row
        for row in payload["measures"]
        if "№ 96" in str(row.get("regulatory_act") or "")
    ]


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

    with factory() as db:
        for raw in _titanium_rows():
            normalized = _normalize_measure_row(raw)
            assert normalized is not None
            db.add(
                SpecialDuty(
                    hs_code_prefix=normalized["hs_code_prefix"],
                    origin_country=normalized["origin_country"],
                    rate_percent=normalized["rate_percent"],
                    rate_specific=normalized["rate_specific"],
                    currency_code=normalized["currency_code"],
                    regulatory_act=normalized["regulatory_act"],
                    measure_type="anti_dumping",
                    manufacturer_exporter=normalized["manufacturer_exporter"],
                    product_description=normalized["product_description"],
                    effective_from=normalized["effective_from"],
                    effective_to=normalized["effective_to"],
                    needs_verification=bool(normalized.get("needs_verification")),
                )
            )
        db.commit()
    try:
        yield factory
    finally:
        engine.dispose()


def _compute(day: date, hs_code: str = "3206110000") -> dict:
    _Clock.current = day
    return compute_payments(
        {
            "hs_code": hs_code,
            "country": "CN",
            "customs_value": 100_000.0,
            "quantity": 1.0,
        }
    )


def test_bundle_has_exact_scope_and_two_active_windows() -> None:
    rows = _titanium_rows()
    assert len(rows) == 2
    assert {row["hs_code"] for row in rows} == {"3206110000"}
    assert {(row["effective_from"], row["effective_to"]) for row in rows} == {
        ("2025-11-16", "2026-10-02"),
        ("2027-08-11", "2030-11-15"),
    }
    assert all(row.get("needs_verification") is True for row in rows)
    assert all("80%" in row["product_description"] for row in rows)
    assert all("приложени" in row["product_description"].lower() for row in rows)


def test_ingestion_preserves_fail_closed_marker() -> None:
    normalized = _normalize_measure_row(_titanium_rows()[0])
    assert normalized is not None
    assert normalized["hs_code_prefix"] == "3206110000"
    assert normalized["needs_verification"] is True
    assert is_safe_official_anti_dumping_source_url(_titanium_rows()[0]["source_url"])
    assert is_safe_official_anti_dumping_source_url(_titanium_rows()[1]["source_url"])


def test_full_bundle_parser_accepts_official_portal_rows() -> None:
    _payload, parser_result, revision, rows, blockers = _validate_bundle_for_ingest(
        "data/raw_normative/eec_anti_dumping.json"
    )
    assert parser_result["status"] == "parsed"
    assert revision == "anti-dumping:2026-06-23"
    assert blockers == []
    titanium = [row for row in rows if row["hs_code_prefix"] == "3206110000"]
    assert len(titanium) == 2
    assert all(row["needs_verification"] is True for row in titanium)


def test_official_portal_allowlist_rejects_lookalikes() -> None:
    assert is_safe_official_anti_dumping_source_url(
        "https://remedies.eaeunion.org/dimd/ru"
    )
    assert not is_safe_official_anti_dumping_source_url(
        "https://remedies.eaeunion.org.example.com/dimd/ru"
    )


def test_needs_verification_only_change_requires_update() -> None:
    row = _normalize_measure_row(_titanium_rows()[0])
    assert row is not None
    existing = SpecialDuty(
        hs_code_prefix=row["hs_code_prefix"],
        origin_country=row["origin_country"],
        rate_percent=row["rate_percent"],
        rate_specific=row["rate_specific"],
        currency_code=row["currency_code"],
        regulatory_act=row["regulatory_act"],
        measure_type="anti_dumping",
        manufacturer_exporter=row["manufacturer_exporter"],
        product_description=row["product_description"],
        effective_from=row["effective_from"],
        effective_to=row["effective_to"],
        source_code="EEC_ANTI_DUMPING",
        source_revision=row["source_revision"],
        source_url=row["source_url"],
        needs_verification=False,
    )
    assert row["needs_verification"] is True
    assert _row_needs_update(existing, row) is True


def test_apply_retires_exact_superseded_broad_row(payment_db) -> None:
    factory = payment_db
    with factory() as db:
        db.add(
            SpecialDuty(
                hs_code_prefix="3206",
                origin_country="CN",
                rate_percent=16.25,
                rate_specific=0.0,
                currency_code="USD",
                regulatory_act="Решение Коллегии ЕЭК № 96 от 14.10.2025",
                measure_type="anti_dumping",
                manufacturer_exporter="",
                product_description=(
                    "Диоксид титана / пигменты TiO2 "
                    "(до 16,25% по изготовителю, ЕЭК №96)"
                ),
                effective_from="2025-11-16",
                effective_to="2030-10-14",
                source_code="EEC_ANTI_DUMPING",
                source_revision="anti-dumping:2026-06-23",
                source_url="https://remedies.eaeunion.org/dimd/ru",
                needs_verification=False,
            )
        )
        db.commit()

    rows = [_normalize_measure_row(raw) for raw in _titanium_rows()]
    assert all(row is not None for row in rows)
    counts = _apply_anti_dumping_rows(
        rows, synced_at=datetime(2026, 10, 15, 8, 0, 0)
    )
    assert counts is not None
    assert counts.retire == 1
    with factory() as db:
        assert (
            db.query(SpecialDuty)
            .filter(SpecialDuty.hs_code_prefix == "3206")
            .count()
            == 0
        )
    assert _compute(date(2026, 10, 2), hs_code="3206120000")["special_duties"] == []


@pytest.mark.usefixtures("payment_db")
def test_neighboring_code_never_matches() -> None:
    result = _compute(date(2026, 10, 2), hs_code="3206120000")
    assert result["special_duties"] == []
    assert result["breakdown"]["special_duties_amount"] == 0.0


@pytest.mark.usefixtures("payment_db")
@pytest.mark.parametrize(
    "day",
    [date(2026, 10, 3), date(2026, 10, 13), date(2027, 8, 10)],
)
def test_suspended_measure_has_no_collectible_amount(day: date) -> None:
    result = _compute(day)
    assert result["special_duties"] == []
    assert result["breakdown"]["special_duties_amount"] == 0.0


@pytest.mark.usefixtures("payment_db")
@pytest.mark.parametrize("day", [date(2026, 10, 2), date(2027, 8, 11)])
def test_active_boundary_is_fail_closed_without_product_facts(day: date) -> None:
    result = _compute(day)
    assert result["breakdown"]["special_duties_amount"] == 0.0
    assert len(result["special_duties"]) == 1
    assert result["special_duties"][0]["needs_verification"] is True
    assert result["special_duties"][0]["amount"] is None
    assert result["special_duties"][0]["warning"]


@pytest.mark.usefixtures("payment_db")
def test_quote_withholds_total_when_product_scope_is_unknown() -> None:
    _Clock.current = date(2026, 10, 2)
    quote = build_payment_quote(
        {
            "hs_code": "3206110000",
            "country": "CN",
            "customs_value": 100_000.0,
            "invoice_currency": "RUB",
            "quantity": 1.0,
        }
    )
    special = next(item for item in quote.line_items if item.code == "special_duty")
    assert special.status == "manual_review_required"
    assert special.amount_rub is None
    assert quote.total_payable_rub is None
