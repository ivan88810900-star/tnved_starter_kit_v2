"""Тесты реестра нормативных источников и gap-отчёта полноты."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import unittest
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app import db as app_db, main as app_main
from app.main import app
from app.services import (
    fcs_preliminary_sync,
    normative_store,
    regulatory_source_completeness,
)
from app.services.normative_store import init_db
from app.services.regulatory_source_completeness import (
    _derive_coverage_status,
    _derive_edition_tracking_status,
    diagnose_source_entry,
    run_regulatory_source_completeness_report,
)
from app.services.regulatory_source_registry import (
    AUTHORITY_LEVEL_LABELS,
    REGULATORY_SOURCE_REGISTRY,
    RegulatorySourceEntry,
    get_registry_entry,
    list_registry_entries,
)


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
def _regulatory_source_database(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[sessionmaker]:
    """Keep source diagnostics and their probe row in a disposable database."""
    temp_dir = tmp_path_factory.mktemp("regulatory-source-completeness")
    database = temp_dir / "regulatory-source-completeness.db"
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
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    patches = pytest.MonkeyPatch()
    patches.setattr(sys.modules[__name__], "init_db", lambda: None)
    patches.setattr(app_main, "init_db", lambda: None)
    patches.setattr(app_db, "engine", engine)
    patches.setattr(app_db, "SessionLocal", factory)
    patches.setattr(normative_store, "engine", engine)
    patches.setattr(normative_store, "SessionLocal", factory)
    patches.setattr(regulatory_source_completeness, "SessionLocal", factory)
    patches.setattr(fcs_preliminary_sync, "SessionLocal", factory)

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


class TestRegulatorySourceRegistry(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def test_registry_has_required_official_sources(self) -> None:
        ids = {e.source_id for e in REGULATORY_SOURCE_REGISTRY}
        required = {
            "eec_tr_ts_catalog",
            "eec_classification_decisions",
            "fts_preliminary_classification",
            "pravo_gov_publication",
            "eec_sgr_decision_299",
            "fsa_registry_evidence",
            "ofac_sdn_list",
            "eu_sanctions_list",
        }
        self.assertTrue(required.issubset(ids))

    def test_authority_levels_are_explicit(self) -> None:
        for entry in REGULATORY_SOURCE_REGISTRY:
            self.assertIn(entry.authority_level, AUTHORITY_LEVEL_LABELS)
            row = list_registry_entries()[0]
            self.assertIn("authority_level", row)
            self.assertIn("is_source_of_truth", row)
            break

    def test_registry_entries_sorted_in_report(self) -> None:
        report = run_regulatory_source_completeness_report()
        ids = [s["source_id"] for s in report["sources"]]
        self.assertEqual(ids, sorted(ids))

    def test_report_summary_counts(self) -> None:
        report = run_regulatory_source_completeness_report()
        self.assertEqual(report["summary"]["total_sources"], len(REGULATORY_SOURCE_REGISTRY))
        self.assertEqual(
            sum(report["summary"]["by_coverage_status"].values()),
            len(REGULATORY_SOURCE_REGISTRY),
        )

    def test_official_sgr_seed_local_path(self) -> None:
        entry = get_registry_entry("eec_sgr_decision_299")
        assert entry is not None
        row = diagnose_source_entry(entry, status_by_code={})
        checked = row["local_source"]["paths_checked"]
        seed = next(p for p in checked if p["path"].endswith("official_sgr_rules.seed.json"))
        self.assertTrue(seed["exists"])

    def test_fsa_runtime_only_not_missing(self) -> None:
        entry = get_registry_entry("fsa_registry_evidence")
        assert entry is not None
        row = diagnose_source_entry(entry, status_by_code={})
        self.assertEqual(row["coverage_status"], "not_applicable")
        self.assertEqual(row["parser_status"], "runtime_only")

    def test_fts_official_not_covered_by_mirror_rows(self) -> None:
        """ПКР Alta (без префикса FCS-) не должны попадать в official FCS probe."""
        from app.db import SessionLocal
        from app.models.core import ClassificationDecision
        from app.services.regulatory_source_completeness import _count_db_probe

        with SessionLocal() as db:
            exists = (
                db.query(ClassificationDecision.id)
                .filter(ClassificationDecision.decision_number == "ALTA-MIRROR-PROBE-TEST")
                .first()
            )
            if not exists:
                db.add(
                    ClassificationDecision(
                        hs_code="8471300000",
                        product_name="Зеркало Alta",
                        description="Тест зеркала",
                        target_entity="Ноутбук",
                        decision_number="ALTA-MIRROR-PROBE-TEST",
                        issue_date="2020-01-01",
                    )
                )
                db.commit()
        self.assertEqual(_count_db_probe("classification_decisions_official_fts"), _count_fcs_official_only())

        entry = get_registry_entry("fts_preliminary_classification")
        assert entry is not None
        row = diagnose_source_entry(entry, status_by_code={})
        if _count_fcs_official_only() == 0:
            self.assertNotEqual(row["coverage_status"], "present")
        self.assertTrue(row["manual_review_required"])

    def test_tks_mirror_uses_fts_alta_source_probe(self) -> None:
        entry = get_registry_entry("tks_predecisions_mirror")
        assert entry is not None
        self.assertEqual(entry.db_probe, "preliminary_decisions_fts_alta")

    def test_commercial_mirror_flagged_manual_review(self) -> None:
        entry = get_registry_entry("tks_predecisions_mirror")
        assert entry is not None
        row = diagnose_source_entry(entry, status_by_code={})
        self.assertFalse(row["is_source_of_truth"])
        self.assertTrue(row["manual_review_required"])

    def test_official_local_copy_without_revision_tracking_is_partial(self) -> None:
        entry = RegulatorySourceEntry(
            source_id="test_official",
            title="Test official source",
            authority_level="official_binding",
            official_url="https://example.test/official",
            description="test",
            source_status_code="TEST_OFFICIAL",
            min_document_count=1,
        )
        tracking = _derive_edition_tracking_status(entry, None)
        coverage = _derive_coverage_status(
            entry,
            {"exists": True},
            None,
            None,
            "ok",
            tracking,
        )
        self.assertEqual(tracking, "unverified")
        self.assertEqual(coverage, "partial")

    def test_official_tracking_requires_dated_non_stale_revision(self) -> None:
        entry = RegulatorySourceEntry(
            source_id="test_official",
            title="Test official source",
            authority_level="official_reference",
            official_url="https://example.test/official",
            description="test",
            source_status_code="TEST_OFFICIAL",
        )
        for source_status in (
            {"revision": "eec:2026-09-24", "synced_at": "2026-09-24T10:00:00"},
            {"revision": "seed", "synced_at": "2026-09-24T10:00:00", "is_stale": False},
            {"revision": "eec:2026-09-24", "is_stale": False},
        ):
            with self.subTest(source_status=source_status):
                self.assertEqual(
                    _derive_edition_tracking_status(entry, source_status),
                    "unverified",
                )

        self.assertEqual(
            _derive_edition_tracking_status(
                entry,
                {
                    "revision": "eec:2026-09-24",
                    "synced_at": "2026-09-24T10:00:00",
                    "is_stale": False,
                },
            ),
            "tracked",
        )
        self.assertEqual(
            _derive_edition_tracking_status(
                entry,
                {
                    "revision": "eec:2026-09-24",
                    "synced_at": "2026-09-24T10:00:00",
                    "is_stale": True,
                },
            ),
            "stale",
        )


def _count_fcs_official_only() -> int:
    from app.services.fcs_preliminary_sync import count_fcs_official_decisions

    return count_fcs_official_decisions()


class TestRegulatorySourceCompletenessApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        cls.client = TestClient(app)

    def test_registry_endpoint(self) -> None:
        r = self.client.get("/api/sources/registry")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "OK")
        self.assertGreaterEqual(len(body["entries"]), 10)

    def test_completeness_endpoint(self) -> None:
        r = self.client.get("/api/sources/completeness")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "OK")
        self.assertIn("sources", body)
        self.assertIn("summary", body)
        self.assertIn("future_sync_notes", body)
        self.assertIn("official_source_gap_ids", body["summary"])
        self.assertIn("official_edition_tracking_gap_ids", body["summary"])
        self.assertTrue(body["summary"]["any_official_edition_tracking_gap"])
        for row in body["sources"]:
            self.assertIn("edition_tracking_status", row)
