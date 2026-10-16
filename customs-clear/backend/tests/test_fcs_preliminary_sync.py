"""Тесты синхронизации предварительных решений FCS и интеграции с completeness monitor."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app import db as app_db
from app.services import (
    fcs_preliminary_sync,
    normative_store,
    regulatory_source_completeness,
)
from app.services.fcs_preliminary_sync import (
    DEFAULT_FIXTURE_PATH,
    FCS_PRELIMINARY_SOURCE_CODE,
    count_fcs_official_decisions,
    load_fcs_preliminary_fixture,
    parse_fcs_preliminary_payload,
    sync_fcs_preliminary_decisions,
)
from app.services.normative_store import init_db, list_sync_log
from app.services.regulatory_source_completeness import diagnose_source_entry
from app.services.regulatory_source_registry import get_registry_entry
from app.services.tnved_code_card import find_preliminary_decisions_for_hs


BACKEND_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_SCRIPT = (
    BACKEND_ROOT / "scripts" / "bootstrap_disposable_classification_inventory.py"
)
DEFAULT_DATABASE = BACKEND_ROOT / "customs.db"
PINNED_CATALOGUE = BACKEND_ROOT / "customs.db.backup_before_pdf_import"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _protected_paths() -> set[Path]:
    paths = {DEFAULT_DATABASE.resolve(), PINNED_CATALOGUE.resolve()}
    configured_url = make_url(app_db.DATABASE_URL)
    if configured_url.drivername.startswith("sqlite") and configured_url.database:
        paths.add(Path(configured_url.database).resolve())

    source_database = os.environ.get("TNVED_SOURCE_DB", "").strip()
    if source_database:
        if source_database.startswith("sqlite:"):
            source_url = make_url(source_database)
            if source_url.database:
                paths.add(Path(source_url.database).resolve())
        elif "://" not in source_database:
            paths.add(Path(source_database).resolve())
    return paths


def _protected_fingerprints() -> dict[Path, str | None]:
    return {
        path: _sha256(path) if path.is_file() else None
        for path in _protected_paths()
    }


@pytest.fixture(scope="module", autouse=True)
def _fcs_preliminary_database(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[sessionmaker]:
    """Keep FCS sync writes in a disposable bootstrapped catalogue."""
    temp_dir = tmp_path_factory.mktemp("fcs-preliminary-sync")
    database = temp_dir / "fcs-preliminary-sync.db"
    protected_hashes = _protected_fingerprints()
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env.pop("TNVED_SOURCE_DB", None)
    result = subprocess.run(
        [sys.executable, str(BOOTSTRAP_SCRIPT), str(database)],
        cwd=BACKEND_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert _protected_fingerprints() == protected_hashes

    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False},
    )
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM classification_decisions"))
        connection.execute(text("DELETE FROM preliminary_decisions"))
        connection.execute(
            text("DELETE FROM sync_log WHERE source_code = :source_code"),
            {"source_code": FCS_PRELIMINARY_SOURCE_CODE},
        )
        connection.execute(
            text("DELETE FROM source_status WHERE source_code = :source_code"),
            {"source_code": FCS_PRELIMINARY_SOURCE_CODE},
        )
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    patches = pytest.MonkeyPatch()
    patches.setattr(sys.modules[__name__], "init_db", lambda: None)
    patches.setattr(app_db, "engine", engine)
    patches.setattr(app_db, "SessionLocal", factory)
    patches.setattr(normative_store, "engine", engine)
    patches.setattr(normative_store, "SessionLocal", factory)
    patches.setattr(fcs_preliminary_sync, "SessionLocal", factory)
    patches.setattr(regulatory_source_completeness, "SessionLocal", factory)

    try:
        yield factory
    finally:
        patches.undo()
        engine.dispose()
        for suffix in ("", "-shm", "-wal"):
            candidate = Path(f"{database}{suffix}")
            if candidate.exists():
                candidate.unlink()
        assert _protected_fingerprints() == protected_hashes


class TestFcsPreliminaryParser(unittest.TestCase):
    def test_parse_fixture_sample(self) -> None:
        records = load_fcs_preliminary_fixture(DEFAULT_FIXTURE_PATH)
        self.assertEqual(len(records), 3)
        self.assertTrue(all(r.decision_number.startswith("FCS-") for r in records))

    def test_parse_rejects_empty_items(self) -> None:
        with self.assertRaises(ValueError):
            parse_fcs_preliminary_payload({"schema_version": "1", "items": []})

    def test_parse_rejects_bad_schema(self) -> None:
        with self.assertRaises(ValueError):
            parse_fcs_preliminary_payload({"schema_version": "99", "items": [{}]})


class TestFcsPreliminarySync(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def test_sync_from_fixture_success(self) -> None:
        result = sync_fcs_preliminary_decisions(fixture_path=DEFAULT_FIXTURE_PATH)
        self.assertEqual(result["status"], "OK")
        self.assertGreaterEqual(result["rows_affected"], 1)
        self.assertGreaterEqual(count_fcs_official_decisions(), 1)

    def test_sync_parser_failure_records_error(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            tmp.write("{ not valid json")
            bad_path = Path(tmp.name)
        try:
            result = sync_fcs_preliminary_decisions(fixture_path=bad_path)
            self.assertEqual(result["status"], "ERROR")
            self.assertIn("error", result)
            logs = list_sync_log(source_code=FCS_PRELIMINARY_SOURCE_CODE, limit=1)
            self.assertTrue(logs)
            self.assertEqual(logs[0]["status"].upper(), "ERROR")
        finally:
            bad_path.unlink(missing_ok=True)

    def test_dry_run_does_not_write_sync_log(self) -> None:
        before = len(list_sync_log(source_code=FCS_PRELIMINARY_SOURCE_CODE, limit=100))
        result = sync_fcs_preliminary_decisions(fixture_path=DEFAULT_FIXTURE_PATH, dry_run=True)
        self.assertEqual(result["status"], "OK")
        self.assertTrue(result["dry_run"])
        after = len(list_sync_log(source_code=FCS_PRELIMINARY_SOURCE_CODE, limit=100))
        self.assertEqual(before, after)


class TestFcsCompletenessIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def test_completeness_reflects_fcs_source_after_sync(self) -> None:
        sync_fcs_preliminary_decisions(fixture_path=DEFAULT_FIXTURE_PATH)
        entry = get_registry_entry("fts_preliminary_classification")
        assert entry is not None
        row = diagnose_source_entry(entry)
        self.assertIn(row["coverage_status"], ("present", "partial"))
        self.assertIn(row["parser_status"], ("ok", "partial", "unknown"))
        self.assertIsNotNone(row.get("last_successful_sync_at"))
        self.assertGreaterEqual(row.get("local_document_count") or 0, 1)

    def test_completeness_parser_failed_on_bad_fixture(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            json.dump({"schema_version": "1", "items": []}, tmp)
            bad_path = Path(tmp.name)
        try:
            sync_fcs_preliminary_decisions(fixture_path=bad_path)
            entry = get_registry_entry("fts_preliminary_classification")
            assert entry is not None
            row = diagnose_source_entry(entry)
            self.assertEqual(row["parser_status"], "failed")
            self.assertEqual(row["coverage_status"], "parser_failed")
        finally:
            bad_path.unlink(missing_ok=True)


class TestFcsTnvedCodeCard(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        sync_fcs_preliminary_decisions(fixture_path=DEFAULT_FIXTURE_PATH)

    def test_code_card_finds_fcs_decisions(self) -> None:
        from app.db import SessionLocal

        with SessionLocal() as db:
            block = find_preliminary_decisions_for_hs(db, "8471300000")
        self.assertGreater(block["total_count"], 0)
        numbers = {d.get("decision_number") for d in block["classification_decisions"]}
        self.assertTrue(any(str(n).startswith("FCS-") for n in numbers if n))

    def test_code_card_empty_state_message(self) -> None:
        from app.db import SessionLocal

        with SessionLocal() as db:
            block = find_preliminary_decisions_for_hs(db, "0000000000")
        self.assertEqual(block["total_count"], 0)
        self.assertTrue(block["empty_message"])


if __name__ == "__main__":
    unittest.main()
