"""Нормализация номеров ДС/СС, извлечение из текста, API /api/permits/verify (мок ФСА)."""
from __future__ import annotations

import importlib.util
import hashlib
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services.permit_extractor import extract_permits_from_text
from app.services.permits_jobs import permits_job_items_as_csv
from app.services.permits_service import check_permits, normalize_number


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = BACKEND_ROOT / "customs.db"
PINNED_CATALOGUE = BACKEND_ROOT / "customs.db.backup_before_pdf_import"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _protected_fingerprints() -> dict[Path, str | None]:
    paths = {
        candidate
        for path in (DEFAULT_DATABASE, PINNED_CATALOGUE)
        for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm"))
    }
    return {
        path: _sha256(path) if path.is_file() else None
        for path in paths
    }


@pytest.fixture(scope="module", autouse=True)
def _isolated_permits_normalize_database(tmp_path_factory: pytest.TempPathFactory):
    """Exercise the permits API without reading or creating ambient SQLite."""
    protected_hashes = _protected_fingerprints()
    temp_dir = tmp_path_factory.mktemp("permits-normalize-api")
    database = temp_dir / "permits-normalize-api.db"
    patches = pytest.MonkeyPatch()
    preloaded_app_modules = {
        module_name
        for module_name in sys.modules
        if module_name == "app" or module_name.startswith("app.")
    }
    patches.setenv("DATABASE_URL", f"sqlite:///{database}")
    patches.delenv("TNVED_SOURCE_DB", raising=False)
    bootstrap = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.services.normative_store import init_db; init_db()",
        ],
        cwd=BACKEND_ROOT,
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        check=False,
    )
    assert bootstrap.returncode == 0, bootstrap.stdout + bootstrap.stderr
    assert _protected_fingerprints() == protected_hashes

    from app import db as app_db, main as app_main
    from app.services import normative_store as normative_store_module

    original_session = app_db.SessionLocal
    original_engine = app_db.engine
    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    for module_name, module in tuple(sys.modules.items()):
        if module is None or not (module_name == "app" or module_name.startswith("app.")):
            continue
        if getattr(module, "SessionLocal", None) is original_session:
            patches.setattr(module, "SessionLocal", factory)
        if getattr(module, "engine", None) is original_engine:
            patches.setattr(module, "engine", engine)

    patches.setattr(normative_store_module, "init_db", lambda: None)
    patches.setattr(app_main, "init_db", lambda: None)

    try:
        yield
    finally:
        patches.undo()
        for module_name, module in tuple(sys.modules.items()):
            if module is None or not (module_name == "app" or module_name.startswith("app.")):
                continue
            if getattr(module, "SessionLocal", None) is factory:
                setattr(module, "SessionLocal", original_session)
            if getattr(module, "engine", None) is engine:
                setattr(module, "engine", original_engine)
        for module_name in tuple(sys.modules):
            if (
                module_name not in preloaded_app_modules
                and (module_name == "app" or module_name.startswith("app."))
            ):
                sys.modules.pop(module_name, None)
        engine.dispose()
        for path in (
            database,
            Path(f"{database}-wal"),
            Path(f"{database}-shm"),
        ):
            if path.exists():
                path.unlink()
        assert _protected_fingerprints() == protected_hashes


# Реальный формат из практики (пользовательский пример)
USER_DS_LINE = "ДС ЕАЭС N RU Д-CN.РА05.В.23373/25"
USER_DS_NUMBER = "ЕАЭС RU Д-CN.РА05.В.23373/25"


class NormalizeNumberTests(unittest.TestCase):
    def test_preserves_cn_in_dash_cn_segment(self):
        """Буква N в «Д-CN» не должна исчезать (ошибка старого normalize)."""
        n = normalize_number(USER_DS_NUMBER)
        self.assertIn("CN", n)
        self.assertIn("23373", n)
        self.assertNotIn("Д-C.", n)  # не «обрубок» без N

    def test_strips_eaeu_n_ru_marker(self):
        """После удаления служебного «N» остаётся ЕАЭС + латинское RU без пробелов."""
        s = normalize_number("ЕАЭС N RU Д-X.YY99.В.00001/24")
        self.assertIn("ЕАЭСRUД-X", s)
        self.assertNotIn("N", s)

    def test_removes_numero_sign(self):
        self.assertEqual(normalize_number("№ RU Д-AB.CD12.В.1/99"), normalize_number("RU Д-AB.CD12.В.1/99"))


class ExtractUserDeclarationTests(unittest.TestCase):
    def test_extract_full_user_example(self):
        found = extract_permits_from_text(USER_DS_LINE)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["type"], "ДС")
        self.assertEqual(found[0]["number"], USER_DS_NUMBER)

    def test_extract_eaeus_prefix_without_standalone_ru_pattern(self):
        """Цепочка «ЕАЭС N RU Д-…» ловится основным шаблоном."""
        text = "Сертификация: ЕАЭС N RU Д-CN.РА05.В.23373/25 оформлена"
        found = extract_permits_from_text(text)
        nums = [x["number"] for x in found if x["type"] == "ДС"]
        self.assertIn(USER_DS_NUMBER, nums)


class PermitsJobCsvTests(unittest.TestCase):
    def test_permits_job_items_as_csv(self):
        csv_text = permits_job_items_as_csv(
            [
                {
                    "type": "ДС",
                    "number": "RU-X",
                    "status": "VALID",
                    "holder": "A",
                    "hs_code_check": {"hs_match": "ok"},
                }
            ]
        )
        self.assertIn("type", csv_text)
        self.assertIn("ДС", csv_text)
        self.assertIn("hs_match", csv_text)


class CheckPermitsAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_check_permits_calls_declaration_with_user_number(self):
        fake_row = {
            "type": "ДС",
            "status": "VALID",
            "number": normalize_number(USER_DS_NUMBER),
            "holder": "ООО Тест",
            "valid_from": "2025-01-01",
            "valid_to": "2030-12-31",
            "registry_link": "https://pub.fsa.gov.ru/rds/declaration?q=test",
            "raw": {"registry_tnved_codes": ["8509400000"]},
        }
        with patch(
            "app.services.permits_service.check_declaration",
            new_callable=AsyncMock,
            return_value=fake_row,
        ) as m_decl:
            rows = await check_permits(
                [{"type": "ДС", "number": USER_DS_NUMBER}],
                item_hs_code="8509400000",
                enrich=True,
            )
        m_decl.assert_awaited_once()
        call_arg = m_decl.await_args[0][0]
        self.assertIn("CN", normalize_number(call_arg))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "VALID")
        hc = rows[0].get("hs_code_check") or {}
        self.assertEqual(hc.get("hs_match"), "ok")


@unittest.skipUnless(
    importlib.util.find_spec("fastapi") and importlib.util.find_spec("httpx"),
    "нужны fastapi и httpx",
)
class PermitsVerifyEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.main import app
        from app.services.normative_store import init_db
        from fastapi.testclient import TestClient
        from tests.support_auth import login_declarant

        init_db()
        cls.client = TestClient(app)
        login_declarant(cls.client)

    @patch("app.api.permits.check_permits", new_callable=AsyncMock)
    def test_post_verify_user_declaration(self, mock_check):
        mock_check.return_value = [
            {
                "type": "ДС",
                "status": "VALID",
                "number": normalize_number(USER_DS_NUMBER),
                "holder": "Заявитель",
                "valid_from": None,
                "valid_to": None,
                "registry_link": "https://example.com",
                "raw": None,
                "verified_at": "2025-01-01T00:00:00+00:00",
                "registry_source": "pub.fsa.gov.ru (Росаккредитация)",
                "hs_code_check": {"hs_match": "unknown", "detail": "x"},
            }
        ]
        r = self.client.post(
            "/api/permits/verify",
            json={
                "permits": [{"type": "ДС", "number": USER_DS_NUMBER}],
                "hs_code": "",
                "enrich": True,
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["status"], "OK")
        self.assertEqual(body["summary"]["total"], 1)
        self.assertEqual(body["summary"]["valid"], 1)
        self.assertEqual(len(body["items"]), 1)
        mock_check.assert_awaited()

    @patch("app.services.permits_jobs.check_permits", new_callable=AsyncMock)
    def test_post_verify_async_persists_job(self, mock_check):
        mock_check.return_value = [
            {
                "type": "ДС",
                "status": "VALID",
                "number": normalize_number(USER_DS_NUMBER),
                "holder": "Заявитель",
                "valid_from": None,
                "valid_to": None,
                "registry_link": "https://example.com",
                "raw": None,
                "verified_at": "2025-01-01T00:00:00+00:00",
                "registry_source": "pub.fsa.gov.ru (Росаккредитация)",
                "hs_code_check": {"hs_match": "unknown", "detail": "x"},
            }
        ]
        r = self.client.post(
            "/api/permits/verify/async",
            json={
                "permits": [{"type": "ДС", "number": USER_DS_NUMBER}],
                "hs_code": "",
                "enrich": True,
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        job_id = r.json().get("job_id")
        self.assertTrue(job_id)
        st = None
        body = {}
        for _ in range(100):
            s = self.client.get(f"/api/permits/verify/jobs/{job_id}")
            self.assertEqual(s.status_code, 200, s.text)
            body = s.json()
            st = body.get("status")
            if st == "done":
                break
            time.sleep(0.02)
        self.assertEqual(st, "done", msg=body)
        self.assertEqual(body.get("summary", {}).get("valid"), 1)
        self.assertEqual(len(body.get("items") or []), 1)
        lst = self.client.get("/api/permits/verify/jobs?limit=20")
        self.assertEqual(lst.status_code, 200)
        ids = [x.get("job_id") for x in (lst.json().get("items") or [])]
        self.assertIn(job_id, ids)
        mock_check.assert_awaited()

        with patch.dict(os.environ, {"ADMIN_API_TOKEN": "permits-export-token"}):
            exp = self.client.get(
                f"/api/permits/verify/jobs/{job_id}/export?format=csv",
                headers={"X-Admin-Token": "permits-export-token"},
            )
        self.assertEqual(exp.status_code, 200, exp.text)
        self.assertIn("text/csv", exp.headers.get("content-type", ""))
        self.assertIn(b"type", exp.content[:300].lower())

        with patch.dict(os.environ, {"ADMIN_API_TOKEN": "permits-export-token"}):
            ej = self.client.get(
                f"/api/permits/verify/jobs/{job_id}/export?format=json",
                headers={"X-Admin-Token": "permits-export-token"},
            )
        self.assertEqual(ej.status_code, 200)
        self.assertEqual(ej.json().get("status"), "OK")
        self.assertEqual(len(ej.json().get("items") or []), 1)

        with patch.dict(os.environ, {"ADMIN_API_TOKEN": "permits-export-token"}):
            bad = self.client.get(
                "/api/permits/verify/jobs/nosuchid1234567890123456789012ab/export",
                headers={"X-Admin-Token": "permits-export-token"},
            )
        self.assertEqual(bad.status_code, 404)


@unittest.skipUnless(
    os.getenv("RUN_FSA_LIVE") == "1",
    "Реальный запрос к pub.fsa.gov.ru: RUN_FSA_LIVE=1 python -m unittest tests.test_permits_normalize_and_api.FsaLiveDeclarationSmoke",
)
class FsaLiveDeclarationSmoke(unittest.IsolatedAsyncioTestCase):
    """Живой вызов ФСА (может быть 403/UNKNOWN без VPN)."""

    async def test_user_declaration_fsa_roundtrip(self):
        from app.services.permits_service import check_declaration, clear_permits_cache

        await clear_permits_cache()
        r = await check_declaration(USER_DS_NUMBER)
        self.assertEqual(r.get("type"), "ДС")
        self.assertIn("CN", (r.get("number") or ""))
        self.assertIn(r.get("status"), ("VALID", "NOT_FOUND", "UNKNOWN"))


if __name__ == "__main__":
    unittest.main()
