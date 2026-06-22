"""Tests for invoice batch and scenario compare."""

from __future__ import annotations

import io
import unittest

import pandas as pd

try:
    from app.services.invoice_batch_service import parse_invoice_file
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
        out = compare_scenarios_extended(payload)
        self.assertEqual(out["status"], "OK")
        self.assertEqual(len(out["scenarios"]), 2)
        self.assertIn("best_scenario", out)


if __name__ == "__main__":
    unittest.main()
