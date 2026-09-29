"""Тесты реестра нормативных источников и gap-отчёта полноты."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.services.normative_store import init_db, list_source_status, upsert_source_status
from app.services.regulatory_source_completeness import (
    _derive_coverage_status,
    _derive_edition_tracking_status,
    _sync_entrypoint_status,
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

    def test_official_sgr_seed_local_path(self) -> None:
        entry = get_registry_entry("eec_sgr_decision_299")
        assert entry is not None
        row = diagnose_source_entry(entry, status_by_code={})
        checked = row["local_source"]["paths_checked"]
        seed = next(p for p in checked if p["path"].endswith("official_sgr_rules.seed.json"))
        self.assertTrue(seed["exists"])

    def test_fsa_runtime_only_not_missing(self) -> None:
        entry = get_registry_entry("fsa_registry_evidence")
        assert entry is not None
        row = diagnose_source_entry(entry, status_by_code={})
        self.assertEqual(row["coverage_status"], "not_applicable")
        self.assertEqual(row["parser_status"], "runtime_only")

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

    def test_sync_entrypoint_status_fails_closed(self) -> None:
        available = _sync_entrypoint_status("sync_sgr_registry.py")
        self.assertEqual(available["status"], "available")
        self.assertTrue(available["exists"])

        self.assertEqual(
            _sync_entrypoint_status("source_sync.py")["status"],
            "missing",
        )
        self.assertEqual(
            _sync_entrypoint_status(None)["status"],
            "not_configured",
        )
        for unsafe in ("../source_sync.py", "nested/source_sync.py", "source_sync.sh"):
            with self.subTest(unsafe=unsafe):
                self.assertEqual(_sync_entrypoint_status(unsafe)["status"], "invalid")

    def test_sync_entrypoint_status_rejects_broken_path_and_wrong_types(self) -> None:
        nul_path = _sync_entrypoint_status("nul\x00.py")
        self.assertEqual(nul_path["status"], "invalid")
        self.assertTrue(nul_path["configured"])
        self.assertFalse(nul_path["exists"])

        for wrong_type in (False, 0, [], {}):
            with self.subTest(wrong_type=wrong_type):
                result = _sync_entrypoint_status(wrong_type)
                self.assertEqual(result["status"], "invalid")
                self.assertTrue(result["configured"])
                self.assertFalse(result["exists"])

        for absent in (None, "", "   "):
            with self.subTest(absent=absent):
                result = _sync_entrypoint_status(absent)
                self.assertEqual(result["status"], "not_configured")
                self.assertFalse(result["configured"])

    def test_sync_entrypoint_status_rejects_controls_and_all_separators(self) -> None:
        for unsafe in (
            "line\nfeed.py",
            "tab\tname.py",
            "..\\escape.py",
            "C:\\tmp\\x.py",
            "nested/source.py",
            "delete\x7fname.py",
        ):
            with self.subTest(unsafe=unsafe):
                result = _sync_entrypoint_status(unsafe)
                self.assertEqual(result["status"], "invalid")
                self.assertTrue(result["configured"])
                self.assertFalse(result["exists"])

        unicode_name = _sync_entrypoint_status("синхронизация_етт.py")
        self.assertNotEqual(unicode_name["status"], "invalid")
        self.assertTrue(unicode_name["configured"])

    def test_missing_official_sync_entrypoint_requires_manual_review(self) -> None:
        entry = RegulatorySourceEntry(
            source_id="test_missing_sync",
            title="Test official source",
            authority_level="official_binding",
            official_url="https://example.test/official",
            description="test",
            local_paths=("data/official_sgr_rules.seed.json",),
            sync_script="missing_sync_entrypoint.py",
        )
        row = diagnose_source_entry(entry, status_by_code={})
        self.assertEqual(row["sync_entrypoint"]["status"], "missing")
        self.assertTrue(row["manual_review_required"])

    def test_official_local_copy_without_revision_tracking_is_partial(self) -> None:
        entry = RegulatorySourceEntry(
            source_id="test_official",
            title="Test official source",
            authority_level="official_binding",
            official_url="https://example.test/official",
            description="test",
            source_status_code="TEST_OFFICIAL",
            min_document_count=1,
        )
        tracking = _derive_edition_tracking_status(entry, None)
        coverage = _derive_coverage_status(
            entry,
            {"exists": True},
            None,
            None,
            "ok",
            tracking,
        )
        self.assertEqual(tracking, "unverified")
        self.assertEqual(coverage, "partial")

    def test_official_tracking_requires_dated_non_stale_revision(self) -> None:
        entry = RegulatorySourceEntry(
            source_id="test_official",
            title="Test official source",
            authority_level="official_reference",
            official_url="https://example.test/official",
            description="test",
            source_status_code="TEST_OFFICIAL",
        )
        for source_status in (
            {"revision": "eec:2026-09-24", "synced_at": "2026-09-24T10:00:00"},
            {"revision": "seed", "synced_at": "2026-09-24T10:00:00", "is_stale": False},
            {"revision": "eec:2026-09-24", "is_stale": False},
        ):
            with self.subTest(source_status=source_status):
                self.assertEqual(
                    _derive_edition_tracking_status(entry, source_status),
                    "unverified",
                )

        self.assertEqual(
            _derive_edition_tracking_status(
                entry,
                {
                    "revision": "eec:2026-09-24",
                    "synced_at": "2026-09-24T10:00:00Z",
                    "is_stale": False,
                },
            ),
            "tracked",
        )
        self.assertEqual(
            _derive_edition_tracking_status(
                entry,
                {
                    "revision": "eec:2026-09-24",
                    "synced_at": "2026-09-24T10:00:00",
                    "is_stale": True,
                },
            ),
            "stale",
        )

    def test_persisted_source_status_round_trips_as_explicit_utc_tracking_evidence(self) -> None:
        from app.db import SessionLocal
        from app.models.core import SourceStatus

        source_code = "TEST_UTC_SOURCE_STATUS"
        entry = RegulatorySourceEntry(
            source_id="test_utc_status",
            title="Test UTC source",
            authority_level="official_reference",
            official_url="https://example.test/official",
            description="test",
            source_status_code=source_code,
        )
        try:
            upsert_source_status(
                source_code=source_code,
                source_name="Test UTC source",
                source_url="https://example.test/official",
                revision="eec:2026-09-29",
                is_stale=False,
                note="integration test",
                synced_at=datetime(2026, 9, 29, 13, 30, tzinfo=timezone(timedelta(hours=3))),
            )
            persisted = next(
                row for row in list_source_status() if row["source_code"] == source_code
            )
            self.assertEqual(persisted["synced_at"], "2026-09-29T10:30:00Z")
            self.assertEqual(
                _derive_edition_tracking_status(
                    entry,
                    persisted,
                    now=datetime(2026, 9, 30, tzinfo=timezone.utc),
                ),
                "tracked",
            )
        finally:
            with SessionLocal() as db:
                db.query(SourceStatus).filter(SourceStatus.source_code == source_code).delete()
                db.commit()

    def test_official_tracking_rejects_undated_or_invalid_revision(self) -> None:
        entry = RegulatorySourceEntry(
            source_id="test_official",
            title="Test official source",
            authority_level="official_binding",
            official_url="https://example.test/official",
            description="test",
            source_status_code="TEST_OFFICIAL",
        )
        current = datetime(2026, 9, 27, 5, 0, tzinfo=timezone.utc)
        for revision in (
            "prod-current",
            "eec:2026-02-31",
            "eec:2999-01-01",
            "seed:2026-09-27",
            "demo-2026-09-27",
        ):
            with self.subTest(revision=revision):
                self.assertEqual(
                    _derive_edition_tracking_status(
                        entry,
                        {
                            "revision": revision,
                            "synced_at": "2026-09-27T04:00:00Z",
                            "is_stale": False,
                        },
                        now=current,
                    ),
                    "unverified",
                )

    def test_official_tracking_rejects_invalid_or_future_sync_timestamp(self) -> None:
        entry = RegulatorySourceEntry(
            source_id="test_official",
            title="Test official source",
            authority_level="official_reference",
            official_url="https://example.test/official",
            description="test",
            source_status_code="TEST_OFFICIAL",
        )
        current = datetime(2026, 9, 27, 5, 0, tzinfo=timezone.utc)
        for synced_at in (
            "not-a-timestamp",
            "2026-09-27",
            "2026-09-27T04:00:00",
            datetime(2026, 9, 27, 4, 0),
            "2999-01-01T00:00:00Z",
            "0001-01-01T00:00:00+14:00",
            "9999-12-31T23:59:59-14:00",
        ):
            with self.subTest(synced_at=synced_at):
                self.assertEqual(
                    _derive_edition_tracking_status(
                        entry,
                        {
                            "revision": "eec:2026-09-27",
                            "synced_at": synced_at,
                            "is_stale": False,
                        },
                        now=current,
                    ),
                    "unverified",
                )

    def test_official_tracking_rejects_malformed_revision_types(self) -> None:
        entry = RegulatorySourceEntry(
            source_id="test_official",
            title="Test official source",
            authority_level="official_reference",
            official_url="https://example.test/official",
            description="test",
            source_status_code="TEST_OFFICIAL",
        )
        current = datetime(2026, 9, 27, 5, 0, tzinfo=timezone.utc)
        for revision in (
            {"revision": "2026-09-26"},
            ["2026-09-26"],
            20260926,
            b"eec:2026-09-26",
            None,
        ):
            with self.subTest(revision=revision):
                self.assertEqual(
                    _derive_edition_tracking_status(
                        entry,
                        {
                            "revision": revision,
                            "synced_at": "2026-09-27T04:00:00Z",
                            "is_stale": False,
                        },
                        now=current,
                    ),
                    "unverified",
                )

    def test_official_tracking_accepts_aware_datetime_sync_timestamp(self) -> None:
        entry = RegulatorySourceEntry(
            source_id="test_official",
            title="Test official source",
            authority_level="official_reference",
            official_url="https://example.test/official",
            description="test",
            source_status_code="TEST_OFFICIAL",
        )
        self.assertEqual(
            _derive_edition_tracking_status(
                entry,
                {
                    "revision": "eec:2026-09-26",
                    "synced_at": datetime(
                        2026,
                        9,
                        27,
                        7,
                        0,
                        tzinfo=timezone(timedelta(hours=3)),
                    ),
                    "is_stale": False,
                },
                now=datetime(2026, 9, 27, 5, 0, tzinfo=timezone.utc),
            ),
            "tracked",
        )

    def test_official_tracking_accepts_valid_dated_provenance(self) -> None:
        entry = RegulatorySourceEntry(
            source_id="test_official",
            title="Test official source",
            authority_level="official_reference",
            official_url="https://example.test/official",
            description="test",
            source_status_code="TEST_OFFICIAL",
        )
        self.assertEqual(
            _derive_edition_tracking_status(
                entry,
                {
                    "revision": "eec:2026-09-26",
                    "synced_at": "2026-09-27T04:00:00+00:00",
                    "is_stale": False,
                },
                now=datetime(2026, 9, 27, 5, 0, tzinfo=timezone.utc),
            ),
            "tracked",
        )


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
        self.assertIn("official_edition_tracking_gap_ids", body["summary"])
        self.assertTrue(body["summary"]["any_official_edition_tracking_gap"])
        self.assertTrue(body["summary"]["any_official_sync_entrypoint_gap"])
        self.assertEqual(
            body["summary"]["official_sync_entrypoint_gap_ids"],
            sorted(body["summary"]["official_sync_entrypoint_gap_ids"]),
        )
        for row in body["sources"]:
            self.assertIn("edition_tracking_status", row)
            self.assertIn("sync_entrypoint", row)
