"""Тесты импорта нормативных ставок: upsert с vat_rule, antidumping_countries."""
import importlib
import io
import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class SourceImportTests(unittest.TestCase):
    """Проверка upsert_hs_rate с новыми полями (vat_rule, antidumping_countries)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temp_dir = tempfile.TemporaryDirectory(prefix="source-import-")
        database = Path(cls._temp_dir.name) / "source-import.db"
        database_url = f"sqlite:///{database}"
        cls._started_patchers = []
        cls.addClassCleanup(cls._cleanup_database)
        env_patcher = unittest.mock.patch.dict(
            os.environ,
            {"DATABASE_URL": database_url},
        )
        env_patcher.start()
        cls._started_patchers.append(env_patcher)
        cls.app_db = importlib.import_module("app.db")
        cls.normative_store = importlib.import_module("app.services.normative_store")
        cls.source_import = importlib.import_module("app.services.source_import")
        cls.tnved_fts = importlib.import_module("app.services.tnved_fts")
        cls.seed_declaration_documents = importlib.import_module(
            "scripts.seed_declaration_documents"
        )
        original_engine = cls.app_db.engine
        original_session_local = cls.app_db.SessionLocal
        cls.engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},
        )
        cls.SessionLocal = sessionmaker(
            bind=cls.engine,
            autocommit=False,
            autoflush=False,
        )
        database_alias_patchers = []
        for module_name, module in tuple(sys.modules.items()):
            if not module or not module_name.startswith(("app.", "scripts.")):
                continue
            if getattr(module, "engine", None) is original_engine:
                database_alias_patchers.append(
                    unittest.mock.patch.object(module, "engine", cls.engine)
                )
            if getattr(module, "SessionLocal", None) is original_session_local:
                database_alias_patchers.append(
                    unittest.mock.patch.object(module, "SessionLocal", cls.SessionLocal)
                )
        cls._patchers = database_alias_patchers + [
            unittest.mock.patch.object(cls.app_db, "engine", cls.engine),
            unittest.mock.patch.object(cls.app_db, "SessionLocal", cls.SessionLocal),
            unittest.mock.patch.object(cls.normative_store, "engine", cls.engine),
            unittest.mock.patch.object(cls.normative_store, "SessionLocal", cls.SessionLocal),
            unittest.mock.patch.object(cls.tnved_fts, "engine", cls.engine),
            unittest.mock.patch.object(cls.tnved_fts, "_fts_ready", None),
            unittest.mock.patch.object(
                cls.seed_declaration_documents,
                "engine",
                cls.engine,
            ),
            unittest.mock.patch.object(
                cls.seed_declaration_documents,
                "SessionLocal",
                cls.SessionLocal,
            ),
            unittest.mock.patch.object(
                cls.source_import,
                "normalize_hs_duty_rate_string",
                cls.normative_store.normalize_hs_duty_rate_string,
            ),
            unittest.mock.patch.object(
                cls.source_import,
                "upsert_hs_rate",
                cls.normative_store.upsert_hs_rate,
            ),
            unittest.mock.patch.object(
                cls.source_import,
                "upsert_source_status",
                cls.normative_store.upsert_source_status,
            ),
        ]
        for patcher in cls._patchers:
            patcher.start()
            cls._started_patchers.append(patcher)
        cls.normative_store.init_db()

    @classmethod
    def _cleanup_database(cls) -> None:
        patcher_error = None
        for patcher in reversed(getattr(cls, "_started_patchers", [])):
            try:
                patcher.stop()
            except Exception as exc:  # pragma: no cover - defensive cleanup
                if patcher_error is None:
                    patcher_error = exc
        try:
            engine = getattr(cls, "engine", None)
            if engine is not None:
                engine.dispose()
        finally:
            temp_dir = getattr(cls, "_temp_dir", None)
            if temp_dir is not None:
                temp_dir.cleanup()
        if patcher_error is not None:
            raise patcher_error

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
        self.normative_store.upsert_hs_rate(row)
        rate, _ = self.normative_store.find_rate_for_hs("7777000000")
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
        self.normative_store.upsert_hs_rate(row)
        rate, _ = self.normative_store.find_rate_for_hs("6666000000")
        self.assertIsNotNone(rate)
        self.assertIn("CN", (rate.antidumping_countries or ""))

    def test_import_xlsx_with_headers(self) -> None:
        wb = Workbook()
        ws = wb.active
        ws.append(["Код ТН ВЭД", "Наименование", "Ставка ввозной пошлины %"])
        ws.append([8509400000, "Чайники", 12.5])
        buf = io.BytesIO()
        wb.save(buf)
        res = self.source_import.import_normative_file(
            "tws_like.xlsx",
            buf.getvalue(),
            source_code="TEST_XLSX",
            source_name="test xlsx",
        )
        self.assertEqual(res["status"], "OK")
        self.assertGreaterEqual(res["imported"], 1)
        rate, _ = self.normative_store.find_rate_for_hs("8509400000")
        self.assertIsNotNone(rate)
        self.assertEqual(str(rate.duty_rate).strip(), "12.5")


if __name__ == "__main__":
    unittest.main()
