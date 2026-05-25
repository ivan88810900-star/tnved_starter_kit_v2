"""Тесты реестра нормативных источников и gap-отчёта полноты."""

from __future__ import annotations

import unittest

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
        """ПКР в classification_decisions (Alta/seed) не должны закрывать official FTS gap."""
        entry = get_registry_entry("fts_preliminary_classification")
        assert entry is not None
        row = diagnose_source_entry(entry, status_by_code={})
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
