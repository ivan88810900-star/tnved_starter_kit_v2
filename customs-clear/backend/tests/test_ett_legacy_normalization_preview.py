from __future__ import annotations

import copy
import hashlib
import unittest

from app.services.staging_ett_legacy_normalization_preview import (
    EttLegacyPreviewError,
    build_legacy_normalization_preview,
)
from app.services.staging_ett_normalization_core import sha256_json
from tests.test_ett_legacy_recovery import _build, _fixture, _historical_line


def _envelope() -> dict:
    return _build(_fixture())


def _rehash_envelope(envelope: dict) -> None:
    envelope["envelope_sha256"] = sha256_json(
        {key: value for key, value in envelope.items() if key != "envelope_sha256"}
    )


class EttLegacyNormalizationPreviewTests(unittest.TestCase):
    def test_preview_preserves_identity_runs_provenance_and_ambiguity(self) -> None:
        envelope = _envelope()
        preview = build_legacy_normalization_preview(envelope)
        self.assertEqual(
            preview["counts"],
            {"raw": 533, "unique": 533, "parsed": 523, "ambiguous": 10},
        )
        self.assertEqual(preview["legal_status"], "UNVERIFIED")
        self.assertEqual(preview["verified"], 0)
        self.assertEqual(preview["admitted"], 0)
        self.assertFalse(preview["execution_performed"])
        self.assertFalse(preview["sql_generated"])
        self.assertNotIn("sql", preview)
        first, middle, last = preview["rows"][0], preview["rows"][20], preview["rows"][-1]
        self.assertEqual(first["legacy_run_id"], "synthetic-cycle-one")
        self.assertEqual(middle["legacy_run_id"], "synthetic-cycle-two")
        self.assertEqual(last["legacy_run_id"], "synthetic-cycle-three")
        for index in (0, 49, 200, 532):
            result = preview["rows"][index]
            raw = envelope["observed"]["raw_rows"][index]
            provenance = envelope["derived"]["provenance"][index]
            self.assertEqual(result["legacy_raw_row_sha256"], raw["row_sha256"])
            self.assertNotEqual(result["result_sha256"], raw["row_sha256"])
            self.assertEqual(result["provenance"], provenance)
        self.assertTrue(preview["rows"][49]["is_ambiguous"])
        self.assertEqual(
            preview["rows"][49]["ambiguity_reason"],
            "QUALIFIED_OR_UNKNOWN_TEXT",
        )

    def test_duplicate_hs_with_distinct_raw_identity_is_not_collapsed(self) -> None:
        fixture = _fixture()
        first_hs = fixture["raw_rows"][0]["hs_code"]
        second = fixture["raw_rows"][1]
        second["hs_code"] = first_hs
        second["raw_line"] = _historical_line(
            first_hs,
            second["description"],
            second["supplementary_unit"],
            second["duty_text"],
        )
        second["row_sha256"] = hashlib.sha256(second["raw_line"].encode()).hexdigest()
        original_second_line = _historical_line(
            "2900000002", "description 2", "unit 2", "5"
        ).encode()
        fixture["source_text_bytes"] = fixture["source_text_bytes"].replace(
            original_second_line, second["raw_line"].encode(), 1
        )
        text_sha = hashlib.sha256(fixture["source_text_bytes"]).hexdigest()
        fixture["legacy_runs"][1]["scope"]["source_text_sha256"] = text_sha
        fixture["legacy_runs"][2]["scope"]["source_text_sha256"] = text_sha
        preview = build_legacy_normalization_preview(_build(fixture))
        matches = [row for row in preview["rows"] if row["hs_code"] == first_hs]
        self.assertEqual(len(matches), 2)
        self.assertEqual(len({row["legacy_raw_row_sha256"] for row in matches}), 2)
        self.assertEqual(preview["counts"]["raw"], 533)

    def test_corruption_and_incomplete_recovery_evidence_fail_closed(self) -> None:
        envelope = _envelope()
        envelope["derived"]["provenance"][0]["row_sha256"] = "0" * 64
        with self.assertRaisesRegex(EttLegacyPreviewError, "envelope SHA mismatch"):
            build_legacy_normalization_preview(envelope)

        envelope = _envelope()
        envelope["derived"]["provenance"][0]["row_sha256"] = "0" * 64
        _rehash_envelope(envelope)
        with self.assertRaisesRegex(EttLegacyPreviewError, "provenance row 1 identity"):
            build_legacy_normalization_preview(envelope)

        fixture = _fixture()
        fixture["source_text_bytes"] = None
        blocked = _build(fixture)
        with self.assertRaisesRegex(EttLegacyPreviewError, "evidence is incomplete"):
            build_legacy_normalization_preview(blocked)

    def test_preview_is_deterministic_and_does_not_mutate_recovery(self) -> None:
        envelope = _envelope()
        before = copy.deepcopy(envelope)
        first = build_legacy_normalization_preview(envelope)
        second = build_legacy_normalization_preview(envelope)
        self.assertEqual(first, second)
        self.assertEqual(first["preview_sha256"], second["preview_sha256"])
        self.assertEqual(envelope, before)


if __name__ == "__main__":
    unittest.main()
