"""Backfill hs_duty_rules из hs_rates и расчёт specific EUR/kg."""

from __future__ import annotations

import unittest
import unittest.mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.db import SessionLocal
from app.models.core import HsRate
from app.models.tnved import Commodity, HsDutyRule, SpecialDuty, VatPreference
from app.services.duty_rules_backfill import backfill_duty_rules_from_hs_rates
from app.services.payment_engine import _find_duty_rule_for_hs, compute_payments


@pytest.fixture(scope="module", autouse=True)
def isolated_duty_rule_db():
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
    patchers = [
        unittest.mock.patch(f"{__name__}.SessionLocal", factory),
        unittest.mock.patch("app.services.payment_engine.SessionLocal", factory),
        unittest.mock.patch("app.services.normative_store.SessionLocal", factory),
        unittest.mock.patch("app.services.rate_display.SessionLocal", factory),
        unittest.mock.patch("app.services.payment_engine.get_country_risk_by_iso", return_value=None),
        unittest.mock.patch("app.services.payment_engine.find_geo_embargo_match", return_value=None),
        unittest.mock.patch("app.services.payment_engine.find_geo_duty_override_row", return_value=None),
        unittest.mock.patch("app.services.payment_engine.get_tariff_preference", return_value=None),
        unittest.mock.patch("app.services.payment_engine.get_recycling_fee", return_value=[]),
        unittest.mock.patch(
            "app.services.payment_engine.get_integrated_data_stats",
            return_value={"hs_rates_count": 1},
        ),
        unittest.mock.patch("app.services.payment_engine.get_tnved_context_for_hs", return_value={}),
    ]
    for patcher in patchers:
        patcher.start()
    with factory() as db:
        db.add(Commodity(chapter_id=1, code="6303929000", description="TEST-ONLY curtains"))
        db.add(
            HsRate(
                hs_code="6303929000",
                hs_prefix="6303",
                duty_rate="0.61 EUR за 1 кг",
                source_revision="test-only",
            )
        )
        db.commit()
    try:
        yield
    finally:
        for patcher in reversed(patchers):
            patcher.stop()
        engine.dispose()


class DutyRulesBackfillTests(unittest.TestCase):
    def test_backfill_creates_specific_rule_for_6303929000(self) -> None:
        code = "6303929000"
        with SessionLocal() as db:
            db.query(HsDutyRule).filter(HsDutyRule.commodity_code == code).delete()
            db.commit()
            stats = backfill_duty_rules_from_hs_rates(db, only_missing=True)
            db.commit()
            row = db.query(HsDutyRule).filter(HsDutyRule.commodity_code == code).one_or_none()

        self.assertGreaterEqual(stats["created"], 1)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row.type, "specific")
        self.assertAlmostEqual(float(row.specific_amount or 0), 0.61)
        self.assertEqual(row.specific_currency, "EUR")
        self.assertEqual(row.specific_uom, "kg")

        rule, match_len = _find_duty_rule_for_hs(code)
        self.assertEqual(match_len, 10)
        self.assertIsNotNone(rule)
        assert rule is not None
        self.assertEqual(rule.type, "specific")
        self.assertAlmostEqual(float(rule.specific_amount or 0), 0.61)


class SpecificDutyComputeTests(unittest.TestCase):
    def test_compute_6303929000_with_net_weight(self) -> None:
        with SessionLocal() as db:
            if db.query(HsDutyRule).filter(HsDutyRule.commodity_code == "6303929000").one_or_none() is None:
                backfill_duty_rules_from_hs_rates(db, only_missing=True)
                db.commit()

        data = compute_payments(
            {
                "hs_code": "6303929000",
                "customs_value": 331400.92,
                "country": "CN",
                "quantity": 1,
                "net_weight_kg": 1860.84,
                "_fx_rates": {"EUR": 82.75, "RUB": 1.0},
            }
        )
        breakdown = data.get("breakdown") or {}
        duty = float(breakdown.get("duty") or 0)
        self.assertGreater(duty, 90000.0)
        self.assertLess(abs(duty - 93962.90), 4000.0)
        auto = data.get("auto_detected") or {}
        self.assertEqual(auto.get("duty_rule_type"), "specific")


if __name__ == "__main__":
    unittest.main()
