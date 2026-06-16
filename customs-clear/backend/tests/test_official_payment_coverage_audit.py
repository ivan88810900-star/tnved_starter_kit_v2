"""Тесты read-only аудита official payment/remedy coverage (issue #53)."""

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
from app.services.anti_dumping_ingestion import run_anti_dumping_apply
from app.services.countervailing_ingestion import run_countervailing_apply
from app.services.official_payment_coverage_audit import run_official_payment_coverage_audit

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
    modules = (
        "app.services.official_payment_coverage_audit",
        "app.services.anti_dumping_ingestion",
        "app.services.countervailing_ingestion",
        "app.services.special_safeguard_ingestion",
        "app.services.import_duty_ingestion",
        "app.services.vat_ingestion",
        "app.services.excise_ingestion",
        "app.services.payment_data_normalization",
        "app.services.payment_data_coverage",
        "app.services.normative_store",
    )
    patches = tuple(unittest.mock.patch(f"{m}.SessionLocal", sm) for m in modules)
    for p in patches:
        p.start()
    return patches


def _stop_patches(*patches: unittest.mock._patch) -> None:
    for p in reversed(patches):
        p.stop()


_INGESTION_ROOT_MODULES = (
    "app.services.import_duty_ingestion",
    "app.services.vat_ingestion",
    "app.services.excise_ingestion",
    "app.services.anti_dumping_ingestion",
    "app.services.special_safeguard_ingestion",
    "app.services.countervailing_ingestion",
)


class _IngestionRootPatch:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._patches: list[unittest.mock._patch] = []

    def __enter__(self) -> Path:
        for mod in _INGESTION_ROOT_MODULES:
            import importlib

            module = importlib.import_module(mod)
            self._patches.append(unittest.mock.patch.object(module, "_BACKEND_ROOT", self.root))
        for p in self._patches:
            p.start()
        return self.root

    def __exit__(self, *args: object) -> None:
        for p in reversed(self._patches):
            p.stop()


def _table_counts(sm: sessionmaker) -> dict[str, int]:
    with sm() as db:
        return {
            "hs_rates": db.query(HsRate).count(),
            "special_duties": db.query(SpecialDuty).count(),
            "source_status": db.query(SourceStatus).count(),
            "sync_log": db.query(SyncLog).count(),
        }


def _domain(report: dict, key: str) -> dict:
    for d in report["domains"]:
        if d["domain_key"] == key or d["domain"] == key:
            return d
    raise KeyError(key)


class _BundleFixture:
    def __init__(self, payload: dict, rel_path: str):
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


def _official_ad_payload(**kwargs: object) -> dict:
    base = {
        "format": "customs_clear_anti_dumping_bundle",
        "revision": "anti-dumping:2026-05-01",
        "official_url": "https://eec.eaeunion.org/comission/department/deptexsec/trade_remedies/",
        "measures": [
            {
                "hs_prefix": "7214",
                "origin_country": "CN",
                "measure_type": "anti_dumping",
                "rate_type": "percent",
                "rate_value": 18.0,
                "regulatory_act": "ЕЭК №123/2024",
            }
        ],
    }
    base.update(kwargs)
    return base


def _official_cv_payload(**kwargs: object) -> dict:
    base = {
        "format": "customs_clear_countervailing_bundle",
        "revision": "countervailing:2026-05-01",
        "official_url": "https://eec.eaeunion.org/comission/department/deptexsec/trade_remedies/",
        "measures": [
            {
                "hs_prefix": "7208",
                "origin_country": "IN",
                "measure_type": "countervailing",
                "rate_type": "percent",
                "rate_value": 11.5,
                "regulatory_act": "ЕЭК №801/2024",
            }
        ],
    }
    base.update(kwargs)
    return base


class TestOfficialPaymentCoverageAuditEmpty(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)
        self._root_ctx = _IngestionRootPatch(Path("/nonexistent"))
        self._root_ctx.__enter__()

    def tearDown(self) -> None:
        self._root_ctx.__exit__()
        _stop_patches(*self._patches)

    def test_detects_missing_source(self) -> None:
        report = run_official_payment_coverage_audit()
        self.assertFalse(report["db_mutated"])
        cv = _domain(report, "EEC_COUNTERVAILING")
        self.assertTrue(cv["missing_source"])
        self.assertFalse(cv["local_bundle_present"])
        self.assertEqual(cv["backfill_situation"], "acquire_official_source")
        self.assertEqual(cv["recommended_next_action"], "acquire_official_source")
        self.assertFalse(cv["domain_unsupported"])

    def test_all_six_domains_supported(self) -> None:
        report = run_official_payment_coverage_audit()
        keys = {d["domain_key"] for d in report["domains"]}
        self.assertEqual(
            keys,
            {
                "EEC_ETT",
                "EEC_VAT",
                "EEC_EXCISE",
                "EEC_ANTI_DUMPING",
                "EEC_SPECIAL_SAFEGUARD",
                "EEC_COUNTERVAILING",
            },
        )
        for d in report["domains"]:
            self.assertFalse(d["domain_unsupported"])

    def test_summary_counts_by_status_and_action(self) -> None:
        report = run_official_payment_coverage_audit()
        summary = report["summary"]
        self.assertEqual(summary["domain_count"], 6)
        self.assertEqual(
            sum(summary["by_coverage_status"].values()),
            6,
        )
        self.assertEqual(
            sum(summary["by_recommended_next_action"].values()),
            6,
        )

    def test_trade_remedies_aggregate_not_present(self) -> None:
        report = run_official_payment_coverage_audit()
        agg = report["trade_remedies_aggregate"]
        self.assertNotEqual(agg["status"], "present")
        self.assertTrue(agg["manual_review_required"])
        self.assertFalse(agg["completeness_verified"])

    def test_does_not_mutate_db(self) -> None:
        before = _table_counts(self.sm)
        report = run_official_payment_coverage_audit()
        after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertFalse(report["db_mutated"])


class TestOfficialPaymentCoverageAuditSourcePresentNotApplied(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_bundle_present_but_not_applied(self) -> None:
        with _BundleFixture(
            _official_cv_payload(), rel_path="data/raw_normative/eec_countervailing.json"
        ) as (root, _rel):
            with _IngestionRootPatch(root):
                report = run_official_payment_coverage_audit()
        cv = _domain(report, "EEC_COUNTERVAILING")
        self.assertTrue(cv["local_bundle_present"])
        self.assertGreater(cv["parsed_rows"], 0)
        self.assertEqual(cv["official_row_count"], 0)
        self.assertTrue(cv["source_present_but_not_applied"])
        self.assertEqual(cv["recommended_next_action"], "run_apply")
        self.assertEqual(cv["backfill_situation"], "run_apply")


class TestOfficialPaymentCoverageAuditOfficialRows(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_official_rows_with_provenance(self) -> None:
        with _BundleFixture(
            _official_cv_payload(), rel_path="data/raw_normative/eec_countervailing.json"
        ) as (root, rel):
            with _IngestionRootPatch(root):
                run_countervailing_apply(rel_path=rel)
                report = run_official_payment_coverage_audit()
        cv = _domain(report, "EEC_COUNTERVAILING")
        self.assertGreater(cv["official_row_count"], 0)
        self.assertEqual(cv["legacy_row_count"], 0)
        self.assertFalse(cv["source_present_but_not_applied"])
        self.assertEqual(cv["coverage_status"], "manual_review_required")
        self.assertFalse(cv["domain_unsupported"])
        self.assertTrue(cv["countervailing_source_url"])
        self.assertTrue(cv["countervailing_synced_at"])

    def test_legacy_rows_not_counted_as_official(self) -> None:
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

        with _BundleFixture(
            _official_ad_payload(), rel_path="data/raw_normative/eec_anti_dumping.json"
        ) as (root, rel):
            with _IngestionRootPatch(root):
                run_anti_dumping_apply(rel_path=rel)
                report = run_official_payment_coverage_audit()
        ad = _domain(report, "EEC_ANTI_DUMPING")
        self.assertGreater(ad["official_row_count"], 0)
        self.assertGreater(ad["legacy_row_count"], 0)


class TestOfficialPaymentCoverageAuditStaleAndUnsafe(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_stale_source_status(self) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self.sm() as db:
            db.add(
                SourceStatus(
                    source_code="EEC_COUNTERVAILING",
                    source_name="CV stale",
                    source_url="https://eec.eaeunion.org/",
                    revision="countervailing:2026-05-01",
                    synced_at=now,
                    is_stale=True,
                )
            )
            db.commit()

        with _BundleFixture(
            _official_cv_payload(), rel_path="data/raw_normative/eec_countervailing.json"
        ) as (root, _rel):
            with _IngestionRootPatch(root):
                report = run_official_payment_coverage_audit()
        cv = _domain(report, "EEC_COUNTERVAILING")
        self.assertTrue(cv["stale_source_status"])
        self.assertEqual(cv["coverage_status"], "stale")
        self.assertEqual(cv["recommended_next_action"], "refresh_official_source")

    def test_unsafe_revision(self) -> None:
        with _BundleFixture(
            _official_cv_payload(revision="seed-2026"),
            rel_path="data/raw_normative/eec_countervailing.json",
        ) as (root, _rel):
            with _IngestionRootPatch(root):
                report = run_official_payment_coverage_audit()
        cv = _domain(report, "EEC_COUNTERVAILING")
        self.assertTrue(cv["unsafe_revision"])
        self.assertEqual(cv["recommended_next_action"], "manual_review_required")

    def test_unsafe_fake_url(self) -> None:
        with _BundleFixture(
            _official_cv_payload(official_url="https://example.com/fake"),
            rel_path="data/raw_normative/eec_countervailing.json",
        ) as (root, _rel):
            with _IngestionRootPatch(root):
                report = run_official_payment_coverage_audit()
        cv = _domain(report, "EEC_COUNTERVAILING")
        self.assertTrue(cv["unsafe_url"])
        self.assertEqual(cv["backfill_situation"], "manual_review_required")


class TestOfficialPaymentCoverageAuditReapplyRecommendation(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_reapply_when_proven_but_missing_row_provenance(self) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self.sm() as db:
            db.add(
                SourceStatus(
                    source_code="EEC_COUNTERVAILING",
                    source_name="CV proven",
                    source_url="https://eec.eaeunion.org/",
                    revision="countervailing:2026-05-01",
                    synced_at=now,
                    is_stale=False,
                )
            )
            db.add(
                SpecialDuty(
                    hs_code_prefix="7208",
                    origin_country="IN",
                    rate_percent=11.5,
                    regulatory_act="LEGACY-CV",
                    measure_type="countervailing",
                )
            )
            db.commit()

        with _BundleFixture(
            _official_cv_payload(), rel_path="data/raw_normative/eec_countervailing.json"
        ) as (root, _rel):
            with _IngestionRootPatch(root):
                report = run_official_payment_coverage_audit()
        cv = _domain(report, "EEC_COUNTERVAILING")
        self.assertGreater(cv["row_count"], 0)
        self.assertEqual(cv["official_row_count"], 0)
        self.assertEqual(cv["recommended_next_action"], "reapply_official_bundle")
        self.assertEqual(cv["backfill_situation"], "reapply_official_bundle")


class TestOfficialPaymentCoverageAuditCountervailingRealDomain(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)

    def tearDown(self) -> None:
        _stop_patches(*self._patches)

    def test_countervailing_uses_registry_and_provenance_fields(self) -> None:
        with _BundleFixture(
            _official_cv_payload(), rel_path="data/raw_normative/eec_countervailing.json"
        ) as (root, rel):
            with _IngestionRootPatch(root):
                run_countervailing_apply(rel_path=rel)
                report = run_official_payment_coverage_audit()
        cv = _domain(report, "EEC_COUNTERVAILING")
        self.assertEqual(cv["domain"], "countervailing")
        self.assertEqual(cv["configured_official_source"], "trade_remedies_countervailing_official")
        self.assertFalse(cv["domain_unsupported"])
        with self.sm() as db:
            row = (
                db.query(SpecialDuty)
                .filter(SpecialDuty.measure_type == "countervailing")
                .one()
            )
            self.assertEqual(row.countervailing_source_code, "EEC_COUNTERVAILING")
            self.assertTrue(row.countervailing_source_revision.startswith("countervailing:"))


@unittest.skipUnless(_API_OK, "fastapi TestClient not available")
class TestOfficialPaymentCoverageAuditEndpoint(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)
        self._root_ctx = _IngestionRootPatch(Path("/nonexistent"))
        self._root_ctx.__enter__()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self._root_ctx.__exit__()
        _stop_patches(*self._patches)

    def test_payment_coverage_audit_endpoint(self) -> None:
        before = _table_counts(self.sm)
        r = self.client.get("/api/sources/payment-coverage-audit")
        after = _table_counts(self.sm)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["status"], "OK")
        self.assertFalse(data["db_mutated"])
        self.assertEqual(len(data["domains"]), 6)
        self.assertEqual(before, after)


class TestOfficialPaymentCoverageAuditScript(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)
        self._root_ctx = _IngestionRootPatch(Path("/nonexistent"))
        self._root_ctx.__enter__()

    def tearDown(self) -> None:
        self._root_ctx.__exit__()
        _stop_patches(*self._patches)

    def test_module_main_prints_json_report(self) -> None:
        from io import StringIO

        from app.scripts.official_payment_coverage_audit import (
            STABLE_DOMAIN_AUDIT_KEYS,
            STABLE_REPORT_TOP_LEVEL_KEYS,
            STABLE_SUMMARY_KEYS,
            main,
        )

        before = _table_counts(self.sm)
        buf = StringIO()
        with unittest.mock.patch("sys.stdout", buf):
            rc = main(["--json"])
        after = _table_counts(self.sm)
        self.assertEqual(rc, 0)
        self.assertEqual(before, after)

        report = json.loads(buf.getvalue())
        self.assertFalse(report["db_mutated"])
        self.assertEqual(set(report.keys()), STABLE_REPORT_TOP_LEVEL_KEYS)
        self.assertEqual(len(report["domains"]), 6)
        self.assertEqual(set(report["summary"].keys()), STABLE_SUMMARY_KEYS)
        self.assertEqual(report["summary"]["domain_count"], 6)
        self.assertEqual(
            sum(report["summary"]["by_coverage_status"].values()),
            6,
        )
        self.assertEqual(
            sum(report["summary"]["by_recommended_next_action"].values()),
            6,
        )
        for domain in report["domains"]:
            self.assertEqual(set(domain.keys()), STABLE_DOMAIN_AUDIT_KEYS)

    def test_module_main_is_idempotent_on_table_counts(self) -> None:
        from io import StringIO

        from app.scripts.official_payment_coverage_audit import main

        before = _table_counts(self.sm)
        for _ in range(2):
            buf = StringIO()
            with unittest.mock.patch("sys.stdout", buf):
                self.assertEqual(main(["--json"]), 0)
            report = json.loads(buf.getvalue())
            self.assertFalse(report["db_mutated"])
        after = _table_counts(self.sm)
        self.assertEqual(before, after)

    def test_module_main_countervailing_supported_domain(self) -> None:
        from io import StringIO

        from app.scripts.official_payment_coverage_audit import main

        with _BundleFixture(
            _official_cv_payload(), rel_path="data/raw_normative/eec_countervailing.json"
        ) as (root, rel):
            with _IngestionRootPatch(root):
                run_countervailing_apply(rel_path=rel)
                buf = StringIO()
                with unittest.mock.patch("sys.stdout", buf):
                    self.assertEqual(main(["--json"]), 0)
                report = json.loads(buf.getvalue())
        cv = _domain(report, "EEC_COUNTERVAILING")
        self.assertEqual(cv["domain"], "countervailing")
        self.assertFalse(cv["domain_unsupported"])
        self.assertGreater(cv["official_row_count"], 0)
        self.assertTrue(cv["countervailing_source_url"])
        self.assertTrue(cv["countervailing_synced_at"])


if __name__ == "__main__":
    unittest.main()
