"""Тесты official special-safeguard ingestion (issue #47)."""

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
from app.services.import_duty_ingestion import discover_import_duty_bundle_path, run_import_duty_apply
from app.services.payment_data_coverage import diagnose_duty_rates, diagnose_trade_remedies, diagnose_vat_rates
from app.services.payment_data_normalization import normalize_anti_dumping, normalize_special_safeguard
from app.services.special_safeguard_ingestion import (
    discover_special_safeguard_bundle_path,
    run_special_safeguard_apply,
    run_special_safeguard_dry_run,
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


def _official_special_safeguard_payload(
    *,
    revision: str = "special-safeguard:2026-05-01",
    official_url: str = "https://eec.eaeunion.org/comission/department/deptexsec/trade_remedies/",
    measures: list[dict] | None = None,
) -> dict:
    return {
        "format": "customs_clear_special_safeguard_bundle",
        "revision": revision,
        "effective_from": "2026-01-01",
        "official_url": official_url,
        "measures": measures
        or [
            {
                "hs_code": "6403990000",
                "hs_prefix": "6403",
                "origin_country": "CN",
                "measure_type": "special_safeguard",
                "rate_type": "percent",
                "rate_value": 12.0,
                "regulatory_act": "ЕЭК №789/2024",
                "product_description": "Обувь",
            },
            {
                "hs_prefix": "9401",
                "origin_country": "TR",
                "measure_type": "special_safeguard",
                "rate_type": "percent",
                "rate_value": 9.0,
                "regulatory_act": "ЕЭК №790/2025",
            },
        ],
    }


class _BundleFixture:
    def __init__(self, payload: dict, rel_path: str = "data/raw_normative/eec_special_safeguard.json"):
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


class TestSpecialSafeguardMissingSource(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)
        import app.services.special_safeguard_ingestion as ssi

        self._root_patch = unittest.mock.patch.object(ssi, "_BACKEND_ROOT", Path("/nonexistent"))
        self._root_patch.start()

    def tearDown(self) -> None:
        self._root_patch.stop()
        _stop_patches(*self._patches)

    def test_dry_run_missing_official_source(self) -> None:
        before = _table_counts(self.sm)
        report = run_special_safeguard_dry_run()
        after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "missing_official_source")
        self.assertTrue(report["dry_run"])
        self.assertFalse(report["db_mutated"])

    def test_apply_missing_official_source_no_provenance(self) -> None:
        before = _table_counts(self.sm)
        report = run_special_safeguard_apply()
        after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "missing_official_source")
        self.assertFalse(report["db_mutated"])
        self.assertEqual(after["source_status"], 0)
        self.assertEqual(after["sync_log"], 0)


class TestSpecialSafeguardDryRunNoMutation(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_dry_run_does_not_mutate_db(self) -> None:
        import app.services.special_safeguard_ingestion as ssi

        with _BundleFixture(_official_special_safeguard_payload()) as (root, rel):
            with unittest.mock.patch.object(ssi, "_BACKEND_ROOT", root):
                before = _table_counts(self.sm)
                report = run_special_safeguard_dry_run(rel_path=rel)
                after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "OK")
        self.assertTrue(report["dry_run"])
        self.assertFalse(report["db_mutated"])
        self.assertGreater(report["row_counts"]["insert"], 0)


class TestSpecialSafeguardApplyProvenance(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_apply_writes_special_duties_with_provenance(self) -> None:
        import app.services.special_safeguard_ingestion as ssi

        with _BundleFixture(_official_special_safeguard_payload()) as (root, rel):
            with unittest.mock.patch.object(ssi, "_BACKEND_ROOT", root):
                report = run_special_safeguard_apply(rel_path=rel)
        self.assertEqual(report["status"], "OK")
        self.assertTrue(report["db_mutated"])
        self.assertEqual(report["provenance"]["source_code"], "EEC_SPECIAL_SAFEGUARD")
        with self.sm() as db:
            rows = db.query(SpecialDuty).filter(SpecialDuty.measure_type == "special_safeguard").all()
            self.assertEqual(len(rows), 2)
            for row in rows:
                self.assertEqual(row.source_code, "EEC_SPECIAL_SAFEGUARD")
                self.assertEqual(row.source_revision, "special-safeguard:2026-05-01")
                self.assertEqual(row.measure_type, "special_safeguard")
                self.assertIsNotNone(row.synced_at)
            st = db.query(SourceStatus).filter(SourceStatus.source_code == "EEC_SPECIAL_SAFEGUARD").first()
            self.assertIsNotNone(st)
            logs = db.query(SyncLog).filter(SyncLog.source_code == "EEC_SPECIAL_SAFEGUARD").all()
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0].status, "OK")


class TestSpecialSafeguardRevisionValidation(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def _apply(self, payload: dict) -> dict:
        import app.services.special_safeguard_ingestion as ssi

        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(ssi, "_BACKEND_ROOT", root):
                return run_special_safeguard_apply(rel_path=rel)

    def test_official_revision_accepted(self) -> None:
        report = self._apply(_official_special_safeguard_payload(revision="special-safeguard:2026-05-01"))
        self.assertEqual(report["status"], "OK")
        self.assertTrue(report["db_mutated"])

    def test_eec_special_safeguard_revision_accepted(self) -> None:
        report = self._apply(_official_special_safeguard_payload(revision="eec-special-safeguard:2026-05-01"))
        self.assertEqual(report["status"], "OK")

    def test_wrong_domain_duty_revision_rejected(self) -> None:
        report = self._apply(_official_special_safeguard_payload(revision="ett:2026-05-01"))
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])

    def test_wrong_domain_anti_dumping_revision_rejected(self) -> None:
        report = self._apply(_official_special_safeguard_payload(revision="anti-dumping:2026-05-01"))
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
                report = self._apply(_official_special_safeguard_payload(revision=revision))
                self.assertNotEqual(report["status"], "OK")
                self.assertFalse(report["db_mutated"])

    def test_explicit_unsafe_row_revision_blocks(self) -> None:
        payload = _official_special_safeguard_payload(
            measures=[
                {
                    "hs_prefix": "6403",
                    "origin_country": "CN",
                    "rate_type": "percent",
                    "rate_value": 12.0,
                    "regulatory_act": "ЕЭК №789/2024",
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


class TestSpecialSafeguardMalformedContainers(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def _apply(self, payload: dict) -> dict:
        import app.services.special_safeguard_ingestion as ssi

        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(ssi, "_BACKEND_ROOT", root):
                return run_special_safeguard_apply(rel_path=rel)

    def test_measures_scalar_parser_failed(self) -> None:
        payload = {
            "format": "customs_clear_special_safeguard_bundle",
            "revision": "special-safeguard:2026-05-01",
            "official_url": "https://eec.eaeunion.org/",
            "measures": 123,
        }
        report = self._apply(payload)
        self.assertEqual(report["status"], "parser_failed")
        self.assertFalse(report["db_mutated"])

    def test_non_object_rows_parser_failed(self) -> None:
        payload = {
            "format": "customs_clear_special_safeguard_bundle",
            "revision": "special-safeguard:2026-05-01",
            "official_url": "https://eec.eaeunion.org/",
            "measures": [123],
        }
        report = self._apply(payload)
        self.assertEqual(report["status"], "parser_failed")
        self.assertFalse(report["db_mutated"])


class TestSpecialSafeguardMixedApplyAtomic(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_one_blocked_row_blocks_entire_apply(self) -> None:
        import app.services.special_safeguard_ingestion as ssi

        payload = _official_special_safeguard_payload(
            measures=[
                {
                    "hs_prefix": "6403",
                    "origin_country": "CN",
                    "rate_type": "percent",
                    "rate_value": 12.0,
                    "regulatory_act": "ЕЭК №789/2024",
                },
                {
                    "hs_prefix": "9401",
                    "origin_country": "TR",
                    "rate_type": "percent",
                    "rate_value": 9.0,
                    "regulatory_act": "ЕЭК №790/2025",
                    "source_revision": "seed-2026",
                },
            ]
        )
        before = _table_counts(self.sm)
        with _BundleFixture(payload) as (root, rel):
            with unittest.mock.patch.object(ssi, "_BACKEND_ROOT", root):
                report = run_special_safeguard_apply(rel_path=rel)
        after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "manual_review_required")
        self.assertFalse(report["db_mutated"])
        with self.sm() as db:
            self.assertEqual(db.query(SourceStatus).count(), 0)
            self.assertEqual(db.query(SyncLog).filter(SyncLog.status == "OK").count(), 0)


class TestSpecialSafeguardCoverageIsolation(unittest.TestCase):
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
                    source_code="EEC_SPECIAL_SAFEGUARD",
                    source_name="SS test",
                    source_url="https://eec.eaeunion.org/",
                    revision="special-safeguard:2026-05-01",
                    synced_at=now,
                    is_stale=False,
                )
            )
            db.commit()
        trade = diagnose_trade_remedies()
        self.assertNotEqual(trade.status, "present")
        ss = normalize_special_safeguard()
        self.assertNotEqual(ss.coverage_status, "present")

    def test_duty_and_vat_coverage_unaffected_by_special_safeguard_status(self) -> None:
        import app.services.special_safeguard_ingestion as ssi

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self.sm() as db:
            db.add(
                SourceStatus(
                    source_code="EEC_SPECIAL_SAFEGUARD",
                    source_name="SS test",
                    source_url="https://eec.eaeunion.org/",
                    revision="special-safeguard:2026-05-01",
                    synced_at=now,
                    is_stale=False,
                )
            )
            db.commit()
        with _BundleFixture(_official_special_safeguard_payload()) as (root, rel):
            with unittest.mock.patch.object(ssi, "_BACKEND_ROOT", root):
                run_special_safeguard_apply(rel_path=rel)
        duty_before = diagnose_duty_rates().status
        vat_before = diagnose_vat_rates().status
        self.assertNotEqual(duty_before, "present")
        self.assertNotEqual(vat_before, "present")


class TestSpecialSafeguardAntiDumpingIsolation(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_bundles_do_not_cross_discover(self) -> None:
        import app.services.anti_dumping_ingestion as adi
        import app.services.special_safeguard_ingestion as ssi

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
        ss_payload = _official_special_safeguard_payload()
        ad_rel = "data/raw_normative/eec_anti_dumping.json"
        ss_rel = "data/raw_normative/eec_special_safeguard.json"

        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel, payload in ((ad_rel, ad_payload), (ss_rel, ss_payload)):
                full = root / rel
                full.parent.mkdir(parents=True, exist_ok=True)
                full.write_text(json.dumps(payload), encoding="utf-8")
            with unittest.mock.patch.object(adi, "_BACKEND_ROOT", root):
                with unittest.mock.patch.object(ssi, "_BACKEND_ROOT", root):
                    self.assertEqual(discover_anti_dumping_bundle_path(rel_path=ad_rel), ad_rel)
                    self.assertEqual(discover_special_safeguard_bundle_path(rel_path=ss_rel), ss_rel)
                    self.assertIsNone(discover_anti_dumping_bundle_path(rel_path=ss_rel))
                    self.assertIsNone(discover_special_safeguard_bundle_path(rel_path=ad_rel))

    def test_special_safeguard_apply_does_not_touch_anti_dumping_rows(self) -> None:
        import app.services.anti_dumping_ingestion as adi
        import app.services.special_safeguard_ingestion as ssi

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
        with _BundleFixture(ad_payload, rel_path="data/raw_normative/eec_anti_dumping.json") as (root, ad_rel):
            with unittest.mock.patch.object(adi, "_BACKEND_ROOT", root):
                run_anti_dumping_apply(rel_path=ad_rel)
        with _BundleFixture(_official_special_safeguard_payload()) as (root2, ss_rel):
            with unittest.mock.patch.object(ssi, "_BACKEND_ROOT", root2):
                report = run_special_safeguard_apply(rel_path=ss_rel)
        self.assertEqual(report["status"], "OK")
        with self.sm() as db:
            ad_rows = db.query(SpecialDuty).filter(SpecialDuty.measure_type == "anti_dumping").all()
            ss_rows = db.query(SpecialDuty).filter(SpecialDuty.measure_type == "special_safeguard").all()
            self.assertEqual(len(ad_rows), 1)
            self.assertEqual(len(ss_rows), 2)
            self.assertEqual(ad_rows[0].source_code, "EEC_ANTI_DUMPING")
            self.assertNotEqual(ad_rows[0].source_code, "EEC_SPECIAL_SAFEGUARD")
            ad_norm = normalize_anti_dumping()
            ss_norm = normalize_special_safeguard()
            self.assertNotEqual(ad_norm.coverage_status, "present")
            self.assertNotEqual(ss_norm.coverage_status, "present")

    def test_anti_dumping_rejects_special_safeguard_revision(self) -> None:
        import app.services.anti_dumping_ingestion as adi

        payload = {
            "format": "customs_clear_anti_dumping_bundle",
            "revision": "special-safeguard:2026-05-01",
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
        with _BundleFixture(payload, rel_path="data/raw_normative/eec_anti_dumping.json") as (root, rel):
            with unittest.mock.patch.object(adi, "_BACKEND_ROOT", root):
                report = run_anti_dumping_apply(rel_path=rel)
        self.assertNotEqual(report["status"], "OK")
        self.assertFalse(report["db_mutated"])

    def test_import_duty_and_vat_do_not_pick_special_safeguard_bundle(self) -> None:
        import app.services.import_duty_ingestion as idi
        import app.services.special_safeguard_ingestion as ssi
        import app.services.vat_ingestion as vi

        with _BundleFixture(_official_special_safeguard_payload()) as (root, rel):
            with unittest.mock.patch.object(ssi, "_BACKEND_ROOT", root):
                with unittest.mock.patch.object(idi, "_BACKEND_ROOT", root):
                    with unittest.mock.patch.object(vi, "_BACKEND_ROOT", root):
                        self.assertIsNone(discover_import_duty_bundle_path(rel_path=rel))
                        self.assertIsNone(discover_vat_bundle_path(rel_path=rel))

    def test_import_duty_rejects_special_safeguard_revision(self) -> None:
        import app.services.import_duty_ingestion as idi

        payload = {
            "format": "customs_clear_normative_bundle",
            "revision": "special-safeguard:2026-05-01",
            "official_ett_url": "https://eec.eaeunion.org/",
            "rates": [{"hs_code": "8471300000", "duty_rate": "5%"}],
        }
        with _BundleFixture(payload, rel_path="data/raw_normative/eec_ett_import_duty.json") as (root, rel):
            with unittest.mock.patch.object(idi, "_BACKEND_ROOT", root):
                report = run_import_duty_apply(rel_path=rel)
        self.assertNotEqual(report["status"], "OK")
        self.assertFalse(report["db_mutated"])

    def test_vat_rejects_special_safeguard_revision(self) -> None:
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
            "revision": "special-safeguard:2026-05-01",
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
