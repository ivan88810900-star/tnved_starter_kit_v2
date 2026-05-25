"""Тесты синхронизации предварительных решений FCS и интеграции с completeness monitor."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.services.fcs_preliminary_sync import (
    DEFAULT_FIXTURE_PATH,
    FCS_PRELIMINARY_SOURCE_CODE,
    count_fcs_official_decisions,
    load_fcs_preliminary_fixture,
    parse_fcs_preliminary_payload,
    sync_fcs_preliminary_decisions,
)
from app.services.normative_store import init_db, list_sync_log
from app.services.regulatory_source_completeness import diagnose_source_entry
from app.services.regulatory_source_registry import get_registry_entry
from app.services.tnved_code_card import find_preliminary_decisions_for_hs


class TestFcsPreliminaryParser(unittest.TestCase):
    def test_parse_fixture_sample(self) -> None:
        records = load_fcs_preliminary_fixture(DEFAULT_FIXTURE_PATH)
        self.assertEqual(len(records), 3)
        self.assertTrue(all(r.decision_number.startswith("FCS-") for r in records))

    def test_parse_rejects_empty_items(self) -> None:
        with self.assertRaises(ValueError):
            parse_fcs_preliminary_payload({"schema_version": "1", "items": []})

    def test_parse_rejects_bad_schema(self) -> None:
        with self.assertRaises(ValueError):
            parse_fcs_preliminary_payload({"schema_version": "99", "items": [{}]})


class TestFcsPreliminarySync(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def test_sync_from_fixture_success(self) -> None:
        result = sync_fcs_preliminary_decisions(fixture_path=DEFAULT_FIXTURE_PATH)
        self.assertEqual(result["status"], "OK")
        self.assertGreaterEqual(result["rows_affected"], 1)
        self.assertGreaterEqual(count_fcs_official_decisions(), 1)

    def test_sync_parser_failure_records_error(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            tmp.write("{ not valid json")
            bad_path = Path(tmp.name)
        try:
            result = sync_fcs_preliminary_decisions(fixture_path=bad_path)
            self.assertEqual(result["status"], "ERROR")
            self.assertIn("error", result)
            logs = list_sync_log(source_code=FCS_PRELIMINARY_SOURCE_CODE, limit=1)
            self.assertTrue(logs)
            self.assertEqual(logs[0]["status"].upper(), "ERROR")
        finally:
            bad_path.unlink(missing_ok=True)

    def test_dry_run_does_not_write_sync_log(self) -> None:
        before = len(list_sync_log(source_code=FCS_PRELIMINARY_SOURCE_CODE, limit=100))
        result = sync_fcs_preliminary_decisions(fixture_path=DEFAULT_FIXTURE_PATH, dry_run=True)
        self.assertEqual(result["status"], "OK")
        self.assertTrue(result["dry_run"])
        after = len(list_sync_log(source_code=FCS_PRELIMINARY_SOURCE_CODE, limit=100))
        self.assertEqual(before, after)


class TestFcsCompletenessIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def test_completeness_reflects_fcs_source_after_sync(self) -> None:
        sync_fcs_preliminary_decisions(fixture_path=DEFAULT_FIXTURE_PATH)
        entry = get_registry_entry("fts_preliminary_classification")
        assert entry is not None
        row = diagnose_source_entry(entry)
        self.assertIn(row["coverage_status"], ("present", "partial"))
        self.assertIn(row["parser_status"], ("ok", "partial", "unknown"))
        self.assertIsNotNone(row.get("last_successful_sync_at"))
        self.assertGreaterEqual(row.get("local_document_count") or 0, 1)

    def test_completeness_parser_failed_on_bad_fixture(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            json.dump({"schema_version": "1", "items": []}, tmp)
            bad_path = Path(tmp.name)
        try:
            sync_fcs_preliminary_decisions(fixture_path=bad_path)
            entry = get_registry_entry("fts_preliminary_classification")
            assert entry is not None
            row = diagnose_source_entry(entry)
            self.assertEqual(row["parser_status"], "failed")
            self.assertEqual(row["coverage_status"], "parser_failed")
        finally:
            bad_path.unlink(missing_ok=True)


class TestFcsTnvedCodeCard(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        sync_fcs_preliminary_decisions(fixture_path=DEFAULT_FIXTURE_PATH)

    def test_code_card_finds_fcs_decisions(self) -> None:
        from app.db import SessionLocal

        with SessionLocal() as db:
            block = find_preliminary_decisions_for_hs(db, "8471300000")
        self.assertGreater(block["total_count"], 0)
        numbers = {d.get("decision_number") for d in block["classification_decisions"]}
        self.assertTrue(any(str(n).startswith("FCS-") for n in numbers if n))

    def test_code_card_empty_state_message(self) -> None:
        from app.db import SessionLocal

        with SessionLocal() as db:
            block = find_preliminary_decisions_for_hs(db, "0000000000")
        self.assertEqual(block["total_count"], 0)
        self.assertTrue(block["empty_message"])


if __name__ == "__main__":
    unittest.main()
