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


def _verified() -> tuple[dict, dict]:
    fixture = _fixture()
    return fixture, _build(fixture)


def _preview(fixture: dict, envelope: dict) -> dict:
    return build_legacy_normalization_preview(
        envelope,
        original_bytes=fixture["original_bytes"],
        source_text_bytes=fixture["source_text_bytes"],
    )


def _rehash_envelope(envelope: dict) -> None:
    envelope["envelope_sha256"] = sha256_json(
        {key: value for key, value in envelope.items() if key != "envelope_sha256"}
    )


class EttLegacyNormalizationPreviewTests(unittest.TestCase):
    def test_preview_preserves_identity_runs_provenance_and_ambiguity(self) -> None:
        fixture, envelope = _verified()
        preview = _preview(fixture, envelope)
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
        preview = _preview(fixture, _build(fixture))
        matches = [row for row in preview["rows"] if row["hs_code"] == first_hs]
        self.assertEqual(len(matches), 2)
        self.assertEqual(len({row["legacy_raw_row_sha256"] for row in matches}), 2)
        self.assertEqual(preview["counts"]["raw"], 533)

    def test_corruption_and_incomplete_recovery_evidence_fail_closed(self) -> None:
        fixture, envelope = _verified()
        envelope["derived"]["provenance"][0]["row_sha256"] = "0" * 64
        with self.assertRaisesRegex(EttLegacyPreviewError, "envelope SHA mismatch"):
            _preview(fixture, envelope)

        fixture, envelope = _verified()
        envelope["derived"]["provenance"][0]["row_sha256"] = "0" * 64
        _rehash_envelope(envelope)
        with self.assertRaisesRegex(EttLegacyPreviewError, "exact-evidence reconstruction"):
            _preview(fixture, envelope)

        fixture = _fixture()
        fixture["source_text_bytes"] = None
        blocked = _build(fixture)
        with self.assertRaisesRegex(EttLegacyPreviewError, "evidence is incomplete"):
            _preview(fixture, blocked)

    def test_preview_is_deterministic_and_does_not_mutate_recovery(self) -> None:
        fixture, envelope = _verified()
        before = copy.deepcopy(envelope)
        first = _preview(fixture, envelope)
        second = _preview(fixture, envelope)
        self.assertEqual(first, second)
        self.assertEqual(first["preview_sha256"], second["preview_sha256"])
        self.assertEqual(envelope, before)

    def test_rehashed_type_and_provenance_corruption_fails_closed(self) -> None:
        corruptions = (
            ("schema_version", lambda envelope: envelope.update(schema_version=True)),
            ("verified", lambda envelope: envelope.update(verified=False)),
            ("admitted", lambda envelope: envelope.update(admitted=False)),
            (
                "source size",
                lambda envelope: envelope["observed"]["source"].update(
                    size_bytes=-1
                ),
            ),
            (
                "source page count",
                lambda envelope: envelope["observed"]["source"].update(
                    page_count=-1
                ),
            ),
            (
                "provenance ordinal",
                lambda envelope: envelope["derived"]["provenance"][0].update(
                    ordinal=True
                ),
            ),
            (
                "derived raw count float",
                lambda envelope: envelope["derived"].update(raw_count=533.0),
            ),
            (
                "page exceeds source",
                lambda envelope: envelope["derived"]["provenance"][0].update(
                    page_number=999, line_number=999
                ),
            ),
            (
                "page order",
                lambda envelope: envelope["derived"]["provenance"][201].update(
                    page_number=1, line_number=999
                ),
            ),
            (
                "line order",
                lambda envelope: envelope["derived"]["provenance"][1].update(
                    line_number=1
                ),
            ),
        )
        for label, corrupt in corruptions:
            with self.subTest(label=label):
                fixture, envelope = _verified()
                corrupt(envelope)
                _rehash_envelope(envelope)
                with self.assertRaises(EttLegacyPreviewError):
                    _preview(fixture, envelope)

    def test_rehashed_historical_semantic_mutations_fail_closed(self) -> None:
        mutations = (
            (
                "duty detached from raw line",
                lambda envelope: envelope["observed"]["raw_rows"][0].update(
                    duty_text="99"
                ),
            ),
            (
                "derived text SHA detached from runs",
                lambda envelope: envelope["derived"].update(
                    source_text_sha256="0" * 64
                ),
            ),
            (
                "final run incomplete",
                lambda envelope: envelope["observed"]["legacy_runs"][-1][
                    "resume_cursor"
                ].update(complete=False),
            ),
        )
        for label, mutate in mutations:
            with self.subTest(label=label):
                fixture, envelope = _verified()
                mutate(envelope)
                _rehash_envelope(envelope)
                with self.assertRaises(EttLegacyPreviewError):
                    _preview(fixture, envelope)

    def test_exact_evidence_bytes_are_required(self) -> None:
        fixture, envelope = _verified()
        with self.assertRaisesRegex(EttLegacyPreviewError, "exact evidence"):
            build_legacy_normalization_preview(
                envelope,
                original_bytes=b"wrong original",
                source_text_bytes=fixture["source_text_bytes"],
            )
        with self.assertRaisesRegex(EttLegacyPreviewError, "exact evidence"):
            build_legacy_normalization_preview(
                envelope,
                original_bytes=fixture["original_bytes"],
                source_text_bytes=b"wrong text",
            )


if __name__ == "__main__":
    unittest.main()
