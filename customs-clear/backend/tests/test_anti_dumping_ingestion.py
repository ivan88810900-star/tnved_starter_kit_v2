"""Тесты official anti-dumping ingestion (issue #45)."""

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
from app.services.anti_dumping_ingestion import run_anti_dumping_apply, run_anti_dumping_dry_run
from app.services.import_duty_ingestion import discover_import_duty_bundle_path, run_import_duty_apply
from app.services.payment_data_coverage import diagnose_duty_rates, diagnose_trade_remedies, diagnose_vat_rates
from app.services.payment_data_normalization import normalize_anti_dumping
from app.services.vat_ingestion import discover_vat_bundle_path, run_vat_apply

try:
    from fastapi.testclient import TestClient

    from app.main import app

    _API_OK = True
except ImportError:
    _API_OK = False


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


def _official_anti_dumping_payload(
    *,
    revision: str = "anti-dumping:2026-05-01",
    official_url: str = "https://eec.eaeunion.org/comission/department/deptexsec/trade_remedies/",
    measures: list[dict] | None = None,
) -> dict:
    return {
        "format": "customs_clear_anti_dumping_bundle",
        "revision": revision,
        "effective_from": "2026-01-01",
        "official_url": official_url,
        "measures": measures
        or [
            {
                "hs_code": "7214200000",
                "hs_prefix": "7214",
                "origin_country": "CN",
                "measure_type": "anti_dumping",
                "rate_type": "percent",
                "rate_value": 18.0,
                "regulatory_act": "ЕЭК №123/2024",
                "product_description": "Прокат стальной",
            },
            {
                "hs_prefix": "8517",
                "origin_country": "UA",
                "measure_type": "anti_dumping",
                "rate_type": "percent",
                "rate_value": 15.0,
                "regulatory_act": "ЕЭК №456/2025",
            },
        ],
    }


class _BundleFixture:
    def __init__(self, payload: dict, rel_path: str = "data/raw_normative/eec_anti_dumping.json"):
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


class TestAntiDumpingMissingSource(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)
        import app.services.anti_dumping_ingestion as adi

        self._root_patch = unittest.mock.patch.object(adi, "_BACKEND_ROOT", Path("/nonexistent"))
        self._root_patch.start()

    def tearDown(self) -> None:
        self._root_patch.stop()
        _stop_patches(*self._patches)

    def test_dry_run_missing_official_source(self) -> None:
        before = _table_counts(self.sm)
        report = run_anti_dumping_dry_run()
        after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "missing_official_source")
        self.assertTrue(report["dry_run"])
        self.assertFalse(report["db_mutated"])

    def test_apply_missing_official_source_no_provenance(self) -> None:
        before = _table_counts(self.sm)
        report = run_anti_dumping_apply()
        after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "missing_official_source")
        self.assertFalse(report["db_mutated"])
        self.assertEqual(after["source_status"], 0)
        self.assertEqual(after["sync_log"], 0)


class TestAntiDumpingDryRunNoMutation(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_dry_run_does_not_mutate_db(self) -> None:
        import app.services.anti_dumping_ingestion as adi

        with _BundleFixture(_official_anti_dumping_payload()) as (root, rel):
            with unittest.mock.patch.object(adi, "_BACKEND_ROOT", root):
                before = _table_counts(self.sm)
                report = run_anti_dumping_dry_run(rel_path=rel)
                after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "OK")
        self.assertTrue(report["dry_run"])
        self.assertFalse(report["db_mutated"])
        self.assertGreater(report["row_counts"]["insert"], 0)


class TestAntiDumpingApplyProvenance(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_apply_writes_special_duties_with_provenance(self) -> None:
        import app.services.anti_dumping_ingestion as adi

        with _BundleFixture(_official_anti_dumping_payload()) as (root, rel):
            with unittest.mock.patch.object(adi, "_BACKEND_ROOT", root):
                report = run_anti_dumping_apply(rel_path=rel)
        self.assertEqual(report["status"], "OK")
        self.assertTrue(report["db_mutated"])
        self.assertEqual(report["provenance"]["source_code"], "EEC_ANTI_DUMPING")
        with self.sm() as db:
            rows = db.query(SpecialDuty).all()
            self.assertEqual(len(rows), 2)
            for row in rows:
                self.assertEqual(row.source_code, "EEC_ANTI_DUMPING")
                self.assertEqual(row.source_revision, "anti-dumping:2026-05-01")
                self.assertEqual(row.measure_type, "anti_dumping")
            st = db.query(SourceStatus).filter(SourceStatus.source_code == "EEC_ANTI_DUMPING").first()
            self.assertIsNotNone(st)
            logs = db.query(SyncLog).filter(SyncLog.source_code == "EEC_ANTI_DUMPING").all()
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0].status, "OK")


class TestAntiDumpingMeasureIdentity(unittest.TestCase):
    """P1: разные производители/окна/scope не должны схлопываться в одну меру."""

    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    @staticmethod
    def _two_manufacturer_payload() -> dict:
        return _official_anti_dumping_payload(
            measures=[
                {
                    "hs_prefix": "7214",
                    "origin_country": "CN",
                    "measure_type": "anti_dumping",
                    "rate_type": "percent",
                    "rate_value": 18.0,
                    "regulatory_act": "ЕЭК №123/2024",
                    "manufacturer_exporter": "Alpha Steel Co",
                    "product_description": "Прокат стальной",
                },
                {
                    "hs_prefix": "7214",
                    "origin_country": "CN",
                    "measure_type": "anti_dumping",
                    "rate_type": "percent",
                    "rate_value": 25.0,
                    "regulatory_act": "ЕЭК №123/2024",
                    "manufacturer_exporter": "Beta Metallurg LLC",
                    "product_description": "Прокат стальной",
                },
            ]
        )

    def _apply(self, payload: dict) -> dict:
        import app.services.anti_dumping_ingestion as adi

        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(adi, "_BACKEND_ROOT", root):
                return run_anti_dumping_apply(rel_path=rel)

    def test_different_manufacturer_creates_separate_rows(self) -> None:
        payload = self._two_manufacturer_payload()
        report = self._apply(payload)
        self.assertEqual(report["status"], "OK")
        self.assertTrue(report["db_mutated"])
        self.assertEqual(report["row_counts"]["insert"], 2)
        with self.sm() as db:
            rows = (
                db.query(SpecialDuty)
                .filter(
                    SpecialDuty.hs_code_prefix == "7214",
                    SpecialDuty.origin_country == "CN",
                    SpecialDuty.regulatory_act == "ЕЭК №123/2024",
                )
                .all()
            )
            self.assertEqual(len(rows), 2)
            by_manuf = {r.manufacturer_exporter: r for r in rows}
            self.assertEqual(set(by_manuf), {"Alpha Steel Co", "Beta Metallurg LLC"})
            self.assertEqual(by_manuf["Alpha Steel Co"].rate_percent, 18.0)
            self.assertEqual(by_manuf["Beta Metallurg LLC"].rate_percent, 25.0)
            for r in rows:
                self.assertEqual(r.source_code, "EEC_ANTI_DUMPING")
                self.assertEqual(r.source_revision, "anti-dumping:2026-05-01")

    def test_reapply_is_idempotent_no_duplicate_or_overwrite(self) -> None:
        payload = self._two_manufacturer_payload()
        self._apply(payload)
        report2 = self._apply(payload)
        self.assertEqual(report2["status"], "OK")
        self.assertEqual(report2["row_counts"]["insert"], 0)
        self.assertEqual(report2["row_counts"]["update"], 0)
        self.assertEqual(report2["row_counts"]["skip"], 2)
        with self.sm() as db:
            rows = (
                db.query(SpecialDuty)
                .filter(SpecialDuty.hs_code_prefix == "7214", SpecialDuty.origin_country == "CN")
                .all()
            )
            self.assertEqual(len(rows), 2)
            by_manuf = {r.manufacturer_exporter: r.rate_percent for r in rows}
            self.assertEqual(by_manuf, {"Alpha Steel Co": 18.0, "Beta Metallurg LLC": 25.0})

    def test_different_effective_window_not_overwritten(self) -> None:
        payload = _official_anti_dumping_payload(
            measures=[
                {
                    "hs_prefix": "7214",
                    "origin_country": "CN",
                    "measure_type": "anti_dumping",
                    "rate_type": "percent",
                    "rate_value": 18.0,
                    "regulatory_act": "ЕЭК №123/2024",
                    "manufacturer_exporter": "Alpha Steel Co",
                    "effective_from": "2026-01-01",
                    "effective_to": "2026-06-30",
                },
                {
                    "hs_prefix": "7214",
                    "origin_country": "CN",
                    "measure_type": "anti_dumping",
                    "rate_type": "percent",
                    "rate_value": 22.0,
                    "regulatory_act": "ЕЭК №123/2024",
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
            rows = db.query(SpecialDuty).filter(SpecialDuty.hs_code_prefix == "7214").all()
            self.assertEqual(len(rows), 2)
            windows = {(r.effective_from, r.effective_to): r.rate_percent for r in rows}
            self.assertEqual(
                windows,
                {("2026-01-01", "2026-06-30"): 18.0, ("2026-07-01", "2026-12-31"): 22.0},
            )


class TestAntiDumpingUnsafeUrls(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def _apply(self, payload: dict) -> dict:
        import app.services.anti_dumping_ingestion as adi

        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(adi, "_BACKEND_ROOT", root):
                return run_anti_dumping_apply(rel_path=rel)

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
                report = self._apply(_official_anti_dumping_payload(official_url=url))
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
                report = self._apply(_official_anti_dumping_payload(official_url=url))
                after = _table_counts(self.sm)
                self.assertEqual(before, after)
                self.assertNotEqual(report["status"], "OK")
                self.assertFalse(report["db_mutated"])

    def test_official_eaeunion_domain_accepted(self) -> None:
        report = self._apply(
            _official_anti_dumping_payload(
                official_url="https://eec.eaeunion.org/comission/department/deptexsec/trade_remedies/"
            )
        )
        self.assertEqual(report["status"], "OK")
        self.assertTrue(report["db_mutated"])


class TestAntiDumpingRevisionValidation(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def _apply(self, payload: dict) -> dict:
        import app.services.anti_dumping_ingestion as adi

        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(adi, "_BACKEND_ROOT", root):
                return run_anti_dumping_apply(rel_path=rel)

    def test_official_revision_accepted(self) -> None:
        report = self._apply(_official_anti_dumping_payload(revision="anti-dumping:2026-05-01"))
        self.assertEqual(report["status"], "OK")
        self.assertTrue(report["db_mutated"])

    def test_eec_anti_dumping_revision_accepted(self) -> None:
        report = self._apply(_official_anti_dumping_payload(revision="eec-anti-dumping:2026-05-01"))
        self.assertEqual(report["status"], "OK")

    def test_wrong_domain_duty_revision_rejected(self) -> None:
        report = self._apply(_official_anti_dumping_payload(revision="ett:2026-05-01"))
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])

    def test_wrong_domain_vat_revision_rejected(self) -> None:
        report = self._apply(_official_anti_dumping_payload(revision="vat:2026-05-01"))
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
                report = self._apply(_official_anti_dumping_payload(revision=revision))
                self.assertNotEqual(report["status"], "OK")
                self.assertFalse(report["db_mutated"])

    def test_blank_row_revision_inherits_bundle_revision(self) -> None:
        payload = _official_anti_dumping_payload(
            revision="anti-dumping:2026-06-01",
            measures=[
                {
                    "hs_prefix": "7214",
                    "origin_country": "CN",
                    "rate_type": "percent",
                    "rate_value": 18.0,
                    "regulatory_act": "ЕЭК №123/2024",
                }
            ],
        )
        report = self._apply(payload)
        self.assertEqual(report["status"], "OK")
        with self.sm() as db:
            row = db.query(SpecialDuty).one()
            self.assertEqual(row.source_revision, "anti-dumping:2026-06-01")

    def test_explicit_unsafe_row_revision_blocks(self) -> None:
        payload = _official_anti_dumping_payload(
            measures=[
                {
                    "hs_prefix": "7214",
                    "origin_country": "CN",
                    "rate_type": "percent",
                    "rate_value": 18.0,
                    "regulatory_act": "ЕЭК №123/2024",
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


class TestAntiDumpingMalformedContainers(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def _apply(self, payload: dict) -> dict:
        import app.services.anti_dumping_ingestion as adi

        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(adi, "_BACKEND_ROOT", root):
                return run_anti_dumping_apply(rel_path=rel)

    def test_measures_scalar_parser_failed(self) -> None:
        payload = {
            "format": "customs_clear_anti_dumping_bundle",
            "revision": "anti-dumping:2026-05-01",
            "official_url": "https://eec.eaeunion.org/",
            "measures": 123,
        }
        report = self._apply(payload)
        self.assertEqual(report["status"], "parser_failed")
        self.assertFalse(report["db_mutated"])

    def test_non_object_rows_parser_failed(self) -> None:
        payload = {
            "format": "customs_clear_anti_dumping_bundle",
            "revision": "anti-dumping:2026-05-01",
            "official_url": "https://eec.eaeunion.org/",
            "measures": [123],
        }
        report = self._apply(payload)
        self.assertEqual(report["status"], "parser_failed")
        self.assertFalse(report["db_mutated"])


class TestAntiDumpingMixedApplyAtomic(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_one_blocked_row_blocks_entire_apply(self) -> None:
        import app.services.anti_dumping_ingestion as adi

        payload = _official_anti_dumping_payload(
            measures=[
                {
                    "hs_prefix": "7214",
                    "origin_country": "CN",
                    "rate_type": "percent",
                    "rate_value": 18.0,
                    "regulatory_act": "ЕЭК №123/2024",
                },
                {
                    "hs_prefix": "8517",
                    "origin_country": "UA",
                    "rate_type": "percent",
                    "rate_value": 15.0,
                    "regulatory_act": "ЕЭК №456/2025",
                    "source_revision": "seed-2026",
                },
            ]
        )
        before = _table_counts(self.sm)
        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(adi, "_BACKEND_ROOT", root):
                report = run_anti_dumping_apply(rel_path=rel)
        after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])
        with self.sm() as db:
            self.assertEqual(db.query(SourceStatus).count(), 0)
            self.assertEqual(db.query(SyncLog).filter(SyncLog.status == "OK").count(), 0)


class TestAntiDumpingLegacyRowsNotOfficial(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        with self.sm() as db:
            db.add(
                SpecialDuty(
                    hs_code_prefix="8517",
                    origin_country="CN",
                    rate_percent=15.0,
                    regulatory_act="LEGACY-AD",
                    measure_type="anti_dumping",
                )
            )
            db.commit()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_legacy_rows_stay_non_official_after_successful_sync(self) -> None:
        import app.services.anti_dumping_ingestion as adi

        with _BundleFixture(_official_anti_dumping_payload()) as (root, rel):
            with unittest.mock.patch.object(adi, "_BACKEND_ROOT", root):
                report = run_anti_dumping_apply(rel_path=rel)
        self.assertEqual(report["status"], "OK")
        with self.sm() as db:
            legacy = (
                db.query(SpecialDuty)
                .filter(SpecialDuty.regulatory_act == "LEGACY-AD")
                .one()
            )
            self.assertEqual(legacy.source_code, "")
            self.assertEqual(legacy.source_revision, "")
        ad = normalize_anti_dumping()
        self.assertNotEqual(ad.coverage_status, "present")
        self.assertGreater(ad.normalized_snapshot.get("special_duties_legacy_rows", 0), 0)
        self.assertGreater(ad.normalized_snapshot.get("special_duties_official_rows", 0), 0)


class TestAntiDumpingCoverageIsolation(unittest.TestCase):
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
                    source_code="EEC_ANTI_DUMPING",
                    source_name="AD test",
                    source_url="https://eec.eaeunion.org/",
                    revision="anti-dumping:2026-05-01",
                    synced_at=now,
                    is_stale=False,
                )
            )
            db.commit()
        trade = diagnose_trade_remedies()
        self.assertNotEqual(trade.status, "present")
        ad = normalize_anti_dumping()
        self.assertNotEqual(ad.coverage_status, "present")

    def test_duty_and_vat_coverage_unaffected_by_anti_dumping_status(self) -> None:
        import app.services.anti_dumping_ingestion as adi

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self.sm() as db:
            db.add(
                SourceStatus(
                    source_code="EEC_ANTI_DUMPING",
                    source_name="AD test",
                    source_url="https://eec.eaeunion.org/",
                    revision="anti-dumping:2026-05-01",
                    synced_at=now,
                    is_stale=False,
                )
            )
            db.commit()
        with _BundleFixture(_official_anti_dumping_payload()) as (root, rel):
            with unittest.mock.patch.object(adi, "_BACKEND_ROOT", root):
                run_anti_dumping_apply(rel_path=rel)
        duty_before = diagnose_duty_rates().status
        vat_before = diagnose_vat_rates().status
        self.assertNotEqual(duty_before, "present")
        self.assertNotEqual(vat_before, "present")


class TestAntiDumpingBundleDiscoveryIsolation(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_import_duty_and_vat_do_not_pick_anti_dumping_bundle(self) -> None:
        import app.services.anti_dumping_ingestion as adi
        import app.services.import_duty_ingestion as idi
        import app.services.vat_ingestion as vi

        with _BundleFixture(_official_anti_dumping_payload()) as (root, rel):
            with unittest.mock.patch.object(adi, "_BACKEND_ROOT", root):
                with unittest.mock.patch.object(idi, "_BACKEND_ROOT", root):
                    with unittest.mock.patch.object(vi, "_BACKEND_ROOT", root):
                        self.assertIsNone(discover_import_duty_bundle_path(rel_path=rel))
                        self.assertIsNone(discover_vat_bundle_path(rel_path=rel))

    def test_import_duty_rejects_anti_dumping_revision(self) -> None:
        import app.services.import_duty_ingestion as idi

        payload = {
            "format": "customs_clear_normative_bundle",
            "revision": "anti-dumping:2026-05-01",
            "official_ett_url": "https://eec.eaeunion.org/",
            "rates": [{"hs_code": "8471300000", "duty_rate": "5%"}],
        }
        with _BundleFixture(payload, rel_path="data/raw_normative/eec_ett_import_duty.json") as (root, rel):
            with unittest.mock.patch.object(idi, "_BACKEND_ROOT", root):
                report = run_import_duty_apply(rel_path=rel)
        self.assertNotEqual(report["status"], "OK")
        self.assertFalse(report["db_mutated"])

    def test_vat_rejects_anti_dumping_revision(self) -> None:
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
            "revision": "anti-dumping:2026-05-01",
            "official_ett_url": "https://eec.eaeunion.org/",
            "rates": [{"hs_code": "3004909200", "vat_import_rate": 10}],
        }
        with _BundleFixture(payload, rel_path="data/raw_normative/eec_ett_vat.json") as (root, rel):
            with unittest.mock.patch.object(vi, "_BACKEND_ROOT", root):
                report = run_vat_apply(rel_path=rel)
        self.assertNotEqual(report["status"], "OK")
        self.assertFalse(report["db_mutated"])


if __name__ == "__main__":
    unittest.main()
