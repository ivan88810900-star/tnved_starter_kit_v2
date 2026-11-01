from __future__ import annotations

import copy
import hashlib
import unittest

from app.services.staging_ett_legacy_recovery import (
    EttLegacyRecoveryError,
    build_legacy_recovery_envelope,
)


SOURCE_ID = "synthetic-eec-ett-chapter29"


def _run(
    run_id: str,
    *,
    scope: dict,
    raw_count: int,
    cursor: dict,
) -> dict:
    return {
        "run_id": run_id,
        "source_id": SOURCE_ID,
        "scope": scope,
        "parser_version": "ett-pdftotext-layout-raw-v1",
        "status": "COLLECTED_UNVERIFIED",
        "raw_count": raw_count,
        "unique_count": raw_count,
        "normalized_count": 0,
        "rejected_count": 0,
        "resume_cursor": cursor,
    }


def _fixture() -> dict:
    original_bytes = b"synthetic immutable chapter-29 original bytes"
    rows = []
    lines = []
    for ordinal in range(1, 534):
        hs_code = f"29{ordinal:08d}"
        duty = "5 with note" if ordinal % 50 == 0 else "5"
        raw_line = (
            f"{hs_code}\tdescription {ordinal}\tunit {ordinal}\t{duty}"
        )
        lines.append(raw_line)
        rows.append(
            {
                "source_id": SOURCE_ID,
                "hs_code": hs_code,
                "description": f"description {ordinal}",
                "supplementary_unit": f"unit {ordinal}",
                "duty_text": duty,
                "raw_line": raw_line,
                "row_sha256": hashlib.sha256(raw_line.encode()).hexdigest(),
                "status": "COLLECTED_UNVERIFIED",
                "ordinal": ordinal,
            }
        )
    pages = [
        "\n".join(lines[:200]),
        "\n".join(lines[200:400]),
        "\n".join(lines[400:]),
    ]
    source_text_bytes = "\f".join(pages).encode()
    text_sha = hashlib.sha256(source_text_bytes).hexdigest()
    runs = [
        _run(
            "synthetic-cycle-one",
            scope={
                "chapter": "29",
                "bounded_rows": 20,
                "classification": "raw collection only",
            },
            raw_count=20,
            cursor={"last_ordinal": 20, "last_hs_code": rows[19]["hs_code"]},
        ),
        _run(
            "synthetic-cycle-two",
            scope={
                "chapter": 29,
                "start_ordinal": 21,
                "end_ordinal": 220,
                "source_text_sha256": text_sha,
            },
            raw_count=200,
            cursor={"next_ordinal": 221},
        ),
        _run(
            "synthetic-cycle-three",
            scope={
                "start_ordinal": 221,
                "end_ordinal": 533,
                "classification": "COLLECTED_UNVERIFIED",
                "historical_source": True,
                "source_text_sha256": text_sha,
            },
            raw_count=313,
            cursor={"next_ordinal": 534, "complete": True},
        ),
    ]
    return {
        "source": {
            "source_id": SOURCE_ID,
            "sha256": hashlib.sha256(original_bytes).hexdigest(),
            "size_bytes": len(original_bytes),
            "page_count": 3,
            "chapter": "29",
        },
        "legacy_runs": runs,
        "raw_rows": rows,
        "original_bytes": original_bytes,
        "source_text_bytes": source_text_bytes,
    }


def _build(fixture: dict) -> dict:
    return build_legacy_recovery_envelope(**fixture)


class EttLegacyRecoveryTests(unittest.TestCase):
    def test_complete_legacy_bundle_is_preserved_and_page_bound(self) -> None:
        fixture = _fixture()
        envelope = _build(fixture)
        self.assertEqual(envelope["status"], "READY_FOR_OFFLINE_PACKAGE_REVIEW")
        self.assertEqual(envelope["missing_evidence"], [])
        self.assertFalse(envelope["execution_performed"])
        self.assertFalse(envelope["sql_generated"])
        self.assertNotIn("sql", envelope)
        self.assertEqual(envelope["verified"], 0)
        self.assertEqual(envelope["admitted"], 0)
        self.assertEqual(envelope["observed"]["legacy_runs"], fixture["legacy_runs"])
        self.assertEqual(envelope["observed"]["raw_rows"], fixture["raw_rows"])
        self.assertEqual(envelope["derived"]["raw_count"], 533)
        self.assertEqual(
            [
                (item["start_ordinal"], item["end_ordinal"])
                for item in envelope["derived"]["run_ranges"]
            ],
            [(1, 20), (21, 220), (221, 533)],
        )
        provenance = envelope["derived"]["provenance"]
        self.assertEqual(len(provenance), 533)
        self.assertEqual(
            {
                key: provenance[200][key]
                for key in ("ordinal", "source_line_number", "page_number", "line_number")
            },
            {
                "ordinal": 201,
                "source_line_number": 201,
                "page_number": 2,
                "line_number": 1,
            },
        )
        ambiguous = envelope["observed"]["raw_rows"][49]
        self.assertEqual(ambiguous["duty_text"], "5 with note")

    def test_missing_original_or_page_evidence_is_blocked_without_sql(self) -> None:
        fixture = _fixture()
        fixture["original_bytes"] = None
        fixture["source_text_bytes"] = None
        envelope = _build(fixture)
        self.assertEqual(envelope["status"], "BLOCKED")
        self.assertEqual(
            envelope["missing_evidence"],
            [
                "exact_original_bytes",
                "exact_source_text_bytes",
                "page_aware_mapping",
            ],
        )
        self.assertEqual(envelope["derived"]["provenance"], [])
        self.assertFalse(envelope["sql_generated"])
        self.assertNotIn("sql", envelope)

    def test_gaps_and_overlaps_fail_closed(self) -> None:
        for label, start, count in (
            ("gap", 22, 199),
            ("overlap", 20, 201),
        ):
            with self.subTest(label=label):
                fixture = _fixture()
                run = fixture["legacy_runs"][1]
                run["scope"]["start_ordinal"] = start
                run["raw_count"] = count
                run["unique_count"] = count
                with self.assertRaisesRegex(
                    EttLegacyRecoveryError, "gap or overlap"
                ):
                    _build(fixture)

    def test_corrupt_hash_and_identity_conflicts_fail_closed(self) -> None:
        fixture = _fixture()
        fixture["raw_rows"][0]["row_sha256"] = "0" * 64
        with self.assertRaisesRegex(EttLegacyRecoveryError, "raw_line SHA mismatch"):
            _build(fixture)

        fixture = _fixture()
        fixture["legacy_runs"][2]["scope"]["source_text_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            EttLegacyRecoveryError, "source text identities conflict"
        ):
            _build(fixture)

        fixture = _fixture()
        fixture["legacy_runs"][1]["source_id"] = "different-source"
        with self.assertRaisesRegex(EttLegacyRecoveryError, "source_id mismatch"):
            _build(fixture)

    def test_ambiguous_page_mapping_fails_closed(self) -> None:
        fixture = _fixture()
        text = fixture["source_text_bytes"].decode()
        first_line = fixture["raw_rows"][0]["raw_line"]
        fixture["source_text_bytes"] = (first_line + "\n" + text).encode()
        text_sha = hashlib.sha256(fixture["source_text_bytes"]).hexdigest()
        fixture["legacy_runs"][1]["scope"]["source_text_sha256"] = text_sha
        fixture["legacy_runs"][2]["scope"]["source_text_sha256"] = text_sha
        with self.assertRaisesRegex(
            EttLegacyRecoveryError, "missing or ambiguous"
        ):
            _build(fixture)

    def test_cursor_and_completion_conflicts_fail_closed(self) -> None:
        fixture = _fixture()
        fixture["legacy_runs"][1]["resume_cursor"]["next_ordinal"] = 222
        with self.assertRaisesRegex(EttLegacyRecoveryError, "cursor mismatch"):
            _build(fixture)

        fixture = _fixture()
        fixture["legacy_runs"][2]["resume_cursor"]["complete"] = False
        with self.assertRaisesRegex(EttLegacyRecoveryError, "not complete"):
            _build(fixture)

    def test_inputs_are_not_mutated(self) -> None:
        fixture = _fixture()
        before = copy.deepcopy(fixture)
        _build(fixture)
        self.assertEqual(fixture, before)


if __name__ == "__main__":
    unittest.main()
