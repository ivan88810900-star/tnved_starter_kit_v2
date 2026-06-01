"""Тесты диагностики покрытия ТН ВЭД и платёжных данных."""

from __future__ import annotations

import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.main import app
from app.models.core import ExchangeRate, GeoSpecialDuty, HsRate, SourceStatus, SyncLog, TnvedEntry
from app.models.tnved import Chapter, Commodity, HsDutyRule, Section, SpecialDuty, VatPreference
from app.services.normative_store import init_db
from app.services.exchange_rates import CBRF_SOURCE_CODE, FALLBACK, TRACKED, update_exchange_rates_from_cbrf
from app.services.payment_data_coverage import (
    diagnose_duty_rates,
    diagnose_excise,
    diagnose_exchange_rates,
    diagnose_trade_remedies,
    run_payment_data_coverage_report,
)

try:
    from fastapi.testclient import TestClient

    _API_OK = True
except ImportError:
    _API_OK = False


_COVERAGE_TABLES = [
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
    Base.metadata.create_all(bind=engine, tables=_COVERAGE_TABLES)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _start_coverage_db_patches(sm: sessionmaker) -> tuple[unittest.mock._patch, unittest.mock._patch]:
    """Hermetic DB: payment_data_coverage + normative_store (list_sync_log)."""
    patch_cov = unittest.mock.patch("app.services.payment_data_coverage.SessionLocal", sm)
    patch_norm = unittest.mock.patch("app.services.normative_store.SessionLocal", sm)
    patch_cov.start()
    patch_norm.start()
    return patch_cov, patch_norm


def _stop_coverage_db_patches(
    patch_cov: unittest.mock._patch,
    patch_norm: unittest.mock._patch,
) -> None:
    patch_norm.stop()
    patch_cov.stop()


class TestPaymentDataCoverageEmptyDb(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patch_cov, self._patch_norm = _start_coverage_db_patches(self.sm)

    def tearDown(self) -> None:
        _stop_coverage_db_patches(self._patch_cov, self._patch_norm)

    def test_empty_db_summary_is_missing_or_not_configured(self) -> None:
        report = run_payment_data_coverage_report()
        self.assertEqual(report["status"], "OK")
        summary = report["summary"]
        self.assertIn(summary["tnved_entries"]["status"], ("missing", "partial"))
        self.assertEqual(summary["duty_rates"]["status"], "missing")
        self.assertEqual(summary["customs_fees"]["status"], "present")
        self.assertEqual(summary["excise"]["status"], "not_configured")
        self.assertEqual(summary["trade_remedies"]["status"], "not_configured")
        self.assertIn(summary["exchange_rates"]["status"], ("missing", "partial"))
        self.assertFalse(report["smart_payments"]["can_produce_final_total"])
        self.assertTrue(summary["excise"]["manual_review_required"])
        self.assertTrue(len(report["next_actions"]) >= 1)


class TestPaymentDataCoveragePartialRates(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        with self.sm() as db:
            db.add(
                HsRate(
                    hs_code="8471300000",
                    hs_prefix="8471",
                    duty_rate="0%",
                    vat_import_rate=22.0,
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

        self._patch_cov, self._patch_norm = _start_coverage_db_patches(self.sm)

    def tearDown(self) -> None:
        _stop_coverage_db_patches(self._patch_cov, self._patch_norm)

    def test_partial_duty_rates_with_gaps(self) -> None:
        duty = diagnose_duty_rates()
        self.assertEqual(duty.status, "partial")
        self.assertEqual(duty.count, 2)
        self.assertTrue(duty.manual_review_required)
        self.assertGreater(len(duty.gaps), 0)

    def test_excise_seed_rows_not_full_coverage(self) -> None:
        excise = diagnose_excise()
        self.assertIn(excise.status, ("not_configured", "partial"))
        self.assertTrue(excise.manual_review_required)
        self.assertNotEqual(excise.status, "present")


class TestPaymentDataCoverageUnknownTradeRemedySources(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        with self.sm() as db:
            db.add(
                SpecialDuty(
                    hs_code_prefix="8517",
                    origin_country="CN",
                    rate_percent=15.0,
                    regulatory_act="TEST-UNKNOWN-SOURCE",
                )
            )
            db.add(
                HsRate(
                    hs_code="7214990000",
                    hs_prefix="7214",
                    duty_rate="5%",
                    vat_import_rate=22.0,
                    has_antidumping=True,
                    antidumping_type="percent",
                    antidumping_value=34.0,
                )
            )
            db.commit()

        self._patch_cov, self._patch_norm = _start_coverage_db_patches(self.sm)

    def tearDown(self) -> None:
        _stop_coverage_db_patches(self._patch_cov, self._patch_norm)

    def test_unknown_trade_remedy_source_not_present(self) -> None:
        trade = diagnose_trade_remedies()
        self.assertIn(trade.status, ("not_configured", "partial"))
        self.assertNotEqual(trade.status, "present")
        self.assertTrue(trade.manual_review_required)
        self.assertGreater(trade.count or 0, 0)


class TestPaymentDataCoverageFreshExchangeRates(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self.sm() as db:
            for code in TRACKED:
                db.add(
                    ExchangeRate(
                        currency_code=code,
                        rate=90.0,
                        nominal=1.0,
                        updated_at=now,
                    )
                )
            db.commit()

        self._patch_cov, self._patch_norm = _start_coverage_db_patches(self.sm)

    def tearDown(self) -> None:
        _stop_coverage_db_patches(self._patch_cov, self._patch_norm)

    def test_fresh_exchange_rates_without_cbr_proof_not_present(self) -> None:
        fx = diagnose_exchange_rates()
        self.assertNotEqual(fx.status, "present")
        self.assertIn(fx.status, ("partial", "manual_review_required"))
        self.assertTrue(fx.manual_review_required)
        self.assertNotEqual(fx.authority_level, "official_binding")

    def test_cbrf_provenance_allows_present(self) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self.sm() as db:
            db.add(
                SourceStatus(
                    source_code=CBRF_SOURCE_CODE,
                    source_name="CBRF test",
                    source_url="https://www.cbr.ru/",
                    revision="cbrf:2026-05-21",
                    synced_at=now,
                    is_stale=False,
                    note="test",
                )
            )
            db.add(
                SyncLog(
                    source_code=CBRF_SOURCE_CODE,
                    synced_at=now,
                    status="OK",
                    revision="cbrf:2026-05-21",
                    rows_affected=5,
                    note="test",
                )
            )
            db.commit()

        fx = diagnose_exchange_rates()
        self.assertEqual(fx.status, "present")
        self.assertEqual(fx.authority_level, "official_binding")
        self.assertFalse(fx.manual_review_required)

    def test_stale_source_status_overrides_older_ok_sync_log(self) -> None:
        """Свежий fallback/stale SourceStatus не должен перебиваться старым SyncLog OK."""
        t0 = datetime.now(timezone.utc).replace(tzinfo=None)
        t1 = t0 + timedelta(minutes=5)
        with self.sm() as db:
            for row in db.query(ExchangeRate).all():
                row.updated_at = t1
                row.rate = 90.0 + hash(row.currency_code) % 7
            db.add(
                SourceStatus(
                    source_code=CBRF_SOURCE_CODE,
                    source_name="CBRF test",
                    source_url="https://www.cbr.ru/",
                    revision="cbrf:2026-05-20",
                    synced_at=t0,
                    is_stale=False,
                    note="old ok",
                )
            )
            db.add(
                SyncLog(
                    source_code=CBRF_SOURCE_CODE,
                    synced_at=t0,
                    status="OK",
                    revision="cbrf:2026-05-20",
                    rows_affected=5,
                    note="old ok",
                )
            )
            db.commit()
            st = (
                db.query(SourceStatus)
                .filter(SourceStatus.source_code == CBRF_SOURCE_CODE)
                .one()
            )
            st.revision = "fallback"
            st.is_stale = True
            st.synced_at = t1
            st.note = "newer fallback"
            db.add(
                SyncLog(
                    source_code=CBRF_SOURCE_CODE,
                    synced_at=t1,
                    status="ERROR",
                    revision="fallback",
                    rows_affected=5,
                    note="newer fallback",
                )
            )
            db.commit()

        fx = diagnose_exchange_rates()
        self.assertNotEqual(fx.status, "present")
        self.assertIn(fx.status, ("partial", "manual_review_required"))
        self.assertNotEqual(fx.authority_level, "official_binding")

    def test_stale_provenance_does_not_prove_newer_mixed_rates(self) -> None:
        """Старый cbrf:* SourceStatus не доказывает exchange_rates, обновлённые позже (mixed)."""
        t0 = datetime.now(timezone.utc).replace(tzinfo=None)
        t1 = t0 + timedelta(hours=1)
        with self.sm() as db:
            db.add(
                SourceStatus(
                    source_code=CBRF_SOURCE_CODE,
                    source_name="CBRF test",
                    source_url="https://www.cbr.ru/",
                    revision="cbrf:2026-05-01",
                    synced_at=t0,
                    is_stale=False,
                    note="old ok provenance",
                )
            )
            for code in TRACKED:
                rate = FALLBACK[code] if code in ("CNY", "BYN") else 95.5
                row = (
                    db.query(ExchangeRate)
                    .filter(ExchangeRate.currency_code == code)
                    .one()
                )
                row.rate = rate
                row.updated_at = t1
            db.commit()

        fx = diagnose_exchange_rates()
        self.assertNotEqual(fx.status, "present")
        self.assertIn(fx.status, ("partial", "manual_review_required"))
        self.assertNotEqual(fx.authority_level, "official_binding")
        self.assertTrue(
            any("старее" in g.lower() or "provenance" in g.lower() for g in fx.gaps)
        )

    def test_newest_sync_log_across_aliases_blocks_stale_ok(self) -> None:
        """Свежий ERROR под CBRF не перебивается старым OK под CBR/EXCHANGE_RATES."""
        t0 = datetime.now(timezone.utc).replace(tzinfo=None)
        t1 = t0 + timedelta(minutes=10)
        with self.sm() as db:
            db.add(
                SyncLog(
                    source_code="CBR",
                    synced_at=t0,
                    status="OK",
                    revision="cbrf:2026-05-01",
                    rows_affected=5,
                    note="stale ok under alias CBR",
                )
            )
            db.add(
                SyncLog(
                    source_code=CBRF_SOURCE_CODE,
                    synced_at=t1,
                    status="ERROR",
                    revision="fallback",
                    rows_affected=5,
                    note="newer fallback under CBRF",
                )
            )
            db.commit()

        fx = diagnose_exchange_rates()
        self.assertNotEqual(fx.status, "present")
        self.assertIn(fx.status, ("partial", "manual_review_required"))
        self.assertNotEqual(fx.authority_level, "official_binding")

    def test_fallback_constants_not_present(self) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self.sm() as db:
            db.query(ExchangeRate).delete()
            for code in TRACKED:
                db.add(
                    ExchangeRate(
                        currency_code=code,
                        rate=FALLBACK[code],
                        nominal=1.0,
                        updated_at=now,
                    )
                )
            db.commit()

        fx = diagnose_exchange_rates()
        self.assertNotEqual(fx.status, "present")
        self.assertIn(fx.status, ("partial", "manual_review_required"))
        self.assertTrue(fx.manual_review_required)


class TestExchangeRatesCbrfProvenanceRecording(unittest.IsolatedAsyncioTestCase):
    async def test_successful_update_records_provenance_and_allows_present(self) -> None:
        sm = _memory_sessionmaker()
        live_rows = {code: (90.0 + idx, 1.0) for idx, code in enumerate(TRACKED)}

        patch_ex = unittest.mock.patch("app.services.exchange_rates.SessionLocal", sm)
        patch_norm = unittest.mock.patch("app.services.normative_store.SessionLocal", sm)
        patch_fetch = unittest.mock.patch(
            "app.services.exchange_rates.fetch_cbr_rates",
            unittest.mock.AsyncMock(return_value=("2026-05-21", live_rows)),
        )
        patch_ex.start()
        patch_norm.start()
        patch_fetch.start()
        try:
            result = await update_exchange_rates_from_cbrf()
            self.assertEqual(result["source"], "CBRF")

            patch_cov, patch_norm_diag = _start_coverage_db_patches(sm)
            try:
                fx = diagnose_exchange_rates()
                self.assertEqual(fx.status, "present")
                self.assertEqual(fx.authority_level, "official_binding")
            finally:
                _stop_coverage_db_patches(patch_cov, patch_norm_diag)
        finally:
            patch_fetch.stop()
            patch_norm.stop()
            patch_ex.stop()

    async def test_fallback_update_does_not_allow_present(self) -> None:
        sm = _memory_sessionmaker()

        patch_ex = unittest.mock.patch("app.services.exchange_rates.SessionLocal", sm)
        patch_norm = unittest.mock.patch("app.services.normative_store.SessionLocal", sm)
        patch_fetch = unittest.mock.patch(
            "app.services.exchange_rates.fetch_cbr_rates",
            unittest.mock.AsyncMock(side_effect=RuntimeError("network down")),
        )
        patch_ex.start()
        patch_norm.start()
        patch_fetch.start()
        try:
            result = await update_exchange_rates_from_cbrf()
            self.assertEqual(result["source"], "fallback")

            patch_cov, patch_norm_diag = _start_coverage_db_patches(sm)
            try:
                fx = diagnose_exchange_rates()
                self.assertNotEqual(fx.status, "present")
                self.assertIn(fx.status, ("partial", "manual_review_required"))
            finally:
                _stop_coverage_db_patches(patch_cov, patch_norm_diag)
        finally:
            patch_fetch.stop()
            patch_norm.stop()
            patch_ex.stop()

    async def test_provenance_write_failure_does_not_clobber_live_cbr_rates(self) -> None:
        sm = _memory_sessionmaker()
        live_rows = {code: (50.0 + idx * 3.7, 1.0) for idx, code in enumerate(TRACKED)}

        patch_ex = unittest.mock.patch("app.services.exchange_rates.SessionLocal", sm)
        patch_norm = unittest.mock.patch("app.services.normative_store.SessionLocal", sm)
        patch_fetch = unittest.mock.patch(
            "app.services.exchange_rates.fetch_cbr_rates",
            unittest.mock.AsyncMock(return_value=("2026-05-21", live_rows)),
        )
        patch_record_ok = unittest.mock.patch(
            "app.services.exchange_rates._record_cbrf_sync_success",
            side_effect=RuntimeError("provenance db lock"),
        )
        patch_ex.start()
        patch_norm.start()
        patch_fetch.start()
        patch_record_ok.start()
        try:
            result = await update_exchange_rates_from_cbrf()
            self.assertEqual(result["source"], "CBRF")
            self.assertFalse(result.get("provenance_recorded"))
            self.assertIn("provenance_error", result)

            with sm() as db:
                usd = (
                    db.query(ExchangeRate)
                    .filter(ExchangeRate.currency_code == "USD")
                    .one()
                )
                self.assertAlmostEqual(float(usd.rate), live_rows["USD"][0], places=4)
                self.assertNotAlmostEqual(float(usd.rate), FALLBACK["USD"], places=4)

            patch_cov, patch_norm_diag = _start_coverage_db_patches(sm)
            try:
                fx = diagnose_exchange_rates()
                self.assertNotEqual(fx.status, "present")
            finally:
                _stop_coverage_db_patches(patch_cov, patch_norm_diag)
        finally:
            patch_record_ok.stop()
            patch_fetch.stop()
            patch_norm.stop()
            patch_ex.stop()

    async def test_partial_cbr_xml_does_not_record_ok_provenance(self) -> None:
        sm = _memory_sessionmaker()
        partial_rows = {"USD": (95.0, 1.0), "EUR": (101.0, 1.0)}

        patch_ex = unittest.mock.patch("app.services.exchange_rates.SessionLocal", sm)
        patch_norm = unittest.mock.patch("app.services.normative_store.SessionLocal", sm)
        patch_fetch = unittest.mock.patch(
            "app.services.exchange_rates.fetch_cbr_rates",
            unittest.mock.AsyncMock(return_value=("2026-05-21", partial_rows)),
        )
        patch_ex.start()
        patch_norm.start()
        patch_fetch.start()
        try:
            result = await update_exchange_rates_from_cbrf()
            self.assertEqual(result["source"], "fallback")
            self.assertEqual(result.get("missing_currencies"), ["CNY", "BYN", "KZT"])

            with sm() as db:
                ok_logs = (
                    db.query(SyncLog)
                    .filter(
                        SyncLog.source_code == CBRF_SOURCE_CODE,
                        SyncLog.status == "OK",
                    )
                    .count()
                )
                self.assertEqual(ok_logs, 0)

            patch_cov, patch_norm_diag = _start_coverage_db_patches(sm)
            try:
                fx = diagnose_exchange_rates()
                self.assertNotEqual(fx.status, "present")
                self.assertIn(fx.status, ("partial", "manual_review_required"))
                self.assertNotEqual(fx.authority_level, "official_binding")
            finally:
                _stop_coverage_db_patches(patch_cov, patch_norm_diag)
        finally:
            patch_fetch.stop()
            patch_norm.stop()
            patch_ex.stop()


class TestPaymentDataCoverageFullDutyScan(unittest.TestCase):
    """Полный проход по каталогу: gap вне sample-окна → partial, не present."""

    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        base = 6_000_000_000
        with self.sm() as db:
            for i in range(600):
                code = f"{base + i:010d}"
                db.add(TnvedEntry(hs_code=code, level=10, title=f"pos {i}"))
            for i in range(500):
                code = f"{base + i:010d}"
                db.add(
                    HsRate(
                        hs_code=code,
                        hs_prefix=code,
                        duty_rate="5%",
                        vat_import_rate=22.0,
                    )
                )
            db.commit()

        self._patch_cov, self._patch_norm = _start_coverage_db_patches(self.sm)

    def tearDown(self) -> None:
        _stop_coverage_db_patches(self._patch_cov, self._patch_norm)

    def test_partial_when_gap_outside_sample_window(self) -> None:
        duty = diagnose_duty_rates()
        self.assertEqual(duty.status, "partial")
        self.assertEqual(duty.covered_codes, 500)
        self.assertEqual(duty.total_codes, 600)
        self.assertEqual(len(duty.missing_samples or []), 5)


class TestPaymentDataCoverageOfficialOnlyDuty(unittest.TestCase):
    """P1 #2: seed/fallback строки не дают official present-покрытие."""

    def _add_eec_proven(self, db) -> None:
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

    def test_seed_full_coverage_with_partial_official_not_present(self) -> None:
        sm = _memory_sessionmaker()
        base = 8_400_000_000
        with sm() as db:
            self._add_eec_proven(db)
            for i in range(100):
                code = f"{base + i:010d}"
                db.add(TnvedEntry(hs_code=code, level=10, title=f"pos {i}"))
                # i<50 official, i>=50 seed; hs_prefix=full code (без prefix-перекрытия).
                db.add(
                    HsRate(
                        hs_code=code,
                        hs_prefix=code,
                        duty_rate="5%",
                        vat_import_rate=22.0,
                        source_revision="ett:2026-05-01" if i < 50 else "seed",
                    )
                )
            db.commit()
        patch_cov, patch_norm = _start_coverage_db_patches(sm)
        try:
            duty = diagnose_duty_rates()
        finally:
            _stop_coverage_db_patches(patch_cov, patch_norm)
        self.assertNotEqual(duty.status, "present")
        self.assertEqual(duty.status, "partial")
        self.assertTrue(duty.manual_review_required)
        self.assertTrue(duty.missing_samples)
        self.assertTrue(any("official" in g.lower() for g in duty.gaps))

    def test_full_official_coverage_can_be_present(self) -> None:
        sm = _memory_sessionmaker()
        base = 8_500_000_000
        with sm() as db:
            self._add_eec_proven(db)
            for i in range(120):
                code = f"{base + i:010d}"
                db.add(TnvedEntry(hs_code=code, level=10, title=f"pos {i}"))
                db.add(
                    HsRate(
                        hs_code=code,
                        hs_prefix=code,
                        duty_rate="5%",
                        vat_import_rate=22.0,
                        source_revision="ett:2026-05-01",
                    )
                )
            db.commit()
        patch_cov, patch_norm = _start_coverage_db_patches(sm)
        try:
            duty = diagnose_duty_rates()
        finally:
            _stop_coverage_db_patches(patch_cov, patch_norm)
        self.assertEqual(duty.status, "present")
        self.assertFalse(duty.manual_review_required)


@unittest.skipUnless(_API_OK, "fastapi not installed")
class TestPaymentDataCoverageApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        cls.client = TestClient(app)

    def test_payment_coverage_endpoint(self) -> None:
        r = self.client.get("/api/sources/payment-coverage")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "OK")
        self.assertIn("summary", body)
        self.assertIn("smart_payments", body)
        self.assertIn("next_actions", body)
        self.assertIn("tnved_entries", body["summary"])
        self.assertIn("duty_rates", body["summary"])
        self.assertIn("excise", body["summary"])