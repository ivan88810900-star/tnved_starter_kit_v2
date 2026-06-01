"""Тесты official import-duty ingestion (issue #37)."""

from __future__ import annotations

import json
import unittest
import unittest.mock
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.main import app
from app.models.core import ExchangeRate, GeoSpecialDuty, HsRate, SourceStatus, SyncLog, TnvedEntry
from app.models.tnved import Chapter, Commodity, HsDutyRule, Section, SpecialDuty, VatPreference
from app.services.import_duty_ingestion import run_import_duty_apply, run_import_duty_dry_run
from app.services.normative_store import init_db
from app.services.payment_data_coverage import diagnose_duty_rates, run_payment_data_coverage_report
from app.services.payment_data_normalization import run_payment_data_normalization_report

try:
    from fastapi.testclient import TestClient

    _API_OK = True
except ImportError:
    _API_OK = False


_TABLES = [
    Section.__table__,
    Chapter.__table__,
    Commodity.__table__,
    HsDutyRule.__table__,
    SpecialDuty.__table__,
    VatPreference.__table__,
    TnvedEntry.__table__,
    HsRate.__table__,
    ExchangeRate.__table__,
    GeoSpecialDuty.__table__,
    SourceStatus.__table__,
    SyncLog.__table__,
]


def _memory_sessionmaker():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=_TABLES)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _start_patches(sm: sessionmaker) -> tuple[unittest.mock._patch, ...]:
    patches = (
        unittest.mock.patch("app.services.import_duty_ingestion.SessionLocal", sm),
        unittest.mock.patch("app.services.payment_data_coverage.SessionLocal", sm),
        unittest.mock.patch("app.services.payment_data_normalization.SessionLocal", sm),
        unittest.mock.patch("app.services.normative_store.SessionLocal", sm),
    )
    for p in patches:
        p.start()
    return patches


def _stop_patches(*patches: unittest.mock._patch) -> None:
    for p in reversed(patches):
        p.stop()


def _table_counts(sm: sessionmaker) -> dict[str, int]:
    with sm() as db:
        return {
            "hs_rates": db.query(HsRate).count(),
            "source_status": db.query(SourceStatus).count(),
            "sync_log": db.query(SyncLog).count(),
        }


def _official_bundle_payload(*, revision: str = "ett:2026-05-01", rates: list[dict] | None = None) -> dict:
    return {
        "format": "customs_clear_normative_bundle",
        "revision": revision,
        "effective_from": "2026-01-01",
        "official_ett_url": "https://eec.eaeunion.org/comission/department/catr/ett/",
        "rates": rates
        or [
            {"hs_code": "8471300000", "hs_prefix": "8471", "duty_rate": "5%"},
            {"hs_code": "8528720001", "hs_prefix": "8528", "duty_rate": "10%"},
        ],
    }


class _BundleFixture:
    def __init__(self, payload: dict, rel_path: str = "data/raw_normative/eec_ett_normative_bundle.json"):
        self.rel_path = rel_path
        self.tmp = Path(unittest.mock.MagicMock())  # placeholder
        self._tmpdir = None
        self._backend_root: Path | None = None
        self.payload = payload

    def __enter__(self) -> tuple[Path, str]:
        import tempfile

        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        full = root / self.rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(json.dumps(self.payload), encoding="utf-8")
        self._backend_root = root
        return root, self.rel_path

    def __exit__(self, *args: object) -> None:
        if self._tmpdir:
            self._tmpdir.cleanup()


class TestImportDutyMissingSource(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)
        import app.services.import_duty_ingestion as idi

        self._root_patch = unittest.mock.patch.object(idi, "_BACKEND_ROOT", Path("/nonexistent"))
        self._root_patch.start()

    def tearDown(self) -> None:
        self._root_patch.stop()
        _stop_patches(*self._patches)

    def test_dry_run_missing_official_source(self) -> None:
        before = _table_counts(self.sm)
        report = run_import_duty_dry_run()
        after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "missing_official_source")
        self.assertTrue(report["dry_run"])
        self.assertFalse(report["db_mutated"])

    def test_apply_missing_official_source_no_provenance(self) -> None:
        before = _table_counts(self.sm)
        report = run_import_duty_apply()
        after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "missing_official_source")
        self.assertFalse(report["db_mutated"])
        self.assertEqual(after["source_status"], 0)
        self.assertEqual(after["sync_log"], 0)


class TestImportDutyDryRunNoMutation(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_dry_run_does_not_mutate_db(self) -> None:
        import app.services.import_duty_ingestion as idi

        with _BundleFixture(_official_bundle_payload()) as (root, rel):
            with unittest.mock.patch.object(idi, "_BACKEND_ROOT", root):
                before = _table_counts(self.sm)
                report = run_import_duty_dry_run(rel_path=rel)
                after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "OK")
        self.assertTrue(report["dry_run"])
        self.assertFalse(report["db_mutated"])
        self.assertGreater(report["row_counts"]["insert"], 0)


class TestImportDutyBlockedBundles(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def _run_blocked(self, payload: dict) -> dict:
        import app.services.import_duty_ingestion as idi

        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(idi, "_BACKEND_ROOT", root):
                return run_import_duty_apply(rel_path=rel)

    def test_seed_bundle_revision_blocks_import(self) -> None:
        report = self._run_blocked(_official_bundle_payload(revision="seed-2026-03"))
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])
        self.assertEqual(_table_counts(self.sm)["source_status"], 0)

    def test_example_bundle_revision_blocks_import(self) -> None:
        report = self._run_blocked(_official_bundle_payload(revision="example-2026-03"))
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])

    def test_explicit_seed_row_revision_blocks_import(self) -> None:
        payload = _official_bundle_payload(
            rates=[
                {"hs_code": "8471300000", "hs_prefix": "8471", "duty_rate": "5%", "source_revision": "seed-2026-03"},
            ]
        )
        report = self._run_blocked(payload)
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])

    def test_demo_row_revision_blocks_import(self) -> None:
        payload = _official_bundle_payload(
            rates=[
                {"hs_code": "8471300000", "hs_prefix": "8471", "duty_rate": "5%", "source_revision": "demo-2026"},
            ]
        )
        report = self._run_blocked(payload)
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])


class TestImportDutyApplyOfficial(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_apply_imports_official_rows_with_provenance(self) -> None:
        import app.services.import_duty_ingestion as idi

        with _BundleFixture(_official_bundle_payload()) as (root, rel):
            with unittest.mock.patch.object(idi, "_BACKEND_ROOT", root):
                report = run_import_duty_apply(rel_path=rel)

        self.assertEqual(report["status"], "OK")
        self.assertTrue(report["db_mutated"])
        self.assertEqual(report["provenance"]["revision"], "ett:2026-05-01")
        self.assertEqual(report["provenance"]["source_code"], "EEC_ETT")
        self.assertIsNotNone(report["provenance"]["checksum_sha256"])

        with self.sm() as db:
            row = db.query(HsRate).filter(HsRate.hs_code == "8471300000").first()
            self.assertIsNotNone(row)
            self.assertEqual(row.source_revision, "ett:2026-05-01")
            self.assertEqual(row.duty_rate, "5%")
            st = db.query(SourceStatus).filter(SourceStatus.source_code == "EEC_ETT").first()
            self.assertIsNotNone(st)
            self.assertEqual(st.revision, "ett:2026-05-01")
            self.assertFalse(st.is_stale)
            logs = db.query(SyncLog).filter(SyncLog.source_code == "EEC_ETT").all()
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0].status, "OK")

    def test_blank_row_revision_inherits_bundle_revision(self) -> None:
        import app.services.import_duty_ingestion as idi

        payload = _official_bundle_payload(
            rates=[{"hs_code": "9401300000", "hs_prefix": "9401", "duty_rate": "7%", "source_revision": ""}]
        )
        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(idi, "_BACKEND_ROOT", root):
                report = run_import_duty_apply(rel_path=rel)
        self.assertEqual(report["status"], "OK")
        with self.sm() as db:
            row = db.query(HsRate).filter(HsRate.hs_code == "9401300000").first()
            self.assertIsNotNone(row)
            self.assertEqual(row.source_revision, "ett:2026-05-01")

    def test_apply_updates_seed_row_to_official(self) -> None:
        import app.services.import_duty_ingestion as idi

        with self.sm() as db:
            db.add(
                HsRate(
                    hs_code="8471300000",
                    hs_prefix="8471",
                    duty_rate="0%",
                    vat_import_rate=22.0,
                    source_revision="seed",
                )
            )
            db.commit()

        with _BundleFixture(_official_bundle_payload()) as (root, rel):
            with unittest.mock.patch.object(idi, "_BACKEND_ROOT", root):
                report = run_import_duty_apply(rel_path=rel)
        self.assertEqual(report["status"], "OK")
        self.assertGreaterEqual(report["row_counts"]["update"], 1)
        with self.sm() as db:
            row = db.query(HsRate).filter(HsRate.hs_code == "8471300000").first()
            self.assertEqual(row.source_revision, "ett:2026-05-01")
            self.assertEqual(row.duty_rate, "5%")

    def test_blocked_apply_does_not_write_source_status_or_sync_log(self) -> None:
        import app.services.import_duty_ingestion as idi

        payload = _official_bundle_payload(revision="fallback-2026")
        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(idi, "_BACKEND_ROOT", root):
                report = run_import_duty_apply(rel_path=rel)
        self.assertEqual(report["status"], "manual_review_required")
        with self.sm() as db:
            self.assertEqual(db.query(SourceStatus).count(), 0)
            self.assertEqual(db.query(SyncLog).count(), 0)


class TestImportDutyCoverageAfterImport(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def _seed_catalog_and_import(self, *, catalog_size: int) -> dict:
        import app.services.import_duty_ingestion as idi

        base = 9_700_000_000
        rates = [
            {"hs_code": f"{base + i:010d}", "hs_prefix": f"{base + i:010d}"[:4], "duty_rate": f"{5 + i % 3}%"}
            for i in range(catalog_size)
        ]
        with self.sm() as db:
            for i in range(catalog_size):
                code = f"{base + i:010d}"
                db.add(TnvedEntry(hs_code=code, level=10, title=f"item {i}"))
            db.commit()

        payload = _official_bundle_payload(rates=rates)
        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(idi, "_BACKEND_ROOT", root):
                return run_import_duty_apply(rel_path=rel)

    def test_partial_catalog_coverage_stays_partial(self) -> None:
        report = self._seed_catalog_and_import(catalog_size=5)
        self.assertEqual(report["status"], "OK")
        duty = diagnose_duty_rates()
        self.assertEqual(duty.status, "partial")
        self.assertIn("официаль", (duty.authority_level or "").lower())
        self.assertTrue(duty.manual_review_required)

    def test_full_catalog_coverage_can_be_present(self) -> None:
        report = self._seed_catalog_and_import(catalog_size=120)
        self.assertEqual(report["status"], "OK")
        duty = diagnose_duty_rates()
        self.assertEqual(duty.status, "present")
        self.assertIn("официаль", (duty.authority_level or "").lower())
        self.assertFalse(duty.manual_review_required)

    def test_normalization_sees_official_import(self) -> None:
        self._seed_catalog_and_import(catalog_size=120)
        norm = run_payment_data_normalization_report()
        duty = norm["domains"]["import_duty"]
        self.assertEqual(duty["coverage_status"], "present")
        cov = run_payment_data_coverage_report()
        self.assertEqual(cov["summary"]["duty_rates"]["status"], "present")


@unittest.skipUnless(_API_OK, "fastapi not installed")
class TestImportDutyApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        cls.client = TestClient(app)

    def test_dry_run_endpoint(self) -> None:
        r = self.client.post("/api/sources/payment-ingestion/import-duty/dry-run")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn(body["status"], ("OK", "missing_official_source", "manual_review_required"))
        self.assertTrue(body["dry_run"])
        self.assertFalse(body["db_mutated"])

    def test_apply_endpoint_requires_admin(self) -> None:
        r = self.client.post("/api/sources/payment-ingestion/import-duty/apply")
        self.assertIn(r.status_code, (401, 403))


if __name__ == "__main__":
    unittest.main()
