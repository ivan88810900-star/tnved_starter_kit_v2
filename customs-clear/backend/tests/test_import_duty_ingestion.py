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


class _RawBundleFixture:
    """Записывает произвольный (возможно невалидный) текст вместо JSON-объекта."""

    def __init__(self, raw_text: str, rel_path: str = "data/raw_normative/eec_ett_normative_bundle.json"):
        self.rel_path = rel_path
        self.raw_text = raw_text
        self._tmpdir = None

    def __enter__(self) -> tuple[Path, str]:
        import tempfile

        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        full = root / self.rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(self.raw_text, encoding="utf-8")
        return root, self.rel_path

    def __exit__(self, *args: object) -> None:
        if self._tmpdir:
            self._tmpdir.cleanup()


class TestImportDutyParserFailures(unittest.TestCase):
    """P1 #1: invalid/non-object bundle → blocked, без OK provenance и мутаций."""

    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def _dry_run(self, raw: str) -> dict:
        import app.services.import_duty_ingestion as idi

        with _RawBundleFixture(raw) as (root, rel):
            with unittest.mock.patch.object(idi, "_BACKEND_ROOT", root):
                return run_import_duty_dry_run(rel_path=rel)

    def _apply(self, raw: str) -> dict:
        import app.services.import_duty_ingestion as idi

        with _RawBundleFixture(raw) as (root, rel):
            with unittest.mock.patch.object(idi, "_BACKEND_ROOT", root):
                return run_import_duty_apply(rel_path=rel)

    def _assert_no_ok_provenance(self) -> None:
        with self.sm() as db:
            self.assertEqual(db.query(SourceStatus).count(), 0)
            self.assertEqual(
                db.query(SyncLog).filter(SyncLog.status == "OK").count(), 0
            )

    def test_invalid_json_dry_run_blocked(self) -> None:
        report = self._dry_run("{ this is : not valid json ,,, ")
        self.assertEqual(report["status"], "parser_failed")
        self.assertTrue(report["dry_run"])
        self.assertFalse(report["db_mutated"])
        self.assertTrue(report["blockers"])

    def test_invalid_json_apply_no_mutation(self) -> None:
        before = _table_counts(self.sm)
        report = self._apply("{ this is : not valid json ,,, ")
        after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "parser_failed")
        self.assertFalse(report["db_mutated"])
        self._assert_no_ok_provenance()

    def test_json_array_apply_blocked(self) -> None:
        before = _table_counts(self.sm)
        report = self._apply("[1, 2, 3]")
        after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "parser_failed")
        self.assertFalse(report["db_mutated"])
        self._assert_no_ok_provenance()

    def test_json_scalar_dry_run_and_apply_blocked(self) -> None:
        dry = self._dry_run("42")
        self.assertEqual(dry["status"], "parser_failed")
        self.assertFalse(dry["db_mutated"])
        before = _table_counts(self.sm)
        report = self._apply("42")
        after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "parser_failed")
        self._assert_no_ok_provenance()


class TestImportDutyMalformedRatesContainer(unittest.TestCase):
    """P2: rates/rows не-list → parser_failed/blocked без crash и без OK provenance."""

    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def _dry_run(self, payload: dict) -> dict:
        import app.services.import_duty_ingestion as idi

        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(idi, "_BACKEND_ROOT", root):
                return run_import_duty_dry_run(rel_path=rel)

    def _apply(self, payload: dict) -> dict:
        import app.services.import_duty_ingestion as idi

        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(idi, "_BACKEND_ROOT", root):
                return run_import_duty_apply(rel_path=rel)

    def _assert_no_ok_provenance(self) -> None:
        with self.sm() as db:
            self.assertEqual(db.query(SourceStatus).count(), 0)
            self.assertEqual(db.query(SyncLog).filter(SyncLog.status == "OK").count(), 0)

    def test_rates_scalar_blocked(self) -> None:
        payload = {"format": "customs_clear_normative_bundle", "revision": "ett:2026-01-01", "rates": 123}
        dry = self._dry_run(payload)
        self.assertEqual(dry["status"], "parser_failed")
        self.assertFalse(dry["db_mutated"])
        before = _table_counts(self.sm)
        report = self._apply(payload)
        after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "parser_failed")
        self.assertFalse(report["db_mutated"])
        self._assert_no_ok_provenance()

    def test_rates_object_blocked(self) -> None:
        payload = {"format": "customs_clear_normative_bundle", "revision": "ett:2026-01-01", "rates": {"a": 1}}
        report = self._apply(payload)
        self.assertEqual(report["status"], "parser_failed")
        self.assertFalse(report["db_mutated"])
        self._assert_no_ok_provenance()

    def test_rows_object_blocked(self) -> None:
        payload = {"format": "customs_clear_normative_bundle", "revision": "ett:2026-01-01", "rows": {"a": 1}}
        report = self._apply(payload)
        self.assertEqual(report["status"], "parser_failed")
        self.assertFalse(report["db_mutated"])
        self._assert_no_ok_provenance()

    def test_non_object_rows_blocked_parser_failed(self) -> None:
        for bad in ([123], ["bad"], [{"hs_code": "8471300000", "duty_rate": "5%"}, 7]):
            payload = {"format": "customs_clear_normative_bundle", "revision": "ett:2026-01-01", "rates": bad}
            dry = self._dry_run(payload)
            self.assertEqual(dry["status"], "parser_failed", msg=f"rates={bad}")
            self.assertFalse(dry["db_mutated"])
            before = _table_counts(self.sm)
            report = self._apply(payload)
            after = _table_counts(self.sm)
            self.assertEqual(before, after, msg=f"rates={bad} mutated DB")
            self.assertEqual(report["status"], "parser_failed")
            self.assertFalse(report["db_mutated"])
            self._assert_no_ok_provenance()

    def test_empty_rates_no_crash_conservative(self) -> None:
        payload = {"format": "customs_clear_normative_bundle", "revision": "ett:2026-01-01", "rates": []}
        dry = self._dry_run(payload)
        self.assertIn(dry["status"], ("manual_review_required", "missing_official_source"))
        self.assertFalse(dry["db_mutated"])
        report = self._apply(payload)
        self.assertNotEqual(report["status"], "OK")
        self.assertFalse(report["db_mutated"])
        self._assert_no_ok_provenance()

    def test_valid_rates_still_works(self) -> None:
        report = self._apply(_official_bundle_payload())
        self.assertEqual(report["status"], "OK")
        self.assertTrue(report["db_mutated"])


class TestImportDutyNonVersionedRevisionRejected(unittest.TestCase):
    """P2: arbitrary non-versioned revisions блокируются (нужен explicit versioned EEC/ETT)."""

    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def _dry_run(self, payload: dict) -> dict:
        import app.services.import_duty_ingestion as idi

        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(idi, "_BACKEND_ROOT", root):
                return run_import_duty_dry_run(rel_path=rel)

    def _apply(self, payload: dict) -> dict:
        import app.services.import_duty_ingestion as idi

        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(idi, "_BACKEND_ROOT", root):
                return run_import_duty_apply(rel_path=rel)

    def test_local_copy_revision_blocked_dry_run_and_apply(self) -> None:
        payload = _official_bundle_payload(revision="local-copy")
        dry = self._dry_run(payload)
        self.assertEqual(dry["status"], "manual_review_required")
        self.assertFalse(dry["db_mutated"])
        before = _table_counts(self.sm)
        report = self._apply(payload)
        after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])
        with self.sm() as db:
            self.assertEqual(db.query(SourceStatus).count(), 0)
            self.assertEqual(db.query(SyncLog).filter(SyncLog.status == "OK").count(), 0)

    def test_foo_revision_blocked(self) -> None:
        report = self._apply(_official_bundle_payload(revision="foo"))
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])

    def test_manual_revision_blocked(self) -> None:
        report = self._apply(_official_bundle_payload(revision="manual"))
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])

    def test_versioned_ett_revision_accepted(self) -> None:
        report = self._apply(_official_bundle_payload(revision="ett:2026-05-01"))
        self.assertEqual(report["status"], "OK")
        self.assertTrue(report["db_mutated"])

    def test_explicit_official_row_revision_accepted(self) -> None:
        payload = _official_bundle_payload(
            rates=[
                {"hs_code": "8471300000", "hs_prefix": "8471", "duty_rate": "5%", "source_revision": "eec-ett:2026-05-01"},
            ]
        )
        report = self._apply(payload)
        self.assertEqual(report["status"], "OK")
        self.assertTrue(report["db_mutated"])
        with self.sm() as db:
            row = db.query(HsRate).filter(HsRate.hs_code == "8471300000").first()
            self.assertEqual(row.source_revision, "eec-ett:2026-05-01")

    def test_explicit_non_versioned_row_revision_blocked(self) -> None:
        payload = _official_bundle_payload(
            rates=[
                {"hs_code": "8471300000", "hs_prefix": "8471", "duty_rate": "5%", "source_revision": "local-copy"},
            ]
        )
        report = self._apply(payload)
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])


class TestImportDutyExactRowPrefixScope(unittest.TestCase):
    """P1: exact 10-значные rows не сохраняют broad prefix и не покрывают siblings."""

    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def _apply(self, payload: dict) -> dict:
        import app.services.import_duty_ingestion as idi

        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(idi, "_BACKEND_ROOT", root):
                return run_import_duty_apply(rel_path=rel)

    def test_exact_row_without_prefix_does_not_persist_broad_prefix(self) -> None:
        payload = _official_bundle_payload(
            rates=[{"hs_code": "8471300000", "duty_rate": "5%"}]
        )
        report = self._apply(payload)
        self.assertEqual(report["status"], "OK")
        with self.sm() as db:
            row = db.query(HsRate).filter(HsRate.hs_code == "8471300000").first()
            self.assertIsNotNone(row)
            self.assertEqual(row.hs_prefix, "8471300000")
            self.assertNotEqual(row.hs_prefix, "8471")

    def test_exact_row_with_autofilled_prefix_cleared(self) -> None:
        # _normalize_rate_row авто-заполняет hs_prefix=hs_code[:4]; importer должен очистить.
        payload = _official_bundle_payload(
            rates=[{"hs_code": "8471300000", "hs_prefix": "8471", "duty_rate": "5%"}]
        )
        report = self._apply(payload)
        self.assertEqual(report["status"], "OK")
        with self.sm() as db:
            row = db.query(HsRate).filter(HsRate.hs_code == "8471300000").first()
            self.assertEqual(row.hs_prefix, "8471300000")

    def test_sibling_not_covered_official_by_exact_row(self) -> None:
        from app.services.payment_data_coverage import diagnose_duty_rates

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self.sm() as db:
            db.add(
                SourceStatus(
                    source_code="EEC_ETT",
                    source_name="EEC ETT",
                    source_url="https://eec.eaeunion.org/",
                    revision="ett:2026-05-01",
                    synced_at=now,
                    is_stale=False,
                )
            )
            # Каталог: 2 sibling-кода под 8471, импортируем official только один из них.
            for code in ("8471300000", "8471900000"):
                db.add(TnvedEntry(hs_code=code, level=10, title=code))
            db.commit()

        payload = _official_bundle_payload(
            rates=[{"hs_code": "8471300000", "duty_rate": "5%"}]
        )
        report = self._apply(payload)
        self.assertEqual(report["status"], "OK")

        with self.sm() as db:
            lookup = {
                (r.hs_code, r.hs_prefix)
                for r in db.query(HsRate).all()
            }
        self.assertIn(("8471300000", "8471300000"), lookup)
        # Sibling не покрыт official: full official coverage не достигнут → not present.
        duty = diagnose_duty_rates()
        self.assertNotEqual(duty.status, "present")

    def test_explicit_prefix_rate_preserved(self) -> None:
        payload = _official_bundle_payload(
            rates=[{"hs_prefix": "8471", "duty_rate": "5%"}]
        )
        report = self._apply(payload)
        self.assertEqual(report["status"], "OK")
        with self.sm() as db:
            row = db.query(HsRate).filter(HsRate.hs_prefix == "8471").first()
            self.assertIsNotNone(row)
            self.assertEqual(row.hs_prefix, "8471")

    def test_explicit_prefix_scope_flag_keeps_prefix(self) -> None:
        payload = _official_bundle_payload(
            rates=[{"hs_code": "8471300000", "hs_prefix": "8471", "prefix_scope": True, "duty_rate": "5%"}]
        )
        report = self._apply(payload)
        self.assertEqual(report["status"], "OK")
        with self.sm() as db:
            row = db.query(HsRate).filter(HsRate.hs_code == "8471300000").first()
            self.assertEqual(row.hs_prefix, "8471")


class TestImportDutyStalePrefixUpdate(unittest.TestCase):
    """P1: stale broad hs_prefix должен обновляться на exact full code при re-import."""

    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def _dry_run(self, payload: dict) -> dict:
        import app.services.import_duty_ingestion as idi

        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(idi, "_BACKEND_ROOT", root):
                return run_import_duty_dry_run(rel_path=rel)

    def _apply(self, payload: dict) -> dict:
        import app.services.import_duty_ingestion as idi

        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(idi, "_BACKEND_ROOT", root):
                return run_import_duty_apply(rel_path=rel)

    def _seed_stale_broad_prefix_row(self) -> None:
        with self.sm() as db:
            db.add(
                HsRate(
                    hs_code="8471300000",
                    hs_prefix="8471",
                    duty_rate="5%",
                    vat_import_rate=22.0,
                    source_revision="ett:2026-05-01",
                    source_url="https://eec.eaeunion.org/comission/department/catr/ett/",
                )
            )
            db.commit()

    def test_dry_run_shows_update_for_prefix_only_change(self) -> None:
        self._seed_stale_broad_prefix_row()
        payload = _official_bundle_payload(
            rates=[{"hs_code": "8471300000", "duty_rate": "5%"}]
        )
        before = _table_counts(self.sm)
        report = self._dry_run(payload)
        after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertFalse(report["db_mutated"])
        self.assertEqual(report["row_counts"]["update"], 1)
        self.assertEqual(report["row_counts"]["skip"], 0)

    def test_apply_updates_stale_broad_prefix_to_exact(self) -> None:
        self._seed_stale_broad_prefix_row()
        payload = _official_bundle_payload(
            rates=[{"hs_code": "8471300000", "duty_rate": "5%"}]
        )
        report = self._apply(payload)
        self.assertEqual(report["status"], "OK")
        self.assertTrue(report["db_mutated"])
        self.assertGreaterEqual(report["row_counts"]["update"], 1)
        with self.sm() as db:
            row = db.query(HsRate).filter(HsRate.hs_code == "8471300000").first()
            self.assertEqual(row.hs_prefix, "8471300000")

    def test_sibling_not_covered_after_prefix_fix(self) -> None:
        from app.services.payment_data_coverage import diagnose_duty_rates

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self.sm() as db:
            db.add(
                SourceStatus(
                    source_code="EEC_ETT",
                    source_name="EEC ETT",
                    source_url="https://eec.eaeunion.org/",
                    revision="ett:2026-05-01",
                    synced_at=now,
                    is_stale=False,
                )
            )
            for code in ("8471300000", "8471900000"):
                db.add(TnvedEntry(hs_code=code, level=10, title=code))
            db.add(
                HsRate(
                    hs_code="8471300000",
                    hs_prefix="8471",
                    duty_rate="5%",
                    vat_import_rate=22.0,
                    source_revision="ett:2026-05-01",
                    source_url="https://eec.eaeunion.org/comission/department/catr/ett/",
                )
            )
            db.commit()
        payload = _official_bundle_payload(
            rates=[{"hs_code": "8471300000", "duty_rate": "5%"}]
        )
        report = self._apply(payload)
        self.assertEqual(report["status"], "OK")
        with self.sm() as db:
            row = db.query(HsRate).filter(HsRate.hs_code == "8471300000").one()
            self.assertEqual(row.hs_prefix, "8471300000")
        duty = diagnose_duty_rates()
        self.assertNotEqual(duty.status, "present")

    def test_exact_prefix_already_correct_skips(self) -> None:
        with self.sm() as db:
            db.add(
                HsRate(
                    hs_code="8471300000",
                    hs_prefix="8471300000",
                    duty_rate="5%",
                    vat_import_rate=22.0,
                    source_revision="ett:2026-05-01",
                    source_url="https://eec.eaeunion.org/comission/department/catr/ett/",
                )
            )
            db.commit()
        payload = _official_bundle_payload(
            rates=[{"hs_code": "8471300000", "duty_rate": "5%"}]
        )
        report = self._dry_run(payload)
        self.assertEqual(report["row_counts"]["update"], 0)
        self.assertEqual(report["row_counts"]["skip"], 1)


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
