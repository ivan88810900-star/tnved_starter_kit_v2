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
        self.assertEqual(cv["backfill_situation"], "missing_official_source")
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
        self.assertEqual(cv["backfill_situation"], "official_source_present_not_applied")


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
        self.assertEqual(cv["backfill_situation"], "unsafe_url")


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
        self.assertEqual(cv["backfill_situation"], "applied_no_row_provenance")


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
        self.assertIs(cv["configured_official_source"], True)
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


_VALID_DIAGNOSTIC_SITUATIONS = frozenset(
    {
        "missing_official_source",
        "official_source_present_not_applied",
        "applied_no_row_provenance",
        "stale_source_status",
        "unsafe_revision",
        "unsafe_url",
        "parser_failure",
        "partial_rows",
        "unsupported_domain",
        "ok",
        "completeness_not_verified",
    }
)

_VALID_NEXT_ACTIONS = frozenset(
    {
        "run_apply",
        "acquire_official_source",
        "reapply_official_bundle",
        "refresh_official_source",
        "manual_review_required",
        "none",
    }
)


class TestOfficialPaymentCoverageAuditFieldContract(unittest.TestCase):
    """Verifies field types and enum contract per Issue #55 requirements."""

    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_patches(self.sm)
        self._root_ctx = _IngestionRootPatch(Path("/nonexistent"))
        self._root_ctx.__enter__()

    def tearDown(self) -> None:
        self._root_ctx.__exit__()
        _stop_patches(*self._patches)

    def test_db_mutated_is_false(self) -> None:
        report = run_official_payment_coverage_audit()
        self.assertIs(report["db_mutated"], False)

    def test_exactly_six_domains_by_expected_key(self) -> None:
        report = run_official_payment_coverage_audit()
        self.assertEqual(len(report["domains"]), 6)
        domain_keys = {d["domain_key"] for d in report["domains"]}
        self.assertEqual(
            domain_keys,
            {
                "EEC_ETT",
                "EEC_VAT",
                "EEC_EXCISE",
                "EEC_ANTI_DUMPING",
                "EEC_SPECIAL_SAFEGUARD",
                "EEC_COUNTERVAILING",
            },
        )

    def test_configured_official_source_is_bool_for_all_domains(self) -> None:
        report = run_official_payment_coverage_audit()
        for d in report["domains"]:
            self.assertIsInstance(
                d["configured_official_source"],
                bool,
                msg=f"{d['domain_key']}: configured_official_source must be bool",
            )

    def test_expected_official_source_is_non_empty_string_for_all_domains(self) -> None:
        report = run_official_payment_coverage_audit()
        for d in report["domains"]:
            self.assertIsInstance(
                d["expected_official_source"],
                str,
                msg=f"{d['domain_key']}: expected_official_source must be str",
            )
            self.assertTrue(
                d["expected_official_source"],
                msg=f"{d['domain_key']}: expected_official_source must be non-empty",
            )

    def test_backfill_situation_uses_diagnostic_values_for_all_domains(self) -> None:
        report = run_official_payment_coverage_audit()
        for d in report["domains"]:
            self.assertIn(
                d["backfill_situation"],
                _VALID_DIAGNOSTIC_SITUATIONS,
                msg=f"{d['domain_key']}: backfill_situation '{d['backfill_situation']}' not in diagnostic enum",
            )

    def test_recommended_next_action_uses_action_values_for_all_domains(self) -> None:
        report = run_official_payment_coverage_audit()
        for d in report["domains"]:
            self.assertIn(
                d["recommended_next_action"],
                _VALID_NEXT_ACTIONS,
                msg=f"{d['domain_key']}: recommended_next_action '{d['recommended_next_action']}' not in action enum",
            )

    def test_summary_has_status_and_action_groups(self) -> None:
        report = run_official_payment_coverage_audit()
        summary = report["summary"]
        self.assertIn("by_coverage_status", summary)
        self.assertIn("by_recommended_next_action", summary)
        self.assertEqual(sum(summary["by_coverage_status"].values()), 6)
        self.assertEqual(sum(summary["by_recommended_next_action"].values()), 6)


class TestCoverageTable(unittest.TestCase):
    """Issue #51 — build_coverage_table: structure, types, pct semantics."""

    def setUp(self) -> None:
        from app.services.official_payment_coverage_audit import build_coverage_table

        sm = _memory_sessionmaker()
        self._patches = _start_patches(sm)
        self._root_ctx = _IngestionRootPatch(Path("/nonexistent"))
        self._root_ctx.__enter__()
        self._table = build_coverage_table()

    def tearDown(self) -> None:
        self._root_ctx.__exit__()
        _stop_patches(*self._patches)

    def test_table_has_six_rows(self) -> None:
        self.assertEqual(len(self._table["rows"]), 6)

    def test_table_db_mutated_is_false(self) -> None:
        self.assertFalse(self._table["db_mutated"])

    def test_table_has_text_table_string(self) -> None:
        self.assertIsInstance(self._table["text_table"], str)
        self.assertIn("Domain", self._table["text_table"])
        self.assertIn("Coverage %", self._table["text_table"])

    def test_coverage_pct_zero_when_no_rows(self) -> None:
        for row in self._table["rows"]:
            if row["in_db"] == 0:
                self.assertEqual(row["coverage_pct"], 0.0)

    def test_coverage_pct_in_range(self) -> None:
        for row in self._table["rows"]:
            self.assertGreaterEqual(row["coverage_pct"], 0.0)
            self.assertLessEqual(row["coverage_pct"], 100.0)

    def test_table_rows_have_required_keys(self) -> None:
        required = {
            "domain_key", "domain", "in_db", "official", "legacy",
            "coverage_pct", "coverage_status", "recommended_next_action",
            "backfill_situation",
        }
        for row in self._table["rows"]:
            self.assertTrue(required.issubset(row.keys()), msg=f"Missing keys in row: {row}")

    def test_table_domain_keys_are_expected_six(self) -> None:
        expected = {"EEC_ETT", "EEC_VAT", "EEC_EXCISE", "EEC_ANTI_DUMPING", "EEC_SPECIAL_SAFEGUARD", "EEC_COUNTERVAILING"}
        got = {r["domain_key"] for r in self._table["rows"]}
        self.assertEqual(got, expected)

    def test_table_official_le_in_db(self) -> None:
        for row in self._table["rows"]:
            self.assertLessEqual(
                row["official"], row["in_db"],
                msg=f"{row['domain_key']}: official ({row['official']}) > in_db ({row['in_db']})",
            )


class TestBackfillPlan(unittest.TestCase):
    """Issue #51 — build_backfill_plan: dry-run, priority ordering, completeness."""

    def setUp(self) -> None:
        from app.services.official_payment_coverage_audit import build_backfill_plan

        sm = _memory_sessionmaker()
        self._patches = _start_patches(sm)
        self._root_ctx = _IngestionRootPatch(Path("/nonexistent"))
        self._root_ctx.__enter__()
        self._plan = build_backfill_plan()

    def tearDown(self) -> None:
        self._root_ctx.__exit__()
        _stop_patches(*self._patches)

    def test_plan_dry_run_true(self) -> None:
        self.assertTrue(self._plan["dry_run"])

    def test_plan_db_mutated_false(self) -> None:
        self.assertFalse(self._plan["db_mutated"])

    def test_plan_total_domains_six(self) -> None:
        self.assertEqual(self._plan["total_domains"], 6)

    def test_plan_has_all_six_domain_keys(self) -> None:
        expected = {"EEC_ETT", "EEC_VAT", "EEC_EXCISE", "EEC_ANTI_DUMPING", "EEC_SPECIAL_SAFEGUARD", "EEC_COUNTERVAILING"}
        got = {item["domain_key"] for item in self._plan["plan"]}
        self.assertEqual(got, expected)

    def test_plan_sorted_by_priority(self) -> None:
        priorities = [item["priority"] for item in self._plan["plan"]]
        self.assertEqual(priorities, sorted(priorities), msg="Plan items must be sorted ascending by priority")

    def test_plan_domains_needing_action_count(self) -> None:
        actionable = [i for i in self._plan["plan"] if i["action"] != "none"]
        self.assertEqual(self._plan["domains_needing_action"], len(actionable))

    def test_plan_action_values_are_valid(self) -> None:
        valid = {"acquire_official_source", "run_apply", "reapply_official_bundle",
                 "refresh_official_source", "manual_review_required", "none"}
        for item in self._plan["plan"]:
            self.assertIn(item["action"], valid, msg=f"{item['domain_key']}: invalid action '{item['action']}'")

    def test_plan_backfill_situation_values_are_valid(self) -> None:
        valid = {
            "missing_official_source", "official_source_present_not_applied",
            "applied_no_row_provenance", "stale_source_status", "unsafe_revision",
            "unsafe_url", "parser_failure", "partial_rows", "unsupported_domain", "ok",
            "completeness_not_verified",
        }
        for item in self._plan["plan"]:
            self.assertIn(
                item["backfill_situation"], valid,
                msg=f"{item['domain_key']}: invalid backfill_situation '{item['backfill_situation']}'",
            )

    def test_plan_acquire_before_run_apply(self) -> None:
        from app.services.official_payment_coverage_audit import _ACTION_PRIORITY

        self.assertLess(
            _ACTION_PRIORITY["acquire_official_source"],
            _ACTION_PRIORITY["run_apply"],
        )
        self.assertLess(
            _ACTION_PRIORITY["run_apply"],
            _ACTION_PRIORITY["reapply_official_bundle"],
        )


class TestCoverageBackfillScript(unittest.TestCase):
    """Issue #51 — app/scripts/coverage_backfill_plan module: prints table + plan."""

    def setUp(self) -> None:
        sm = _memory_sessionmaker()
        self._patches = _start_patches(sm)
        self._root_ctx = _IngestionRootPatch(Path("/nonexistent"))
        self._root_ctx.__enter__()

    def tearDown(self) -> None:
        self._root_ctx.__exit__()
        _stop_patches(*self._patches)

    def test_script_json_output_valid(self) -> None:
        import io
        from app.scripts.coverage_backfill_plan import main

        with unittest.mock.patch("sys.argv", ["coverage_backfill_plan", "--json"]):
            with unittest.mock.patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                rc = main()
        self.assertEqual(rc, 0)
        output = mock_out.getvalue()
        parsed = json.loads(output)
        self.assertIn("coverage_table", parsed)
        self.assertIn("backfill_plan", parsed)
        self.assertFalse(parsed["coverage_table"]["db_mutated"])
        self.assertTrue(parsed["backfill_plan"]["dry_run"])

    def test_script_text_output_contains_domain_keys(self) -> None:
        import io
        from app.scripts.coverage_backfill_plan import main

        with unittest.mock.patch("sys.argv", ["coverage_backfill_plan"]):
            with unittest.mock.patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                rc = main()
        self.assertEqual(rc, 0)
        output = mock_out.getvalue()
        for key in ("EEC_ETT", "EEC_VAT", "EEC_EXCISE", "EEC_ANTI_DUMPING"):
            self.assertIn(key, output, msg=f"Expected domain key {key!r} in script output")


if __name__ == "__main__":
    unittest.main()
