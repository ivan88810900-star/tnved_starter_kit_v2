"""Тесты реестра нормативных источников и gap-отчёта полноты."""

from __future__ import annotations

import os
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.services.normative_store import init_db
from app.services.regulatory_source_completeness import (
    diagnose_source_entry,
    run_regulatory_source_completeness_report,
)
from app.services.regulatory_source_registry import (
    AUTHORITY_LEVEL_LABELS,
    REGULATORY_SOURCE_REGISTRY,
    RegulatorySourceEntry,
    get_registry_entry,
    list_registry_entries,
)


class TestRegulatorySourceRegistry(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def test_registry_has_required_official_sources(self) -> None:
        ids = {e.source_id for e in REGULATORY_SOURCE_REGISTRY}
        required = {
            "eec_tr_ts_catalog",
            "eec_classification_decisions",
            "fts_preliminary_classification",
            "pravo_gov_publication",
            "eec_sgr_decision_299",
            "eec_sgr_registry",
            "fsa_registry_evidence",
            "ofac_sdn_list",
            "eu_sanctions_list",
        }
        self.assertTrue(required.issubset(ids))

    def test_authority_levels_are_explicit(self) -> None:
        for entry in REGULATORY_SOURCE_REGISTRY:
            self.assertIn(entry.authority_level, AUTHORITY_LEVEL_LABELS)
            row = list_registry_entries()[0]
            self.assertIn("authority_level", row)
            self.assertIn("is_source_of_truth", row)
            break

    def test_registry_entries_sorted_in_report(self) -> None:
        report = run_regulatory_source_completeness_report()
        ids = [s["source_id"] for s in report["sources"]]
        self.assertEqual(ids, sorted(ids))

    def test_report_summary_counts(self) -> None:
        report = run_regulatory_source_completeness_report()
        self.assertEqual(report["summary"]["total_sources"], len(REGULATORY_SOURCE_REGISTRY))
        self.assertEqual(
            sum(report["summary"]["by_coverage_status"].values()),
            len(REGULATORY_SOURCE_REGISTRY),
        )

    def test_official_sgr_legal_list_is_separate_from_issued_registry(self) -> None:
        legal_entry = get_registry_entry("eec_sgr_decision_299")
        registry_entry = get_registry_entry("eec_sgr_registry")
        assert legal_entry is not None
        assert registry_entry is not None
        self.assertIsNone(legal_entry.db_probe)
        self.assertTrue(legal_entry.manual_review_default)
        self.assertEqual(registry_entry.db_probe, "sgr_certificates")
        self.assertEqual(registry_entry.source_status_code, "SGR_REGISTRY")

    def test_official_sgr_seed_local_path(self) -> None:
        entry = get_registry_entry("eec_sgr_registry")
        assert entry is not None
        row = diagnose_source_entry(entry, status_by_code={})
        checked = row["local_source"]["paths_checked"]
        seed = next(p for p in checked if p["path"].endswith("official_sgr_rules.seed.json"))
        self.assertTrue(seed["exists"])

    def test_fsa_has_bulk_registry_probe(self) -> None:
        entry = get_registry_entry("fsa_registry_evidence")
        assert entry is not None
        row = diagnose_source_entry(entry, status_by_code={})
        self.assertEqual(entry.db_probe, "fsa_certificates")
        self.assertNotEqual(row["coverage_status"], "not_applicable")
        self.assertNotEqual(row["parser_status"], "runtime_only")

    def test_fts_official_not_covered_by_mirror_rows(self) -> None:
        """ПКР Alta (без префикса FCS-) не должны попадать в official FCS probe."""
        from app.db import SessionLocal
        from app.models.core import ClassificationDecision
        from app.services.regulatory_source_completeness import _count_db_probe

        with SessionLocal() as db:
            exists = (
                db.query(ClassificationDecision.id)
                .filter(ClassificationDecision.decision_number == "ALTA-MIRROR-PROBE-TEST")
                .first()
            )
            if not exists:
                db.add(
                    ClassificationDecision(
                        hs_code="8471300000",
                        product_name="Зеркало Alta",
                        description="Тест зеркала",
                        target_entity="Ноутбук",
                        decision_number="ALTA-MIRROR-PROBE-TEST",
                        issue_date="2020-01-01",
                    )
                )
                db.commit()
        self.assertEqual(_count_db_probe("classification_decisions_official_fts"), _count_fcs_official_only())

        entry = get_registry_entry("fts_preliminary_classification")
        assert entry is not None
        row = diagnose_source_entry(entry, status_by_code={})
        if _count_fcs_official_only() == 0:
            self.assertNotEqual(row["coverage_status"], "present")
        self.assertTrue(row["manual_review_required"])

    def test_tks_mirror_uses_fts_alta_source_probe(self) -> None:
        entry = get_registry_entry("tks_predecisions_mirror")
        assert entry is not None
        self.assertEqual(entry.db_probe, "preliminary_decisions_fts_alta")

    def test_commercial_mirror_flagged_manual_review(self) -> None:
        entry = get_registry_entry("tks_predecisions_mirror")
        assert entry is not None
        row = diagnose_source_entry(entry, status_by_code={})
        self.assertFalse(row["is_source_of_truth"])
        self.assertTrue(row["manual_review_required"])

    def test_trade_remedy_contours_have_distinct_probes_and_statuses(self) -> None:
        expected = {
            "trade_remedies_official": (
                "special_duties_anti_dumping",
                "EEC_ANTI_DUMPING",
            ),
            "trade_remedies_special_safeguard_official": (
                "special_duties_special_safeguard",
                "EEC_SPECIAL_SAFEGUARD",
            ),
            "trade_remedies_countervailing_official": (
                "special_duties_countervailing",
                "EEC_COUNTERVAILING",
            ),
        }
        actual: dict[str, tuple[str | None, str | None]] = {}
        for source_id in expected:
            entry = get_registry_entry(source_id)
            assert entry is not None
            actual[source_id] = (entry.db_probe, entry.source_status_code)
        self.assertEqual(actual, expected)

    def test_excise_and_odata_vat_have_db_and_status_proof(self) -> None:
        excise = get_registry_entry("rf_excise_tax_code")
        vat = get_registry_entry("eec_odata_vat_preferences")
        assert excise is not None
        assert vat is not None
        self.assertEqual(
            (excise.db_probe, excise.source_status_code),
            ("hs_rates_excise_eec", "EEC_EXCISE"),
        )
        self.assertEqual(
            (vat.db_probe, vat.source_status_code),
            ("vat_preferences_eec_odata", "EEC_ODATA"),
        )

    def test_official_db_rows_without_matching_source_status_are_not_present(self) -> None:
        entry = RegulatorySourceEntry(
            source_id="test_official_db",
            title="Test",
            authority_level="official_reference",
            official_url="https://example.test/source",
            description="Test",
            db_probe="synthetic_probe",
            source_status_code="EXPECTED_STATUS",
        )
        with (
            patch(
                "app.services.regulatory_source_completeness._count_db_probe",
                return_value=12,
            ),
            patch(
                "app.services.regulatory_source_completeness._latest_sync_for_code",
                return_value=None,
            ),
        ):
            missing = diagnose_source_entry(entry, status_by_code={})
            wrong = diagnose_source_entry(
                entry,
                status_by_code={
                    "WRONG_STATUS": {
                        "source_code": "WRONG_STATUS",
                        "revision": "official-2026-09-01",
                        "synced_at": "2026-09-01T00:00:00",
                        "is_stale": False,
                    }
                },
                generated_at="2026-09-01T01:00:00",
            )
        self.assertEqual(missing["coverage_status"], "partial")
        self.assertEqual(missing["parser_status"], "unverified")
        self.assertFalse(missing["source_status_verified"])
        self.assertEqual(wrong["coverage_status"], "partial")
        self.assertFalse(wrong["source_status_verified"])

    def test_healthy_matching_source_status_allows_official_presence(self) -> None:
        entry = RegulatorySourceEntry(
            source_id="test_official_db",
            title="Test",
            authority_level="official_reference",
            official_url="https://example.test/source",
            description="Test",
            db_probe="synthetic_probe",
            source_status_code="EXPECTED_STATUS",
            refresh_cadence="daily",
            max_age_hours=48,
        )
        status = {
            "source_code": "EXPECTED_STATUS",
            "revision": "official-2026-09-01",
            "synced_at": "2026-09-01T00:00:00",
            "is_stale": False,
        }
        with (
            patch(
                "app.services.regulatory_source_completeness._count_db_probe",
                return_value=12,
            ),
            patch(
                "app.services.regulatory_source_completeness._latest_sync_for_code",
                return_value=None,
            ),
        ):
            row = diagnose_source_entry(
                entry,
                status_by_code={"EXPECTED_STATUS": status},
                generated_at="2026-09-02T00:00:00",
            )
        self.assertEqual(row["coverage_status"], "present")
        self.assertEqual(row["parser_status"], "ok")
        self.assertTrue(row["source_status_verified"])
        self.assertFalse(row["freshness"]["is_overdue"])

    def test_missed_cadence_marks_preserved_snapshot_stale(self) -> None:
        entry = RegulatorySourceEntry(
            source_id="test_official_db",
            title="Test",
            authority_level="registry_evidence",
            official_url="https://example.test/source",
            description="Test",
            db_probe="synthetic_probe",
            source_status_code="EXPECTED_STATUS",
            refresh_cadence="daily",
            max_age_hours=48,
        )
        status = {
            "source_code": "EXPECTED_STATUS",
            "revision": "official-2026-08-01",
            "synced_at": "2026-08-01T00:00:00Z",
            "is_stale": False,
        }
        with (
            patch(
                "app.services.regulatory_source_completeness._count_db_probe",
                return_value=12,
            ),
            patch(
                "app.services.regulatory_source_completeness._latest_sync_for_code",
                return_value=None,
            ),
        ):
            row = diagnose_source_entry(
                entry,
                status_by_code={"EXPECTED_STATUS": status},
                generated_at="2026-09-01T00:00:00Z",
            )
        self.assertEqual(row["coverage_status"], "stale")
        self.assertEqual(row["parser_status"], "stale")
        self.assertFalse(row["source_status_verified"])
        self.assertTrue(row["freshness"]["is_overdue"])

    def test_latest_failed_sync_cannot_reuse_previous_green_status(self) -> None:
        entry = RegulatorySourceEntry(
            source_id="test_official_db",
            title="Test",
            authority_level="official_reference",
            official_url="https://example.test/source",
            description="Test",
            db_probe="synthetic_probe",
            source_status_code="EXPECTED_STATUS",
        )
        status = {
            "source_code": "EXPECTED_STATUS",
            "revision": "official-2026-09-01",
            "synced_at": "2026-09-01T00:00:00Z",
            "is_stale": False,
        }
        with (
            patch(
                "app.services.regulatory_source_completeness._count_db_probe",
                return_value=12,
            ),
            patch(
                "app.services.regulatory_source_completeness._latest_sync_for_code",
                return_value={"status": "ERROR", "synced_at": "2026-09-01T01:00:00Z"},
            ),
        ):
            row = diagnose_source_entry(
                entry,
                status_by_code={"EXPECTED_STATUS": status},
                generated_at="2026-09-01T02:00:00Z",
            )
        self.assertEqual(row["coverage_status"], "parser_failed")
        self.assertFalse(row["source_status_verified"])

    def test_scheduled_sources_publish_explicit_freshness_contract(self) -> None:
        daily = get_registry_entry("cbr_exchange_rates")
        weekly = get_registry_entry("fsa_registry_evidence")
        assert daily is not None
        assert weekly is not None
        self.assertEqual((daily.refresh_cadence, daily.max_age_hours), ("daily", 48))
        self.assertEqual((weekly.refresh_cadence, weekly.max_age_hours), ("weekly", 216))

    def test_payment_db_probes_are_contour_specific(self) -> None:
        from app.db import SessionLocal
        from app.models.core import HsRate
        from app.models.tnved import SpecialDuty, VatPreference
        from app.services.regulatory_source_completeness import _count_db_probe

        token = uuid.uuid4().hex[:12]
        act = f"completeness-probe-{token}"
        hs_code = f"99{int(token[:8], 16) % 100000000:08d}"
        decree = f"VAT completeness probe {token}"
        probes = (
            "special_duties_anti_dumping",
            "special_duties_special_safeguard",
            "special_duties_countervailing",
            "hs_rates_excise_eec",
            "vat_preferences_eec_odata",
        )
        before = {probe: int(_count_db_probe(probe) or 0) for probe in probes}
        try:
            with SessionLocal() as db:
                db.add_all(
                    [
                        SpecialDuty(
                            hs_code_prefix="7304",
                            origin_country="CN",
                            measure_type="anti_dumping",
                            source_code="EEC_ANTI_DUMPING",
                            regulatory_act=act,
                        ),
                        SpecialDuty(
                            hs_code_prefix="7305",
                            origin_country="CN",
                            measure_type="special_safeguard",
                            safeguard_source_code="EEC_SPECIAL_SAFEGUARD",
                            regulatory_act=act,
                        ),
                        SpecialDuty(
                            hs_code_prefix="7306",
                            origin_country="CN",
                            measure_type="countervailing",
                            countervailing_source_code="EEC_COUNTERVAILING",
                            regulatory_act=act,
                        ),
                        # A borrowed anti-dumping marker must not close the
                        # special-safeguard contour.
                        SpecialDuty(
                            hs_code_prefix="7307",
                            origin_country="CN",
                            measure_type="special_safeguard",
                            source_code="EEC_ANTI_DUMPING",
                            regulatory_act=act,
                        ),
                        HsRate(
                            hs_code=hs_code,
                            hs_prefix=hs_code,
                            excise_source_code="EEC_EXCISE",
                            source_revision=f"probe-{token}",
                        ),
                        HsRate(
                            hs_code=hs_code[:-1] + "1",
                            hs_prefix=hs_code[:-1] + "1",
                            excise_source_code="",
                            source_revision=f"probe-{token}",
                        ),
                        VatPreference(
                            hs_code_prefix=hs_code,
                            vat_rate=10,
                            decree_info=decree,
                        ),
                    ]
                )
                db.commit()

            self.assertEqual(
                _count_db_probe("special_duties_anti_dumping"),
                before["special_duties_anti_dumping"] + 1,
            )
            self.assertEqual(
                _count_db_probe("special_duties_special_safeguard"),
                before["special_duties_special_safeguard"] + 1,
            )
            self.assertEqual(
                _count_db_probe("special_duties_countervailing"),
                before["special_duties_countervailing"] + 1,
            )
            self.assertEqual(
                _count_db_probe("hs_rates_excise_eec"),
                before["hs_rates_excise_eec"] + 1,
            )
            self.assertEqual(
                _count_db_probe("vat_preferences_eec_odata"),
                before["vat_preferences_eec_odata"] + 1,
            )
        finally:
            with SessionLocal() as db:
                db.query(SpecialDuty).filter(SpecialDuty.regulatory_act == act).delete(
                    synchronize_session=False
                )
                db.query(HsRate).filter(HsRate.source_revision == f"probe-{token}").delete(
                    synchronize_session=False
                )
                db.query(VatPreference).filter(VatPreference.decree_info == decree).delete(
                    synchronize_session=False
                )
                db.commit()


def _count_fcs_official_only() -> int:
    from app.services.fcs_preliminary_sync import count_fcs_official_decisions

    return count_fcs_official_decisions()


class TestRegulatorySourceCompletenessApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        cls.client = TestClient(app)

    def test_registry_endpoint(self) -> None:
        r = self.client.get("/api/sources/registry")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "OK")
        self.assertGreaterEqual(len(body["entries"]), 10)

    def test_completeness_endpoint(self) -> None:
        r = self.client.get("/api/sources/completeness")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "OK")
        self.assertIn("sources", body)
        self.assertIn("summary", body)
        self.assertIn("future_sync_notes", body)
        self.assertIn("official_source_gap_ids", body["summary"])

    def test_update_plan_endpoint_covers_registry(self) -> None:
        r = self.client.get("/api/sources/updates/plan")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["coverage"]["valid"])
        self.assertEqual(len(body["sources"]), len(REGULATORY_SOURCE_REGISTRY))

    def test_update_run_requires_admin_token(self) -> None:
        r = self.client.post("/api/sources/updates/run?cadence=daily")
        self.assertIn(r.status_code, (401, 403))

    def test_update_status_explicitly_reports_never_run(self) -> None:
        with (
            patch("app.api.sources.load_last_update_report", return_value=None),
            patch(
                "app.api.sources.regulatory_review_queue_summary",
                return_value={"notification_required": False},
            ),
            patch("app.api.sources.is_read_only_mode", return_value=False),
            patch("app.api.sources.is_scheduler_running", return_value=True),
            patch(
                "app.api.sources.regulatory_jobs_status",
                return_value={"daily": {"job_id": "regulatory_sources_daily", "next_run_at": None}},
            ),
        ):
            r = self.client.get("/api/sources/updates/status")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "never_run")
        self.assertIsNone(body["last_run"])
        self.assertFalse(body["read_only"])
        self.assertTrue(body["scheduler"]["running"])

    def test_update_status_exposes_last_persisted_outcome(self) -> None:
        last_run = {"status": "partial", "cadence": "daily", "results": [{"status": "error"}]}
        with (
            patch("app.api.sources.load_last_update_report", return_value=last_run),
            patch(
                "app.api.sources.regulatory_review_queue_summary",
                return_value={"notification_required": False},
            ),
            patch("app.api.sources.is_read_only_mode", return_value=False),
            patch("app.api.sources.is_scheduler_running", return_value=False),
            patch("app.api.sources.regulatory_jobs_status", return_value={}),
        ):
            r = self.client.get("/api/sources/updates/status")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "partial")
        self.assertEqual(body["last_run"], last_run)

    def test_update_run_read_only_is_rejected_before_runner(self) -> None:
        with (
            patch.dict(os.environ, {"ADMIN_API_TOKEN": "test-admin"}),
            patch("app.api.sources.is_read_only_mode", return_value=True),
            patch(
                "app.api.sources.run_regulatory_update_cycle",
                new_callable=AsyncMock,
            ) as run,
        ):
            r = self.client.post(
                "/api/sources/updates/run?cadence=daily",
                headers={"X-Admin-Token": "test-admin"},
            )
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["detail"]["error_code"], "read_only_mode")
        run.assert_not_awaited()
