"""Тесты импорта нормативных ставок: upsert с vat_rule, antidumping_countries."""
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services.normative_store import find_rate_for_hs, init_db, upsert_hs_rate
from app.services.source_import import import_normative_file


class SourceImportTests(unittest.TestCase):
    """Проверка upsert_hs_rate с новыми полями (vat_rule, antidumping_countries)."""

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(cls._tmpdir.name) / "source-import.db"
        cls._engine = create_engine(f"sqlite:///{db_path}")
        cls._session_local = sessionmaker(
            bind=cls._engine,
            autocommit=False,
            autoflush=False,
        )
        cls.addClassCleanup(cls._tmpdir.cleanup)
        cls.addClassCleanup(cls._engine.dispose)
        cls._patchers = (
            mock.patch.dict(os.environ, {"DATABASE_URL": f"sqlite:///{db_path}"}),
            mock.patch("app.db.engine", cls._engine),
            mock.patch("app.db.SessionLocal", cls._session_local),
            mock.patch("app.services.normative_store.engine", cls._engine),
            mock.patch("app.services.normative_store.SessionLocal", cls._session_local),
            mock.patch("app.services.tnved_fts.engine", cls._engine),
            mock.patch("app.services.tnved_fts._fts_ready", None),
            mock.patch("scripts.seed_declaration_documents.engine", cls._engine),
            mock.patch(
                "scripts.seed_declaration_documents.SessionLocal",
                cls._session_local,
            ),
        )
        for patcher in cls._patchers:
            patcher.start()
            cls.addClassCleanup(patcher.stop)
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
