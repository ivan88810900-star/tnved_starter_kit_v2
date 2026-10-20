"""Invoice operands must fail closed before payment multiplication."""
from __future__ import annotations

import io
import math
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.invoice import InvoiceLineIn
from app.main import app
from app.services.invoice_batch_service import calculate_line_payments, parse_invoice_file
from tests.support_auth import login_declarant


class InvoiceEconomicInputAdmissionTests(unittest.TestCase):
    @staticmethod
    def _line(**updates):
        line = {
            "description": "чайник",
            "hs_code": "8509400000",
            "quantity": 2,
            "unit_price": 50,
            "currency": "RUB",
        }
        line.update(updates)
        return line

    def test_schema_rejects_missing_non_positive_and_non_finite_operands(self) -> None:
        with self.assertRaises(ValidationError):
            InvoiceLineIn.model_validate({"description": "чайник"})

        for field in ("quantity", "unit_price"):
            for value in (0, -1, math.nan, math.inf, -math.inf):
                with self.subTest(field=field, value=value):
                    with self.assertRaisesRegex(ValidationError, "конечным положительным"):
                        InvoiceLineIn.model_validate(self._line(**{field: value}))

        for field in ("weight_gross_kg", "weight_net_kg"):
            for value in (0, -1, math.nan, math.inf, -math.inf):
                with self.subTest(field=field, value=value):
                    with self.assertRaisesRegex(ValidationError, "конечным положительным"):
                        InvoiceLineIn.model_validate(self._line(**{field: value}))

    def test_schema_rejects_numpy_boolean_before_numeric_coercion(self) -> None:
        for field in ("quantity", "unit_price", "weight_gross_kg", "weight_net_kg"):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValidationError, "boolean"):
                    InvoiceLineIn.model_validate(self._line(**{field: np.bool_(True)}))

    def test_schema_rejects_gross_weight_below_net_weight(self) -> None:
        with self.assertRaisesRegex(ValidationError, "не меньше weight_net_kg"):
            InvoiceLineIn.model_validate(
                self._line(weight_gross_kg=2, weight_net_kg=3)
            )
        valid = InvoiceLineIn.model_validate(
            self._line(weight_gross_kg=3, weight_net_kg=3)
        )
        self.assertEqual(valid.weight_gross_kg, valid.weight_net_kg)

    def test_service_rejects_two_negative_operands_before_they_cancel_out(self) -> None:
        with (
            patch("app.services.invoice_batch_service.get_rates_map", return_value={"RUB": 1.0}),
            patch("app.services.invoice_batch_service.compute_payments") as compute,
        ):
            with self.assertRaisesRegex(ValueError, "quantity.*конечным положительным"):
                calculate_line_payments(self._line(quantity=-2, unit_price=-50))
        compute.assert_not_called()

    def test_service_rejects_non_finite_and_overflowing_operands(self) -> None:
        cases = (
            ("quantity", 0),
            ("unit_price", -1),
            ("weight_gross_kg", math.inf),
            ("weight_net_kg", math.nan),
            ("engine_volume", -1),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value):
                with self.assertRaisesRegex(ValueError, "конечным положительным"):
                    calculate_line_payments(self._line(**{field: value}))

        with self.assertRaisesRegex(ValueError, "invoice_value.*конечным положительным"):
            calculate_line_payments(self._line(quantity=1e308, unit_price=1e308))

    def test_csv_and_xlsx_reject_two_negative_operands(self) -> None:
        frame = pd.DataFrame([self._line(quantity=-2, unit_price=-50)])
        for suffix in ("csv", "xlsx"):
            with self.subTest(suffix=suffix):
                buf = io.BytesIO()
                if suffix == "csv":
                    frame.to_csv(buf, index=False)
                else:
                    frame.to_excel(buf, index=False)
                with self.assertRaisesRegex(ValueError, "quantity.*конечным положительным"):
                    parse_invoice_file(buf.getvalue(), f"invoice.{suffix}")

    def test_parser_rejects_invoice_value_overflow(self) -> None:
        frame = pd.DataFrame([self._line(quantity=1e308, unit_price=1e308)])
        buf = io.BytesIO()
        frame.to_csv(buf, index=False)
        with self.assertRaisesRegex(ValueError, "invoice_value.*конечным положительным"):
            parse_invoice_file(buf.getvalue(), "invoice.csv")

    def test_parser_and_service_reject_gross_weight_below_net_weight(self) -> None:
        line = self._line(weight_gross_kg=2, weight_net_kg=3)
        frame = pd.DataFrame([line])
        buf = io.BytesIO()
        frame.to_csv(buf, index=False)
        with self.assertRaisesRegex(ValueError, "не меньше weight_net_kg"):
            parse_invoice_file(buf.getvalue(), "invoice.csv")

        with (
            patch("app.services.invoice_batch_service.get_rates_map") as rates,
            patch("app.services.invoice_batch_service.calculate_rop") as rop,
        ):
            with self.assertRaisesRegex(ValueError, "не меньше weight_net_kg"):
                calculate_line_payments(line)
        rates.assert_not_called()
        rop.assert_not_called()

    def test_endpoint_rejects_negative_pair_with_422(self) -> None:
        client = TestClient(app)
        login_declarant(client)
        response = client.post(
            "/api/invoice/calculate-batch",
            json={"lines": [self._line(quantity=-2, unit_price=-50)], "auto_classify": False},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("конечным положительным", response.text)

    def test_json_and_upload_endpoints_return_422_for_overflow(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)
        login_declarant(client)
        response = client.post(
            "/api/invoice/calculate-batch",
            json={
                "lines": [self._line(quantity=1e308, unit_price=1e308)],
                "auto_classify": False,
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("invoice_value", response.text)

        frame = pd.DataFrame([self._line(quantity=1e308, unit_price=1e308)])
        buf = io.BytesIO()
        frame.to_csv(buf, index=False)
        response = client.post(
            "/api/invoice/upload?auto_classify=false",
            files={"file": ("invoice.csv", buf.getvalue(), "text/csv")},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("invoice_value", response.text)

    def test_endpoint_returns_422_when_gross_weight_is_below_net(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)
        login_declarant(client)
        response = client.post(
            "/api/invoice/calculate-batch",
            json={
                "lines": [self._line(weight_gross_kg=2, weight_net_kg=3)],
                "auto_classify": False,
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("не меньше weight_net_kg", response.text)

    def test_service_rejects_fx_overflow_before_payment_engine(self) -> None:
        with (
            patch(
                "app.services.invoice_batch_service.get_rates_map",
                return_value={"USD": 1e308, "RUB": 1.0},
            ),
            patch("app.services.invoice_batch_service.compute_payments") as compute,
        ):
            with self.assertRaisesRegex(ValueError, "customs_value.*конечным положительным"):
                calculate_line_payments(
                    self._line(quantity=1, unit_price=1e308, currency="USD")
                )
        compute.assert_not_called()

    def test_valid_operands_reach_payment_engine_unchanged(self) -> None:
        payment = {
            "status": "OK",
            "breakdown": {
                "duty": 0.0,
                "vat": 0.0,
                "excise": 0.0,
                "customs_fee": 0.0,
                "total_payable": 100.0,
            },
            "recycling_fee": {"fee_amount": 0.0},
        }
        with (
            patch("app.services.invoice_batch_service.get_rates_map", return_value={"RUB": 1.0}),
            patch("app.services.invoice_batch_service.compute_payments", return_value=payment) as compute,
            patch(
                "app.services.invoice_batch_service.calculate_rop",
                return_value={"total_rop_rub": 0.0, "not_subject_to_rop": True},
            ),
        ):
            result = calculate_line_payments(
                self._line(weight_gross_kg=3.0, weight_net_kg=2.5)
            )
        payload = compute.call_args.args[0]
        self.assertEqual(payload["customs_value"], 100.0)
        self.assertEqual(payload["gross_weight_kg"], 3.0)
        self.assertEqual(payload["net_weight_kg"], 2.5)
        self.assertEqual(result["customs_value_original"], 100.0)


if __name__ == "__main__":
    unittest.main()
