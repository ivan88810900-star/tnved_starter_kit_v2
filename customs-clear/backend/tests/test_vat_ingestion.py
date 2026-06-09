"""Тесты official VAT ingestion (issue #39)."""

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
from app.services.normative_store import init_db
from app.services.payment_data_coverage import (
    diagnose_duty_rates,
    diagnose_vat_rates,
    run_payment_data_coverage_report,
)
from app.services.payment_data_normalization import normalize_vat, run_payment_data_normalization_report
from app.services.vat_ingestion import run_vat_apply, run_vat_dry_run

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


def _seed_hs_rates_for_bundle(sm: sessionmaker, *, duty_revision: str = "seed-2026-03") -> None:
    """Существующие hs_rates для кодов из default VAT bundle (без VAT insert path)."""
    with sm() as db:
        for code, prefix, duty in (
            ("3004909200", "3004", "5%"),
            ("8471300000", "8471", "10%"),
        ):
            db.add(
                HsRate(
                    hs_code=code,
                    hs_prefix=prefix,
                    duty_rate=duty,
                    vat_import_rate=22.0,
                    vat_rule="none",
                    source_revision=duty_revision,
                    source_url="seed://local",
                )
            )
        db.commit()


def _official_vat_bundle_payload(*, revision: str = "ett:2026-05-01", rates: list[dict] | None = None) -> dict:
    return {
        "format": "customs_clear_normative_bundle",
        "revision": revision,
        "effective_from": "2026-01-01",
        "official_ett_url": "https://eec.eaeunion.org/comission/department/catr/ett/",
        "rates": rates
        or [
            {"hs_code": "3004909200", "hs_prefix": "3004", "vat_import_rate": 10, "vat_rule": "reduced10"},
            {"hs_code": "8471300000", "hs_prefix": "8471", "vat_import_rate": 22, "vat_rule": "none"},
        ],
    }


class _BundleFixture:
    def __init__(self, payload: dict, rel_path: str = "data/raw_normative/eec_ett_vat.json"):
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


class TestVatMissingSource(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)
        import app.services.vat_ingestion as vi

        self._root_patch = unittest.mock.patch.object(vi, "_BACKEND_ROOT", Path("/nonexistent"))
        self._root_patch.start()

    def tearDown(self) -> None:
        self._root_patch.stop()
        _stop_patches(*self._patches)

    def test_dry_run_missing_official_source(self) -> None:
        before = _table_counts(self.sm)
        report = run_vat_dry_run()
        after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "missing_official_source")
        self.assertTrue(report["dry_run"])
        self.assertFalse(report["db_mutated"])

    def test_apply_missing_official_source_no_provenance(self) -> None:
        before = _table_counts(self.sm)
        report = run_vat_apply()
        after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "missing_official_source")
        self.assertFalse(report["db_mutated"])
        self.assertEqual(after["source_status"], 0)
        self.assertEqual(after["sync_log"], 0)


class TestVatDryRunNoMutation(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_dry_run_does_not_mutate_db(self) -> None:
        import app.services.vat_ingestion as vi

        _seed_hs_rates_for_bundle(self.sm)
        with _BundleFixture(_official_vat_bundle_payload()) as (root, rel):
            with unittest.mock.patch.object(vi, "_BACKEND_ROOT", root):
                before = _table_counts(self.sm)
                report = run_vat_dry_run(rel_path=rel)
                after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "OK")
        self.assertTrue(report["dry_run"])
        self.assertFalse(report["db_mutated"])
        self.assertEqual(report["row_counts"]["insert"], 0)
        self.assertGreater(report["row_counts"]["update"], 0)


class TestVatBlockedBundles(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def _run_blocked(self, payload: dict) -> dict:
        import app.services.vat_ingestion as vi

        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(vi, "_BACKEND_ROOT", root):
                return run_vat_apply(rel_path=rel)

    def test_seed_bundle_revision_blocks_import(self) -> None:
        report = self._run_blocked(_official_vat_bundle_payload(revision="seed-2026-03"))
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])
        self.assertEqual(_table_counts(self.sm)["source_status"], 0)

    def test_example_bundle_revision_blocks_import(self) -> None:
        report = self._run_blocked(_official_vat_bundle_payload(revision="example-2026-03"))
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])

    def test_explicit_seed_row_revision_blocks_import(self) -> None:
        payload = _official_vat_bundle_payload(
            rates=[
                {
                    "hs_code": "3004909200",
                    "vat_import_rate": 10,
                    "vat_rule": "reduced10",
                    "source_revision": "seed-2026-03",
                },
            ]
        )
        report = self._run_blocked(payload)
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])

    def test_duty_only_rows_no_importable_vat(self) -> None:
        payload = _official_vat_bundle_payload(
            rates=[{"hs_code": "8471300000", "duty_rate": "5%"}]
        )
        report = self._run_blocked(payload)
        self.assertNotEqual(report["status"], "OK")
        self.assertFalse(report["db_mutated"])
        self.assertTrue(any("no_importable_vat_rows" in b for b in report["blockers"]))


class TestVatApplyOfficial(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_apply_imports_official_vat_with_provenance(self) -> None:
        import app.services.vat_ingestion as vi

        _seed_hs_rates_for_bundle(self.sm, duty_revision="ett:2026-05-01")
        with _BundleFixture(_official_vat_bundle_payload()) as (root, rel):
            with unittest.mock.patch.object(vi, "_BACKEND_ROOT", root):
                report = run_vat_apply(rel_path=rel)

        self.assertEqual(report["status"], "OK")
        self.assertTrue(report["db_mutated"])
        self.assertEqual(report["provenance"]["revision"], "ett:2026-05-01")
        self.assertEqual(report["provenance"]["source_code"], "EEC_VAT")

        with self.sm() as db:
            row = db.query(HsRate).filter(HsRate.hs_code == "3004909200").first()
            self.assertIsNotNone(row)
            # P1 #2: duty provenance не перезаписывается VAT slice.
            self.assertEqual(row.source_revision, "ett:2026-05-01")
            self.assertEqual(row.vat_rule, "reduced10")
            self.assertEqual(float(row.vat_import_rate), 10.0)
            self.assertEqual(row.duty_rate, "5%")
            st = db.query(SourceStatus).filter(SourceStatus.source_code == "EEC_VAT").first()
            self.assertIsNotNone(st)
            logs = db.query(SyncLog).filter(SyncLog.source_code == "EEC_VAT").all()
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0].status, "OK")

    def test_blank_row_revision_does_not_create_hs_rate(self) -> None:
        import app.services.vat_ingestion as vi

        payload = _official_vat_bundle_payload(
            rates=[
                {
                    "hs_code": "9401300000",
                    "vat_import_rate": 10,
                    "vat_rule": "reduced10",
                    "source_revision": "",
                }
            ]
        )
        before = _table_counts(self.sm)
        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(vi, "_BACKEND_ROOT", root):
                report = run_vat_apply(rel_path=rel)
        after = _table_counts(self.sm)
        self.assertEqual(before["hs_rates"], after["hs_rates"])
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])
        with self.sm() as db:
            self.assertIsNone(db.query(HsRate).filter(HsRate.hs_code == "9401300000").first())

    def test_apply_updates_seed_row_vat_only(self) -> None:
        import app.services.vat_ingestion as vi

        with self.sm() as db:
            db.add(
                HsRate(
                    hs_code="3004909200",
                    hs_prefix="3004",
                    duty_rate="7%",
                    vat_import_rate=22.0,
                    vat_rule="none",
                    source_revision="seed-2026-03",
                    source_url="seed://local",
                )
            )
            db.commit()

        payload = _official_vat_bundle_payload(
            rates=[{"hs_code": "3004909200", "vat_import_rate": 10, "vat_rule": "reduced10"}]
        )
        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(vi, "_BACKEND_ROOT", root):
                report = run_vat_apply(rel_path=rel)

        self.assertEqual(report["status"], "OK")
        with self.sm() as db:
            row = db.query(HsRate).filter(HsRate.hs_code == "3004909200").first()
            self.assertEqual(row.source_revision, "seed-2026-03")
            self.assertEqual(row.source_url, "seed://local")
            self.assertEqual(row.vat_rule, "reduced10")
            self.assertEqual(row.duty_rate, "7%")

    def test_blocked_apply_no_source_status_or_sync_log(self) -> None:
        import app.services.vat_ingestion as vi

        payload = _official_vat_bundle_payload(revision="fallback-2026")
        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(vi, "_BACKEND_ROOT", root):
                report = run_vat_apply(rel_path=rel)
        self.assertEqual(report["status"], "manual_review_required")
        with self.sm() as db:
            self.assertEqual(db.query(SourceStatus).count(), 0)
            self.assertEqual(db.query(SyncLog).count(), 0)


class _RawBundleFixture:
    def __init__(self, raw_text: str, rel_path: str = "data/raw_normative/eec_ett_vat.json"):
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


class TestVatParserFailures(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def _apply(self, raw: str) -> dict:
        import app.services.vat_ingestion as vi

        with _RawBundleFixture(raw) as (root, rel):
            with unittest.mock.patch.object(vi, "_BACKEND_ROOT", root):
                return run_vat_apply(rel_path=rel)

    def test_invalid_json_apply_no_mutation(self) -> None:
        before = _table_counts(self.sm)
        report = self._apply("{ not valid json")
        after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "parser_failed")
        self.assertFalse(report["db_mutated"])
        with self.sm() as db:
            self.assertEqual(db.query(SyncLog).filter(SyncLog.status == "OK").count(), 0)

    def test_malformed_rates_container(self) -> None:
        payload = json.dumps(
            {"format": "customs_clear_normative_bundle", "revision": "ett:2026-01-01", "rates": 123}
        )
        report = self._apply(payload)
        self.assertEqual(report["status"], "parser_failed")
        self.assertFalse(report["db_mutated"])


class TestVatMissingSourceUrl(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def _apply(self, payload: dict) -> dict:
        import app.services.vat_ingestion as vi

        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(vi, "_BACKEND_ROOT", root):
                return run_vat_apply(rel_path=rel)

    def test_missing_source_url_blocks(self) -> None:
        payload = {
            "format": "customs_clear_normative_bundle",
            "revision": "ett:2026-05-01",
            "rates": [{"hs_code": "3004909200", "vat_import_rate": 10, "vat_rule": "reduced10"}],
        }
        report = self._apply(payload)
        self.assertNotEqual(report["status"], "OK")
        self.assertTrue(any("source_url" in b for b in report["blockers"]))
        with self.sm() as db:
            self.assertEqual(db.query(SyncLog).count(), 0)


class TestVatNoInsertZeroDutyRows(unittest.TestCase):
    """P1 #1: VAT apply не создаёт hs_rates с duty_rate=0 для отсутствующих кодов."""

    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_missing_hs_code_not_inserted_on_apply(self) -> None:
        import app.services.vat_ingestion as vi

        payload = _official_vat_bundle_payload(
            rates=[{"hs_code": "9999999999", "vat_import_rate": 10, "vat_rule": "reduced10"}]
        )
        before = _table_counts(self.sm)
        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(vi, "_BACKEND_ROOT", root):
                dry = run_vat_dry_run(rel_path=rel)
                report = run_vat_apply(rel_path=rel)
        after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertEqual(dry["row_counts"]["insert"], 0)
        self.assertGreaterEqual(dry["row_counts"]["blocked"], 1)
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])
        with self.sm() as db:
            self.assertEqual(db.query(HsRate).count(), 0)
            self.assertEqual(db.query(SyncLog).filter(SyncLog.status == "OK").count(), 0)

    def test_all_rows_missing_no_ok_provenance(self) -> None:
        import app.services.vat_ingestion as vi

        with _BundleFixture(_official_vat_bundle_payload()) as (root, rel):
            with unittest.mock.patch.object(vi, "_BACKEND_ROOT", root):
                report = run_vat_apply(rel_path=rel)
        self.assertEqual(report["status"], "manual_review_required")
        with self.sm() as db:
            self.assertEqual(db.query(SourceStatus).count(), 0)
            self.assertEqual(db.query(SyncLog).filter(SyncLog.status == "OK").count(), 0)
            for row in db.query(HsRate).all():
                self.assertNotEqual(row.duty_rate, "0")


class TestVatAtomicApply(unittest.TestCase):
    """P1: blocked apply атомарен — без partial commit при missing_hs_rate."""

    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_mixed_existing_and_missing_rows_no_partial_mutation(self) -> None:
        import app.services.vat_ingestion as vi

        with self.sm() as db:
            db.add(
                HsRate(
                    hs_code="3004909200",
                    hs_prefix="3004",
                    duty_rate="5%",
                    vat_import_rate=22.0,
                    vat_rule="none",
                    source_revision="seed-2026-03",
                )
            )
            db.commit()

        payload = _official_vat_bundle_payload(
            rates=[
                {"hs_code": "3004909200", "vat_import_rate": 10, "vat_rule": "reduced10"},
                {"hs_code": "9999999999", "vat_import_rate": 10, "vat_rule": "reduced10"},
            ]
        )
        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(vi, "_BACKEND_ROOT", root):
                dry = run_vat_dry_run(rel_path=rel)
                report = run_vat_apply(rel_path=rel)

        self.assertEqual(dry["row_counts"]["blocked"], 1)
        self.assertTrue(any("missing_hs_rate: 9999999999" in b for b in dry["blockers"]))
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])
        with self.sm() as db:
            row = db.query(HsRate).filter(HsRate.hs_code == "3004909200").one()
            self.assertEqual(float(row.vat_import_rate), 22.0)
            self.assertEqual(row.vat_rule, "none")
            self.assertIsNone(db.query(HsRate).filter(HsRate.hs_code == "9999999999").first())
            self.assertEqual(db.query(SourceStatus).count(), 0)
            self.assertEqual(db.query(SyncLog).filter(SyncLog.status == "OK").count(), 0)

    def test_apply_vat_rows_not_called_when_plan_has_blockers(self) -> None:
        import app.services.vat_ingestion as vi

        with self.sm() as db:
            db.add(
                HsRate(
                    hs_code="3004909200",
                    hs_prefix="3004",
                    duty_rate="5%",
                    vat_import_rate=22.0,
                    vat_rule="none",
                    source_revision="seed",
                )
            )
            db.commit()

        payload = _official_vat_bundle_payload(
            rates=[
                {"hs_code": "3004909200", "vat_import_rate": 10, "vat_rule": "reduced10"},
                {"hs_code": "9999999999", "vat_import_rate": 10, "vat_rule": "reduced10"},
            ]
        )
        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(vi, "_BACKEND_ROOT", root):
                with unittest.mock.patch.object(vi, "_apply_vat_rows") as mock_apply:
                    report = run_vat_apply(rel_path=rel)
        mock_apply.assert_not_called()
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])

    def test_all_existing_rows_apply_ok(self) -> None:
        import app.services.vat_ingestion as vi

        _seed_hs_rates_for_bundle(self.sm)
        with _BundleFixture(_official_vat_bundle_payload()) as (root, rel):
            with unittest.mock.patch.object(vi, "_BACKEND_ROOT", root):
                report = run_vat_apply(rel_path=rel)
        self.assertEqual(report["status"], "OK")
        self.assertTrue(report["db_mutated"])
        with self.sm() as db:
            self.assertEqual(db.query(SyncLog).filter(SyncLog.status == "OK").count(), 1)


class TestVatExplicitZeroRate(unittest.TestCase):
    """P2: explicit zero VAT rate (0 / "0") не теряется из-за truthy fallback."""

    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_zero_numeric_rate_dry_run_counts_update(self) -> None:
        import app.services.vat_ingestion as vi

        with self.sm() as db:
            db.add(
                HsRate(
                    hs_code="3004909200",
                    hs_prefix="3004",
                    duty_rate="5%",
                    vat_import_rate=22.0,
                    vat_rule="none",
                    source_revision="seed",
                )
            )
            db.commit()

        payload = _official_vat_bundle_payload(
            rates=[{"hs_code": "3004909200", "vat_import_rate": 0, "vat_rule": "zero"}]
        )
        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(vi, "_BACKEND_ROOT", root):
                dry = run_vat_dry_run(rel_path=rel)
        self.assertEqual(dry["row_counts"]["update"], 1)

    def test_zero_numeric_rate_apply_sets_zero(self) -> None:
        import app.services.vat_ingestion as vi

        with self.sm() as db:
            db.add(
                HsRate(
                    hs_code="3004909200",
                    hs_prefix="3004",
                    duty_rate="5%",
                    vat_import_rate=22.0,
                    vat_rule="none",
                    source_revision="seed",
                )
            )
            db.commit()

        payload = _official_vat_bundle_payload(
            rates=[{"hs_code": "3004909200", "vat_import_rate": 0, "vat_rule": "zero"}]
        )
        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(vi, "_BACKEND_ROOT", root):
                report = run_vat_apply(rel_path=rel)
        self.assertEqual(report["status"], "OK")
        with self.sm() as db:
            row = db.query(HsRate).filter(HsRate.hs_code == "3004909200").one()
            self.assertEqual(float(row.vat_import_rate), 0.0)
            self.assertEqual(row.vat_rule, "zero")

    def test_zero_string_rate_apply_sets_zero(self) -> None:
        import app.services.vat_ingestion as vi

        with self.sm() as db:
            db.add(
                HsRate(
                    hs_code="8471300000",
                    hs_prefix="8471",
                    duty_rate="10%",
                    vat_import_rate=22.0,
                    vat_rule="none",
                    source_revision="seed",
                )
            )
            db.commit()

        payload = _official_vat_bundle_payload(
            rates=[{"hs_code": "8471300000", "vat_import_rate": "0", "vat_rule": "zero"}]
        )
        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(vi, "_BACKEND_ROOT", root):
                report = run_vat_apply(rel_path=rel)
        self.assertEqual(report["status"], "OK")
        with self.sm() as db:
            row = db.query(HsRate).filter(HsRate.hs_code == "8471300000").one()
            self.assertEqual(float(row.vat_import_rate), 0.0)


class TestVatPreserveDutyProvenance(unittest.TestCase):
    """P1 #2: VAT apply не перезаписывает import-duty provenance и duty_rate."""

    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_seed_duty_provenance_unchanged_after_vat_apply(self) -> None:
        import app.services.vat_ingestion as vi

        with self.sm() as db:
            db.add(
                HsRate(
                    hs_code="8471300000",
                    hs_prefix="8471",
                    duty_rate="12%",
                    vat_import_rate=22.0,
                    vat_rule="none",
                    source_revision="seed-2026-03",
                    source_url="seed://duty",
                )
            )
            db.commit()

        payload = _official_vat_bundle_payload(
            rates=[{"hs_code": "8471300000", "vat_import_rate": 22, "vat_rule": "none"}]
        )
        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(vi, "_BACKEND_ROOT", root):
                report = run_vat_apply(rel_path=rel)
        self.assertEqual(report["status"], "OK")
        with self.sm() as db:
            row = db.query(HsRate).filter(HsRate.hs_code == "8471300000").one()
            self.assertEqual(row.source_revision, "seed-2026-03")
            self.assertEqual(row.source_url, "seed://duty")
            self.assertEqual(row.duty_rate, "12%")
        duty = diagnose_duty_rates()
        self.assertNotEqual(duty.status, "present")

    def test_official_duty_provenance_unchanged_after_vat_apply(self) -> None:
        import app.services.vat_ingestion as vi
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self.sm() as db:
            db.add(
                SourceStatus(
                    source_code="EEC_ETT",
                    source_name="EEC",
                    source_url="https://eec.eaeunion.org/",
                    revision="ett:2026-05-01",
                    synced_at=now,
                    is_stale=False,
                )
            )
            db.add(
                HsRate(
                    hs_code="3004909200",
                    hs_prefix="3004",
                    duty_rate="8%",
                    vat_import_rate=22.0,
                    vat_rule="none",
                    source_revision="ett:2026-05-01",
                    source_url="https://eec.eaeunion.org/duty",
                )
            )
            db.commit()

        payload = _official_vat_bundle_payload(
            rates=[{"hs_code": "3004909200", "vat_import_rate": 10, "vat_rule": "reduced10"}]
        )
        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(vi, "_BACKEND_ROOT", root):
                report = run_vat_apply(rel_path=rel)
        self.assertEqual(report["status"], "OK")
        with self.sm() as db:
            row = db.query(HsRate).filter(HsRate.hs_code == "3004909200").one()
            self.assertEqual(row.source_revision, "ett:2026-05-01")
            self.assertEqual(row.source_url, "https://eec.eaeunion.org/duty")
            self.assertEqual(row.duty_rate, "8%")
            self.assertEqual(row.vat_rule, "reduced10")


class TestVatCoverageAfterImport(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_official_vat_seen_in_coverage_and_normalization(self) -> None:
        import app.services.vat_ingestion as vi

        _seed_hs_rates_for_bundle(self.sm, duty_revision="seed-2026-03")
        with _BundleFixture(_official_vat_bundle_payload()) as (root, rel):
            with unittest.mock.patch.object(vi, "_BACKEND_ROOT", root):
                report = run_vat_apply(rel_path=rel)
        self.assertEqual(report["status"], "OK")

        vat_cov = diagnose_vat_rates()
        self.assertEqual(vat_cov.status, "present")
        self.assertFalse(vat_cov.manual_review_required)

        duty_cov = diagnose_duty_rates()
        self.assertNotEqual(duty_cov.status, "present")

        norm = run_payment_data_normalization_report()
        self.assertEqual(norm["domains"]["vat"]["coverage_status"], "present")

        cov = run_payment_data_coverage_report()
        self.assertEqual(cov["summary"]["vat_rates"]["status"], "present")

    def test_seed_vat_not_present_in_coverage(self) -> None:
        with self.sm() as db:
            db.add(
                HsRate(
                    hs_code="3004909200",
                    hs_prefix="3004",
                    duty_rate="0%",
                    vat_import_rate=10.0,
                    vat_rule="reduced10",
                    source_revision="seed-2026-03",
                )
            )
            db.add(
                VatPreference(
                    hs_code_prefix="3004",
                    vat_rate=10,
                    decree_info="TEST",
                )
            )
            db.commit()

        vat_cov = diagnose_vat_rates()
        self.assertNotEqual(vat_cov.status, "present")
        vat_norm = normalize_vat()
        self.assertNotEqual(vat_norm.coverage_status, "present")


@unittest.skipUnless(_API_OK, "fastapi not installed")
class TestVatApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        cls.client = TestClient(app)

    def test_dry_run_endpoint(self) -> None:
        r = self.client.post("/api/sources/payment-ingestion/vat/dry-run")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn(body["status"], ("OK", "missing_official_source", "manual_review_required"))
        self.assertTrue(body["dry_run"])
        self.assertFalse(body["db_mutated"])

    def test_apply_endpoint_requires_admin(self) -> None:
        r = self.client.post("/api/sources/payment-ingestion/vat/apply")
        self.assertIn(r.status_code, (401, 403))


if __name__ == "__main__":
    unittest.main()
