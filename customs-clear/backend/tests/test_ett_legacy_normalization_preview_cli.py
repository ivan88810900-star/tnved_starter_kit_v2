from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from app.services.staging_ett_normalization_core import canonical_json
from scripts.ett_legacy_normalization_preview import main
from tests.test_ett_legacy_normalization_preview import _preview, _verified


class EttLegacyNormalizationPreviewCliTests(unittest.TestCase):
    def _inputs(self, root: Path) -> tuple[dict, dict, Path, Path, Path]:
        fixture, envelope = _verified()
        envelope_path = root / "recovery-envelope.json"
        original_path = root / "original.pdf"
        source_text_path = root / "source.txt"
        envelope_path.write_text(
            json.dumps(envelope, ensure_ascii=False),
            encoding="utf-8",
        )
        original_path.write_bytes(fixture["original_bytes"])
        source_text_path.write_bytes(fixture["source_text_bytes"])
        return fixture, envelope, envelope_path, original_path, source_text_path

    def _run(
        self,
        envelope_path: Path,
        original_path: Path,
        source_text_path: Path,
        output_path: Path,
    ) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(
                [
                    "--recovery-envelope",
                    str(envelope_path),
                    "--original",
                    str(original_path),
                    "--source-text",
                    str(source_text_path),
                    "--output",
                    str(output_path),
                ]
            )
        return result, stdout.getvalue(), stderr.getvalue()

    def test_writes_canonical_preview_without_sql_or_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture, envelope, envelope_path, original_path, source_text_path = (
                self._inputs(root)
            )
            output_path = root / "preview.json"
            result, stdout, stderr = self._run(
                envelope_path, original_path, source_text_path, output_path
            )
            self.assertEqual(result, 0, stderr)
            preview = _preview(fixture, envelope)
            self.assertEqual(
                output_path.read_bytes(),
                (canonical_json(preview) + "\n").encode("utf-8"),
            )
            summary = json.loads(stdout)
            self.assertEqual(summary["preview_sha256"], preview["preview_sha256"])
            self.assertEqual(summary["counts"], preview["counts"])
            self.assertEqual(summary["legal_status"], "UNVERIFIED")
            self.assertEqual(summary["verified"], 0)
            self.assertEqual(summary["admitted"], 0)
            self.assertFalse(stderr)
            self.assertNotIn("sql", preview)
            self.assertFalse(preview["execution_performed"])
            self.assertFalse(preview["sql_generated"])

    def test_existing_output_is_never_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, envelope_path, original_path, source_text_path = self._inputs(root)
            output_path = root / "preview.json"
            output_path.write_bytes(b"keep-existing")
            result, _, stderr = self._run(
                envelope_path, original_path, source_text_path, output_path
            )
            self.assertEqual(result, 2)
            self.assertIn("File exists", stderr)
            self.assertEqual(output_path.read_bytes(), b"keep-existing")
            self.assertEqual(list(root.glob(".preview.json.*.tmp")), [])

    def test_duplicate_json_keys_fail_before_artifact_creation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, envelope_path, original_path, source_text_path = self._inputs(root)
            envelope_path.write_text(
                '{"schema_version":1,"schema_version":1}',
                encoding="utf-8",
            )
            output_path = root / "preview.json"
            result, _, stderr = self._run(
                envelope_path, original_path, source_text_path, output_path
            )
            self.assertEqual(result, 2)
            self.assertIn("duplicate JSON key", stderr)
            self.assertFalse(output_path.exists())

    def test_mismatched_original_bytes_fail_without_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, envelope_path, original_path, source_text_path = self._inputs(root)
            original_path.write_bytes(b"wrong")
            output_path = root / "preview.json"
            result, _, stderr = self._run(
                envelope_path, original_path, source_text_path, output_path
            )
            self.assertEqual(result, 2)
            self.assertIn("exact evidence", stderr)
            self.assertFalse(output_path.exists())


if __name__ == "__main__":
    unittest.main()
