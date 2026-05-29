"""Тесты нормализации / readiness платёжных источников (issue #33)."""

from __future__ import annotations

import unittest
import unittest.mock
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.main import app
from app.models.core import GeoSpecialDuty, HsRate, SourceStatus, SyncLog, TnvedEntry
from app.models.tnved import Commodity, HsDutyRule, Section, SpecialDuty, VatPreference
from app.services.normative_store import init_db
from app.services.payment_data_normalization import (
    normalize_anti_dumping,
    normalize_excise,
    normalize_import_duty,
    normalize_vat,
    run_payment_data_normalization_report,
)

try:
    from fastapi.testclient import TestClient

    _API_OK = True
except ImportError:
    _API_OK = False


_NORM_TABLES = [
    Section.__table__,
    Commodity.__table__,
    HsDutyRule.__table__,
    SpecialDuty.__table__,
    VatPreference.__table__,
    TnvedEntry.__table__,
    HsRate.__table__,
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
    Base.metadata.create_all(bind=engine, tables=_NORM_TABLES)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _start_db_patches(sm: sessionmaker) -> tuple[unittest.mock._patch, unittest.mock._patch, unittest.mock._patch]:
    p_cov = unittest.mock.patch("app.services.payment_data_coverage.SessionLocal", sm)
    p_norm = unittest.mock.patch("app.services.payment_data_normalization.SessionLocal", sm)
    p_store = unittest.mock.patch("app.services.normative_store.SessionLocal", sm)
    p_cov.start()
    p_norm.start()
    p_store.start()
    return p_cov, p_norm, p_store


def _stop_db_patches(*patches: unittest.mock._patch) -> None:
    for p in reversed(patches):
        p.stop()


def _add_eec_proven(db) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(
        SourceStatus(
            source_code="EEC_ETT",
            source_name="EEC ETT test",
            source_url="https://eec.eaeunion.org/",
            revision="ett:2026-05-01",
            synced_at=now,
            is_stale=False,
            note="test",
        )
    )


class TestPaymentNormalizationEmptyDb(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patches = _start_db_patches(self.sm)

    def tearDown(self) -> None:
        _stop_db_patches(*self._patches)

    def test_empty_db_domains_conservative(self) -> None:
        report = run_payment_data_normalization_report()
        self.assertEqual(report["status"], "OK")
        domains = report["domains"]
        self.assertEqual(domains["import_duty"]["coverage_status"], "missing")
        self.assertEqual(domains["vat"]["coverage_status"], "missing")
        self.assertIn(
            domains["excise"]["coverage_status"],
            ("missing", "manual_review_required"),
        )
        self.assertEqual(domains["anti_dumping"]["coverage_status"], "missing")
        self.assertTrue(domains["excise"]["manual_review_required"])
        self.assertNotEqual(domains["import_duty"]["coverage_status"], "present")


class TestPaymentNormalizationPartialDuty(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        with self.sm() as db:
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
        self._patches = _start_db_patches(self.sm)

    def tearDown(self) -> None:
        _stop_db_patches(*self._patches)

    def test_partial_duty_not_present(self) -> None:
        duty = normalize_import_duty()
        self.assertEqual(duty.coverage_status, "partial")
        self.assertNotEqual(duty.coverage_status, "present")
        self.assertTrue(duty.manual_review_required)


class TestPaymentNormalizationFullDutyPresent(unittest.TestCase):
    """Полное покрытие + EEC proven + не-seed → present."""

    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        base = 7_000_000_000
        with self.sm() as db:
            _add_eec_proven(db)
            for i in range(120):
                code = f"{base + i:010d}"
                db.add(TnvedEntry(hs_code=code, level=10, title=f"item {i}"))
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
        self._patches = _start_db_patches(self.sm)

    def tearDown(self) -> None:
        _stop_db_patches(*self._patches)

    def test_present_when_all_catalog_codes_covered(self) -> None:
        duty = normalize_import_duty()
        self.assertEqual(duty.coverage_status, "present")
        self.assertFalse(duty.manual_review_required)
        self.assertEqual(duty.mapped_hs_codes, 120)
        self.assertEqual(duty.total_catalog_codes, 120)


class TestPaymentNormalizationVat(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        with self.sm() as db:
            _add_eec_proven(db)
            db.add(
                HsRate(
                    hs_code="3004909200",
                    hs_prefix="3004",
                    duty_rate="0%",
                    vat_import_rate=10.0,
                    vat_rule="reduced10",
                    source_revision="ett:2026-05-01",
                )
            )
            db.add(
                VatPreference(
                    hs_code_prefix="3004",
                    vat_rate=10,
                    decree_info="TEST-PP",
                )
            )
            db.commit()
        self._patches = _start_db_patches(self.sm)

    def tearDown(self) -> None:
        _stop_db_patches(*self._patches)

    def test_vat_present_with_preferences(self) -> None:
        vat = normalize_vat()
        self.assertEqual(vat.coverage_status, "present")
        self.assertFalse(vat.manual_review_required)

    def test_vat_partial_without_preferences(self) -> None:
        with self.sm() as db:
            db.query(VatPreference).delete()
            rate = db.query(HsRate).filter(HsRate.hs_code == "3004909200").one()
            rate.vat_import_rate = 22.0
            rate.vat_rule = "none"
            db.commit()
        vat = normalize_vat()
        self.assertEqual(vat.coverage_status, "partial")
        self.assertTrue(vat.manual_review_required)


class TestPaymentNormalizationExciseAndAntiDumping(unittest.TestCase):
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
                SpecialDuty(
                    hs_code_prefix="8517",
                    origin_country="CN",
                    rate_percent=15.0,
                    regulatory_act="TEST-AD",
                )
            )
            db.commit()
        self._patches = _start_db_patches(self.sm)

    def tearDown(self) -> None:
        _stop_db_patches(*self._patches)

    def test_excise_never_present_on_seed(self) -> None:
        excise = normalize_excise()
        self.assertNotEqual(excise.coverage_status, "present")
        self.assertTrue(excise.manual_review_required)

    def test_anti_dumping_manual_review_without_official_contour(self) -> None:
        ad = normalize_anti_dumping()
        self.assertNotEqual(ad.coverage_status, "present")
        self.assertIn(ad.coverage_status, ("manual_review_required", "partial", "missing"))
        self.assertTrue(ad.manual_review_required)


class TestPaymentNormalizationSeedNotPresent(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        base = 8_000_000_000
        with self.sm() as db:
            _add_eec_proven(db)
            for i in range(150):
                code = f"{base + i:010d}"
                db.add(TnvedEntry(hs_code=code, level=10, title=f"x {i}"))
                db.add(
                    HsRate(
                        hs_code=code,
                        hs_prefix=code[:4],
                        duty_rate="0%",
                        vat_import_rate=22.0,
                        source_revision="seed",
                    )
                )
            db.commit()
        self._patches = _start_db_patches(self.sm)

    def tearDown(self) -> None:
        _stop_db_patches(*self._patches)

    def test_all_seed_hs_rates_not_present(self) -> None:
        duty = normalize_import_duty()
        self.assertNotEqual(duty.coverage_status, "present")
        self.assertEqual(duty.coverage_status, "partial")
        self.assertTrue(any("seed" in g.lower() for g in duty.known_gaps))


@unittest.skipUnless(_API_OK, "fastapi not installed")
class TestPaymentNormalizationApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        cls.client = TestClient(app)

    def test_payment_normalization_endpoint(self) -> None:
        r = self.client.get("/api/sources/payment-normalization")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "OK")
        self.assertIn("domains", body)
        self.assertIn("import_duty", body["domains"])
        self.assertIn("vat", body["domains"])
        self.assertIn("excise", body["domains"])
        self.assertIn("anti_dumping", body["domains"])
        self.assertIn("overall_readiness", body)
