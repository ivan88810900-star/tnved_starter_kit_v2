"""Тесты Smart Payments quote API и сервиса."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services.normative_store import init_db
from app.services.payment_engine import compute_payments
from app.services.payment_quote_service import build_payment_quote

try:
    from fastapi.testclient import TestClient

    from app.main import app

    _API_OK = True
except ImportError:
    _API_OK = False


def _complete_payment_result() -> dict:
    """Engine result with final arithmetic but no trade-remedy coverage."""
    return {
        "status": "OK",
        "customs_value": 100_000.0,
        "country": "DE",
        "breakdown": {
            "duty": 5_000.0,
            "duty_rate": 5.0,
            "vat": 23_100.0,
            "vat_rate": 22.0,
            "customs_fee": 1_067.0,
            "excise": 0.0,
            "antidumping": 0.0,
            "special_duties_amount": 0.0,
            "total_payable": 29_167.0,
        },
        "auto_detected": {
            "excise_type": "none",
            "antidumping_type": "none",
        },
        "data_quality": {
            "match_length": 10,
            "confidence": "high",
            "antidumping_status": "n/a",
        },
        "payment_review_reasons": [],
        "special_duties": [],
        "sources": [],
        "legal_basis": {},
    }


class PaymentQuoteStatusConsistencyTests(unittest.TestCase):
    def _patch_complete_engine_without_special_duty_coverage(self):
        return (
            patch(
                "app.services.payment_quote_service.get_rates_map",
                return_value={"RUB": 1.0},
            ),
            patch(
                "app.services.payment_quote_service.compute_payments",
                return_value=_complete_payment_result(),
            ),
            patch(
                "app.services.payment_quote_service._special_duties_configured_for_hs",
                return_value=False,
            ),
        )

    def test_unconfigured_special_duty_contour_marks_quote_for_review(self):
        rates_patch, compute_patch, coverage_patch = (
            self._patch_complete_engine_without_special_duty_coverage()
        )
        with rates_patch, compute_patch, coverage_patch:
            quote = build_payment_quote(
                {
                    "hs_code": "0101210000",
                    "customs_value": 100_000,
                    "invoice_currency": "RUB",
                    "country": "DE",
                }
            )

        special = next(item for item in quote.line_items if item.code == "special_duty")
        self.assertEqual(special.status, "not_configured")
        self.assertIsNone(quote.total_payable_rub)
        self.assertEqual(quote.status, "REVIEW_REQUIRED")

    @unittest.skipUnless(_API_OK, "payment quote API tests need FastAPI app")
    def test_api_never_returns_ok_with_withheld_total(self):
        rates_patch, compute_patch, coverage_patch = (
            self._patch_complete_engine_without_special_duty_coverage()
        )
        with rates_patch, compute_patch, coverage_patch:
            response = TestClient(app).post(
                "/api/payments/quote",
                json={
                    "hs_code": "0101210000",
                    "customs_value": 100_000,
                    "invoice_currency": "RUB",
                    "country": "DE",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "REVIEW_REQUIRED")
        self.assertIsNone(body["total_payable_rub"])

    @unittest.skipUnless(_API_OK, "payment quote API tests need FastAPI app")
    def test_api_rejects_negative_economic_input(self):
        """API не возвращает quote для отрицательного фрахта."""
        with patch(
            "app.services.payment_quote_service.get_rates_map",
            return_value={"RUB": 1.0},
        ):
            response = TestClient(app).post(
                "/api/payments/quote",
                json={
                    "hs_code": "8509400000",
                    "customs_value": 100_000,
                    "invoice_currency": "RUB",
                    "freight": -1,
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Стоимость фрахта", response.json()["detail"])

    @unittest.skipUnless(_API_OK, "payment quote API tests need FastAPI app")
    def test_api_rejects_boolean_economic_inputs_before_float_coercion(self):
        """Pydantic не должен превращать JSON boolean в 0.0/1.0."""
        for key, value in (
            ("customs_value", True),
            ("freight", True),
            ("insurance", False),
            ("duty_rate", True),
            ("vat_rate", False),
            ("excise", True),
            ("quantity", True),
            ("net_weight_kg", False),
            ("extra_quantity", True),
        ):
            with self.subTest(key=key):
                payload = {
                    "hs_code": "8509400000",
                    "customs_value": 100_000,
                    "invoice_currency": "RUB",
                    key: value,
                }
                response = TestClient(app).post("/api/payments/quote", json=payload)
                self.assertEqual(response.status_code, 422)
                self.assertIn("boolean", response.text)


class PaymentQuoteServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def _quote(self, **kwargs):
        defaults = {
            "hs_code": "8509400000",
            "customs_value": 100_000,
            "freight": 0,
            "invoice_currency": "RUB",
        }
        defaults.update(kwargs)
        return build_payment_quote(defaults)

    def _line(self, quote, code: str):
        for item in quote.line_items:
            if item.code == code:
                return item
        self.fail(f"line item {code!r} not found")

    def test_successful_quote_has_core_line_items(self):
        quote = self._quote()
        self.assertEqual(quote.status, "REVIEW_REQUIRED")
        codes = {item.code for item in quote.line_items}
        self.assertTrue({"duty", "vat", "customs_fee", "excise", "antidumping", "special_duty"}.issubset(codes))
        duty = self._line(quote, "duty")
        vat = self._line(quote, "vat")
        fee = self._line(quote, "customs_fee")
        self.assertEqual(duty.status, "manual_review_required")
        self.assertIsNone(duty.amount_rub)
        self.assertEqual(vat.status, "manual_review_required")
        self.assertIsNone(vat.amount_rub)
        self.assertEqual(fee.status, "applied")
        self.assertIsNone(quote.total_payable_rub)

    def test_excise_applied_for_beer(self):
        raw = compute_payments({"hs_code": "2203009900", "customs_value": 200_000})
        quote = self._quote(hs_code="2203009900", customs_value=200_000)
        excise = self._line(quote, "excise")
        self.assertGreater(raw["breakdown"]["excise"], 0)
        self.assertEqual(excise.status, "manual_review_required")
        self.assertIsNone(excise.amount_rub)
        self.assertIsNone(quote.total_payable_rub)

    def test_excise_not_silently_zero_for_unknown_code(self):
        quote = self._quote(hs_code="4738291056", customs_value=100_000)
        excise = self._line(quote, "excise")
        self.assertEqual(excise.status, "manual_review_required")
        self.assertIsNone(excise.amount_rub)
        self.assertIsNone(quote.total_payable_rub)
        self.assertTrue(any(w.code.startswith("excise_") for w in quote.warnings))

    def test_antidumping_manual_review_without_country(self):
        quote = self._quote(hs_code="7214990000", customs_value=100_000)
        ad = self._line(quote, "antidumping")
        self.assertEqual(ad.status, "manual_review_required")
        self.assertIsNone(ad.amount_rub)
        self.assertIsNone(quote.total_payable_rub)
        self.assertTrue(any("antidumping" in w.code for w in quote.warnings))

    def test_antidumping_applied_with_country(self):
        raw = compute_payments({"hs_code": "7214990000", "customs_value": 100_000, "country": "CN"})
        quote = self._quote(hs_code="7214990000", customs_value=100_000, country="CN")
        ad = self._line(quote, "antidumping")
        self.assertGreater(raw["breakdown"]["antidumping"], 0)
        self.assertIn("hs_rate_source_binding_unverified", raw["payment_review_reasons"])
        self.assertEqual(ad.status, "manual_review_required")
        self.assertIsNone(ad.amount_rub)
        self.assertIsNone(quote.total_payable_rub)

    def test_special_duty_not_configured_blocks_final_total(self):
        quote = self._quote(hs_code="8517120000", customs_value=50_000, country="CN")
        spec = self._line(quote, "special_duty")
        self.assertIn(spec.status, {"not_configured", "not_applicable", "applied", "manual_review_required"})
        if spec.status == "not_configured":
            self.assertIsNone(spec.amount_rub)
            self.assertIsNone(quote.total_payable_rub)
            self.assertTrue(any(w.code == "special_duty_not_configured" for w in quote.warnings))

    def test_assumptions_and_sources_present(self):
        quote = self._quote(country="DE", quantity=10)
        self.assertTrue(len(quote.assumptions) >= 2)
        self.assertTrue(any(a.key == "country" for a in quote.assumptions))
        self.assertIsInstance(quote.sources, list)

    def test_ambiguous_live_animal_quote_requires_characteristic(self):
        quote = self._quote(hs_code="0102291000", customs_value=100_000)
        vat = self._line(quote, "vat")

        self.assertEqual(quote.status, "REVIEW_REQUIRED")
        self.assertEqual(vat.status, "manual_review_required")
        self.assertIsNone(vat.amount_rub)
        self.assertTrue(
            any(w.code == "vat_live_animal_characteristic_review" for w in quote.warnings)
        )

    def test_confirmed_non_breeding_live_animal_quote_uses_vat10(self):
        quote = self._quote(
            hs_code="0102291000",
            customs_value=100_000,
            live_animal_breeding_status="non_breeding",
        )
        vat = self._line(quote, "vat")

        self.assertEqual(vat.rate_label, "10.0%")
        self.assertTrue(
            any(
                a.key == "live_animal_breeding_status" and "неплеменное" in a.value
                for a in quote.assumptions
            )
        )


@unittest.skipUnless(_API_OK, "payment quote API tests need FastAPI app")
class PaymentQuoteApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)

    def test_api_quote_endpoint(self):
        r = self.client.post(
            "/api/payments/quote",
            json={
                "hs_code": "8509400000",
                "customs_value": 500_000,
                "freight": 45_000,
                "invoice_currency": "RUB",
            },
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "REVIEW_REQUIRED")
        self.assertIn("line_items", body)
        self.assertGreater(len(body["line_items"]), 0)
        self.assertIn("warnings", body)
        self.assertIn("assumptions", body)
        lines = {line["code"]: line for line in body["line_items"]}
        self.assertEqual(lines["duty"]["status"], "manual_review_required")
        self.assertIsNone(lines["duty"]["amount_rub"])
        self.assertEqual(lines["vat"]["status"], "manual_review_required")
        self.assertIsNone(lines["vat"]["amount_rub"])
        self.assertIsNone(body["total_payable_rub"])

    def test_api_quote_antidumping_manual_review(self):
        r = self.client.post(
            "/api/payments/quote",
            json={"hs_code": "7214990000", "customs_value": 100_000},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        ad = next(x for x in body["line_items"] if x["code"] == "antidumping")
        self.assertEqual(ad["status"], "manual_review_required")
        self.assertIsNone(ad["amount_rub"])
        self.assertIsNone(body["total_payable_rub"])

    def test_api_rejects_untyped_live_animal_characteristic(self):
        r = self.client.post(
            "/api/payments/quote",
            json={
                "hs_code": "0102291000",
                "customs_value": 100_000,
                "live_animal_breeding_status": "probably-not-breeding",
            },
        )
        self.assertEqual(r.status_code, 422)
