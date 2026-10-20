"""Payment-facing request models must not coerce JSON booleans into numbers."""
from __future__ import annotations

import io
import unittest

import pandas as pd
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.assistant import CopilotLineIn, CopilotRequest
from app.api.calculator import (
    CalculatorRequest,
    CompareScenarioIn,
    CompareSharedEconomics,
    ScenarioCompareBase,
)
from app.api.compliance import ComplianceItemIn
from app.api.invoice import InvoiceBatchRequest, InvoiceLineIn
from app.main import app
from app.services.invoice_batch_service import calculate_line_payments
from app.services.invoice_batch_service import parse_invoice_file
from tests.support_auth import login_declarant


class PaymentApiBooleanInputTests(unittest.TestCase):
    def assert_boolean_rejected(self, model, base: dict, fields: tuple[str, ...]) -> None:
        for field in fields:
            with self.subTest(model=model.__name__, field=field):
                payload = dict(base)
                payload[field] = True
                with self.assertRaises(ValidationError) as raised:
                    model.model_validate(payload)
                self.assertIn("boolean", str(raised.exception))

    def test_calculator_models_reject_boolean_economic_inputs(self) -> None:
        self.assert_boolean_rejected(
            CalculatorRequest,
            {"hs_code": "8509400000", "customs_value": 100_000},
            (
                "customs_value",
                "freight",
                "insurance",
                "duty_rate",
                "vat_rate",
                "excise",
                "quantity",
                "net_weight_kg",
                "extra_quantity",
                "engine_volume",
            ),
        )
        self.assert_boolean_rejected(
            CompareSharedEconomics,
            {"customs_value": 100_000},
            (
                "customs_value",
                "freight",
                "insurance",
                "quantity",
                "net_weight_kg",
                "extra_quantity",
            ),
        )
        self.assert_boolean_rejected(
            CompareScenarioIn,
            {"hs_code": "8509400000"},
            ("duty_rate", "vat_rate", "excise"),
        )
        self.assert_boolean_rejected(
            ScenarioCompareBase,
            {"hs_code": "8509400000", "customs_value": 100_000},
            ("customs_value", "weight_gross_kg", "weight_net_kg"),
        )

    def test_compliance_model_rejects_boolean_economic_inputs(self) -> None:
        self.assert_boolean_rejected(
            ComplianceItemIn,
            {
                "hs_code": "8509400000",
                "description": "чайник",
                "customs_value": 100_000,
            },
            (
                "customs_value",
                "freight",
                "insurance",
                "duty_rate",
                "vat_rate",
                "excise",
                "quantity",
            ),
        )

    def test_copilot_models_reject_boolean_economic_inputs(self) -> None:
        for model in (CopilotRequest, CopilotLineIn):
            self.assert_boolean_rejected(
                model,
                {"description": "чайник"},
                ("customs_value", "freight", "insurance", "quantity"),
            )

    def test_invoice_models_reject_boolean_economic_inputs(self) -> None:
        self.assert_boolean_rejected(
            InvoiceLineIn,
            {"description": "чайник"},
            ("quantity", "unit_price", "weight_gross_kg", "weight_net_kg"),
        )
        self.assert_boolean_rejected(
            InvoiceBatchRequest,
            {"lines": [{"description": "чайник"}]},
            ("calendar_year",),
        )

    def test_invoice_service_rejects_boolean_before_float_coercion(self) -> None:
        for field in (
            "quantity",
            "unit_price",
            "weight_gross_kg",
            "weight_net_kg",
            "engine_volume",
        ):
            with self.subTest(field=field):
                line = {
                    "description": "чайник",
                    "hs_code": "8509400000",
                    "quantity": 1,
                    "unit_price": 100,
                    field: True,
                }
                with self.assertRaisesRegex(ValueError, "boolean"):
                    calculate_line_payments(line)

    def test_invoice_file_parser_rejects_booleans_before_float_coercion(self) -> None:
        for suffix in ("csv", "xlsx"):
            for field in (
                "quantity",
                "unit_price",
                "weight_gross_kg",
                "weight_net_kg",
            ):
                with self.subTest(suffix=suffix, field=field):
                    row = {
                        "description": "чайник",
                        "quantity": 1,
                        "unit_price": 100,
                        "weight_gross_kg": 2,
                        "weight_net_kg": 1,
                        field: True,
                    }
                    buf = io.BytesIO()
                    frame = pd.DataFrame([row])
                    if suffix == "csv":
                        frame.to_csv(buf, index=False)
                    else:
                        frame.to_excel(buf, index=False)
                    with self.assertRaisesRegex(ValueError, "boolean"):
                        parse_invoice_file(buf.getvalue(), f"invoice.{suffix}")

    def test_invoice_file_parser_preserves_valid_numeric_values(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "description": "чайник",
                    "quantity": 2,
                    "unit_price": 150.5,
                    "weight_gross_kg": 3.5,
                    "weight_net_kg": 3,
                }
            ]
        )
        buf = io.BytesIO()
        frame.to_excel(buf, index=False)
        [line] = parse_invoice_file(buf.getvalue(), "invoice.xlsx")
        self.assertEqual(line["quantity"], 2.0)
        self.assertEqual(line["unit_price"], 150.5)
        self.assertEqual(line["weight_gross_kg"], 3.5)
        self.assertEqual(line["weight_net_kg"], 3)

    def test_calculator_endpoint_returns_422_before_payment_execution(self) -> None:
        client = TestClient(app)
        for field in (
            "customs_value",
            "freight",
            "insurance",
            "duty_rate",
            "vat_rate",
            "excise",
            "quantity",
            "net_weight_kg",
            "extra_quantity",
            "engine_volume",
        ):
            with self.subTest(field=field):
                payload = {
                    "hs_code": "8509400000",
                    "customs_value": 100_000,
                    "save_history": False,
                    field: True,
                }
                response = client.post("/api/calculator/compute", json=payload)
                self.assertEqual(response.status_code, 422)
                self.assertIn("boolean", response.text)

    def test_invoice_endpoint_returns_422_before_payment_execution(self) -> None:
        client = TestClient(app)
        login_declarant(client)
        for field in (
            "quantity",
            "unit_price",
            "weight_gross_kg",
            "weight_net_kg",
        ):
            with self.subTest(field=field):
                line = {
                    "description": "чайник",
                    "quantity": 1,
                    "unit_price": 100,
                    field: True,
                }
                response = client.post(
                    "/api/invoice/calculate-batch",
                    json={"lines": [line], "auto_classify": False},
                )
                self.assertEqual(response.status_code, 422)
                self.assertIn("boolean", response.text)


if __name__ == "__main__":
    unittest.main()
