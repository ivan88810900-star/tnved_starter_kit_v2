"""Регрессия special_duties / trade remedies в payment_engine."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

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

    def test_unbound_7214_without_country_withholds_final_payment(self) -> None:
        res = self._calc(hs_code="7214990000", country=None)
        self.assertEqual(res["status"], "REVIEW_REQUIRED")
        self.assertEqual(res["breakdown"]["special_duties_amount"], 0.0)
        self.assertIn("hs_rate_source_binding_unverified", res["payment_review_reasons"])
        self.assertIsNone(res["breakdown"]["total_payable"])

    def test_removed_legacy_7214_special_duty_is_not_reintroduced(self) -> None:
        res = self._calc(hs_code="7214990000", country="CN")
        self.assertEqual(res["status"], "REVIEW_REQUIRED")
        self.assertEqual(res["breakdown"]["special_duties_amount"], 0.0)
        self.assertEqual(res.get("special_duties"), [])
        self.assertIn("hs_rate_source_binding_unverified", res["payment_review_reasons"])
        self.assertIsNone(res["breakdown"]["total_payable"])

    def test_kz_chapter_20_no_legacy_garbage(self) -> None:
        """После удаления id 1,2,4,5,6 — KZ + гл.20 не даёт 120% мусорной ставки."""
        res = self._calc(hs_code="2005400000", country="KZ", customs_value=50_000, net_weight_kg=100)
        self.assertEqual(res["breakdown"]["special_duties_amount"], 0.0)

    def test_missing_8429_rate_does_not_create_final_zero_measure(self) -> None:
        res = self._calc(hs_code="8429100000", country="CN", customs_value=500_000)
        self.assertEqual(res["status"], "REVIEW_REQUIRED")
        self.assertEqual(res["breakdown"]["special_duties_amount"], 0.0)
        self.assertIn("hs_rate_source_missing", res["payment_review_reasons"])
        self.assertIsNone(res["breakdown"]["total_payable"])
        self.assertNotIn("применена ставка 0%", res["legal_basis"]["duty"])
        self.assertIn("окончательный платёж удержан", res["legal_basis"]["duty"])

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


    def test_unverified_active_measure_fails_closed_at_effective_boundary(self) -> None:
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
            details = res.get("special_duties") or []
            self.assertEqual(res["breakdown"]["special_duties_amount"], 0.0)
            self.assertEqual(details[0]["review_reason"], "special_duty_provenance_unverified")
            self.assertIn("special_duty_provenance_unverified", res["payment_review_reasons"])
            self.assertIsNone(res["breakdown"]["total_payable"])
        finally:
            with SessionLocal() as db:
                db.query(SpecialDuty).filter(
                    SpecialDuty.regulatory_act.in_(list(markers.values()))
                ).delete(synchronize_session=False)
                db.commit()

    @staticmethod
    def _official_anti_dumping_row(*, act: str, rate: float = 7.0) -> SpecialDuty:
        today = date.today()
        return SpecialDuty(
            hs_code_prefix="9996",
            origin_country="ZZ",
            rate_percent=rate,
            rate_specific=0.0,
            currency_code="RUB",
            regulatory_act=act,
            measure_type="anti_dumping",
            manufacturer_exporter="",
            product_description="",
            effective_from=(today - timedelta(days=1)).isoformat(),
            effective_to=(today + timedelta(days=365)).isoformat(),
            source_code="EEC_ANTI_DUMPING",
            source_revision="anti-dumping:2026-09-29",
            source_url="https://eec.eaeunion.org/comission/department/trade/trade-remedies/",
            synced_at=datetime.now(timezone.utc).replace(tzinfo=None),
            needs_verification=False,
        )

    def test_official_measure_is_applied_once_when_exact_duplicate_exists(self) -> None:
        marker = "TEST-OFFICIAL-DUPLICATE-SPECIAL-DUTY"
        with SessionLocal() as db:
            db.add_all([
                self._official_anti_dumping_row(act=marker),
                self._official_anti_dumping_row(act=marker),
            ])
            db.commit()
        try:
            res = self._calc(hs_code="9996999999", country="ZZ")
            self.assertEqual(res["breakdown"]["special_duties_amount"], 7_000.0)
            applied = [d for d in res["special_duties"] if not d.get("warning")]
            self.assertEqual(len(applied), 1)
        finally:
            with SessionLocal() as db:
                db.query(SpecialDuty).filter(SpecialDuty.regulatory_act == marker).delete()
                db.commit()

    def test_overlapping_distinct_official_measures_fail_closed(self) -> None:
        markers = ["TEST-OFFICIAL-OVERLAP-A", "TEST-OFFICIAL-OVERLAP-B"]
        with SessionLocal() as db:
            db.add_all([
                self._official_anti_dumping_row(act=markers[0], rate=7.0),
                self._official_anti_dumping_row(act=markers[1], rate=9.0),
            ])
            db.commit()
        try:
            res = self._calc(hs_code="9996999999", country="ZZ")
            self.assertEqual(res["breakdown"]["special_duties_amount"], 0.0)
            self.assertEqual(
                res["special_duties"][0]["review_reason"],
                "special_duty_overlap_unresolved",
            )
            self.assertIn("special_duty_overlap_unresolved", res["payment_review_reasons"])
            self.assertIsNone(res["breakdown"]["total_payable"])
        finally:
            with SessionLocal() as db:
                db.query(SpecialDuty).filter(SpecialDuty.regulatory_act.in_(markers)).delete(
                    synchronize_session=False
                )
                db.commit()

    def test_needs_verification_blocks_even_official_markers(self) -> None:
        marker = "TEST-NEEDS-VERIFICATION-SPECIAL-DUTY"
        row = self._official_anti_dumping_row(act=marker)
        row.needs_verification = True
        with SessionLocal() as db:
            db.add(row)
            db.commit()
        try:
            res = self._calc(hs_code="9996999999", country="ZZ")
            self.assertEqual(res["breakdown"]["special_duties_amount"], 0.0)
            self.assertEqual(
                res["special_duties"][0]["review_reason"],
                "special_duty_provenance_unverified",
            )
        finally:
            with SessionLocal() as db:
                db.query(SpecialDuty).filter(SpecialDuty.regulatory_act == marker).delete()
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
