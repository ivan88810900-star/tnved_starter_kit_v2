"""Тесты импорта нормативных ставок: upsert с vat_rule, antidumping_countries."""
import io
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import db as app_db
from app.services import normative_store, tnved_fts
from app.services.normative_store import find_rate_for_hs, init_db, upsert_hs_rate
from app.services.source_import import import_normative_file


class SourceImportTests(unittest.TestCase):
    """Проверка upsert_hs_rate с новыми полями (vat_rule, antidumping_countries)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temp_dir = tempfile.TemporaryDirectory(prefix="source-import-")
        database = Path(cls._temp_dir.name) / "source-import.db"
        database_url = f"sqlite:///{database}"
        cls.engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},
        )
        cls.SessionLocal = sessionmaker(
            bind=cls.engine,
            autocommit=False,
            autoflush=False,
        )
        cls._patchers = [
            unittest.mock.patch.dict(os.environ, {"DATABASE_URL": database_url}),
            unittest.mock.patch.object(app_db, "engine", cls.engine),
            unittest.mock.patch.object(app_db, "SessionLocal", cls.SessionLocal),
            unittest.mock.patch.object(normative_store, "engine", cls.engine),
            unittest.mock.patch.object(normative_store, "SessionLocal", cls.SessionLocal),
            unittest.mock.patch.object(tnved_fts, "engine", cls.engine),
            unittest.mock.patch.object(tnved_fts, "_fts_ready", None),
        ]
        cls._started_patchers = []
        cls.addClassCleanup(cls._cleanup_database)
        for patcher in cls._patchers:
            patcher.start()
            cls._started_patchers.append(patcher)
        init_db()

    @classmethod
    def _cleanup_database(cls) -> None:
        for patcher in reversed(cls._started_patchers):
            patcher.stop()
        cls.engine.dispose()
        cls._temp_dir.cleanup()

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
