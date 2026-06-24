"""Backfill hs_duty_rules из hs_rates и расчёт specific EUR/kg."""

from __future__ import annotations

import unittest

from app.db import SessionLocal
from app.models.tnved import HsDutyRule
from app.services.duty_rules_backfill import backfill_duty_rules_from_hs_rates
from app.services.normative_store import init_db
from app.services.payment_engine import _find_duty_rule_for_hs


class DutyRulesBackfillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

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
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def test_compute_6303929000_with_net_weight(self) -> None:
        from fastapi.testclient import TestClient
        from app.main import app

        with SessionLocal() as db:
            if db.query(HsDutyRule).filter(HsDutyRule.commodity_code == "6303929000").one_or_none() is None:
                backfill_duty_rules_from_hs_rates(db, only_missing=True)
                db.commit()

        client = TestClient(app)
        resp = client.post(
            "/api/calculator/compute",
            json={
                "hs_code": "6303929000",
                "customs_value": 331400.92,
                "currency": "RUB",
                "country_of_origin": "CN",
                "quantity": 1,
                "net_weight_kg": 1860.84,
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        breakdown = data.get("breakdown") or {}
        duty = float(breakdown.get("duty") or 0)
        self.assertGreater(duty, 90000.0)
        self.assertLess(abs(duty - 93962.90), 4000.0)
        auto = data.get("auto_detected") or {}
        self.assertEqual(auto.get("duty_rule_type"), "specific")


if __name__ == "__main__":
    unittest.main()
