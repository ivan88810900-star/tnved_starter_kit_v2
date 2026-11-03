from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from app.services import staging_raw_ingest
from app.services.staging_raw_ingest import (
    AmbiguousEttRowError,
    CHAPTER30_PARSER_VERSION,
    InvalidUtf8SourceError,
    PARSER_VERSION,
    PLUS_PARSER_VERSION,
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
        self.assertEqual(payload["parser_version"], PARSER_VERSION)
        self.assertEqual(
            set(payload),
            {
                "schema_version",
                "parser_version",
                "source_text_sha256",
                "row_status",
                "normalization_performed",
                "legal_admission_performed",
                "totals",
                "batch",
                "resume_cursor",
                "duplicate_evidence",
            },
        )
        self.assertEqual(row["status"], "COLLECTED_UNVERIFIED")
        self.assertIs(payload["normalization_performed"], False)
        self.assertIs(payload["legal_admission_performed"], False)

    def test_literal_plus_prefix_is_preserved_and_hashed_exactly(self) -> None:
        raw_line = "+ " + _line(
            "3004100006",
            "– – – – содержащие в качестве",
            duty="6,563С)",
        )

        payload = prepare_ett_staging_batch(
            (raw_line + "\n").encode("utf-8"),
            allow_leading_plus=True,
        )

        row = payload["batch"]["rows"][0]
        self.assertEqual(row["raw_line"], raw_line)
        self.assertEqual(row["hs_code"], "3004100006")
        self.assertEqual(row["supplementary_unit"], "–")
        self.assertEqual(row["duty_text"], "6,563С)")
        self.assertEqual(
            row["row_sha256"], hashlib.sha256(raw_line.encode("utf-8")).hexdigest()
        )
        self.assertEqual(payload["parser_version"], PLUS_PARSER_VERSION)
        self.assertIs(payload["allow_leading_plus"], True)
        self.assertEqual(
            payload["completeness"],
            {
                "status": "BLOCKED",
                "source_provenance_verified": False,
                "multiline_continuations_collected": False,
            },
        )

    def test_chapter30_shape_keeps_82_code_lines_and_16_plus_markers(self) -> None:
        lines = []
        for ordinal in range(1, 83):
            duty = "6,563С)" if ordinal <= 6 else "3"
            prefix = "+ " if ordinal <= 16 else ""
            lines.append(
                prefix
                + _line(
                    f"{3_000_000_000 + ordinal:010d}",
                    f"фармацевтическая позиция {ordinal}",
                    duty=duty,
                )
            )

        payload = prepare_ett_staging_batch(
            ("\n".join(lines) + "\n").encode("utf-8"),
            batch_size=82,
            allow_leading_plus=True,
        )
        rows = payload["batch"]["rows"]

        self.assertEqual(payload["totals"]["raw_count"], 82)
        self.assertEqual(payload["totals"]["unique_count"], 82)
        self.assertEqual(sum(row["raw_line"].startswith("+ ") for row in rows), 16)
        self.assertEqual(sum(row["duty_text"].endswith("63С)") for row in rows), 6)
        self.assertTrue(all(row["supplementary_unit"] == "–" for row in rows))
        self.assertTrue(
            all(
                row["row_sha256"]
                == hashlib.sha256(row["raw_line"].encode("utf-8")).hexdigest()
                for row in rows
            )
        )

    @staticmethod
    def _chapter30_multiline_fixture(*, continuation_shift: int = 0) -> bytes:
        first = "+ " + _line(
            "3002130000", "– – проверяемая позиция,", duty="3"
        )
        semantic_column = first.index("проверяемая")
        continuation = (
            " " * (semantic_column + continuation_shift) + "продолжение описания"
        )
        previous = _line("3005903100", "– – – марля", duty="5")
        target = _line("3005905000", "– – – вата", duty="5")
        return (
            "     3002            Проверяемый верхний заголовок,\n"
            "                     продолжение верхнего заголовка\n"
            "Ставка ввозной\n"
            "Код                       Наименование позиции\n"
            "в долларах США)\n"
            "3002 13         – иммунологические продукты:\n"
            f"{first}\n"
            f"{continuation}\n"
            "                – – следующий контекст:\n"
            f"{previous}\n"
            + " " * 66
            + "63С)\n"
            f"{target}\n"
        ).encode("utf-8")

    @staticmethod
    def _chapter30_duty_binding() -> tuple[dict[str, object], ...]:
        return (
            {
                "marker_source_line": 11,
                "marker": "63С)",
                "page_number": 1,
                "target_hs_code": "3005905000",
                "target_source_line": 12,
                "previous_hs_code": "3005903100",
                "previous_source_line": 10,
                "marker_y": (20.0, 30.0),
                "target_y": (25.0, 35.0),
                "previous_y": (5.0, 15.0),
                "binding_basis": "reviewed_pdf_page_bbox_vertical_overlap",
            },
        )

    def test_chapter30_profile_binds_multiline_and_context_without_mutating_raw(self) -> None:
        source = self._chapter30_multiline_fixture()
        source_hash = hashlib.sha256(source).hexdigest()
        with (
            mock.patch.object(
                staging_raw_ingest, "CHAPTER30_SOURCE_TEXT_SHA256", source_hash
            ),
            mock.patch.object(staging_raw_ingest, "CHAPTER30_EXPECTED_ROWS", 3),
            mock.patch.object(
                staging_raw_ingest, "CHAPTER30_EXPECTED_PLUS_ROWS", 1
            ),
            mock.patch.object(
                staging_raw_ingest,
                "CHAPTER30_REVIEWED_DUTY_NOTE_BINDINGS",
                self._chapter30_duty_binding(),
            ),
        ):
            payload = prepare_ett_staging_batch(
                source,
                batch_size=3,
                allow_leading_plus=True,
                bind_chapter30_multiline=True,
            )

        first, previous, target = payload["batch"]["rows"]
        self.assertEqual(payload["parser_version"], CHAPTER30_PARSER_VERSION)
        self.assertTrue(first["raw_line"].startswith("+ "))
        self.assertEqual(
            first["row_sha256"],
            hashlib.sha256(first["raw_line"].encode("utf-8")).hexdigest(),
        )
        self.assertEqual(
            first["description_provenance"]["fragments"],
            ["– – проверяемая позиция,", "продолжение описания"],
        )
        self.assertIn(
            "3002            Проверяемый верхний заголовок",
            first["preceding_context_provenance"]["text"],
        )
        self.assertIn(
            "продолжение верхнего заголовка",
            first["preceding_context_provenance"]["text"],
        )
        self.assertNotIn("следующий контекст", first["description"])
        self.assertIn(
            "следующий контекст",
            previous["preceding_context_provenance"]["text"],
        )
        self.assertEqual(previous["duty_text"], "5")
        self.assertEqual(previous["duty_provenance"]["rendered_text"], "5")
        self.assertNotIn("note_marker", previous["duty_provenance"])
        self.assertEqual(target["duty_text"], "5")
        self.assertEqual(target["duty_provenance"]["text"], "5")
        self.assertEqual(target["duty_provenance"]["rendered_text"], "5 63С)")
        self.assertEqual(
            target["duty_provenance"]["note_marker"]["target_hs_code"],
            "3005905000",
        )
        self.assertEqual(
            target["duty_provenance"]["note_marker"]["marker_source_line"], 11
        )
        self.assertEqual(
            payload["completeness"]["record_outcomes"],
            {"complete": 3, "ambiguous": 0, "errors": 0},
        )
        self.assertEqual(payload["completeness"]["duty_continuation_line_count"], 0)
        self.assertEqual(
            payload["completeness"]["reviewed_duty_note_binding_count"], 1
        )

    def test_chapter30_profile_rejects_digest_before_parsing(self) -> None:
        with mock.patch.object(staging_raw_ingest, "_parse_rows") as parser:
            with self.assertRaisesRegex(
                StagingRawIngestError, "non-reviewed source layout"
            ):
                prepare_ett_staging_batch(
                    b"not the reviewed layout",
                    allow_leading_plus=True,
                    bind_chapter30_multiline=True,
                )
            parser.assert_not_called()

    def test_chapter30_profile_rejects_misaligned_orphan_continuation(self) -> None:
        source = self._chapter30_multiline_fixture(continuation_shift=1)
        source_hash = hashlib.sha256(source).hexdigest()
        with (
            mock.patch.object(
                staging_raw_ingest, "CHAPTER30_SOURCE_TEXT_SHA256", source_hash
            ),
            mock.patch.object(staging_raw_ingest, "CHAPTER30_EXPECTED_ROWS", 3),
            mock.patch.object(
                staging_raw_ingest, "CHAPTER30_EXPECTED_PLUS_ROWS", 1
            ),
            mock.patch.object(
                staging_raw_ingest,
                "CHAPTER30_REVIEWED_DUTY_NOTE_BINDINGS",
                self._chapter30_duty_binding(),
            ),
            self.assertRaisesRegex(
                AmbiguousEttRowError, "unclassified chapter-30 table context"
            ),
        ):
            prepare_ett_staging_batch(
                source,
                allow_leading_plus=True,
                bind_chapter30_multiline=True,
            )

    def test_chapter30_profile_rejects_nonexclusive_duty_note_placement(self) -> None:
        source = self._chapter30_multiline_fixture()
        source_hash = hashlib.sha256(source).hexdigest()
        bad_binding = dict(self._chapter30_duty_binding()[0])
        bad_binding["previous_y"] = (25.0, 35.0)
        with (
            mock.patch.object(
                staging_raw_ingest, "CHAPTER30_SOURCE_TEXT_SHA256", source_hash
            ),
            mock.patch.object(staging_raw_ingest, "CHAPTER30_EXPECTED_ROWS", 3),
            mock.patch.object(
                staging_raw_ingest, "CHAPTER30_EXPECTED_PLUS_ROWS", 1
            ),
            mock.patch.object(
                staging_raw_ingest,
                "CHAPTER30_REVIEWED_DUTY_NOTE_BINDINGS",
                (bad_binding,),
            ),
            self.assertRaisesRegex(
                AmbiguousEttRowError, "geometry is not exclusive"
            ),
        ):
            prepare_ett_staging_batch(
                source,
                allow_leading_plus=True,
                bind_chapter30_multiline=True,
            )

    def test_legacy_pin_keeps_533_rows_while_opt_in_exposes_five_candidates(
        self,
    ) -> None:
        unmarked = [
            _line(f"{2_900_000_000 + ordinal:010d}", f"legacy товар {ordinal}")
            for ordinal in range(1, 534)
        ]
        plus_candidates = [
            "+ "
            + _line(
                f"{2_999_000_000 + ordinal:010d}",
                f"отдельный кандидат {ordinal}",
            )
            for ordinal in range(1, 6)
        ]
        mixed = unmarked[:151] + plus_candidates + unmarked[151:]
        source = ("\n".join(mixed) + "\n").encode("utf-8")

        legacy = prepare_ett_staging_batch(source, batch_size=1000)
        plus_aware = prepare_ett_staging_batch(
            source,
            batch_size=1000,
            allow_leading_plus=True,
        )

        self.assertEqual(legacy["parser_version"], PARSER_VERSION)
        self.assertNotIn("allow_leading_plus", legacy)
        self.assertNotIn("completeness", legacy)
        self.assertEqual(legacy["totals"]["raw_count"], 533)
        self.assertEqual(legacy["batch"]["rows"][151]["ordinal"], 152)
        self.assertEqual(legacy["batch"]["rows"][151]["raw_line"], unmarked[151])
        self.assertEqual(
            legacy["batch"]["rows"][151]["row_sha256"],
            hashlib.sha256(unmarked[151].encode("utf-8")).hexdigest(),
        )
        self.assertEqual(plus_aware["parser_version"], PLUS_PARSER_VERSION)
        self.assertIs(plus_aware["allow_leading_plus"], True)
        self.assertEqual(plus_aware["totals"]["raw_count"], 538)
        self.assertEqual(
            sum(
                row["raw_line"].startswith("+ ")
                for row in plus_aware["batch"]["rows"]
            ),
            5,
        )
        self.assertEqual(plus_aware["batch"]["rows"][156]["ordinal"], 157)
        self.assertEqual(plus_aware["batch"]["rows"][156]["raw_line"], unmarked[151])

    def test_invalid_utf8_is_rejected(self) -> None:
        for source in (b"\xff", b"header\n2901 10 000 1   \xff\n"):
            with self.subTest(source=source):
                with self.assertRaisesRegex(InvalidUtf8SourceError, "not valid UTF-8"):
                    prepare_ett_staging_batch(source)

    def test_leading_plus_mode_requires_a_real_boolean(self) -> None:
        with self.assertRaisesRegex(TypeError, "allow_leading_plus must be a boolean"):
            prepare_ett_staging_batch(_source(1), allow_leading_plus=1)

    def test_unicode_replacement_character_is_rejected_as_lossy_provenance(self) -> None:
        source = (_line("2901100001", "испорчено \ufffd") + "\n").encode("utf-8")
        with self.assertRaisesRegex(InvalidUtf8SourceError, "replacement character"):
            prepare_ett_staging_batch(source)

    def test_non_ascii_digits_are_never_accepted_as_an_hs_code(self) -> None:
        source = "٢٩٠١ ١٠ ٠٠٠ ١   – – этан            –            3\n".encode("utf-8")
        with self.assertRaisesRegex(StagingRawIngestError, "no exact 10-digit"):
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

    def test_malformed_change_prefix_is_rejected(self) -> None:
        for prefix in ("+3004-prefix", "+\u00a0", "* ", "*", "++ ", "++", "—", "＋ "):
            with self.subTest(prefix=prefix):
                malformed = (
                    prefix + _line("3004100006", "неподдерживаемый маркер")
                    if prefix != "+3004-prefix"
                    else "+3004 10 000 6   неподдерживаемый маркер            –            5"
                )
                source = (
                    _line("3004100005", "валидная строка")
                    + "\n"
                    + malformed
                    + "\n"
                ).encode("utf-8")
                with self.assertRaisesRegex(
                    AmbiguousEttRowError, "unsupported code prefix"
                ):
                    prepare_ett_staging_batch(source, allow_leading_plus=True)

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
            self.assertEqual(json.loads(serialized)["parser_version"], PARSER_VERSION)

    def test_cli_plus_mode_uses_the_versioned_parser(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path = root / "source.txt"
            output_path = root / "batch.json"
            raw_line = "+ " + _line("3004100006", "маркированная строка")
            source_path.write_bytes((raw_line + "\n").encode("utf-8"))
            script = Path(__file__).parents[1] / "scripts" / "prepare_ett_staging_batch.py"

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--text",
                    str(source_path),
                    "--allow-leading-plus",
                    "--output",
                    str(output_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["parser_version"], PLUS_PARSER_VERSION)
            self.assertEqual(payload["batch"]["rows"][0]["raw_line"], raw_line)


if __name__ == "__main__":
    unittest.main()


