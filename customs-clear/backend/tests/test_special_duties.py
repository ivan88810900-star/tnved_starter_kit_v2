"""Регрессия special_duties / trade remedies в payment_engine."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models.core import SourceStatus
from app.models.tnved import SpecialDuty
from app.services.normative_store import init_db
from app.services.payment_engine import compute_payments
from app.services.payment_quote_service import build_payment_quote


class SpecialDutiesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def setUp(self) -> None:
        self._previous_anti_dumping_status: dict[str, object] | None = None
        revision = f"anti-dumping:{date.today().isoformat()}"
        with SessionLocal() as db:
            status = (
                db.query(SourceStatus)
                .filter(SourceStatus.source_code == "EEC_ANTI_DUMPING")
                .first()
            )
            if status is None:
                status = SourceStatus(
                    source_code="EEC_ANTI_DUMPING",
                    source_name="TEST anti-dumping status",
                    source_url="https://eec.eaeunion.org/comission/department/trade/trade-remedies/",
                    revision=revision,
                    synced_at=datetime.now(timezone.utc).replace(tzinfo=None),
                    is_stale=False,
                    note="test current contour",
                )
                db.add(status)
            else:
                self._previous_anti_dumping_status = {
                    "source_name": status.source_name,
                    "source_url": status.source_url,
                    "revision": status.revision,
                    "synced_at": status.synced_at,
                    "is_stale": status.is_stale,
                    "note": status.note,
                }
                status.source_url = "https://eec.eaeunion.org/comission/department/trade/trade-remedies/"
                status.revision = revision
                status.synced_at = datetime.now(timezone.utc).replace(tzinfo=None)
                status.is_stale = False
                status.note = "test current contour"
            db.commit()

    def tearDown(self) -> None:
        with SessionLocal() as db:
            status = (
                db.query(SourceStatus)
                .filter(SourceStatus.source_code == "EEC_ANTI_DUMPING")
                .first()
            )
            if self._previous_anti_dumping_status is None:
                if status is not None:
                    db.delete(status)
            elif status is not None:
                for field, value in self._previous_anti_dumping_status.items():
                    setattr(status, field, value)
            db.commit()

    def _calc(self, **kwargs: object) -> dict:
        defaults: dict = {
            "hs_code": "7214990000",
            "customs_value": 100_000.0,
            "freight": 0.0,
            "quantity": 1.0,
        }
        defaults.update(kwargs)
        return compute_payments(defaults)

    def _public_calc(
        self,
        *,
        hs_code: str,
        country: str,
        manufacturer: str | None = None,
        product_description: str | None = None,
    ) -> dict:
        payload = {
            "hs_code": hs_code,
            "customs_value": 100_000.0,
            "currency": "RUB",
            "country_of_origin": country,
            "quantity": 1.0,
        }
        if manufacturer is not None:
            payload["manufacturer"] = manufacturer
        if product_description is not None:
            payload["product_description"] = product_description
        response = TestClient(app).post(
            "/api/calculator/compute",
            json=payload,
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

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
            source_revision=f"anti-dumping:{today.isoformat()}",
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

    def test_scoped_measure_requires_confirmed_manufacturer_and_product(self) -> None:
        marker = "TEST-SCOPED-SPECIAL-DUTY"
        row = self._official_anti_dumping_row(act=marker)
        row.manufacturer_exporter = "Alpha Steel Co"
        row.product_description = "Прокат горячекатаный"
        with SessionLocal() as db:
            db.add(row)
            db.commit()
        try:
            for manufacturer, product_description in (
                (None, None),
                ("Beta Steel Co", "Прокат горячекатаный"),
                ("Alpha Steel Co", "Холоднокатаный прокат"),
            ):
                with self.subTest(
                    manufacturer=manufacturer,
                    product_description=product_description,
                ):
                    result = self._public_calc(
                        hs_code="9996999999",
                        country="ZZ",
                        manufacturer=manufacturer,
                        product_description=product_description,
                    )
                    self.assertEqual(result["status"], "REVIEW_REQUIRED")
                    self.assertEqual(result["breakdown"]["special_duties_amount"], 0.0)
                    self.assertIsNone(result["breakdown"]["total_payable"])
                    self.assertIn(
                        "special_duty_scope_unresolved",
                        result["payment_review_reasons"],
                    )

            matched = self._public_calc(
                hs_code="9996999999",
                country="ZZ",
                manufacturer="  alpha   STEEL co  ",
                product_description="ПРОКАТ   ГОРЯЧЕКАТАНЫЙ",
            )
            self.assertEqual(matched["breakdown"]["special_duties_amount"], 7_000.0)
            self.assertNotIn(
                "special_duty_scope_unresolved",
                matched["payment_review_reasons"],
            )
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

    def test_public_path_rejects_future_trade_remedy_revision_and_sync(self) -> None:
        today = date.today()
        markers = ["TEST-FUTURE-REVISION", "TEST-FUTURE-SYNC"]
        revision_future = self._official_anti_dumping_row(act=markers[0])
        revision_future.hs_code_prefix = "9995"
        revision_future.source_revision = "anti-dumping:2099-01-01"
        sync_future = self._official_anti_dumping_row(act=markers[1])
        sync_future.hs_code_prefix = "9994"
        sync_future.source_revision = f"anti-dumping:{today.isoformat()}"
        sync_future.synced_at = datetime(2099, 1, 1)
        with SessionLocal() as db:
            db.add_all([revision_future, sync_future])
            db.commit()
        try:
            for hs_code in ("9995999999", "9994999999"):
                with self.subTest(hs_code=hs_code):
                    result = self._public_calc(hs_code=hs_code, country="ZZ")
                    self.assertEqual(result["status"], "REVIEW_REQUIRED")
                    self.assertEqual(result["breakdown"]["special_duties_amount"], 0.0)
                    self.assertIsNone(result["breakdown"]["total_payable"])
                    self.assertIn(
                        "special_duty_provenance_future",
                        result["payment_review_reasons"],
                    )
        finally:
            with SessionLocal() as db:
                db.query(SpecialDuty).filter(SpecialDuty.regulatory_act.in_(markers)).delete(
                    synchronize_session=False
                )
                db.commit()

    def test_public_path_rejects_stale_trade_remedy_source_status(self) -> None:
        marker = "TEST-STALE-SOURCE-STATUS-SPECIAL-DUTY"
        row = self._official_anti_dumping_row(act=marker)
        row.hs_code_prefix = "9992"
        row.source_revision = f"anti-dumping:{date.today().isoformat()}"
        with SessionLocal() as db:
            status = (
                db.query(SourceStatus)
                .filter(SourceStatus.source_code == "EEC_ANTI_DUMPING")
                .one()
            )
            status.revision = row.source_revision
            status.synced_at = datetime.now(timezone.utc).replace(tzinfo=None)
            status.is_stale = True
            status.note = "test stale contour"
            db.add(row)
            db.commit()
        try:
            result = self._public_calc(hs_code="9992999999", country="ZZ")
            self.assertEqual(result["status"], "REVIEW_REQUIRED")
            self.assertEqual(result["breakdown"]["special_duties_amount"], 0.0)
            self.assertIsNone(result["breakdown"]["total_payable"])
            self.assertIn(
                "special_duty_provenance_stale",
                result["payment_review_reasons"],
            )
        finally:
            with SessionLocal() as db:
                db.query(SpecialDuty).filter(SpecialDuty.regulatory_act == marker).delete()
                db.commit()

    def test_public_path_rejects_aged_trade_remedy_revision(self) -> None:
        marker = "TEST-AGED-REVISION-SPECIAL-DUTY"
        old_date = date.today() - timedelta(days=91)
        old_revision = f"anti-dumping:{old_date.isoformat()}"
        row = self._official_anti_dumping_row(act=marker)
        row.hs_code_prefix = "9991"
        row.source_revision = old_revision
        with SessionLocal() as db:
            status = (
                db.query(SourceStatus)
                .filter(SourceStatus.source_code == "EEC_ANTI_DUMPING")
                .one()
            )
            status.revision = old_revision
            status.synced_at = datetime.now(timezone.utc).replace(tzinfo=None)
            status.is_stale = False
            db.add(row)
            db.commit()
        try:
            result = self._public_calc(hs_code="9991999999", country="ZZ")
            self.assertEqual(result["status"], "REVIEW_REQUIRED")
            self.assertEqual(result["breakdown"]["special_duties_amount"], 0.0)
            self.assertIsNone(result["breakdown"]["total_payable"])
            self.assertIn(
                "special_duty_provenance_stale",
                result["payment_review_reasons"],
            )
        finally:
            with SessionLocal() as db:
                db.query(SpecialDuty).filter(SpecialDuty.regulatory_act == marker).delete()
                db.commit()

    def test_public_path_rejects_specific_trade_remedy_without_typed_unit(self) -> None:
        marker = "TEST-UNITLESS-SPECIFIC-SPECIAL-DUTY"
        row = self._official_anti_dumping_row(act=marker, rate=0.0)
        row.hs_code_prefix = "9993"
        row.rate_specific = 5_000.0
        with SessionLocal() as db:
            db.add(row)
            db.commit()
        try:
            result = self._public_calc(hs_code="9993999999", country="ZZ")
            self.assertEqual(result["status"], "REVIEW_REQUIRED")
            self.assertEqual(result["breakdown"]["special_duties_amount"], 0.0)
            self.assertIsNone(result["breakdown"]["total_payable"])
            self.assertIn(
                "special_duty_specific_unit_unverified",
                result["payment_review_reasons"],
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
            self.assertIn("special_duty_dates_invalid", res["payment_review_reasons"])
            quote = build_payment_quote({
                "hs_code": "9997999999", "country": "ZZ",
                "customs_value": 100_000, "invoice_currency": "RUB",
            })
            special = next(line for line in quote.line_items if line.code == "special_duty")
            self.assertEqual(special.status, "manual_review_required")
            self.assertIsNone(special.amount_rub)
            self.assertIsNone(quote.total_payable_rub)
        finally:
            with SessionLocal() as db:
                db.query(SpecialDuty).filter(
                    SpecialDuty.regulatory_act.in_(list(markers.values()))
                ).delete(synchronize_session=False)
                db.commit()

    def test_inverted_window_requires_review_instead_of_not_applicable(self) -> None:
        marker = "TEST-INVERTED-SPECIAL-WINDOW"
        row = self._official_anti_dumping_row(act=marker)
        row.effective_from = "2099-01-01"
        row.effective_to = "2020-01-01"
        with SessionLocal() as db:
            db.add(row)
            db.commit()
        try:
            result = self._public_calc(hs_code="9996999999", country="ZZ")
            self.assertIn("special_duty_dates_invalid", result["payment_review_reasons"])
            self.assertIsNone(result["breakdown"]["total_payable"])
        finally:
            with SessionLocal() as db:
                db.query(SpecialDuty).filter(SpecialDuty.regulatory_act == marker).delete()
                db.commit()

    def test_percent_only_special_duty_does_not_require_unused_fx(self) -> None:
        marker = "TEST-PERCENT-ONLY-FOREIGN-CURRENCY"
        row = self._official_anti_dumping_row(act=marker)
        row.currency_code = "EUR"
        with SessionLocal() as db:
            db.add(row)
            db.commit()
        try:
            result = self._public_calc(hs_code="9996999999", country="ZZ")
            self.assertEqual(result["breakdown"]["special_duties_amount"], 7000.0)
            self.assertEqual(result["special_duties"][0]["amount"], 7000.0)
            # No conversion was needed; never invent an EUR/RUB exchange rate.
            self.assertIsNone(result["special_duties"][0]["fx_rate"])
        finally:
            with SessionLocal() as db:
                db.query(SpecialDuty).filter(SpecialDuty.regulatory_act == marker).delete()
                db.commit()

    def test_invalid_special_duty_rates_withhold_quote_line(self) -> None:
        marker = "TEST-INVALID-SPECIAL-RATE"
        for field in ("rate_percent", "rate_specific"):
            for invalid in (-7.0, float("inf")):
                with self.subTest(field=field, value=invalid):
                    row = self._official_anti_dumping_row(act=marker)
                    setattr(row, field, invalid)
                    with SessionLocal() as db:
                        db.add(row)
                        db.commit()
                    try:
                        result = self._calc(hs_code="9996999999", country="ZZ")
                        self.assertEqual(result["breakdown"]["special_duties_amount"], 0.0)
                        self.assertIn("special_duty_rate_invalid", result["payment_review_reasons"])
                        quote = build_payment_quote({
                            "hs_code": "9996999999", "country": "ZZ",
                            "customs_value": 100_000, "invoice_currency": "RUB",
                        })
                        special = next(line for line in quote.line_items if line.code == "special_duty")
                        self.assertEqual(special.status, "manual_review_required")
                        self.assertIsNone(special.amount_rub)
                        self.assertIsNone(quote.total_payable_rub)
                    finally:
                        with SessionLocal() as db:
                            db.query(SpecialDuty).filter(SpecialDuty.regulatory_act == marker).delete()
                            db.commit()


if __name__ == "__main__":
    unittest.main()
