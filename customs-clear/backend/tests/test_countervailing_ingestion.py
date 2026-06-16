"""Тесты official countervailing ingestion (issue #49)."""

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
from app.models.core import ExchangeRate, GeoSpecialDuty, HsRate, SourceStatus, SyncLog, TnvedEntry
from app.models.tnved import Chapter, Commodity, HsDutyRule, Section, SpecialDuty, VatPreference
from app.services.anti_dumping_ingestion import (
    discover_anti_dumping_bundle_path,
    run_anti_dumping_apply,
)
from app.services.countervailing_ingestion import (
    discover_countervailing_bundle_path,
    run_countervailing_apply,
    run_countervailing_dry_run,
)
from app.services.import_duty_ingestion import discover_import_duty_bundle_path, run_import_duty_apply
from app.services.payment_data_coverage import diagnose_duty_rates, diagnose_trade_remedies, diagnose_vat_rates
from app.services.payment_data_normalization import (
    normalize_anti_dumping,
    normalize_countervailing,
    normalize_special_safeguard,
)
from app.services.special_safeguard_ingestion import (
    discover_special_safeguard_bundle_path,
    run_special_safeguard_apply,
)
from app.services.vat_ingestion import discover_vat_bundle_path, run_vat_apply

_TABLES = [
    Section.__table__,
    Chapter.__table__,
    Commodity.__table__,
    HsDutyRule.__table__,
    VatPreference.__table__,
    TnvedEntry.__table__,
    SpecialDuty.__table__,
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
        unittest.mock.patch("app.services.countervailing_ingestion.SessionLocal", sm),
        unittest.mock.patch("app.services.special_safeguard_ingestion.SessionLocal", sm),
        unittest.mock.patch("app.services.anti_dumping_ingestion.SessionLocal", sm),
        unittest.mock.patch("app.services.import_duty_ingestion.SessionLocal", sm),
        unittest.mock.patch("app.services.vat_ingestion.SessionLocal", sm),
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
            "special_duties": db.query(SpecialDuty).count(),
            "source_status": db.query(SourceStatus).count(),
            "sync_log": db.query(SyncLog).count(),
        }


def _official_countervailing_payload(
    *,
    revision: str = "countervailing:2026-05-01",
    official_url: str = "https://eec.eaeunion.org/comission/department/deptexsec/trade_remedies/",
    measures: list[dict] | None = None,
) -> dict:
    return {
        "format": "customs_clear_countervailing_bundle",
        "revision": revision,
        "effective_from": "2026-01-01",
        "official_url": official_url,
        "measures": measures
        or [
            {
                "hs_code": "7208510000",
                "hs_prefix": "7208",
                "origin_country": "IN",
                "measure_type": "countervailing",
                "rate_type": "percent",
                "rate_value": 11.5,
                "regulatory_act": "ЕЭК №801/2024",
                "product_description": "Прокат горячекатаный",
            },
            {
                "hs_prefix": "3901",
                "origin_country": "US",
                "measure_type": "countervailing",
                "rate_type": "percent",
                "rate_value": 8.0,
                "regulatory_act": "ЕЭК №802/2025",
            },
        ],
    }


class _BundleFixture:
    def __init__(self, payload: dict, rel_path: str = "data/raw_normative/eec_countervailing.json"):
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


class TestCountervailingMissingSource(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)
        import app.services.countervailing_ingestion as ci

        self._root_patch = unittest.mock.patch.object(ci, "_BACKEND_ROOT", Path("/nonexistent"))
        self._root_patch.start()

    def tearDown(self) -> None:
        self._root_patch.stop()
        _stop_patches(*self._patches)

    def test_dry_run_missing_official_source(self) -> None:
        before = _table_counts(self.sm)
        report = run_countervailing_dry_run()
        after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "missing_official_source")
        self.assertTrue(report["dry_run"])
        self.assertFalse(report["db_mutated"])

    def test_apply_missing_official_source_no_provenance(self) -> None:
        before = _table_counts(self.sm)
        report = run_countervailing_apply()
        after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "missing_official_source")
        self.assertFalse(report["db_mutated"])
        self.assertEqual(after["source_status"], 0)
        self.assertEqual(after["sync_log"], 0)


class TestCountervailingDryRunNoMutation(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_dry_run_does_not_mutate_db(self) -> None:
        import app.services.countervailing_ingestion as ci

        with _BundleFixture(_official_countervailing_payload()) as (root, rel):
            with unittest.mock.patch.object(ci, "_BACKEND_ROOT", root):
                before = _table_counts(self.sm)
                report = run_countervailing_dry_run(rel_path=rel)
                after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "OK")
        self.assertTrue(report["dry_run"])
        self.assertFalse(report["db_mutated"])
        self.assertGreater(report["row_counts"]["insert"], 0)


class TestCountervailingApplyProvenance(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_apply_writes_special_duties_with_provenance(self) -> None:
        import app.services.countervailing_ingestion as ci

        with _BundleFixture(_official_countervailing_payload()) as (root, rel):
            with unittest.mock.patch.object(ci, "_BACKEND_ROOT", root):
                report = run_countervailing_apply(rel_path=rel)
        self.assertEqual(report["status"], "OK")
        self.assertTrue(report["db_mutated"])
        self.assertEqual(report["provenance"]["source_code"], "EEC_COUNTERVAILING")
        with self.sm() as db:
            rows = db.query(SpecialDuty).filter(SpecialDuty.measure_type == "countervailing").all()
            self.assertEqual(len(rows), 2)
            for row in rows:
                self.assertEqual(row.countervailing_source_code, "EEC_COUNTERVAILING")
                self.assertEqual(row.countervailing_source_revision, "countervailing:2026-05-01")
                self.assertTrue(row.countervailing_source_url)
                self.assertIsNotNone(row.countervailing_synced_at)
                self.assertEqual(row.measure_type, "countervailing")
                self.assertEqual(row.source_code, "")
                self.assertEqual(row.source_revision, "")
                self.assertEqual(row.safeguard_source_code, "")
                self.assertEqual(row.safeguard_source_revision, "")
                self.assertIsNone(row.synced_at)
                self.assertIsNone(row.safeguard_synced_at)
            st = db.query(SourceStatus).filter(SourceStatus.source_code == "EEC_COUNTERVAILING").first()
            self.assertIsNotNone(st)
            logs = db.query(SyncLog).filter(SyncLog.source_code == "EEC_COUNTERVAILING").all()
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0].status, "OK")


class TestCountervailingRevisionValidation(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def _apply(self, payload: dict) -> dict:
        import app.services.countervailing_ingestion as ci

        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(ci, "_BACKEND_ROOT", root):
                return run_countervailing_apply(rel_path=rel)

    def test_official_revision_accepted(self) -> None:
        report = self._apply(_official_countervailing_payload(revision="countervailing:2026-05-01"))
        self.assertEqual(report["status"], "OK")
        self.assertTrue(report["db_mutated"])

    def test_eec_countervailing_revision_accepted(self) -> None:
        report = self._apply(_official_countervailing_payload(revision="eec-countervailing:2026-05-01"))
        self.assertEqual(report["status"], "OK")

    def test_eec_colon_countervailing_revision_accepted(self) -> None:
        report = self._apply(_official_countervailing_payload(revision="eec:countervailing:2026-05-01"))
        self.assertEqual(report["status"], "OK")

    def test_wrong_domain_duty_revision_rejected(self) -> None:
        report = self._apply(_official_countervailing_payload(revision="ett:2026-05-01"))
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])

    def test_wrong_domain_anti_dumping_revision_rejected(self) -> None:
        report = self._apply(_official_countervailing_payload(revision="anti-dumping:2026-05-01"))
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])

    def test_wrong_domain_special_safeguard_revision_rejected(self) -> None:
        report = self._apply(_official_countervailing_payload(revision="special-safeguard:2026-05-01"))
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])

    def test_non_official_revision_tokens_rejected(self) -> None:
        for revision in (
            "seed-2026-03",
            "fallback:2026",
            "legacy-2026",
            "demo-2026",
            "test-2026",
            "example-2026",
            "manual",
            "local-copy",
            "unknown",
            "",
        ):
            with self.subTest(revision=revision):
                report = self._apply(_official_countervailing_payload(revision=revision))
                self.assertNotEqual(report["status"], "OK")
                self.assertFalse(report["db_mutated"])

    def test_explicit_unsafe_row_revision_blocks(self) -> None:
        payload = _official_countervailing_payload(
            measures=[
                {
                    "hs_prefix": "7208",
                    "origin_country": "IN",
                    "rate_type": "percent",
                    "rate_value": 11.5,
                    "regulatory_act": "ЕЭК №801/2024",
                    "source_revision": "local-copy",
                }
            ]
        )
        before = _table_counts(self.sm)
        report = self._apply(payload)
        after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])


class TestCountervailingUnsafeUrls(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def _apply(self, payload: dict) -> dict:
        import app.services.countervailing_ingestion as ci

        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(ci, "_BACKEND_ROOT", root):
                return run_countervailing_apply(rel_path=rel)

    def test_unsafe_urls_blocked(self) -> None:
        for url in (
            "",
            "https://example.com/decision",
            "http://localhost/decision",
            "http://127.0.0.1/decision",
            "seed://local",
            "file:///tmp/decision",
            "manual",
            "local-copy",
        ):
            with self.subTest(url=url):
                before = _table_counts(self.sm)
                report = self._apply(_official_countervailing_payload(official_url=url))
                after = _table_counts(self.sm)
                self.assertEqual(before, after)
                self.assertNotEqual(report["status"], "OK")
                self.assertFalse(report["db_mutated"])

    def test_arbitrary_external_domain_rejected(self) -> None:
        for url in (
            "https://evil.ru/decision",
            "https://eec.eaeunion.org.attacker.com/decision",
            "https://fake-eaeunion.org/decision",
            "http://eec.eaeunion.org/decision",
        ):
            with self.subTest(url=url):
                before = _table_counts(self.sm)
                report = self._apply(_official_countervailing_payload(official_url=url))
                after = _table_counts(self.sm)
                self.assertEqual(before, after)
                self.assertNotEqual(report["status"], "OK")
                self.assertFalse(report["db_mutated"])

    def test_official_eaeunion_domain_accepted(self) -> None:
        report = self._apply(
            _official_countervailing_payload(
                official_url="https://eec.eaeunion.org/comission/department/deptexsec/trade_remedies/"
            )
        )
        self.assertEqual(report["status"], "OK")
        self.assertTrue(report["db_mutated"])


class TestCountervailingMalformedContainers(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def _apply(self, payload: dict) -> dict:
        import app.services.countervailing_ingestion as ci

        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(ci, "_BACKEND_ROOT", root):
                return run_countervailing_apply(rel_path=rel)

    def test_measures_scalar_parser_failed(self) -> None:
        payload = {
            "format": "customs_clear_countervailing_bundle",
            "revision": "countervailing:2026-05-01",
            "official_url": "https://eec.eaeunion.org/",
            "measures": 123,
        }
        report = self._apply(payload)
        self.assertEqual(report["status"], "parser_failed")
        self.assertFalse(report["db_mutated"])

    def test_non_object_rows_parser_failed(self) -> None:
        payload = {
            "format": "customs_clear_countervailing_bundle",
            "revision": "countervailing:2026-05-01",
            "official_url": "https://eec.eaeunion.org/",
            "measures": [123],
        }
        report = self._apply(payload)
        self.assertEqual(report["status"], "parser_failed")
        self.assertFalse(report["db_mutated"])


class TestCountervailingMixedApplyAtomic(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_one_blocked_row_blocks_entire_apply(self) -> None:
        import app.services.countervailing_ingestion as ci

        payload = _official_countervailing_payload(
            measures=[
                {
                    "hs_prefix": "7208",
                    "origin_country": "IN",
                    "rate_type": "percent",
                    "rate_value": 11.5,
                    "regulatory_act": "ЕЭК №801/2024",
                },
                {
                    "hs_prefix": "3901",
                    "origin_country": "US",
                    "rate_type": "percent",
                    "rate_value": 8.0,
                    "regulatory_act": "ЕЭК №802/2025",
                    "source_revision": "seed-2026",
                },
            ]
        )
        before = _table_counts(self.sm)
        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(ci, "_BACKEND_ROOT", root):
                report = run_countervailing_apply(rel_path=rel)
        after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])
        with self.sm() as db:
            self.assertEqual(db.query(SourceStatus).count(), 0)
            self.assertEqual(db.query(SyncLog).filter(SyncLog.status == "OK").count(), 0)


class TestCountervailingMeasureIdentity(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def _apply(self, payload: dict) -> dict:
        import app.services.countervailing_ingestion as ci

        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(ci, "_BACKEND_ROOT", root):
                return run_countervailing_apply(rel_path=rel)

    def test_different_manufacturer_creates_separate_rows(self) -> None:
        payload = _official_countervailing_payload(
            measures=[
                {
                    "hs_prefix": "7208",
                    "origin_country": "IN",
                    "measure_type": "countervailing",
                    "rate_type": "percent",
                    "rate_value": 11.5,
                    "regulatory_act": "ЕЭК №801/2024",
                    "manufacturer_exporter": "Alpha Steel Co",
                },
                {
                    "hs_prefix": "7208",
                    "origin_country": "IN",
                    "measure_type": "countervailing",
                    "rate_type": "percent",
                    "rate_value": 14.0,
                    "regulatory_act": "ЕЭК №801/2024",
                    "manufacturer_exporter": "Beta Metallurg LLC",
                },
            ]
        )
        report = self._apply(payload)
        self.assertEqual(report["status"], "OK")
        self.assertEqual(report["row_counts"]["insert"], 2)
        with self.sm() as db:
            rows = db.query(SpecialDuty).filter(SpecialDuty.hs_code_prefix == "7208").all()
            self.assertEqual(len(rows), 2)

    def test_reapply_is_idempotent(self) -> None:
        payload = _official_countervailing_payload()
        self._apply(payload)
        report2 = self._apply(payload)
        self.assertEqual(report2["status"], "OK")
        self.assertEqual(report2["row_counts"]["insert"], 0)
        self.assertEqual(report2["row_counts"]["update"], 0)
        self.assertEqual(report2["row_counts"]["skip"], 2)

    def test_different_effective_window_not_overwritten(self) -> None:
        payload = _official_countervailing_payload(
            measures=[
                {
                    "hs_prefix": "7208",
                    "origin_country": "IN",
                    "measure_type": "countervailing",
                    "rate_type": "percent",
                    "rate_value": 11.5,
                    "regulatory_act": "ЕЭК №801/2024",
                    "manufacturer_exporter": "Alpha Steel Co",
                    "effective_from": "2026-01-01",
                    "effective_to": "2026-06-30",
                },
                {
                    "hs_prefix": "7208",
                    "origin_country": "IN",
                    "measure_type": "countervailing",
                    "rate_type": "percent",
                    "rate_value": 13.0,
                    "regulatory_act": "ЕЭК №801/2024",
                    "manufacturer_exporter": "Alpha Steel Co",
                    "effective_from": "2026-07-01",
                    "effective_to": "2026-12-31",
                },
            ]
        )
        report = self._apply(payload)
        self.assertEqual(report["status"], "OK")
        self.assertEqual(report["row_counts"]["insert"], 2)
        with self.sm() as db:
            rows = db.query(SpecialDuty).filter(SpecialDuty.hs_code_prefix == "7208").all()
            self.assertEqual(len(rows), 2)


class TestCountervailingCoverageIsolation(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_global_source_status_alone_not_present(self) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self.sm() as db:
            db.add(
                SourceStatus(
                    source_code="EEC_COUNTERVAILING",
                    source_name="CV test",
                    source_url="https://eec.eaeunion.org/",
                    revision="countervailing:2026-05-01",
                    synced_at=now,
                    is_stale=False,
                )
            )
            db.commit()
        trade = diagnose_trade_remedies()
        self.assertNotEqual(trade.status, "present")
        cv = normalize_countervailing()
        self.assertNotEqual(cv.coverage_status, "present")

    def test_legacy_row_not_promoted_by_source_status(self) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self.sm() as db:
            db.add(
                SpecialDuty(
                    hs_code_prefix="7208",
                    origin_country="IN",
                    rate_percent=11.5,
                    regulatory_act="LEGACY-CV",
                    measure_type="countervailing",
                    countervailing_source_code="",
                    countervailing_source_revision="",
                )
            )
            db.add(
                SourceStatus(
                    source_code="EEC_COUNTERVAILING",
                    source_name="CV test",
                    source_url="https://eec.eaeunion.org/",
                    revision="countervailing:2026-05-01",
                    synced_at=now,
                    is_stale=False,
                )
            )
            db.commit()
        cv = normalize_countervailing()
        self.assertNotEqual(cv.coverage_status, "present")
        self.assertEqual(cv.normalized_snapshot.get("special_duties_official_rows", -1), 0)


class TestCountervailingTradeRemedyIsolation(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def _apply_countervailing(self, payload: dict | None = None) -> dict:
        import app.services.countervailing_ingestion as ci

        with _BundleFixture(payload or _official_countervailing_payload()) as (root, rel):
            with unittest.mock.patch.object(ci, "_BACKEND_ROOT", root):
                return run_countervailing_apply(rel_path=rel)

    def _apply_anti_dumping(self) -> dict:
        import app.services.anti_dumping_ingestion as adi

        ad_payload = {
            "format": "customs_clear_anti_dumping_bundle",
            "revision": "anti-dumping:2026-05-01",
            "official_url": "https://eec.eaeunion.org/",
            "measures": [
                {
                    "hs_prefix": "7214",
                    "origin_country": "CN",
                    "rate_type": "percent",
                    "rate_value": 18.0,
                    "regulatory_act": "ЕЭК №123/2024",
                }
            ],
        }
        with _BundleFixture(ad_payload, rel_path="data/raw_normative/eec_anti_dumping.json") as (root, rel):
            with unittest.mock.patch.object(adi, "_BACKEND_ROOT", root):
                return run_anti_dumping_apply(rel_path=rel)

    def _apply_special_safeguard(self) -> dict:
        import app.services.special_safeguard_ingestion as ssi

        ss_payload = {
            "format": "customs_clear_special_safeguard_bundle",
            "revision": "special-safeguard:2026-05-01",
            "official_url": "https://eec.eaeunion.org/",
            "measures": [
                {
                    "hs_prefix": "6403",
                    "origin_country": "CN",
                    "rate_type": "percent",
                    "rate_value": 12.0,
                    "regulatory_act": "ЕЭК №789/2024",
                }
            ],
        }
        with _BundleFixture(ss_payload, rel_path="data/raw_normative/eec_special_safeguard.json") as (root, rel):
            with unittest.mock.patch.object(ssi, "_BACKEND_ROOT", root):
                return run_special_safeguard_apply(rel_path=rel)

    def test_bundles_do_not_cross_discover(self) -> None:
        import app.services.countervailing_ingestion as ci

        cv_rel = "data/raw_normative/eec_countervailing.json"
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            full = root / cv_rel
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(json.dumps(_official_countervailing_payload()), encoding="utf-8")
            with unittest.mock.patch.object(ci, "_BACKEND_ROOT", root):
                self.assertEqual(discover_countervailing_bundle_path(rel_path=cv_rel), cv_rel)
                self.assertIsNone(discover_anti_dumping_bundle_path(rel_path=cv_rel))
                self.assertIsNone(discover_special_safeguard_bundle_path(rel_path=cv_rel))

    def test_countervailing_sync_does_not_change_anti_dumping_readiness(self) -> None:
        ad_before = normalize_anti_dumping().normalized_snapshot.get("special_duties_official_rows", 0)
        self._apply_countervailing()
        ad_after = normalize_anti_dumping()
        self.assertEqual(
            ad_after.normalized_snapshot.get("special_duties_official_rows", 0), ad_before
        )
        self.assertNotEqual(ad_after.coverage_status, "present")

    def test_countervailing_sync_does_not_change_special_safeguard_readiness(self) -> None:
        ss_before = normalize_special_safeguard().normalized_snapshot.get("special_duties_official_rows", 0)
        self._apply_countervailing()
        ss_after = normalize_special_safeguard()
        self.assertEqual(
            ss_after.normalized_snapshot.get("special_duties_official_rows", 0), ss_before
        )
        self.assertNotEqual(ss_after.coverage_status, "present")

    def test_anti_dumping_sync_does_not_change_countervailing_readiness(self) -> None:
        cv_before = normalize_countervailing().normalized_snapshot.get("special_duties_official_rows", 0)
        self._apply_anti_dumping()
        cv_after = normalize_countervailing()
        self.assertEqual(
            cv_after.normalized_snapshot.get("special_duties_official_rows", 0), cv_before
        )
        self.assertNotEqual(cv_after.coverage_status, "present")

    def test_special_safeguard_sync_does_not_change_countervailing_readiness(self) -> None:
        cv_before = normalize_countervailing().normalized_snapshot.get("special_duties_official_rows", 0)
        self._apply_special_safeguard()
        cv_after = normalize_countervailing()
        self.assertEqual(
            cv_after.normalized_snapshot.get("special_duties_official_rows", 0), cv_before
        )
        self.assertNotEqual(cv_after.coverage_status, "present")

    def test_trade_remedies_partial_even_with_all_official(self) -> None:
        ad_report = self._apply_anti_dumping()
        ss_report = self._apply_special_safeguard()
        cv_report = self._apply_countervailing()
        self.assertEqual(ad_report["status"], "OK")
        self.assertEqual(ss_report["status"], "OK")
        self.assertEqual(cv_report["status"], "OK")
        trade = diagnose_trade_remedies()
        self.assertIn(trade.status, ("manual_review_required", "partial"))
        self.assertNotEqual(trade.status, "present")
        self.assertTrue(trade.manual_review_required)

    def test_official_countervailing_marker_isolated(self) -> None:
        from app.services.payment_revision_utils import (
            is_official_anti_dumping_row_marker,
            is_official_countervailing_row_marker,
            is_official_special_safeguard_row_marker,
        )

        self.assertTrue(
            is_official_countervailing_row_marker(
                countervailing_source_code="EEC_COUNTERVAILING",
                countervailing_source_revision="countervailing:2026-05-01",
            )
        )
        self.assertFalse(
            is_official_anti_dumping_row_marker(
                source_code="EEC_COUNTERVAILING",
                source_revision="countervailing:2026-05-01",
            )
        )
        self.assertFalse(
            is_official_special_safeguard_row_marker(
                safeguard_source_code="EEC_COUNTERVAILING",
                safeguard_source_revision="countervailing:2026-05-01",
            )
        )

    def test_import_duty_and_vat_do_not_pick_countervailing_bundle(self) -> None:
        import app.services.countervailing_ingestion as ci
        import app.services.import_duty_ingestion as idi
        import app.services.vat_ingestion as vi

        with _BundleFixture(_official_countervailing_payload()) as (root, rel):
            with unittest.mock.patch.object(ci, "_BACKEND_ROOT", root):
                with unittest.mock.patch.object(idi, "_BACKEND_ROOT", root):
                    with unittest.mock.patch.object(vi, "_BACKEND_ROOT", root):
                        self.assertIsNone(discover_import_duty_bundle_path(rel_path=rel))
                        self.assertIsNone(discover_vat_bundle_path(rel_path=rel))

    def test_import_duty_rejects_countervailing_revision(self) -> None:
        import app.services.import_duty_ingestion as idi

        payload = {
            "format": "customs_clear_normative_bundle",
            "revision": "countervailing:2026-05-01",
            "official_ett_url": "https://eec.eaeunion.org/",
            "rates": [{"hs_code": "8471300000", "duty_rate": "5%"}],
        }
        with _BundleFixture(payload, rel_path="data/raw_normative/eec_ett_import_duty.json") as (root, rel):
            with unittest.mock.patch.object(idi, "_BACKEND_ROOT", root):
                report = run_import_duty_apply(rel_path=rel)
        self.assertNotEqual(report["status"], "OK")
        self.assertFalse(report["db_mutated"])

    def test_vat_rejects_countervailing_revision(self) -> None:
        import app.services.vat_ingestion as vi

        with self.sm() as db:
            db.add(
                HsRate(
                    hs_code="3004909200",
                    hs_prefix="3004",
                    duty_rate="5%",
                    vat_import_rate=22.0,
                    source_revision="seed",
                )
            )
            db.commit()

        payload = {
            "format": "customs_clear_normative_bundle",
            "revision": "countervailing:2026-05-01",
            "official_ett_url": "https://eec.eaeunion.org/",
            "rates": [{"hs_code": "3004909200", "vat_import_rate": 10}],
        }
        with _BundleFixture(payload, rel_path="data/raw_normative/eec_ett_vat.json") as (root, rel):
            with unittest.mock.patch.object(vi, "_BACKEND_ROOT", root):
                report = run_vat_apply(rel_path=rel)
        self.assertNotEqual(report["status"], "OK")
        self.assertFalse(report["db_mutated"])

    def test_duty_and_vat_coverage_unaffected_by_countervailing_status(self) -> None:
        import app.services.countervailing_ingestion as ci

        with _BundleFixture(_official_countervailing_payload()) as (root, rel):
            with unittest.mock.patch.object(ci, "_BACKEND_ROOT", root):
                run_countervailing_apply(rel_path=rel)
        duty_before = diagnose_duty_rates().status
        vat_before = diagnose_vat_rates().status
        self.assertNotEqual(duty_before, "present")
        self.assertNotEqual(vat_before, "present")


if __name__ == "__main__":
    unittest.main()
