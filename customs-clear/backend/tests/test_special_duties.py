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


    def test_effective_start_date_is_enforced_at_boundary(self) -> None:
        today = date.today()
        future_from = (today + timedelta(days=30)).isoformat()
        future_to = (today + timedelta(days=365)).isoformat()
        markers = {
            "future": "TEST-FUTURE-SPECIAL-DUTY",
            "today": "TEST-TODAY-SPECIAL-DUTY",
            "legacy": "TEST-LEGACY-NO-START-SPECIAL-DUTY",
        }
        with SessionLocal() as db:
            db.add_all(
                [
                    SpecialDuty(
                        hs_code_prefix="9998",
                        origin_country="ZZ",
                        rate_percent=99.0,
                        rate_specific=0.0,
                        currency_code="RUB",
                        regulatory_act=markers["future"],
                        measure_type="anti_dumping",
                        effective_from=future_from,
                        effective_to=future_to,
                    ),
                    SpecialDuty(
                        hs_code_prefix="9998",
                        origin_country="ZZ",
                        rate_percent=7.0,
                        rate_specific=0.0,
                        currency_code="RUB",
                        regulatory_act=markers["today"],
                        measure_type="special_safeguard",
                        effective_from=today.isoformat(),
                        effective_to=future_to,
                    ),
                    SpecialDuty(
                        hs_code_prefix="9998",
                        origin_country="ZZ",
                        rate_percent=3.0,
                        rate_specific=0.0,
                        currency_code="RUB",
                        regulatory_act=markers["legacy"],
                        measure_type="countervailing",
                        effective_from="",
                        effective_to=future_to,
                    ),
                ]
            )
            db.commit()
        try:
            res = self._calc(hs_code="9998999999", country="ZZ")
            details = [
                d for d in (res.get("special_duties") or [])
                if not d.get("warning") and d.get("regulatory_act") in markers.values()
            ]
            by_act = {d["regulatory_act"]: d for d in details}

            self.assertNotIn(markers["future"], by_act)
            self.assertIn(markers["today"], by_act)
            self.assertIn(markers["legacy"], by_act)
            self.assertEqual(by_act[markers["today"]]["effective_from"], today.isoformat())
            self.assertEqual(by_act[markers["today"]]["effective_to"], future_to)
            self.assertAlmostEqual(
                sum(float(d["amount"]) for d in details),
                10_000.0,
                places=2,
            )
        finally:
            with SessionLocal() as db:
                db.query(SpecialDuty).filter(
                    SpecialDuty.regulatory_act.in_(list(markers.values()))
                ).delete(synchronize_session=False)
                db.commit()

    def test_non_iso_or_invalid_effective_dates_fail_closed(self) -> None:
        future_to = (date.today() + timedelta(days=365)).isoformat()
        markers = {
            "dot": "TEST-NON-ISO-DOT-START",
            "slash": "TEST-NON-ISO-SLASH-START",
            "impossible": "TEST-IMPOSSIBLE-ISO-START",
            "bad_end": "TEST-MALFORMED-END",
        }
        windows = {
            markers["dot"]: ("01.10.2099", future_to),
            markers["slash"]: ("10/01/2099", future_to),
            markers["impossible"]: ("2099-02-30", future_to),
            markers["bad_end"]: ("2020-01-01", "not-a-date"),
        }
        with SessionLocal() as db:
            db.add_all(
                [
                    SpecialDuty(
                        hs_code_prefix="9997",
                        origin_country="ZZ",
                        rate_percent=99.0,
                        rate_specific=0.0,
                        currency_code="RUB",
                        regulatory_act=marker,
                        measure_type="anti_dumping",
                        effective_from=starts,
                        effective_to=ends,
                    )
                    for marker, (starts, ends) in windows.items()
                ]
            )
            db.commit()
        try:
            res = self._calc(hs_code="9997999999", country="ZZ")
            details = res.get("special_duties") or []
            acts = {d.get("regulatory_act") for d in details if not d.get("warning")}
            self.assertTrue(acts.isdisjoint(markers.values()))
            self.assertEqual(res["breakdown"]["special_duties_amount"], 0.0)
        finally:
            with SessionLocal() as db:
                db.query(SpecialDuty).filter(
                    SpecialDuty.regulatory_act.in_(list(markers.values()))
                ).delete(synchronize_session=False)
                db.commit()


if __name__ == "__main__":
    unittest.main()
