"""Тесты Smart Payments quote API и сервиса."""

from __future__ import annotations

import unittest

from app.services.normative_store import init_db
from app.services.payment_engine import compute_payments
from app.services.payment_quote_service import build_payment_quote

try:
    from fastapi.testclient import TestClient

    from app.main import app

    _API_OK = True
except ImportError:
    _API_OK = False


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
        raw = compute_payments({
            "hs_code": "8509400000", "customs_value": 100_000,
            "freight": 0, "invoice_currency": "RUB",
        })
        quote = self._quote()
        self.assertEqual(raw["status"], "REVIEW_REQUIRED")
        self.assertGreater(raw["breakdown"]["duty"], 0)
        self.assertGreater(raw["breakdown"]["vat"], 0)
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
        self.assertEqual(raw["status"], quote.status)
        self.assertEqual(quote.status, "REVIEW_REQUIRED")
        self.assertEqual(excise.status, "manual_review_required")
        self.assertIsNone(excise.amount_rub)
        self.assertIsNone(quote.total_payable_rub)

    def test_excise_not_silently_zero_for_unknown_code(self):
        quote = self._quote(hs_code="4738291056", customs_value=100_000)
        excise = self._line(quote, "excise")
        self.assertIn(excise.status, {"unknown", "not_applicable"})
        if excise.status == "unknown":
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
        self.assertEqual(raw["auto_detected"]["antidumping_value"], 18.0)
        self.assertEqual(raw["breakdown"]["antidumping"], 0.0)
        self.assertIn("hs_rate_source_binding_unverified", raw["payment_review_reasons"])
        self.assertEqual(raw["status"], quote.status)
        self.assertEqual(quote.status, "REVIEW_REQUIRED")
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


@unittest.skipUnless(_API_OK, "payment quote API tests need FastAPI app")
class PaymentQuoteApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)

    def test_api_quote_endpoint(self):
        raw = compute_payments({
            "hs_code": "8509400000", "customs_value": 500_000,
            "freight": 45_000, "invoice_currency": "RUB",
        })
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
        self.assertGreater(raw["breakdown"]["duty"], 0)
        self.assertGreater(raw["breakdown"]["vat"], 0)
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
