from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.services.staging_ett_normalization_core import (
    COLLECTED_UNVERIFIED,
    ETT_NORMALIZER_VERSION,
    canonical_json,
    sha256_json,
)
from app.services.staging_ett_offline_plan import (
    EttOfflinePlanError,
    build_offline_artifacts,
    write_offline_artifacts,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
RUNNER = BACKEND_ROOT / "scripts" / "ett_offline_plan.py"
SOURCE_ID = "eec-ett:group01:2022-04-25"
SOURCE_REVISION = "2022-04-25-group01"
SOURCE_BYTES = b"synthetic immutable ETT group01 bytes"


def _write_canonical(path: Path, value) -> bytes:
    content = canonical_json(value).encode("utf-8")
    path.write_bytes(content)
    return content


def _build_package(root: Path) -> dict:
    root.mkdir()
    source_path = root / "original.bin"
    source_path.write_bytes(SOURCE_BYTES)
    source_sha = hashlib.sha256(SOURCE_BYTES).hexdigest()
    source = {
        "source_id": SOURCE_ID,
        "authority": "EEC",
        "dataset": "EEC-ETT",
        "source_url": "https://eec.eaeunion.org/upload/ett/group01.pdf",
        "source_revision": SOURCE_REVISION,
        "object_bucket": "official-originals",
        "object_key": "ett/2022-04-25/group01/original.pdf",
        "sha256": source_sha,
        "size_bytes": len(SOURCE_BYTES),
        "media_type": "application/pdf",
        "captured_at": "2026-10-30T00:00:00+00:00",
        "status": COLLECTED_UNVERIFIED,
    }
    raw_rows = []
    provenance = []
    extraction_rows = []
    duties = ["0"] * 30 + ["5"] * 51 + ["5 63С)"] * 5
    for ordinal, duty in enumerate(duties, start=1):
        hs_code = f"{ordinal:010d}"
        description = f"Товар №{ordinal} — тест"
        supplementary_unit = "кг" if ordinal % 2 else ""
        page_number = 1 + (ordinal - 1) // 20
        raw_line = f"{hs_code}\t{description}\t{supplementary_unit}\t{duty}"
        hash_payload = {
            "hs_code": hs_code,
            "description": description,
            "supplementary_unit": supplementary_unit,
            "duty_text": duty,
            "page_number": page_number,
            "line_number": ordinal,
            "raw_line": raw_line,
        }
        row_sha = sha256_json(hash_payload)
        raw_rows.append(
            {
                "source_id": SOURCE_ID,
                "hs_code": hs_code,
                "description": description,
                "supplementary_unit": supplementary_unit,
                "duty_text": duty,
                "raw_line": raw_line,
                "row_sha256": row_sha,
                "status": COLLECTED_UNVERIFIED,
                "ordinal": ordinal,
            }
        )
        provenance.append(
            {
                "ordinal": ordinal,
                "hs_code": hs_code,
                "row_sha256": row_sha,
                "page_number": page_number,
                "line_number": ordinal,
            }
        )
        extraction_rows.append({"ordinal": ordinal, **hash_payload})
    base_scope = {"dataset": "EEC-ETT", "group": "01"}
    identity = {
        "source_id": SOURCE_ID,
        "source_sha256": source_sha,
        "source_size_bytes": len(SOURCE_BYTES),
        "source_url": source["source_url"],
        "source_revision": SOURCE_REVISION,
        "object_bucket": source["object_bucket"],
        "object_key": source["object_key"],
        "scope": base_scope,
        "parser_version": "ett-immutable-group-pdf-staging-v1",
    }
    ingest_run = {
        "run_id": f"ett:{sha256_json(identity)}",
        "source_id": SOURCE_ID,
        "scope": {
            **base_scope,
            "source_identity": identity,
            "stage_counts": {"normalized": 0, "verified": 0, "admitted": 0},
            "row_provenance": provenance,
        },
        "parser_version": identity["parser_version"],
        "status": COLLECTED_UNVERIFIED,
        "raw_count": 86,
        "unique_count": 86,
        "normalized_count": 0,
        "rejected_count": 0,
        "resume_cursor": {"next_ordinal": 87, "raw_count": 86, "complete": True},
    }
    extraction = {
        "schema_version": 1,
        "source_id": SOURCE_ID,
        "source_revision": SOURCE_REVISION,
        "rows": extraction_rows,
    }
    extraction_bytes = _write_canonical(root / "extraction.json", extraction)
    extraction_sha = hashlib.sha256(extraction_bytes).hexdigest()
    manifest = {
        "schema_version": 1,
        "source_id": SOURCE_ID,
        "source_revision": SOURCE_REVISION,
        "source_sha256": source_sha,
        "source_size_bytes": len(SOURCE_BYTES),
        "extraction_sha256": extraction_sha,
        "extraction_size_bytes": len(extraction_bytes),
    }
    manifest_bytes = _write_canonical(root / "manifest.json", manifest)
    package = {
        "schema_version": 1,
        "normalizer_version": ETT_NORMALIZER_VERSION,
        "source_object": source,
        "ingest_run": ingest_run,
        "raw_rows": raw_rows,
        "artifacts": {
            "source_bytes": {
                "path": "original.bin",
                "sha256": source_sha,
                "size_bytes": len(SOURCE_BYTES),
            },
            "retained_manifest": {
                "path": "manifest.json",
                "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                "size_bytes": len(manifest_bytes),
            },
            "retained_extraction": {
                "path": "extraction.json",
                "sha256": extraction_sha,
                "size_bytes": len(extraction_bytes),
            },
        },
    }
    _write_canonical(root / "package.json", package)
    return package


def _rewrite_package(root: Path, package: dict) -> None:
    _write_canonical(root / "package.json", package)


class OfflinePlanRunnerTests(unittest.TestCase):
    def test_pure_86_row_plan_and_sql_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            package_dir = Path(temporary) / "package"
            _build_package(package_dir)
            plan, sql = build_offline_artifacts(package_dir)
        self.assertEqual(plan["expected_counts"], {
            "raw": 86,
            "parsed": 81,
            "ambiguous": 5,
            "verified": 0,
            "admitted": 0,
        })
        self.assertEqual(
            plan["normalization_digest"],
            "a8505e8754342f082ce0d1018ba691a64b079e7130facaddf9dbfd51dc27c2f3",
        )
        self.assertTrue(all(row["legal_status"] == "UNVERIFIED" for row in plan["rows"]))
        self.assertTrue(all(not row["verified"] and not row["admitted"] for row in plan["rows"]))
        ambiguous = [row for row in plan["rows"] if row["is_ambiguous"]]
        self.assertEqual(len(ambiguous), 5)
        self.assertTrue(all(row["normalized_rate_text"] is None for row in ambiguous))
        self.assertIn("CREATE TABLE tariff_ingest.ett_normalization_results", sql)
        self.assertIn("conflicting existing normalization version", sql)
        self.assertIn("same-version exact replay mutates zero rows", plan["invariants"])
        self.assertNotIn("HsRate", sql)
        self.assertNotIn("DATABASE_URL", sql)
        self.assertEqual(
            sql.count("CREATE TABLE tariff_ingest.ett_normalization_results"), 1
        )
        self.assertLess(sql.index("current_database()"), sql.index("source_objects s"))
        self.assertLess(
            sql.index("ett_collected_rows package mismatch"),
            sql.index("CREATE TABLE tariff_ingest.ett_normalization_results"),
        )
        self.assertIn("GET DIAGNOSTICS inserted_count = ROW_COUNT", sql)
        self.assertIn("normalization post-insert verification failed", sql)
        self.assertIn("unsupported triggers or RLS", sql)
        self.assertEqual(
            sql.count("INSERT INTO tariff_ingest.ett_normalization_results"), 1
        )
        self.assertNotRegex(sql, r"(?im)^\s*(UPDATE|DELETE|ALTER|DROP|TRUNCATE)\b")
        self.assertNotRegex(
            sql,
            r"(?im)^\s*(START\s+TRANSACTION|BEGIN\s*;|COMMIT|ROLLBACK|\\connect)\b",
        )

    def test_cli_runs_with_site_packages_disabled_and_is_deterministic(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package_dir = root / "package"
            _build_package(package_dir)
            outputs = []
            for name in ("first", "second"):
                output = root / name
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-S",
                        str(RUNNER),
                        "--package",
                        str(package_dir),
                        "--output-dir",
                        str(output),
                    ],
                    cwd=BACKEND_ROOT,
                    env={**os.environ, "DATABASE_URL": "must-not-be-read"},
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                outputs.append(output)
            self.assertEqual(
                (outputs[0] / "plan.json").read_bytes(),
                (outputs[1] / "plan.json").read_bytes(),
            )
            self.assertEqual(
                (outputs[0] / "apply.sql").read_bytes(),
                (outputs[1] / "apply.sql").read_bytes(),
            )

    def test_print_package_schema_without_optional_dependencies(self):
        completed = subprocess.run(
            [sys.executable, "-S", str(RUNNER), "--print-package-schema"],
            cwd=BACKEND_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        schema = json.loads(completed.stdout)
        self.assertIn("retained_manifest_required_bindings", schema)
        self.assertIn("retained_extraction_row_fields", schema)

    def test_retained_json_formatting_and_existing_envelopes_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package_dir = root / "package"
            package = _build_package(package_dir)
            extraction_path = package_dir / "extraction.json"
            extraction = json.loads(extraction_path.read_text(encoding="utf-8"))
            extraction_bytes = json.dumps(
                extraction["rows"], ensure_ascii=False, indent=2
            ).encode("utf-8")
            extraction_path.write_bytes(extraction_bytes)
            extraction_sha = hashlib.sha256(extraction_bytes).hexdigest()
            package["artifacts"]["retained_extraction"].update(
                sha256=extraction_sha, size_bytes=len(extraction_bytes)
            )
            manifest = {
                "existing": {
                    "source": {
                        "id": SOURCE_ID,
                        "revision": SOURCE_REVISION,
                        "sha256": package["source_object"]["sha256"],
                        "size": package["source_object"]["size_bytes"],
                    },
                    "extraction": {
                        "sha256": extraction_sha,
                        "size": len(extraction_bytes),
                    },
                }
            }
            manifest_bytes = json.dumps(
                manifest, ensure_ascii=False, indent=2
            ).encode("utf-8")
            (package_dir / "manifest.json").write_bytes(manifest_bytes)
            package["artifacts"]["retained_manifest"].update(
                sha256=hashlib.sha256(manifest_bytes).hexdigest(),
                size_bytes=len(manifest_bytes),
            )
            _rewrite_package(package_dir, package)
            plan, _ = build_offline_artifacts(package_dir)
            self.assertEqual(plan["expected_counts"]["raw"], 86)

    def test_output_directory_is_atomic_and_must_be_new(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package_dir = root / "package"
            _build_package(package_dir)
            output = root / "output"
            output.mkdir()
            marker = output / "marker"
            marker.write_text("unchanged", encoding="utf-8")
            with self.assertRaisesRegex(EttOfflinePlanError, "must not already exist"):
                write_offline_artifacts(package_dir, output)
            self.assertEqual(marker.read_text(encoding="utf-8"), "unchanged")

    def test_rejects_bool_ordinal_before_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package_dir = root / "package"
            package = _build_package(package_dir)
            package["raw_rows"][0]["ordinal"] = True
            _rewrite_package(package_dir, package)
            output = root / "output"
            with self.assertRaisesRegex(EttOfflinePlanError, "positive integer"):
                write_offline_artifacts(package_dir, output)
            self.assertFalse(output.exists())

    def test_rejects_full_identity_and_run_id_corruption(self):
        for mutation, message in (
            (
                lambda package: package["ingest_run"]["scope"]["source_identity"].__setitem__(
                    "source_url", "https://example.invalid/wrong.pdf"
                ),
                "source_identity",
            ),
            (
                lambda package: package["ingest_run"].__setitem__("run_id", "ett:" + "0" * 64),
                "run_id",
            ),
        ):
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                package_dir = root / "package"
                package = _build_package(package_dir)
                mutation(package)
                _rewrite_package(package_dir, package)
                with self.assertRaisesRegex(EttOfflinePlanError, message):
                    write_offline_artifacts(package_dir, root / "output")
                self.assertFalse((root / "output").exists())

    def test_rejects_raw_and_provenance_hash_corruption_separately(self):
        cases = (
            (
                lambda package: package["raw_rows"][0].__setitem__("description", "corrupt"),
                "canonical raw row SHA mismatch",
            ),
            (
                lambda package: package["ingest_run"]["scope"]["row_provenance"][0].__setitem__(
                    "row_sha256", "0" * 64
                ),
                "row provenance identity mismatch",
            ),
        )
        for mutation, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                package_dir = root / "package"
                package = _build_package(package_dir)
                mutation(package)
                _rewrite_package(package_dir, package)
                with self.assertRaisesRegex(EttOfflinePlanError, message):
                    write_offline_artifacts(package_dir, root / "output")
                self.assertFalse((root / "output").exists())

    def test_rejects_source_manifest_and_extraction_corruption(self):
        corruptions = (
            ("original.bin", b"corrupt", "source_bytes byte digest"),
            ("manifest.json", b"{}", "retained_manifest byte digest"),
            ("extraction.json", b"{}", "retained_extraction byte digest"),
        )
        for filename, value, message in corruptions:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                package_dir = root / "package"
                _build_package(package_dir)
                (package_dir / filename).write_bytes(value)
                with self.assertRaisesRegex(EttOfflinePlanError, message):
                    write_offline_artifacts(package_dir, root / "output")
                self.assertFalse((root / "output").exists())

    def test_rejects_extraction_rows_even_with_updated_descriptor_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package_dir = root / "package"
            package = _build_package(package_dir)
            extraction_path = package_dir / "extraction.json"
            extraction = json.loads(extraction_path.read_text(encoding="utf-8"))
            extraction["rows"][0]["raw_line"] = "different"
            extraction_bytes = _write_canonical(extraction_path, extraction)
            digest = hashlib.sha256(extraction_bytes).hexdigest()
            package["artifacts"]["retained_extraction"].update(
                sha256=digest, size_bytes=len(extraction_bytes)
            )
            manifest_path = package_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.update(
                extraction_sha256=digest, extraction_size_bytes=len(extraction_bytes)
            )
            manifest_bytes = _write_canonical(manifest_path, manifest)
            package["artifacts"]["retained_manifest"].update(
                sha256=hashlib.sha256(manifest_bytes).hexdigest(),
                size_bytes=len(manifest_bytes),
            )
            _rewrite_package(package_dir, package)
            with self.assertRaisesRegex(EttOfflinePlanError, "extraction rows mismatch"):
                write_offline_artifacts(package_dir, root / "output")
            self.assertFalse((root / "output").exists())

    def test_rejects_missing_fields_and_path_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package_dir = root / "package"
            package = _build_package(package_dir)
            del package["source_object"]["source_revision"]
            _rewrite_package(package_dir, package)
            with self.assertRaisesRegex(EttOfflinePlanError, "fields mismatch"):
                build_offline_artifacts(package_dir)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package_dir = root / "package"
            package = _build_package(package_dir)
            package["artifacts"]["source_bytes"]["path"] = "../outside.bin"
            _rewrite_package(package_dir, package)
            with self.assertRaisesRegex(EttOfflinePlanError, "stay inside"):
                build_offline_artifacts(package_dir)

    def test_plan_digest_and_sql_digest_are_self_verifying(self):
        with tempfile.TemporaryDirectory() as temporary:
            package_dir = Path(temporary) / "package"
            _build_package(package_dir)
            plan, sql = build_offline_artifacts(package_dir)
        plan_digest = plan.pop("plan_sha256")
        self.assertEqual(plan_digest, sha256_json(plan))
        self.assertEqual(plan["sql_sha256"], hashlib.sha256(sql.encode()).hexdigest())

    def test_no_optional_database_imports_in_pure_runner_boundary(self):
        paths = (
            BACKEND_ROOT / "app/services/staging_ett_normalization_core.py",
            BACKEND_ROOT / "app/services/staging_ett_offline_plan.py",
            RUNNER,
        )
        combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)
        self.assertNotIn("sqlalchemy", combined.lower())
        self.assertNotIn("alembic", combined.lower())
        self.assertNotIn("DATABASE_URL", combined)
        self.assertNotIn("import socket", combined)


if __name__ == "__main__":
    unittest.main()

