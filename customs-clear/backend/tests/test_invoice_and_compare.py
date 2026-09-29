"""Tests for invoice batch and scenario compare."""

from __future__ import annotations

import io
import asyncio
import unittest
from unittest.mock import patch

import pandas as pd

try:
    from app.services.invoice_batch_service import calculate_batch_lines, parse_invoice_file
    from app.services.scenario_compare_service import compare_scenarios_extended

    _OK = True
except ImportError:
    _OK = False


@unittest.skipIf(not _OK, "deps missing")
class InvoiceBatchTests(unittest.TestCase):
    def test_parse_csv(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "description": "Shoes",
                    "hs_code": "6403990000",
                    "quantity": 2,
                    "unit_price": 50,
                    "currency": "USD",
                    "weight_gross_kg": 3,
                    "weight_net_kg": 2.5,
                    "country_of_origin": "CN",
                }
            ]
        )
        buf = io.BytesIO()
        df.to_csv(buf, index=False)
        lines = parse_invoice_file(buf.getvalue(), "test.csv")
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["description"], "Shoes")

    def test_batch_total_stays_unavailable_when_any_line_requires_review(self) -> None:
        unavailable = {
            "customs_value": 100.0,
            "duty": 0.0,
            "vat": None,
            "excise": 0.0,
            "customs_fee": 0.0,
            "recycling_fee": 0.0,
            "rop": {"total_rop_rub": 0.0},
            "total_payable": None,
            "payments_status": "REVIEW_REQUIRED",
        }
        with patch(
            "app.services.invoice_batch_service.calculate_line_payments",
            return_value=unavailable,
        ):
            result = asyncio.run(
                calculate_batch_lines([{"description": "review"}], auto_classify=False)
            )

        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertIsNone(result["totals"]["vat"])
        self.assertIsNone(result["totals"]["total_payable"])


@unittest.skipIf(not _OK, "deps missing")
class ScenarioCompareTests(unittest.TestCase):
    def test_compare_two_countries(self) -> None:
        payload = {
            "base": {
                "hs_code": "8471300000",
                "customs_value": 1000,
                "currency": "USD",
                "weight_gross_kg": 110,
                "weight_net_kg": 100,
            },
            "scenarios": [
                {"name": "CN", "country_of_origin": "CN"},
                {"name": "DE", "country_of_origin": "DE"},
            ],
        }
        with patch(
            "app.services.scenario_compare_service.get_rates_map",
            return_value={"USD": 92.0, "RUB": 1.0},
        ):
            out = compare_scenarios_extended(payload)
        self.assertEqual(out["status"], "REVIEW_REQUIRED")
        self.assertEqual(len(out["scenarios"]), 2)
        self.assertIsNone(out["best_scenario"])
        self.assertTrue(all(row["total"] is None for row in out["scenarios"]))


if __name__ == "__main__":
    unittest.main()
