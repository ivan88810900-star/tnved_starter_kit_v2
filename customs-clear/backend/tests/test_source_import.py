"""Тесты импорта нормативных ставок: upsert с vat_rule, antidumping_countries."""
import io
import unittest

from openpyxl import Workbook

from app.services.normative_store import find_rate_for_hs, init_db, upsert_hs_rate
from app.services.source_import import import_normative_file


class SourceImportTests(unittest.TestCase):
    """Проверка upsert_hs_rate с новыми полями (vat_rule, antidumping_countries)."""

    @classmethod
    def setUpClass(cls):
        init_db()

    def test_upsert_with_vat_rule(self):
        """Upsert с vat_rule и vat_rule_basis."""
        row = {
            "hs_prefix": "7777",
            "hs_code": "7777",
            "duty_rate": "5",
            "vat_import_rate": 10.0,
            "vat_rule": "reduced10",
            "vat_rule_basis": "НК РФ ст. 164 п. 2",
            "excise_type": "none",
            "excise_value": 0.0,
            "antidumping_countries": "",
        }
        upsert_hs_rate(row)
        rate, _ = find_rate_for_hs("7777000000")
        self.assertIsNotNone(rate)
        self.assertEqual(rate.vat_rule, "reduced10")
        self.assertIn("164", rate.vat_rule_basis or "")

    def test_upsert_with_antidumping_countries(self):
        """Upsert с antidumping_countries."""
        row = {
            "hs_prefix": "6666",
            "hs_code": "6666",
            "duty_rate": "10",
            "vat_import_rate": 22.0,
            "antidumping_type": "percent",
            "antidumping_value": 15.0,
            "antidumping_countries": "CN,UA",
        }
        upsert_hs_rate(row)
        rate, _ = find_rate_for_hs("6666000000")
        self.assertIsNotNone(rate)
        self.assertIn("CN", (rate.antidumping_countries or ""))

    def test_import_xlsx_with_headers(self) -> None:
        wb = Workbook()
        ws = wb.active
        ws.append(["Код ТН ВЭД", "Наименование", "Ставка ввозной пошлины %"])
        ws.append([8509400000, "Чайники", 12.5])
        buf = io.BytesIO()
        wb.save(buf)
        res = import_normative_file(
            "tws_like.xlsx",
            buf.getvalue(),
            source_code="TEST_XLSX",
            source_name="test xlsx",
        )
        self.assertEqual(res["status"], "OK")
        self.assertGreaterEqual(res["imported"], 1)
        rate, _ = find_rate_for_hs("8509400000")
        self.assertIsNotNone(rate)
        self.assertEqual(str(rate.duty_rate).strip(), "12.5")


if __name__ == "__main__":
    unittest.main()
