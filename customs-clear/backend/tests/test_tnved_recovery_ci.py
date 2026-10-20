from __future__ import annotations

from contextlib import closing
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from app.services.tnved_recovery_store import TnvedRecoveryStore


ROOT = Path(__file__).resolve().parents[1]
CHAPTERS = tuple(f"{number:02d}" for number in range(1, 98) if number != 77)
COUNTS = {"sources": 99, "editions": 96, "nodes": 192, "notes": 107, "ten_digit": 96}


def _builder():
    path = ROOT / "scripts/build_tnved_recovery.py"
    spec = importlib.util.spec_from_file_location("build_tnved_recovery_ci", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _gate_runner():
    path = ROOT / "scripts/run_tnved_recovery_ci.py"
    spec = importlib.util.spec_from_file_location("run_tnved_recovery_ci", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _fixture(directory: Path) -> tuple[Path, Path, str, str]:
    section_sizes = [5] * 12 + [4] * 9
    rows: list[str] = ["<html><body><table>"]
    offset = 0
    for number, size in enumerate(section_sizes, 1):
        roman = _builder()._to_roman(number)
        rows.append(f"<tr><td>РАЗДЕЛ {roman}</td><td>Синтетический раздел {number}</td></tr>")
        for chapter in CHAPTERS[offset : offset + size]:
            rows.append(f"<tr><td>Группа {chapter}</td><td>Синтетическая группа {chapter}</td></tr>")
        offset += size
    rows.append("</table></body></html>")
    index_raw = "".join(rows).encode()
    index_sha = _sha(index_raw)

    sources = [
        {
            "id": "eec-ett-index",
            "url": "https://example.invalid/eec-index",
            "title": "Synthetic EEC index",
            "sha256": index_sha,
            "retrievedAt": None,
            "mediaType": "text/html",
            "rawPath": "synthetic/ett-index.html",
        }
    ]
    for chapter in CHAPTERS:
        sources.append(
            {
                "id": f"source-{chapter}",
                "url": f"https://example.invalid/chapter-{chapter}",
                "title": f"Synthetic chapter {chapter}",
                "sha256": hashlib.sha256(chapter.encode()).hexdigest(),
                "retrievedAt": None,
                "mediaType": "application/pdf",
                "rawPath": f"synthetic/{chapter}.pdf",
            }
        )
    for suffix in ("a", "b"):
        sources.append(
            {
                "id": f"unused-{suffix}",
                "url": f"https://example.invalid/unused-{suffix}",
                "title": f"Synthetic unused {suffix}",
                "sha256": hashlib.sha256(suffix.encode()).hexdigest(),
                "retrievedAt": None,
                "mediaType": "text/plain",
                "rawPath": f"synthetic/unused-{suffix}.txt",
            }
        )

    editions = []
    nodes = []
    for chapter in CHAPTERS:
        edition = f"edition-{chapter}"
        source = f"source-{chapter}"
        editions.append(
            {
                "id": edition,
                "validFrom": None,
                "validTo": None,
                "chainStatus": "unverified",
                "complete": False,
                "chapters": [chapter],
                "sourceIds": [source],
                "limitations": ["synthetic CI fixture"],
            }
        )
        nodes.extend(
            [
                {
                    "editionId": edition,
                    "code": chapter,
                    "label": f"Synthetic chapter {chapter}",
                    "parentCode": None,
                    "sourceId": source,
                    "page": 1,
                    "path": [f"Synthetic chapter {chapter}"],
                    "noteRefs": [],
                    "changeSymbol": "",
                },
                {
                    "editionId": edition,
                    "code": f"{chapter}00000000",
                    "label": f"Synthetic leaf {chapter}",
                    "parentCode": chapter,
                    "sourceId": source,
                    "page": 2,
                    "path": [f"Synthetic chapter {chapter}", f"Synthetic leaf {chapter}"],
                    "noteRefs": [],
                    "changeSymbol": "",
                },
            ]
        )

    notes = [
        {
            "id": f"note-{number:03d}",
            "title": f"Synthetic note {number}",
            "sourceId": f"source-{CHAPTERS[number % len(CHAPTERS)]}",
            "page": number + 1,
            "text": "Synthetic fixture only",
            "url": None,
        }
        for number in range(COUNTS["notes"])
    ]
    catalog = {
        "schemaVersion": 1,
        "id": "synthetic-offline-ci-v1",
        "generatedAt": None,
        "importCoverage": {"acceptedChapters": list(CHAPTERS), "failedChapters": []},
        "sources": sources,
        "editions": editions,
        "notes": notes,
        "nodes": nodes,
    }
    catalog_raw = json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    catalog_path, index_path = directory / "catalog.json", directory / "ett-index.html"
    catalog_path.write_bytes(catalog_raw)
    index_path.write_bytes(index_raw)
    return catalog_path, index_path, _sha(catalog_raw), index_sha


class TnvedRecoveryOfflineCiTest(unittest.TestCase):
    def test_gate_rejects_zero_subject_tests(self) -> None:
        output = io.StringIO()
        exit_code = _gate_runner().run_suite(unittest.TestSuite(), stream=output)
        self.assertEqual(exit_code, 2)
        self.assertIn("no subject tests discovered", output.getvalue())

    def test_gate_rejects_all_subject_tests_skipped(self) -> None:
        class SkippedSubject(unittest.TestCase):
            @unittest.skip("synthetic missing fixture")
            def runTest(self) -> None:
                raise AssertionError("skip did not apply")

        output = io.StringIO()
        exit_code = _gate_runner().run_suite(
            unittest.TestSuite([SkippedSubject()]),
            stream=output,
        )
        self.assertEqual(exit_code, 4)
        self.assertIn("all subject tests skipped", output.getvalue())

    def test_gate_rejects_skipped_builders_even_when_guard_tests_pass(self) -> None:
        class MixedSuite(unittest.TestCase):
            def test_guard_one(self) -> None:
                pass

            def test_guard_two(self) -> None:
                pass

            @unittest.skip("synthetic missing builder fixture")
            def test_builder_one(self) -> None:
                raise AssertionError("skip did not apply")

            @unittest.skip("synthetic missing builder fixture")
            def test_builder_two(self) -> None:
                raise AssertionError("skip did not apply")

        suite = unittest.defaultTestLoader.loadTestsFromTestCase(MixedSuite)
        prefix = f"{MixedSuite.__module__}.{MixedSuite.__qualname__}."
        output = io.StringIO()
        exit_code = _gate_runner().run_required_subjects(
            suite,
            required_ids=(prefix + "test_builder_one", prefix + "test_builder_two"),
            stream=output,
        )
        self.assertEqual(exit_code, 4)
        self.assertIn("discovered=2 executed=2 skipped=2", output.getvalue())
        self.assertIn("all subject tests skipped", output.getvalue())

    def test_gate_rejects_missing_builders_even_when_guard_tests_remain(self) -> None:
        class GuardOnlySuite(unittest.TestCase):
            def test_guard_one(self) -> None:
                pass

            def test_guard_two(self) -> None:
                pass

        suite = unittest.defaultTestLoader.loadTestsFromTestCase(GuardOnlySuite)
        output = io.StringIO()
        exit_code = _gate_runner().run_required_subjects(
            suite,
            required_ids=("mandatory.builder.test_one", "mandatory.builder.test_two"),
            stream=output,
        )
        self.assertEqual(exit_code, 2)
        self.assertIn("missing mandatory subject tests", output.getvalue())

    def test_builder_is_deterministic_integral_and_readable(self) -> None:
        builder = _builder()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            catalog, index, catalog_sha, index_sha = _fixture(root)
            first, second = root / "first.sqlite", root / "second.sqlite"
            manifest = root / "manifest.json"
            arguments = {
                "catalog_sha256": catalog_sha,
                "index_sha256": index_sha,
                "expected_counts": COUNTS,
                "expected_chapters": CHAPTERS,
                "expected_section_count": 21,
            }
            one = builder._build_with_pins(catalog, index, first, manifest, **arguments)
            two = builder._build_with_pins(catalog, index, second, None, **arguments)

            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(one["sqliteSha256"], two["sqliteSha256"])
            self.assertEqual(one["logicalSha256"], two["logicalSha256"])
            self.assertEqual(one["counts"], {**COUNTS, "sections": 21, "chapters": 96})
            self.assertEqual(json.loads(manifest.read_text())["legalStatus"], "unverified")
            for database in (first, second):
                self.assertFalse(any(Path(f"{database}{suffix}").exists() for suffix in ("-journal", "-wal", "-shm")))
                with closing(sqlite3.connect(f"file:{database.resolve()}?mode=ro&immutable=1", uri=True)) as connection:
                    self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                    self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

            with TnvedRecoveryStore(first) as store:
                self.assertEqual(store.status()["nodes"], COUNTS["nodes"])
                self.assertEqual(store.status()["legal_status"], "unverified")
                item = store.lookup("0100000000")
                self.assertIsNotNone(item)
                assert item is not None
                self.assertIsNone(item["rates"])
                self.assertEqual(store.breadcrumb(item["code"])[-1]["code"], item["code"])
                self.assertEqual(store.search(item["code"])[0]["code"], item["code"])

    def test_builder_rejects_bytes_outside_supplied_pins(self) -> None:
        builder = _builder()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            catalog, index, catalog_sha, index_sha = _fixture(root)
            with self.assertRaisesRegex(ValueError, "approved input"):
                builder.build(catalog, index, root / "operational-rejected.sqlite")
            catalog.write_bytes(catalog.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "approved input"):
                builder._build_with_pins(
                    catalog,
                    index,
                    root / "rejected.sqlite",
                    None,
                    catalog_sha256=catalog_sha,
                    index_sha256=index_sha,
                    expected_counts=COUNTS,
                    expected_chapters=CHAPTERS,
                    expected_section_count=21,
                )


if __name__ == "__main__":
    unittest.main()
