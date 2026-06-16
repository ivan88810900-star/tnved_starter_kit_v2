"""Тесты official payment coverage audit (issue #51)."""

from __future__ import annotations

import json
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.main import app
from app.models.core import HsRate, SourceStatus, SyncLog, TnvedEntry
from app.models.tnved import HsDutyRule, SpecialDuty
from app.services.normative_store import init_db
from app.services.official_payment_coverage_audit import (
    audit_official_domain,
    run_official_payment_coverage_audit,
)

try:
    from fastapi.testclient import TestClient

    _API_OK = True
except ImportError:
    _API_OK = False


_AUDIT_TABLES = [
    HsDutyRule.__table__,
    SpecialDuty.__table__,
    TnvedEntry.__table__,
    HsRate.__table__,
    SourceStatus.__table__,
    SyncLog.__table__,
]


def _memory_sessionmaker():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=_AUDIT_TABLES)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _start_audit_db_patches(sm: sessionmaker) -> tuple[unittest.mock._patch, ...]:
    patches = (
        unittest.mock.patch("app.services.official_payment_coverage_audit.SessionLocal", sm),
        unittest.mock.patch("app.services.payment_data_coverage.SessionLocal", sm),
        unittest.mock.patch("app.services.payment_source_ingestion.SessionLocal", sm),
    )
    for p in patches:
        p.start()
    return patches


def _stop_audit_db_patches(*patches: unittest.mock._patch) -> None:
    for p in reversed(patches):
        p.stop()


def _table_counts(sm: sessionmaker) -> dict[str, int]:
    with sm() as db:
        return {
            "hs_rates": db.query(HsRate).count(),
            "special_duties": db.query(SpecialDuty).count(),
            "source_status": db.query(SourceStatus).count(),
            "sync_log": db.query(SyncLog).count(),
        }


def _official_duty_bundle_payload() -> dict:
    return {
        "revision": "ett:2026-05-01",
        "format": "normative_bundle",
        "rates": [
            {
                "hs_code": "8471300000",
                "hs_prefix": "8471",
                "duty_rate": "0%",
                "vat_import_rate": 22.0,
                "source_revision": "ett:2026-05-01",
            }
        ],
    }


def _official_vat_bundle_payload() -> dict:
    return {
        "revision": "vat:2026-05-01",
        "format": "normative_bundle",
        "rates": [
            {
                "hs_code": "3004909200",
                "hs_prefix": "3004",
                "duty_rate": "5%",
                "vat_import_rate": 10.0,
                "vat_rule": "reduced10",
                "source_revision": "vat:2026-05-01",
            }
        ],
    }


class _BundleFixture:
    def __init__(self, rel_path: str, payload: dict) -> None:
        self.rel_path = rel_path
        self.payload = payload
        self._tmpdir: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> tuple[Path, str]:
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        full = root / self.rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(json.dumps(self.payload), encoding="utf-8")
        return root, self.rel_path

    def __exit__(self, *args: object) -> None:
        if self._tmpdir:
            self._tmpdir.cleanup()


class TestOfficialPaymentCoverageAuditEmptyDb(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_audit_db_patches(self.sm)
        import app.services.import_duty_ingestion as idi

        self._root_patch = unittest.mock.patch.object(idi, "_BACKEND_ROOT", Path("/nonexistent"))
        self._root_patch.start()

    def tearDown(self) -> None:
        self._root_patch.stop()
        _stop_audit_db_patches(*self._patches)

    def test_audit_detects_missing_source(self) -> None:
        audit = audit_official_domain("EEC_ETT")
        self.assertTrue(audit.missing_source)
        self.assertFalse(audit.local_bundle_present)
        self.assertEqual(audit.recommended_next_action, "acquire_official_source")
        self.assertIn(audit.coverage_status, ("missing", "incomplete"))

    def test_all_domains_reported(self) -> None:
        report = run_official_payment_coverage_audit()
        self.assertEqual(report["status"], "OK")
        self.assertFalse(report["db_mutated"])
        codes = {d["domain"] for d in report["domains"]}
        self.assertEqual(
            codes,
            {
                "EEC_ETT",
                "EEC_VAT",
                "EEC_EXCISE",
                "EEC_ANTI_DUMPING",
                "EEC_SPECIAL_SAFEGUARD",
                "EEC_COUNTERVAILING",
            },
        )

    def test_countervailing_domain_unsupported(self) -> None:
        cv = audit_official_domain("EEC_COUNTERVAILING")
        self.assertTrue(cv.domain_unsupported)
        self.assertTrue(cv.manual_review_required)
        self.assertEqual(cv.recommended_next_action, "manual_review_required")
        self.assertEqual(cv.backfill_situation, "domain_unsupported")
        self.assertNotEqual(cv.coverage_status, "present")


class TestOfficialPaymentCoverageAuditSourcePresentNotApplied(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_audit_db_patches(self.sm)

    def tearDown(self) -> None:
        _stop_audit_db_patches(*self._patches)

    def test_import_duty_bundle_present_recommends_run_apply(self) -> None:
        import app.services.import_duty_ingestion as idi
        import app.services.payment_source_ingestion as psi

        with _BundleFixture(
            "data/raw_normative/eec_ett_import_duty.json",
            _official_duty_bundle_payload(),
        ) as (root, _rel):
            with unittest.mock.patch.object(idi, "_BACKEND_ROOT", root), unittest.mock.patch.object(
                psi, "_BACKEND_ROOT", root
            ):
                audit = audit_official_domain("EEC_ETT")
        self.assertTrue(audit.local_bundle_present)
        self.assertTrue(audit.source_present_but_not_applied)
        self.assertEqual(audit.recommended_next_action, "run_apply")
        self.assertEqual(audit.backfill_situation, "official_source_present_not_applied")
        self.assertEqual(audit.official_row_count, 0)


class TestOfficialPaymentCoverageAuditOfficialProvenance(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        with self.sm() as db:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
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
            db.add(
                HsRate(
                    hs_code="8471300000",
                    hs_prefix="8471",
                    duty_rate="0%",
                    vat_import_rate=22.0,
                    source_revision="ett:2026-05-01",
                )
            )
            db.commit()
        self._patches = _start_audit_db_patches(self.sm)

    def tearDown(self) -> None:
        _stop_audit_db_patches(*self._patches)

    def test_official_rows_with_row_level_provenance(self) -> None:
        audit = audit_official_domain("EEC_ETT")
        self.assertEqual(audit.official_row_count, 1)
        self.assertEqual(audit.legacy_row_count, 0)
        self.assertFalse(audit.missing_source)
        self.assertIn(audit.coverage_status, ("present", "partial", "manual_review_required"))


class TestOfficialPaymentCoverageAuditLegacyRows(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
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
            db.add(
                HsRate(
                    hs_code="8471300000",
                    hs_prefix="8471",
                    duty_rate="0%",
                    vat_import_rate=22.0,
                    source_revision="ett:2026-05-01",
                )
            )
            db.commit()
        self._patches = _start_audit_db_patches(self.sm)

    def tearDown(self) -> None:
        _stop_audit_db_patches(*self._patches)

    def test_legacy_rows_not_counted_as_official(self) -> None:
        audit = audit_official_domain("EEC_ETT")
        self.assertEqual(audit.official_row_count, 1)
        self.assertEqual(audit.legacy_row_count, 1)
        self.assertTrue(audit.partial_rows or audit.legacy_row_count > 0)


class TestOfficialPaymentCoverageAuditStaleSourceStatus(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        with self.sm() as db:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            db.add(
                SourceStatus(
                    source_code="EEC_VAT",
                    source_name="EEC VAT",
                    source_url="https://eec.eaeunion.org/",
                    revision="vat:2026-05-01",
                    synced_at=now,
                    is_stale=True,
                )
            )
            db.commit()
        self._patches = _start_audit_db_patches(self.sm)

    def tearDown(self) -> None:
        _stop_audit_db_patches(*self._patches)

    def test_stale_source_status_recommends_refresh(self) -> None:
        audit = audit_official_domain("EEC_VAT")
        self.assertTrue(audit.stale_source_status)
        self.assertEqual(audit.recommended_next_action, "refresh_official_source")
        self.assertEqual(audit.backfill_situation, "stale_source_status")
        self.assertEqual(audit.coverage_status, "stale")


class TestOfficialPaymentCoverageAuditUnsafeRevision(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        with self.sm() as db:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            db.add(
                SourceStatus(
                    source_code="EEC_EXCISE",
                    source_name="EEC EXCISE",
                    source_url="https://www.nalog.gov.ru/",
                    revision="seed-2026-03",
                    synced_at=now,
                    is_stale=False,
                )
            )
            db.commit()
        self._patches = _start_audit_db_patches(self.sm)

    def tearDown(self) -> None:
        _stop_audit_db_patches(*self._patches)

    def test_unsafe_revision_detected(self) -> None:
        audit = audit_official_domain("EEC_EXCISE")
        self.assertTrue(audit.unsafe_revision)
        self.assertIn(
            audit.recommended_next_action,
            ("manual_review_required", "refresh_official_source"),
        )
        self.assertEqual(audit.backfill_situation, "unsafe_revision")


class TestOfficialPaymentCoverageAuditUnsafeUrl(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        with self.sm() as db:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            db.add(
                SourceStatus(
                    source_code="EEC_ANTI_DUMPING",
                    source_name="EEC AD",
                    source_url="https://example.com/fake-ad",
                    revision="anti-dumping:2026-05-01",
                    synced_at=now,
                    is_stale=False,
                )
            )
            db.commit()
        self._patches = _start_audit_db_patches(self.sm)

    def tearDown(self) -> None:
        _stop_audit_db_patches(*self._patches)

    def test_unsafe_url_detected(self) -> None:
        audit = audit_official_domain("EEC_ANTI_DUMPING")
        self.assertTrue(audit.unsafe_url)
        self.assertEqual(audit.recommended_next_action, "manual_review_required")
        self.assertEqual(audit.backfill_situation, "unsafe_url")


class TestOfficialPaymentCoverageAuditNoMutation(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_audit_db_patches(self.sm)

    def tearDown(self) -> None:
        _stop_audit_db_patches(*self._patches)

    def test_audit_does_not_mutate_db(self) -> None:
        before = _table_counts(self.sm)
        report = run_official_payment_coverage_audit()
        after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertFalse(report["db_mutated"])


class TestOfficialPaymentCoverageAuditTradeRemedies(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        with self.sm() as db:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            db.add(
                SourceStatus(
                    source_code="EEC_ANTI_DUMPING",
                    source_name="EEC AD",
                    source_url="https://eec.eaeunion.org/",
                    revision="anti-dumping:2026-05-01",
                    synced_at=now,
                    is_stale=False,
                )
            )
            db.add(
                SpecialDuty(
                    hs_code_prefix="8517",
                    origin_country="CN",
                    rate_percent=15.0,
                    measure_type="anti_dumping",
                    source_code="EEC_ANTI_DUMPING",
                    source_revision="anti-dumping:2026-05-01",
                )
            )
            db.commit()
        self._patches = _start_audit_db_patches(self.sm)

    def tearDown(self) -> None:
        _stop_audit_db_patches(*self._patches)

    def test_trade_remedies_manual_review_without_completeness_proof(self) -> None:
        audit = audit_official_domain("EEC_ANTI_DUMPING")
        self.assertEqual(audit.coverage_status, "manual_review_required")
        self.assertTrue(audit.manual_review_required)
        self.assertEqual(audit.backfill_situation, "completeness_not_verified")
        self.assertNotEqual(audit.coverage_status, "present")
        self.assertTrue(any("completeness" in g.lower() for g in audit.known_gaps))


class TestOfficialPaymentCoverageAuditReapplyProvenance(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        with self.sm() as db:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            db.add(
                SourceStatus(
                    source_code="EEC_VAT",
                    source_name="EEC VAT",
                    source_url="https://eec.eaeunion.org/",
                    revision="vat:2026-05-01",
                    synced_at=now,
                    is_stale=False,
                )
            )
            db.add(
                HsRate(
                    hs_code="3004909200",
                    hs_prefix="3004",
                    duty_rate="5%",
                    vat_import_rate=10.0,
                    vat_rule="reduced10",
                    source_revision="seed",
                )
            )
            db.commit()
        self._patches = _start_audit_db_patches(self.sm)

    def tearDown(self) -> None:
        _stop_audit_db_patches(*self._patches)

    def test_proven_status_without_row_marker_recommends_reapply(self) -> None:
        audit = audit_official_domain("EEC_VAT")
        self.assertEqual(audit.legacy_row_count, 1)
        self.assertEqual(audit.official_row_count, 0)
        self.assertEqual(audit.recommended_next_action, "reapply_official_bundle")
        self.assertEqual(audit.backfill_situation, "applied_no_row_provenance")


class TestOfficialPaymentCoverageAuditParserFailed(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_audit_db_patches(self.sm)

    def tearDown(self) -> None:
        _stop_audit_db_patches(*self._patches)

    def test_malformed_bundle_parser_failed(self) -> None:
        import app.services.import_duty_ingestion as idi
        import app.services.payment_source_ingestion as psi

        bad_payload = {"revision": "ett:2026-05-01", "rates": "not-a-list"}
        with _BundleFixture(
            "data/raw_normative/eec_ett_import_duty.json",
            bad_payload,
        ) as (root, _rel):
            with unittest.mock.patch.object(idi, "_BACKEND_ROOT", root), unittest.mock.patch.object(
                psi, "_BACKEND_ROOT", root
            ):
                audit = audit_official_domain("EEC_ETT")
        self.assertTrue(audit.parser_failed)
        self.assertEqual(audit.coverage_status, "parser_failed")
        self.assertEqual(audit.recommended_next_action, "manual_review_required")


class TestOfficialPaymentCoverageAuditRecommendations(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_audit_db_patches(self.sm)

    def tearDown(self) -> None:
        _stop_audit_db_patches(*self._patches)

    def test_recommendation_acquire_official_source(self) -> None:
        import app.services.excise_ingestion as ei

        with unittest.mock.patch.object(ei, "_BACKEND_ROOT", Path("/nonexistent")):
            audit = audit_official_domain("EEC_EXCISE")
        self.assertEqual(audit.recommended_next_action, "acquire_official_source")

    def test_recommendation_refresh_official_source(self) -> None:
        with self.sm() as db:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            db.add(
                SourceStatus(
                    source_code="EEC_SPECIAL_SAFEGUARD",
                    source_name="EEC SS",
                    source_url="https://eec.eaeunion.org/",
                    revision="special-safeguard:2026-05-01",
                    synced_at=now,
                    is_stale=True,
                )
            )
            db.commit()
        audit = audit_official_domain("EEC_SPECIAL_SAFEGUARD")
        self.assertEqual(audit.recommended_next_action, "refresh_official_source")


@unittest.skipUnless(_API_OK, "fastapi not installed")
class TestOfficialPaymentCoverageAuditApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        cls.client = TestClient(app)

    def test_payment_coverage_audit_endpoint(self) -> None:
        r = self.client.get("/api/sources/payment-coverage-audit")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "OK")
        self.assertFalse(body["db_mutated"])
        self.assertIn("domains", body)
        self.assertIn("summary", body)
        self.assertIn("EEC_ETT", body["summary"])
