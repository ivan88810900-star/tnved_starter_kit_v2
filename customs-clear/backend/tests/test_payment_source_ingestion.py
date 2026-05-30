"""Тесты ingestion plan/dry-run официальных платёжных источников (issue #35)."""

from __future__ import annotations

import unittest
import unittest.mock
from datetime import datetime, timezone

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.main import app
from app.models.core import ExchangeRate, GeoSpecialDuty, HsRate, SourceStatus, SyncLog, TnvedEntry
from app.models.tnved import Chapter, Commodity, HsDutyRule, Section, SpecialDuty, VatPreference
from app.services.normative_store import init_db
from app.services.payment_source_ingestion import (
    parse_normative_bundle_file,
    run_payment_source_ingestion_dry_run,
    run_payment_source_ingestion_plan,
)

try:
    from fastapi.testclient import TestClient

    _API_OK = True
except ImportError:
    _API_OK = False


_INGESTION_TABLES = [
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
    Base.metadata.create_all(bind=engine, tables=_INGESTION_TABLES)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _start_db_patches(sm: sessionmaker) -> tuple[unittest.mock._patch, ...]:
    patches = (
        unittest.mock.patch("app.services.payment_data_coverage.SessionLocal", sm),
        unittest.mock.patch("app.services.payment_data_normalization.SessionLocal", sm),
        unittest.mock.patch("app.services.payment_source_ingestion.SessionLocal", sm),
        unittest.mock.patch("app.services.normative_store.SessionLocal", sm),
    )
    for p in patches:
        p.start()
    return patches


def _stop_db_patches(*patches: unittest.mock._patch) -> None:
    for p in reversed(patches):
        p.stop()


def _table_counts(sm: sessionmaker) -> dict[str, int]:
    with sm() as db:
        return {
            "hs_rates": db.query(HsRate).count(),
            "hs_duty_rules": db.query(HsDutyRule).count(),
            "vat_preferences": db.query(VatPreference).count(),
            "special_duties": db.query(SpecialDuty).count(),
            "geo_special_duties": db.query(GeoSpecialDuty).count(),
            "source_status": db.query(SourceStatus).count(),
            "sync_log": db.query(SyncLog).count(),
        }


def _add_eec_proven(db, revision: str = "ett:2026-05-01") -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(
        SourceStatus(
            source_code="EEC_ETT",
            source_name="EEC ETT test",
            source_url="https://eec.eaeunion.org/",
            revision=revision,
            synced_at=now,
            is_stale=False,
            note="test",
        )
    )


class TestPaymentIngestionEmptyDb(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_db_patches(self.sm)

    def tearDown(self) -> None:
        _stop_db_patches(*self._patches)

    def test_plan_does_not_mutate_db(self) -> None:
        before = _table_counts(self.sm)
        plan = run_payment_source_ingestion_plan()
        after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertFalse(plan["db_mutated"])
        self.assertEqual(plan["mode"], "plan")

    def test_dry_run_does_not_mutate_db(self) -> None:
        before = _table_counts(self.sm)
        report = run_payment_source_ingestion_dry_run()
        after = _table_counts(self.sm)
        self.assertEqual(before, after)
        self.assertTrue(report["dry_run"])
        self.assertFalse(report["db_mutated"])

    def test_missing_official_source_has_blockers(self) -> None:
        report = run_payment_source_ingestion_plan()
        excise = report["domains"]["excise"]
        self.assertIn(excise["readiness"], ("missing_source", "manual_review_required", "blocked"))
        self.assertTrue(excise["manual_review_required"])
        self.assertGreater(len(excise["blockers"]), 0)

    def test_links_normalization_status(self) -> None:
        report = run_payment_source_ingestion_plan()
        self.assertIn("normalization_link", report)
        self.assertIn("overall_readiness", report["normalization_link"])
        duty = report["domains"]["import_duty"]
        self.assertEqual(duty["normalization_status"], "missing")


class TestPaymentIngestionSeedBlocked(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        with self.sm() as db:
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
            db.add(
                GeoSpecialDuty(
                    hs_code_prefix="7208",
                    country_iso="UA",
                    measure_type="anti_dumping",
                    duty_rate="15%",
                    document_basis="TEST-SEED",
                )
            )
            db.commit()
        self._patches = _start_db_patches(self.sm)

    def tearDown(self) -> None:
        _stop_db_patches(*self._patches)

    def test_seed_fixture_candidate_blocked(self) -> None:
        report = run_payment_source_ingestion_dry_run()
        geo_candidates = [
            c
            for c in report["domains"]["anti_dumping"]["candidates"]
            if c["source_code"] == "geo_special_duties_seed"
        ]
        self.assertEqual(len(geo_candidates), 1)
        cand = geo_candidates[0]
        self.assertIn(cand["provenance_kind"], ("legacy_seed", "seed"))
        self.assertEqual(cand["readiness"], "blocked")

    def test_no_ready_to_ingest_for_seed_domains(self) -> None:
        report = run_payment_source_ingestion_dry_run()
        for domain in ("import_duty", "vat", "excise", "anti_dumping"):
            self.assertNotEqual(report["domains"][domain]["readiness"], "ready_to_ingest")
        self.assertNotEqual(report["overall_readiness"], "ready_to_ingest")


class TestPaymentIngestionExampleBundleNotOfficial(unittest.TestCase):
    def test_normative_bundle_example_manual_review(self) -> None:
        parsed = parse_normative_bundle_file("data/normative_bundle.example.json")
        self.assertEqual(parsed["status"], "manual_review_required")
        self.assertIn(parsed.get("reason"), ("non_official_bundle_revision",))

    def test_example_bundle_candidate_not_ready(self) -> None:
        sm = _memory_sessionmaker()
        patches = _start_db_patches(sm)
        try:
            report = run_payment_source_ingestion_dry_run()
        finally:
            _stop_db_patches(*patches)
        bundle_cands = [
            c
            for c in report["domains"]["import_duty"]["candidates"]
            if c["source_code"] == "normative_bundle_example"
        ]
        self.assertEqual(len(bundle_cands), 1)
        self.assertNotEqual(bundle_cands[0]["readiness"], "ready_to_ingest")
        self.assertIn(bundle_cands[0]["provenance_kind"], ("legacy_seed", "seed", "fallback"))


class TestPaymentIngestionOfficialProvenanceRequired(unittest.TestCase):
    def test_eec_seed_revision_not_ready(self) -> None:
        sm = _memory_sessionmaker()
        base = 9_500_000_000
        with sm() as db:
            _add_eec_proven(db, revision="seed-2026-03")
            for i in range(120):
                code = f"{base + i:010d}"
                db.add(TnvedEntry(hs_code=code, level=10, title=f"t {i}"))
                db.add(
                    HsRate(
                        hs_code=code,
                        hs_prefix=code[:4],
                        duty_rate="5%",
                        vat_import_rate=22.0,
                        source_revision="ett:2026-05-01",
                    )
                )
            db.commit()
        patches = _start_db_patches(sm)
        try:
            report = run_payment_source_ingestion_plan()
        finally:
            _stop_db_patches(*patches)

        eec_cands = [
            c
            for c in report["domains"]["import_duty"]["candidates"]
            if c["source_code"] == "eec_ett_tariff"
        ]
        self.assertEqual(len(eec_cands), 1)
        self.assertNotEqual(eec_cands[0]["readiness"], "ready_to_ingest")
        self.assertIn(eec_cands[0]["provenance_kind"], ("seed", "fallback"))

    def test_eec_official_proven_still_conservative_without_full_normalization(self) -> None:
        sm = _memory_sessionmaker()
        base = 9_600_000_000
        with sm() as db:
            _add_eec_proven(db, revision="ett:2026-05-01")
            for i in range(120):
                code = f"{base + i:010d}"
                db.add(TnvedEntry(hs_code=code, level=10, title=f"o {i}"))
                db.add(
                    HsRate(
                        hs_code=code,
                        hs_prefix=code[:4],
                        duty_rate="5%",
                        vat_import_rate=22.0,
                        source_revision="ett:2026-05-01",
                    )
                )
            db.commit()
        patches = _start_db_patches(sm)
        try:
            report = run_payment_source_ingestion_dry_run()
        finally:
            _stop_db_patches(*patches)

        duty = report["domains"]["import_duty"]
        self.assertIn("normalization_status", duty)
        eec = next(c for c in duty["candidates"] if c["source_code"] == "eec_ett_tariff")
        self.assertEqual(eec["provenance_kind"], "official")
        if duty["normalization_status"] == "present":
            self.assertEqual(eec["readiness"], "ready_to_ingest")
        else:
            self.assertNotEqual(duty["readiness"], "ready_to_ingest")


class TestPaymentIngestionStaleSourceStatusBlocked(unittest.TestCase):
    def test_stale_source_status_not_ready_even_if_normalization_present(self) -> None:
        sm = _memory_sessionmaker()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with sm() as db:
            db.add(
                SourceStatus(
                    source_code="EEC_ODATA",
                    source_name="EEC OData test",
                    source_url="https://opendata.eaeunion.org/",
                    revision="odata:2026-05",
                    synced_at=now,
                    is_stale=True,
                    note="stale official contour",
                )
            )
            db.commit()
        fake_norm = {
            "domains": {"vat": {"coverage_status": "present"}},
            "overall_readiness": "present",
            "generated_at": now.isoformat(),
        }
        patches = _start_db_patches(sm)
        norm_patch = unittest.mock.patch(
            "app.services.payment_source_ingestion.run_payment_data_normalization_report",
            return_value=fake_norm,
        )
        norm_patch.start()
        try:
            report = run_payment_source_ingestion_dry_run()
        finally:
            norm_patch.stop()
            _stop_db_patches(*patches)
        vat = report["domains"]["vat"]
        cand = next(
            c for c in vat["candidates"] if c["source_code"] == "eec_odata_vat_preferences"
        )
        self.assertEqual(cand["provenance_kind"], "official")
        self.assertTrue(cand["source_status_stale"])
        self.assertNotEqual(cand["readiness"], "ready_to_ingest")
        self.assertTrue(cand["manual_review_required"])
        self.assertTrue(any("source_status_stale" in b for b in cand["blockers"]))


class TestPaymentIngestionNonOfficialRevisionPrefix(unittest.TestCase):
    def _run_with_eec_revision(self, revision: str) -> dict:
        sm = _memory_sessionmaker()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with sm() as db:
            db.add(
                SourceStatus(
                    source_code="EEC_ETT",
                    source_name="EEC ETT test",
                    source_url="https://eec.eaeunion.org/",
                    revision=revision,
                    synced_at=now,
                    is_stale=False,
                )
            )
            db.commit()
        patches = _start_db_patches(sm)
        try:
            report = run_payment_source_ingestion_plan()
        finally:
            _stop_db_patches(*patches)
        duty = report["domains"]["import_duty"]
        return next(c for c in duty["candidates"] if c["source_code"] == "eec_ett_tariff")

    def test_demo_revision_not_official(self) -> None:
        cand = self._run_with_eec_revision("demo-2026")
        self.assertNotEqual(cand["provenance_kind"], "official")
        self.assertNotEqual(cand["readiness"], "ready_to_ingest")

    def test_example_revision_not_official(self) -> None:
        cand = self._run_with_eec_revision("example-2026")
        self.assertNotEqual(cand["provenance_kind"], "official")
        self.assertNotEqual(cand["readiness"], "ready_to_ingest")

    def test_test_prefix_revision_not_official(self) -> None:
        cand = self._run_with_eec_revision("test-2026")
        self.assertNotEqual(cand["provenance_kind"], "official")
        self.assertNotEqual(cand["readiness"], "ready_to_ingest")


class TestPaymentIngestionCommercialMirrorBlocked(unittest.TestCase):
    def test_tws_mirror_blocked(self) -> None:
        sm = _memory_sessionmaker()
        patches = _start_db_patches(sm)
        try:
            report = run_payment_source_ingestion_plan()
        finally:
            _stop_db_patches(*patches)
        tws = next(
            c
            for c in report["domains"]["import_duty"]["candidates"]
            if c["source_code"] == "tws_commercial_tariff"
        )
        self.assertEqual(tws["provenance_kind"], "commercial_mirror")
        self.assertEqual(tws["readiness"], "blocked")


class TestPaymentIngestionDryRunRowCounts(unittest.TestCase):
    def test_dry_run_reports_affected_tables(self) -> None:
        sm = _memory_sessionmaker()
        with sm() as db:
            db.add(
                HsRate(
                    hs_code="8471300000",
                    hs_prefix="8471",
                    duty_rate="5%",
                    vat_import_rate=22.0,
                    source_revision="seed",
                )
            )
            db.commit()
        patches = _start_db_patches(sm)
        try:
            report = run_payment_source_ingestion_dry_run()
        finally:
            _stop_db_patches(*patches)
        duty = report["domains"]["import_duty"]
        self.assertIn("hs_rates", duty["affected_tables"])
        self.assertGreater(len(duty["candidates"]), 0)


@unittest.skipUnless(_API_OK, "fastapi not installed")
class TestPaymentIngestionApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        cls.client = TestClient(app)

    def test_plan_endpoint(self) -> None:
        r = self.client.get("/api/sources/payment-ingestion/plan")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "OK")
        self.assertFalse(body["db_mutated"])
        self.assertIn("domains", body)
        self.assertIn("import_duty", body["domains"])

    def test_dry_run_endpoint(self) -> None:
        r = self.client.post("/api/sources/payment-ingestion/dry-run")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["dry_run"])
        self.assertFalse(body["db_mutated"])

    def test_registry_endpoint(self) -> None:
        r = self.client.get("/api/sources/payment-ingestion/registry")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "OK")
        self.assertGreater(len(body["sources"]), 0)
