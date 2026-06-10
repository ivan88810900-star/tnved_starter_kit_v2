"""Тесты official excise ingestion (issue #41)."""

from __future__ import annotations

import json
import unittest
import unittest.mock
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.main import app
from app.models.core import ExchangeRate, GeoSpecialDuty, HsRate, SourceStatus, SyncLog, TnvedEntry
from app.models.tnved import Chapter, Commodity, HsDutyRule, Section, SpecialDuty, VatPreference
from app.services.excise_ingestion import run_excise_apply, run_excise_dry_run
from app.services.import_duty_ingestion import discover_import_duty_bundle_path, run_import_duty_dry_run
from app.services.normative_store import init_db
from app.services.payment_data_coverage import diagnose_duty_rates, diagnose_excise, diagnose_vat_rates
from app.services.vat_ingestion import discover_vat_bundle_path, run_vat_dry_run

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
        unittest.mock.patch("app.services.excise_ingestion.SessionLocal", sm),
        unittest.mock.patch("app.services.vat_ingestion.SessionLocal", sm),
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


def _seed_hs_rates_for_bundle(sm: sessionmaker) -> None:
    with sm() as db:
        for code, prefix, duty in (
            ("2203009900", "2203", "5%"),
            ("2402209000", "2402", "10%"),
        ):
            db.add(
                HsRate(
                    hs_code=code,
                    hs_prefix=prefix,
                    duty_rate=duty,
                    vat_import_rate=22.0,
                    vat_rule="none",
                    source_revision="ett:2026-05-01",
                    source_url="https://eec.eaeunion.org/comission/department/catr/ett/",
                )
            )
        db.commit()


def _official_excise_bundle_payload(*, revision: str = "excise:2026-05-01", rates: list[dict] | None = None) -> dict:
    return {
        "format": "customs_clear_normative_bundle",
        "revision": revision,
        "effective_from": "2026-01-01",
        "official_excise_url": "https://eec.eaeunion.org/comission/department/catr/ett/",
        "rates": rates
        or [
            {
                "hs_code": "2203009900",
                "excise_type": "percent",
                "excise_value": 5.0,
                "excise_basis": "НК РФ ст. 193",
            },
            {
                "hs_code": "2402209000",
                "excise_type": "fixed",
                "excise_value": 2500.0,
                "excise_basis": "НК РФ ст. 193",
            },
        ],
    }


class _BundleFixture:
    def __init__(self, payload: dict, rel_path: str = "data/raw_normative/eec_ett_excise.json"):
        self.rel_path = rel_path
        self.payload = payload
        self._tmpdir = None

    def __enter__(self) -> tuple[Path, str]:
        import tempfile

        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        full = root / self.rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(json.dumps(self.payload), encoding="utf-8")
        return root, self.rel_path

    def __exit__(self, *args: object) -> None:
        if self._tmpdir:
            self._tmpdir.cleanup()


class TestExciseMissingSource(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)
        import app.services.excise_ingestion as ei

        self._root_patch = unittest.mock.patch.object(ei, "_BACKEND_ROOT", Path("/nonexistent"))
        self._root_patch.start()

    def tearDown(self) -> None:
        self._root_patch.stop()
        _stop_patches(*self._patches)

    def test_dry_run_missing_official_source(self) -> None:
        before = _table_counts(self.sm)
        report = run_excise_dry_run()
        after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "missing_official_source")
        self.assertTrue(report["dry_run"])
        self.assertFalse(report["db_mutated"])

    def test_apply_missing_official_source_no_provenance(self) -> None:
        before = _table_counts(self.sm)
        report = run_excise_apply()
        after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "missing_official_source")
        self.assertFalse(report["db_mutated"])
        self.assertEqual(after["source_status"], 0)
        self.assertEqual(after["sync_log"], 0)


class TestExciseDryRunNoMutation(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_dry_run_does_not_mutate_db(self) -> None:
        import app.services.excise_ingestion as ei

        _seed_hs_rates_for_bundle(self.sm)
        with _BundleFixture(_official_excise_bundle_payload()) as (root, rel):
            with unittest.mock.patch.object(ei, "_BACKEND_ROOT", root):
                before = _table_counts(self.sm)
                report = run_excise_dry_run(rel_path=rel)
                after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "OK")
        self.assertTrue(report["dry_run"])
        self.assertFalse(report["db_mutated"])
        self.assertGreater(report["row_counts"]["update"], 0)


class TestExciseBlockedBundles(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def _run_blocked(self, payload: dict) -> dict:
        import app.services.excise_ingestion as ei

        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(ei, "_BACKEND_ROOT", root):
                return run_excise_apply(rel_path=rel)

    def test_seed_bundle_revision_blocks_import(self) -> None:
        report = self._run_blocked(_official_excise_bundle_payload(revision="seed-2026-03"))
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])
        self.assertEqual(_table_counts(self.sm)["source_status"], 0)

    def test_explicit_seed_row_revision_blocks_import(self) -> None:
        payload = _official_excise_bundle_payload(
            rates=[
                {
                    "hs_code": "2203009900",
                    "excise_type": "percent",
                    "excise_value": 5.0,
                    "source_revision": "seed-2026-03",
                },
            ]
        )
        report = self._run_blocked(payload)
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])

    def test_vat_only_rows_no_importable_excise(self) -> None:
        payload = _official_excise_bundle_payload(
            rates=[{"hs_code": "2203009900", "vat_import_rate": 10, "vat_rule": "reduced10"}]
        )
        report = self._run_blocked(payload)
        self.assertNotEqual(report["status"], "OK")
        self.assertFalse(report["db_mutated"])
        self.assertTrue(any("no_importable_excise_rows" in b for b in report["blockers"]))


class TestExciseApplyOfficial(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_apply_imports_official_excise_with_provenance(self) -> None:
        import app.services.excise_ingestion as ei

        _seed_hs_rates_for_bundle(self.sm)
        with _BundleFixture(_official_excise_bundle_payload()) as (root, rel):
            with unittest.mock.patch.object(ei, "_BACKEND_ROOT", root):
                report = run_excise_apply(rel_path=rel)

        self.assertEqual(report["status"], "OK")
        self.assertTrue(report["db_mutated"])
        self.assertEqual(report["provenance"]["revision"], "excise:2026-05-01")
        self.assertEqual(report["provenance"]["source_code"], "EEC_EXCISE")

        with self.sm() as db:
            row = db.query(HsRate).filter(HsRate.hs_code == "2203009900").first()
            self.assertIsNotNone(row)
            self.assertEqual(row.source_revision, "ett:2026-05-01")
            self.assertEqual(row.excise_type, "percent")
            self.assertEqual(float(row.excise_value), 5.0)
            self.assertEqual(row.excise_source_code, "EEC_EXCISE")
            self.assertEqual(row.excise_source_revision, "excise:2026-05-01")
            st = db.query(SourceStatus).filter(SourceStatus.source_code == "EEC_EXCISE").first()
            self.assertIsNotNone(st)
            logs = db.query(SyncLog).filter(SyncLog.source_code == "EEC_EXCISE").all()
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0].status, "OK")

    def test_blank_row_revision_inherits_official_bundle_revision(self) -> None:
        import app.services.excise_ingestion as ei

        _seed_hs_rates_for_bundle(self.sm)
        payload = _official_excise_bundle_payload(
            revision="excise:2026-06-01",
            rates=[{"hs_code": "2203009900", "excise_type": "percent", "excise_value": 5.0}],
        )
        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(ei, "_BACKEND_ROOT", root):
                report = run_excise_apply(rel_path=rel)
        self.assertEqual(report["status"], "OK")
        with self.sm() as db:
            row = db.query(HsRate).filter(HsRate.hs_code == "2203009900").first()
            self.assertEqual(row.excise_source_revision, "excise:2026-06-01")

    def test_blocked_apply_no_source_status_or_sync_log(self) -> None:
        import app.services.excise_ingestion as ei

        payload = _official_excise_bundle_payload(revision="fallback-2026")
        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(ei, "_BACKEND_ROOT", root):
                report = run_excise_apply(rel_path=rel)
        self.assertEqual(report["status"], "manual_review_required")
        with self.sm() as db:
            self.assertEqual(db.query(SourceStatus).count(), 0)
            self.assertEqual(db.query(SyncLog).count(), 0)


class TestExciseMissingSourceUrl(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_missing_source_url_blocks(self) -> None:
        import app.services.excise_ingestion as ei

        payload = {
            "format": "customs_clear_normative_bundle",
            "revision": "excise:2026-05-01",
            "rates": [{"hs_code": "2203009900", "excise_type": "percent", "excise_value": 5.0}],
        }
        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(ei, "_BACKEND_ROOT", root):
                report = run_excise_apply(rel_path=rel)
        self.assertNotEqual(report["status"], "OK")
        self.assertTrue(any("source_url" in b for b in report["blockers"]))
        with self.sm() as db:
            self.assertEqual(db.query(SyncLog).count(), 0)


class TestExciseAtomicApply(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_missing_hs_rate_blocks_atomic_apply(self) -> None:
        import app.services.excise_ingestion as ei

        _seed_hs_rates_for_bundle(self.sm)
        payload = _official_excise_bundle_payload(
            rates=[
                {"hs_code": "2203009900", "excise_type": "percent", "excise_value": 5.0},
                {"hs_code": "9999999999", "excise_type": "percent", "excise_value": 12.0},
            ]
        )
        with self.sm() as db:
            before_row = db.query(HsRate).filter(HsRate.hs_code == "2203009900").first()
            before_excise = (before_row.excise_type, before_row.excise_value)

        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(ei, "_BACKEND_ROOT", root):
                report = run_excise_apply(rel_path=rel)

        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])
        with self.sm() as db:
            row = db.query(HsRate).filter(HsRate.hs_code == "2203009900").first()
            self.assertEqual((row.excise_type, float(row.excise_value)), before_excise)
            self.assertEqual(db.query(SourceStatus).count(), 0)


class TestExciseParserFailures(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_malformed_rates_container(self) -> None:
        import app.services.excise_ingestion as ei

        payload = json.dumps(
            {"format": "customs_clear_normative_bundle", "revision": "excise:2026-01-01", "rates": 123}
        )
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rel = "data/raw_normative/eec_ett_excise.json"
            full = root / rel
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(payload, encoding="utf-8")
            with unittest.mock.patch.object(ei, "_BACKEND_ROOT", root):
                report = run_excise_apply(rel_path=rel)
        self.assertEqual(report["status"], "parser_failed")
        self.assertFalse(report["db_mutated"])


class TestExciseRevisionValidation(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def _apply(self, payload: dict) -> dict:
        import app.services.excise_ingestion as ei

        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(ei, "_BACKEND_ROOT", root):
                return run_excise_apply(rel_path=rel)

    def test_ett_revision_rejected_in_excise_ingestion(self) -> None:
        report = self._apply(_official_excise_bundle_payload(revision="ett:2026-05-01"))
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])

    def test_vat_revision_rejected_in_excise_ingestion(self) -> None:
        report = self._apply(_official_excise_bundle_payload(revision="vat:2026-05-01"))
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])

    def test_non_official_revision_tokens_rejected(self) -> None:
        for revision in ("manual", "local-copy", "unknown", "demo-2026", "test-2026", ""):
            with self.subTest(revision=revision):
                report = self._apply(_official_excise_bundle_payload(revision=revision))
                self.assertNotEqual(report["status"], "OK")
                self.assertFalse(report["db_mutated"])


class TestExciseBundleIsolation(unittest.TestCase):
    """Excise bundle не должен shadow import-duty/VAT discovery."""

    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_excise_bundle_not_used_by_import_duty_or_vat(self) -> None:
        import app.services.excise_ingestion as ei
        import app.services.import_duty_ingestion as idi
        import app.services.vat_ingestion as vi

        with _BundleFixture(_official_excise_bundle_payload()) as (root, rel):
            with unittest.mock.patch.object(ei, "_BACKEND_ROOT", root):
                with unittest.mock.patch.object(idi, "_BACKEND_ROOT", root):
                    with unittest.mock.patch.object(vi, "_BACKEND_ROOT", root):
                        self.assertIsNone(discover_import_duty_bundle_path())
                        self.assertIsNone(discover_vat_bundle_path())
                        duty = run_import_duty_dry_run()
                        vat = run_vat_dry_run()
        self.assertEqual(duty["status"], "missing_official_source")
        self.assertEqual(vat["status"], "missing_official_source")

    def test_excise_bundle_passed_to_import_duty_blocked(self) -> None:
        import app.services.import_duty_ingestion as idi

        with _BundleFixture(_official_excise_bundle_payload()) as (root, rel):
            with unittest.mock.patch.object(idi, "_BACKEND_ROOT", root):
                report = run_import_duty_dry_run(rel_path=rel)
        self.assertNotEqual(report["status"], "OK")
        self.assertIn(report["status"], ("manual_review_required", "missing_official_source"))
        if report["status"] == "manual_review_required":
            self.assertTrue(
                any("excise_only" in b or "no_importable_duty_rows" in b for b in report["blockers"])
            )


class TestExciseCoverageIsolation(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_seed_excise_rows_not_present_coverage(self) -> None:
        with self.sm() as db:
            db.add(
                HsRate(
                    hs_code="2203009900",
                    hs_prefix="2203",
                    duty_rate="5%",
                    excise_type="percent",
                    excise_value=5.0,
                    source_revision="seed",
                )
            )
            db.commit()
        excise = diagnose_excise()
        self.assertNotEqual(excise.status, "present")
        self.assertTrue(excise.manual_review_required)

    def test_excise_source_status_does_not_affect_duty_or_vat(self) -> None:
        import app.services.excise_ingestion as ei

        _seed_hs_rates_for_bundle(self.sm)
        duty_before = diagnose_duty_rates().status
        vat_before = diagnose_vat_rates().status
        with _BundleFixture(_official_excise_bundle_payload()) as (root, rel):
            with unittest.mock.patch.object(ei, "_BACKEND_ROOT", root):
                run_excise_apply(rel_path=rel)
        self.assertEqual(diagnose_duty_rates().status, duty_before)
        self.assertEqual(diagnose_vat_rates().status, vat_before)


class TestExciseOfficialCoveragePresent(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_official_excise_apply_enables_present_coverage(self) -> None:
        import app.services.excise_ingestion as ei

        _seed_hs_rates_for_bundle(self.sm)
        with _BundleFixture(_official_excise_bundle_payload()) as (root, rel):
            with unittest.mock.patch.object(ei, "_BACKEND_ROOT", root):
                report = run_excise_apply(rel_path=rel)
        self.assertEqual(report["status"], "OK")
        excise = diagnose_excise()
        self.assertEqual(excise.status, "present")
        self.assertFalse(excise.manual_review_required)


@unittest.skipUnless(_API_OK, "fastapi not installed")
class TestExciseApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        cls.client = TestClient(app)

    def test_dry_run_endpoint(self) -> None:
        r = self.client.post("/api/sources/payment-ingestion/excise/dry-run")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn(body["status"], ("OK", "missing_official_source", "manual_review_required"))
        self.assertTrue(body["dry_run"])
        self.assertFalse(body["db_mutated"])

    def test_apply_endpoint_requires_admin(self) -> None:
        r = self.client.post("/api/sources/payment-ingestion/excise/apply")
        self.assertIn(r.status_code, (401, 403))


if __name__ == "__main__":
    unittest.main()
