"""Регрессия special_duties / trade remedies в payment_engine."""
from __future__ import annotations

import unittest
from datetime import date, timedelta

from app.db import SessionLocal
from app.models.tnved import SpecialDuty
from app.services.normative_store import init_db
from app.services.payment_engine import compute_payments


class SpecialDutiesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def _calc(self, **kwargs: object) -> dict:
        defaults: dict = {
            "hs_code": "7214990000",
            "customs_value": 100_000.0,
            "freight": 0.0,
            "quantity": 1.0,
        }
        defaults.update(kwargs)
        return compute_payments(defaults)

    def test_cn_without_country_returns_warning_not_silent_zero(self) -> None:
        res = self._calc(hs_code="7214990000", country=None)
        self.assertEqual(res["status"], "OK")
        self.assertEqual(res["breakdown"]["special_duties_amount"], 0.0)
        self.assertTrue(res.get("special_duties_warning") or res["special_duties"])
        details = res.get("special_duties") or []
        if details:
            self.assertIn("warning", details[0])

    def test_cn_7214_special_duty_applied(self) -> None:
        res = self._calc(hs_code="7214990000", country="CN")
        self.assertEqual(res["status"], "OK")
        self.assertGreater(res["breakdown"]["special_duties_amount"], 0.0)
        details = res.get("special_duties") or []
        self.assertTrue(any(d.get("hs_code_prefix", "").startswith("7214") for d in details))

    def test_kz_chapter_20_no_legacy_garbage(self) -> None:
        """После удаления id 1,2,4,5,6 — KZ + гл.20 не даёт 120% мусорной ставки."""
        res = self._calc(hs_code="2005400000", country="KZ", customs_value=50_000, net_weight_kg=100)
        self.assertEqual(res["breakdown"]["special_duties_amount"], 0.0)

    def test_cn_8429_bulldozers_rate(self) -> None:
        res = self._calc(hs_code="8429100000", country="CN", customs_value=500_000)
        self.assertGreater(res["breakdown"]["special_duties_amount"], 0.0)
        details = res.get("special_duties") or []
        rates = [float(d.get("rate_percent") or 0) for d in details if not d.get("warning")]
        self.assertTrue(any(abs(r - 44.65) < 0.01 for r in rates), f"rates={rates}")

    def test_expired_measure_not_applied(self) -> None:
        expired_to = (date.today() - timedelta(days=30)).isoformat()
        marker = "TEST-EXPIRED-SPECIAL-DUTY"
        with SessionLocal() as db:
            db.add(
                SpecialDuty(
                    hs_code_prefix="9999",
                    origin_country="CN",
                    rate_percent=99.0,
                    rate_specific=0.0,
                    currency_code="USD",
                    regulatory_act=marker,
                    measure_type="anti_dumping",
                    effective_from="2020-01-01",
                    effective_to=expired_to,
                )
            )
            db.commit()
        try:
            res = self._calc(hs_code="9999999999", country="CN")
            details = res.get("special_duties") or []
            acts = [d.get("regulatory_act") for d in details if not d.get("warning")]
            self.assertNotIn(marker, acts)
            self.assertEqual(res["breakdown"]["special_duties_amount"], 0.0)
        finally:
            with SessionLocal() as db:
                db.query(SpecialDuty).filter(SpecialDuty.regulatory_act == marker).delete()
                db.commit()


if __name__ == "__main__":
    unittest.main()
