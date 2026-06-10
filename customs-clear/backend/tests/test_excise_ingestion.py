"""Тесты official excise ingestion (issue #42)."""

from __future__ import annotations

import json
import unittest
import unittest.mock
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.main import app
from app.models.core import ExchangeRate, GeoSpecialDuty, HsRate, SourceStatus, SyncLog, TnvedEntry
from app.models.tnved import Chapter, Commodity, HsDutyRule, Section, SpecialDuty, VatPreference
from app.services.excise_ingestion import run_excise_apply, run_excise_dry_run
from app.services.normative_store import init_db
from app.services.payment_data_coverage import (
    diagnose_duty_rates,
    diagnose_excise,
    diagnose_vat_rates,
    run_payment_data_coverage_report,
)
from app.services.payment_data_normalization import normalize_excise, run_payment_data_normalization_report

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


def _seed_hs_rates_for_bundle(sm: sessionmaker, *, duty_revision: str = "seed-2026-03") -> None:
    with sm() as db:
        for code, prefix, duty in (
            ("2203009900", "2203", "0%"),
            ("2402209000", "2402", "5%"),
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


def _official_excise_bundle_payload(*, revision: str = "excise:2026-05-01", rates: list[dict] | None = None) -> dict:
    return {
        "format": "customs_clear_normative_bundle",
        "revision": revision,
        "effective_from": "2026-01-01",
        "official_excise_url": "https://www.nalog.gov.ru/rn77/about_fts/docs/12345678",
        "rates": rates
        or [
            {
                "hs_code": "2203009900",
                "hs_prefix": "2203",
                "excise_type": "percent",
                "excise_value": 5.0,
                "excise_basis": "НК РФ ст. 193",
            },
            {
                "hs_code": "2402209000",
                "hs_prefix": "2402",
                "excise_type": "fixed",
                "excise_value": 2800.0,
                "excise_basis": "НК РФ ст. 193 табак",
            },
        ],
    }


class _BundleFixture:
    def __init__(self, payload: dict, rel_path: str = "data/raw_normative/eec_excise.json"):
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
        self.assertEqual(report["row_counts"]["insert"], 0)
        self.assertGreater(report["row_counts"]["update"], 0)


class TestExciseApplyOfficial(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_apply_imports_official_excise_with_provenance(self) -> None:
        import app.services.excise_ingestion as ei

        _seed_hs_rates_for_bundle(self.sm, duty_revision="ett:2026-05-01")
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

    def test_preserve_duty_and_vat_provenance(self) -> None:
        import app.services.excise_ingestion as ei

        with self.sm() as db:
            db.add(
                HsRate(
                    hs_code="2203009900",
                    hs_prefix="2203",
                    duty_rate="7%",
                    vat_import_rate=10.0,
                    vat_rule="reduced10",
                    source_revision="seed-2026-03",
                    source_url="seed://duty",
                    vat_source_code="EEC_VAT",
                    vat_source_revision="vat:2026-05-01",
                    vat_source_url="https://eec.eaeunion.org/",
                )
            )
            db.commit()

        payload = _official_excise_bundle_payload(
            rates=[
                {
                    "hs_code": "2203009900",
                    "excise_type": "percent",
                    "excise_value": 5.0,
                    "excise_basis": "НК РФ",
                }
            ]
        )
        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(ei, "_BACKEND_ROOT", root):
                report = run_excise_apply(rel_path=rel)
        self.assertEqual(report["status"], "OK")
        with self.sm() as db:
            row = db.query(HsRate).filter(HsRate.hs_code == "2203009900").one()
            self.assertEqual(row.source_revision, "seed-2026-03")
            self.assertEqual(row.source_url, "seed://duty")
            self.assertEqual(row.duty_rate, "7%")
            self.assertEqual(row.vat_source_code, "EEC_VAT")
            self.assertEqual(row.vat_source_revision, "vat:2026-05-01")
            self.assertEqual(row.excise_source_code, "EEC_EXCISE")


class _RawBundleFixture:
    def __init__(self, raw_text: str, rel_path: str = "data/raw_normative/eec_excise.json"):
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
        with _RawBundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(ei, "_BACKEND_ROOT", root):
                report = run_excise_apply(rel_path=rel)
        self.assertEqual(report["status"], "parser_failed")
        self.assertFalse(report["db_mutated"])


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
            "rates": [
                {
                    "hs_code": "2203009900",
                    "excise_type": "percent",
                    "excise_value": 5.0,
                }
            ],
        }
        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(ei, "_BACKEND_ROOT", root):
                report = run_excise_apply(rel_path=rel)
        self.assertNotEqual(report["status"], "OK")
        self.assertTrue(any("source_url" in b for b in report["blockers"]))


class TestExciseAtomicApply(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_mixed_existing_and_missing_rows_no_partial_mutation(self) -> None:
        import app.services.excise_ingestion as ei

        with self.sm() as db:
            db.add(
                HsRate(
                    hs_code="2203009900",
                    hs_prefix="2203",
                    duty_rate="0%",
                    vat_import_rate=22.0,
                    source_revision="seed",
                )
            )
            db.commit()
            before_row = db.query(HsRate).filter(HsRate.hs_code == "2203009900").one()
            before_excise = (before_row.excise_type, before_row.excise_value)

        payload = _official_excise_bundle_payload()
        before = _table_counts(self.sm)
        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(ei, "_BACKEND_ROOT", root):
                report = run_excise_apply(rel_path=rel)
        after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])
        with self.sm() as db:
            row = db.query(HsRate).filter(HsRate.hs_code == "2203009900").one()
            self.assertEqual((row.excise_type, row.excise_value), before_excise)
            self.assertEqual(db.query(SourceStatus).count(), 0)


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

    def test_excise_revision_accepted(self) -> None:
        _seed_hs_rates_for_bundle(self.sm)
        report = self._apply(_official_excise_bundle_payload(revision="excise:2026-05-01"))
        self.assertEqual(report["status"], "OK")

    def test_vat_revision_rejected(self) -> None:
        report = self._apply(_official_excise_bundle_payload(revision="vat:2026-05-01"))
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])

    def test_ett_revision_rejected(self) -> None:
        report = self._apply(_official_excise_bundle_payload(revision="ett:2026-05-01"))
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])

    def test_non_official_revision_tokens_rejected(self) -> None:
        for revision in (
            "seed-2026-03",
            "fallback:2026",
            "demo-2026",
            "test-2026",
            "example-2026",
            "manual",
            "local-copy",
            "unknown",
            "",
        ):
            with self.subTest(revision=revision):
                report = self._apply(_official_excise_bundle_payload(revision=revision))
                self.assertNotEqual(report["status"], "OK")
                self.assertFalse(report["db_mutated"])

    def test_blank_row_revision_inherits_bundle_revision(self) -> None:
        _seed_hs_rates_for_bundle(self.sm)
        payload = _official_excise_bundle_payload(
            revision="excise:2026-06-01",
            rates=[
                {
                    "hs_code": "2203009900",
                    "excise_type": "percent",
                    "excise_value": 5.0,
                }
            ],
        )
        report = self._apply(payload)
        self.assertEqual(report["status"], "OK")
        with self.sm() as db:
            row = db.query(HsRate).filter(HsRate.hs_code == "2203009900").one()
            self.assertEqual(row.excise_source_revision, "excise:2026-06-01")

    def test_explicit_unsafe_row_revision_blocked(self) -> None:
        payload = _official_excise_bundle_payload(
            rates=[
                {
                    "hs_code": "2203009900",
                    "excise_type": "percent",
                    "excise_value": 5.0,
                    "source_revision": "manual",
                }
            ]
        )
        report = self._apply(payload)
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])


class TestExciseCoverageAfterImport(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_official_excise_seen_in_coverage_and_normalization(self) -> None:
        import app.services.excise_ingestion as ei

        _seed_hs_rates_for_bundle(self.sm)
        with _BundleFixture(_official_excise_bundle_payload()) as (root, rel):
            with unittest.mock.patch.object(ei, "_BACKEND_ROOT", root):
                report = run_excise_apply(rel_path=rel)
        self.assertEqual(report["status"], "OK")

        excise_cov = diagnose_excise()
        self.assertEqual(excise_cov.status, "present")
        self.assertFalse(excise_cov.manual_review_required)

        duty_cov = diagnose_duty_rates()
        self.assertNotEqual(duty_cov.status, "present")

        vat_cov = diagnose_vat_rates()
        self.assertNotEqual(vat_cov.status, "present")

        norm = run_payment_data_normalization_report()
        self.assertEqual(norm["domains"]["excise"]["coverage_status"], "present")

        cov = run_payment_data_coverage_report()
        self.assertEqual(cov["summary"]["excise"]["status"], "present")

    def test_seed_excise_not_present_without_row_marker(self) -> None:
        with self.sm() as db:
            db.add(
                HsRate(
                    hs_code="2203009900",
                    hs_prefix="2203",
                    duty_rate="0%",
                    vat_import_rate=22.0,
                    excise_type="percent",
                    excise_value=12.0,
                    source_revision="seed-2026-03",
                )
            )
            db.commit()

        excise_cov = diagnose_excise()
        self.assertNotEqual(excise_cov.status, "present")
        excise_norm = normalize_excise()
        self.assertNotEqual(excise_norm.coverage_status, "present")

    def test_global_excise_source_status_alone_not_present(self) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self.sm() as db:
            db.add(
                SourceStatus(
                    source_code="EEC_EXCISE",
                    source_name="EEC EXCISE",
                    source_url="https://www.nalog.gov.ru/",
                    revision="excise:2026-05-01",
                    synced_at=now,
                    is_stale=False,
                )
            )
            db.add(
                HsRate(
                    hs_code="2203009900",
                    hs_prefix="2203",
                    duty_rate="0%",
                    vat_import_rate=22.0,
                    excise_type="percent",
                    excise_value=12.0,
                    source_revision="seed",
                )
            )
            db.commit()

        excise_cov = diagnose_excise()
        self.assertNotEqual(excise_cov.status, "present")
        self.assertTrue(excise_cov.manual_review_required)


class TestExciseDomainIsolation(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_vat_bundle_rejected_for_excise(self) -> None:
        import app.services.excise_ingestion as ei

        payload = {
            "format": "customs_clear_normative_bundle",
            "revision": "vat:2026-05-01",
            "official_ett_url": "https://eec.eaeunion.org/",
            "rates": [{"hs_code": "2203009900", "vat_import_rate": 10, "vat_rule": "reduced10"}],
        }
        with _BundleFixture(payload, rel_path="data/raw_normative/eec_ett_vat.json") as (root, rel):
            with unittest.mock.patch.object(ei, "_BACKEND_ROOT", root):
                dry = run_excise_dry_run(rel_path=rel)
                report = run_excise_apply(rel_path=rel)
        self.assertNotEqual(dry["status"], "OK")
        self.assertNotEqual(report["status"], "OK")


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
