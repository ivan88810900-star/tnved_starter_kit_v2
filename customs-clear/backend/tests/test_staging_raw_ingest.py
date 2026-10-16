from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.services.staging_raw_ingest import (
    AmbiguousEttRowError,
    InvalidUtf8SourceError,
    StagingRawIngestError,
    prepare_ett_staging_batch,
)


def _line(code: str, description: str, unit: str = "–", duty: str = "5") -> str:
    grouped = f"{code[:4]} {code[4:6]} {code[6:9]} {code[9]}"
    return f"{grouped}   {description}            {unit}            {duty}"


def _source(row_count: int) -> bytes:
    lines = [
        _line(f"{2_900_000_000 + ordinal:010d}", f"товар {ordinal}")
        for ordinal in range(1, row_count + 1)
    ]
    return ("заголовок\n" + "\n".join(lines) + "\n").encode("utf-8")


class StagingRawIngestTests(unittest.TestCase):
    def test_cyrillic_and_en_dash_bytes_are_preserved_and_hashed_exactly(self) -> None:
        raw_line = "  2901 10 000 1   – – этан; бутан            –            3  "
        payload = prepare_ett_staging_batch((raw_line + "\n").encode("utf-8"))

        row = payload["batch"]["rows"][0]
        self.assertEqual(row["raw_line"], raw_line)
        self.assertEqual(row["description"], "– – этан; бутан")
        self.assertEqual(row["supplementary_unit"], "–")
        self.assertEqual(row["duty_text"], "3")
        self.assertEqual(
            row["row_sha256"], hashlib.sha256(raw_line.encode("utf-8")).hexdigest()
        )
        self.assertEqual(row["status"], "COLLECTED_UNVERIFIED")
        self.assertIs(payload["normalization_performed"], False)
        self.assertIs(payload["legal_admission_performed"], False)

    def test_invalid_utf8_is_rejected(self) -> None:
        for source in (b"\xff", b"header\n2901 10 000 1   \xff\n"):
            with self.subTest(source=source):
                with self.assertRaisesRegex(InvalidUtf8SourceError, "not valid UTF-8"):
                    prepare_ett_staging_batch(source)

    def test_unicode_replacement_character_is_rejected_as_lossy_provenance(self) -> None:
        source = (_line("2901100001", "испорчено \ufffd") + "\n").encode("utf-8")
        with self.assertRaisesRegex(InvalidUtf8SourceError, "replacement character"):
            prepare_ett_staging_batch(source)

    def test_resume_at_ordinal_21_is_one_based_and_bounded(self) -> None:
        payload = prepare_ett_staging_batch(_source(30), start_ordinal=21, batch_size=4)

        self.assertEqual(
            payload["totals"],
            {"raw_count": 30, "unique_count": 30, "duplicate_row_count": 0},
        )
        self.assertEqual(payload["batch"]["start_ordinal"], 21)
        self.assertEqual(payload["batch"]["end_ordinal"], 24)
        self.assertEqual(
            [row["ordinal"] for row in payload["batch"]["rows"]], [21, 22, 23, 24]
        )
        self.assertEqual(
            payload["resume_cursor"], {"next_ordinal": 25, "complete": False}
        )

    def test_hashes_and_payload_are_deterministic(self) -> None:
        source = _source(3)
        first = prepare_ett_staging_batch(source, batch_size=2)
        second = prepare_ett_staging_batch(source, batch_size=2)

        self.assertEqual(first, second)
        self.assertEqual(first["source_text_sha256"], hashlib.sha256(source).hexdigest())

    def test_duplicate_rows_are_retained_with_exact_and_code_evidence(self) -> None:
        first = _line("2901100001", "– – этан", duty="3")
        changed = _line("2901100001", "– – этан", duty="5")
        source = f"{first}\n{first}\n{changed}\n".encode("utf-8")

        payload = prepare_ett_staging_batch(source)

        self.assertEqual(
            payload["totals"],
            {"raw_count": 3, "unique_count": 2, "duplicate_row_count": 1},
        )
        self.assertEqual(payload["batch"]["raw_count"], 3)
        self.assertEqual(payload["batch"]["unique_count"], 2)
        self.assertEqual(
            [row["ordinal"] for row in payload["batch"]["rows"]], [1, 2, 3]
        )
        self.assertEqual(
            payload["duplicate_evidence"]["exact_rows"][0]["ordinals"], [1, 2]
        )
        self.assertEqual(
            payload["duplicate_evidence"]["hs_codes"][0]["ordinals"], [1, 2, 3]
        )
        self.assertEqual(
            len(payload["duplicate_evidence"]["hs_codes"][0]["row_sha256s"]), 2
        )

    def test_batch_scales_to_200_rows_without_changing_global_counts(self) -> None:
        payload = prepare_ett_staging_batch(
            _source(533), start_ordinal=21, batch_size=200
        )

        self.assertEqual(payload["totals"]["raw_count"], 533)
        self.assertEqual(payload["totals"]["unique_count"], 533)
        self.assertEqual(payload["batch"]["raw_count"], 200)
        self.assertEqual(payload["batch"]["unique_count"], 200)
        self.assertEqual(payload["batch"]["end_ordinal"], 220)
        self.assertEqual(
            payload["resume_cursor"], {"next_ordinal": 221, "complete": False}
        )

    def test_ambiguous_code_shaped_row_fails_closed(self) -> None:
        source = (
            "2901 10 000 1   описание без двух конечных колонок\n".encode("utf-8")
        )
        with self.assertRaisesRegex(AmbiguousEttRowError, "expected description"):
            prepare_ett_staging_batch(source)

    def test_cursor_may_point_to_exact_completion_but_not_beyond(self) -> None:
        source = _source(2)
        complete = prepare_ett_staging_batch(source, start_ordinal=3, batch_size=1)
        self.assertEqual(complete["batch"]["rows"], [])
        self.assertEqual(
            complete["resume_cursor"], {"next_ordinal": 3, "complete": True}
        )

        with self.assertRaisesRegex(StagingRawIngestError, "beyond completion"):
            prepare_ett_staging_batch(source, start_ordinal=4, batch_size=1)

    def test_cli_text_input_emits_utf8_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path = root / "source.txt"
            output_path = root / "batch.json"
            source_path.write_bytes(
                (_line("2901100001", "– – этан") + "\n").encode("utf-8")
            )
            script = Path(__file__).parents[1] / "scripts" / "prepare_ett_staging_batch.py"

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--text",
                    str(source_path),
                    "--output",
                    str(output_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            serialized = output_path.read_text(encoding="utf-8")
            self.assertIn("этан", serialized)
            self.assertNotIn("\\u044d", serialized)
            self.assertEqual(
                json.loads(serialized)["batch"]["rows"][0]["hs_code"], "2901100001"
            )


if __name__ == "__main__":
    unittest.main()
