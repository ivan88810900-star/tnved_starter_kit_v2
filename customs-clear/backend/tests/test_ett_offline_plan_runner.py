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


def _build_package(
    root: Path,
    *,
    row_count: int = 86,
    chapter: str = "01",
    source_id: str = SOURCE_ID,
    source_revision: str = SOURCE_REVISION,
) -> dict:
    root.mkdir()
    source_bytes = (
        SOURCE_BYTES
        if chapter == "01"
        else f"synthetic immutable ETT chapter{chapter} bytes".encode()
    )
    source_path = root / "original.bin"
    source_path.write_bytes(source_bytes)
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    source = {
        "source_id": source_id,
        "authority": "EEC",
        "dataset": "EEC-ETT",
        "source_url": f"https://eec.eaeunion.org/upload/ett/group{chapter}.pdf",
        "source_revision": source_revision,
        "object_bucket": "official-originals",
        "object_key": f"ett/2022-04-25/group{chapter}/original.pdf",
        "sha256": source_sha,
        "size_bytes": len(source_bytes),
        "media_type": "application/pdf",
        "captured_at": "2026-10-30T00:00:00+00:00",
        "status": COLLECTED_UNVERIFIED,
    }
    raw_rows = []
    provenance = []
    extraction_rows = []
    duty_cycle = ["0"] * 30 + ["5"] * 51 + ["5 63С)"] * 5
    duties = [duty_cycle[index % len(duty_cycle)] for index in range(row_count)]
    for ordinal, duty in enumerate(duties, start=1):
        hs_code = f"{chapter}{ordinal:08d}"
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
                "source_id": source_id,
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
    base_scope = {
        "chapter": chapter,
        "task_id": f"synthetic-retained-group{chapter}",
        "manifest": {"schema_version": 1, "kind": "retained"},
        "extraction": {"schema_version": 1, "rows": row_count},
        "readback_verified": True,
    }
    identity = {
        "source_id": source_id,
        "source_sha256": source_sha,
        "source_size_bytes": len(source_bytes),
        "source_url": source["source_url"],
        "source_revision": source_revision,
        "object_bucket": source["object_bucket"],
        "object_key": source["object_key"],
        "scope": base_scope,
        "parser_version": "ett-immutable-group-pdf-staging-v1",
    }
    ingest_run = {
        "run_id": f"ett:{sha256_json(identity)}",
        "source_id": source_id,
        "scope": {
            **base_scope,
            "source_identity": identity,
            "stage_counts": {"normalized": 0, "verified": 0, "admitted": 0},
            "row_provenance": provenance,
        },
        "parser_version": identity["parser_version"],
        "status": COLLECTED_UNVERIFIED,
        "raw_count": row_count,
        "unique_count": row_count,
        "normalized_count": 0,
        "rejected_count": 0,
        "resume_cursor": {
            "next_ordinal": row_count + 1,
            "raw_count": row_count,
            "complete": True,
        },
    }
    extraction = {
        "schema_version": 1,
        "source_id": source_id,
        "source_revision": source_revision,
        "rows": extraction_rows,
    }
    extraction_bytes = _write_canonical(root / "extraction.json", extraction)
    extraction_sha = hashlib.sha256(extraction_bytes).hexdigest()
    manifest = {
        "schema_version": 1,
        "source_id": source_id,
        "source_revision": source_revision,
        "source_sha256": source_sha,
        "source_size_bytes": len(source_bytes),
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
                "size_bytes": len(source_bytes),
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


def _replace_manifest(root: Path, package: dict, manifest: dict) -> None:
    manifest_bytes = json.dumps(
        manifest, ensure_ascii=False, indent=2
    ).encode("utf-8")
    (root / "manifest.json").write_bytes(manifest_bytes)
    package["artifacts"]["retained_manifest"].update(
        sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        size_bytes=len(manifest_bytes),
    )
    _rewrite_package(root, package)


def _replace_extraction(root: Path, package: dict, extraction: dict) -> None:
    extraction_bytes = _write_canonical(root / "extraction.json", extraction)
    extraction_sha = hashlib.sha256(extraction_bytes).hexdigest()
    package["artifacts"]["retained_extraction"].update(
        sha256=extraction_sha,
        size_bytes=len(extraction_bytes),
    )
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if "extraction_sha256" in manifest:
        manifest.update(
            extraction_sha256=extraction_sha,
            extraction_size_bytes=len(extraction_bytes),
        )
    else:
        manifest["objects"]["extraction"].update(
            sha256=extraction_sha,
            size_bytes=len(extraction_bytes),
        )
    _replace_manifest(root, package, manifest)


def _rebind_row_hs_code(
    root: Path, package: dict, *, ordinal: int, hs_code: str
) -> None:
    raw = package["raw_rows"][ordinal - 1]
    provenance = package["ingest_run"]["scope"]["row_provenance"][ordinal - 1]
    extraction_path = root / "extraction.json"
    extraction = json.loads(extraction_path.read_text(encoding="utf-8"))
    raw["hs_code"] = hs_code
    raw["raw_line"] = hs_code + "\t" + raw["raw_line"].split("\t", 1)[1]
    hash_payload = {
        "hs_code": hs_code,
        "description": raw["description"],
        "supplementary_unit": raw["supplementary_unit"],
        "duty_text": raw["duty_text"],
        "page_number": provenance["page_number"],
        "line_number": provenance["line_number"],
        "raw_line": raw["raw_line"],
    }
    row_sha = sha256_json(hash_payload)
    raw["row_sha256"] = row_sha
    provenance.update(hs_code=hs_code, row_sha256=row_sha)
    extraction["rows"][ordinal - 1] = {"ordinal": ordinal, **hash_payload}
    _replace_extraction(root, package, extraction)


def _rebind_scope_identity(package: dict) -> None:
    scope = package["ingest_run"]["scope"]
    identity = scope["source_identity"]
    identity["scope"] = {
        key: value
        for key, value in scope.items()
        if key not in {"source_identity", "stage_counts", "row_provenance"}
    }
    package["ingest_run"]["run_id"] = f"ett:{sha256_json(identity)}"


def _legacy_manifest(package: dict) -> dict:
    source = package["source_object"]
    extraction = package["artifacts"]["retained_extraction"]
    extraction_key = str(
        Path(source["object_key"]).with_name("extraction.json")
    )
    return {
        "schema_version": 1,
        "authority": source["authority"],
        "dataset": source["dataset"],
        "chapter": package["ingest_run"]["scope"]["chapter"],
        "source_url": source["source_url"],
        "source_revision": source["source_revision"],
        "captured_at": source["captured_at"].replace("+00:00", "Z"),
        "status": source["status"],
        "admission": {
            "normalized": 0,
            "verified": 0,
            "admitted": 0,
        },
        "objects": {
            "original": {
                "bucket": source["object_bucket"],
                "key": source["object_key"],
                "media_type": source["media_type"],
                "sha256": source["sha256"],
                "size_bytes": source["size_bytes"],
            },
            "extraction": {
                "bucket": source["object_bucket"],
                "key": extraction_key,
                "media_type": "application/json",
                "sha256": extraction["sha256"],
                "size_bytes": extraction["size_bytes"],
                "raw_count": package["ingest_run"]["raw_count"],
                "unique_count": package["ingest_run"]["unique_count"],
                "next_ordinal": package["ingest_run"]["resume_cursor"][
                    "next_ordinal"
                ],
            },
        },
    }


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
            "a27ef170c43f6402e308998e4aadbeeaabf5706cbb5573189179ce9a7fd0771f",
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

    def test_faithful_533_chapter_plan_and_534_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            package_dir = Path(temporary) / "package"
            _build_package(
                package_dir,
                row_count=533,
                chapter="29",
                source_id="synthetic-eec-ett:chapter29",
                source_revision="synthetic-chapter29-revision",
            )
            plan, _ = build_offline_artifacts(package_dir)
        self.assertEqual(plan["expected_counts"]["raw"], 533)
        self.assertEqual(
            plan["expected_counts"]["parsed"]
            + plan["expected_counts"]["ambiguous"],
            533,
        )
        self.assertTrue(all(row["hs_code"].startswith("29") for row in plan["rows"]))
        self.assertTrue(all(not row["verified"] for row in plan["rows"]))
        self.assertTrue(all(not row["admitted"] for row in plan["rows"]))

        with tempfile.TemporaryDirectory() as temporary:
            package_dir = Path(temporary) / "package"
            _build_package(
                package_dir,
                row_count=534,
                chapter="29",
                source_id="synthetic-eec-ett:chapter29",
                source_revision="synthetic-chapter29-revision",
            )
            with self.assertRaisesRegex(
                EttOfflinePlanError, "raw row count must be between 1 and 533"
            ):
                build_offline_artifacts(package_dir)

    def test_rejects_invalid_chapter_and_hs_prefix_mismatch(self):
        for chapter in ("1", "290", 29, "٢٩"):
            with self.subTest(chapter=chapter), tempfile.TemporaryDirectory() as temporary:
                package_dir = Path(temporary) / "package"
                package = _build_package(package_dir)
                package["ingest_run"]["scope"]["chapter"] = chapter
                _rebind_scope_identity(package)
                _rewrite_package(package_dir, package)
                with self.assertRaisesRegex(
                    EttOfflinePlanError, "exact ASCII two-digit string"
                ):
                    build_offline_artifacts(package_dir)

        with tempfile.TemporaryDirectory() as temporary:
            package_dir = Path(temporary) / "package"
            package = _build_package(package_dir)
            package["ingest_run"]["scope"]["chapter"] = "29"
            _rebind_scope_identity(package)
            _rewrite_package(package_dir, package)
            with self.assertRaisesRegex(
                EttOfflinePlanError, "hs_code chapter prefix"
            ):
                build_offline_artifacts(package_dir)

    def test_same_hs_with_distinct_identity_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            package_dir = Path(temporary) / "package"
            package = _build_package(package_dir)
            repeated_hs = package["raw_rows"][0]["hs_code"]
            _rebind_row_hs_code(
                package_dir,
                package,
                ordinal=86,
                hs_code=repeated_hs,
            )
            plan, _ = build_offline_artifacts(package_dir)
        repeated = [row for row in plan["rows"] if row["hs_code"] == repeated_hs]
        self.assertEqual([row["ordinal"] for row in repeated], [1, 86])
        self.assertEqual(len({row["raw_row_sha256"] for row in repeated}), 2)
        self.assertEqual(
            [row["syntax_status"] for row in repeated],
            ["PARSED", "AMBIGUOUS"],
        )
        self.assertEqual(
            [row["line_number"] for row in repeated],
            [1, 86],
        )

    def test_rejects_duplicate_raw_identity_even_when_provenance_matches(self):
        with tempfile.TemporaryDirectory() as temporary:
            package_dir = Path(temporary) / "package"
            package = _build_package(package_dir)
            duplicate_sha = package["raw_rows"][0]["row_sha256"]
            package["raw_rows"][85]["row_sha256"] = duplicate_sha
            package["ingest_run"]["scope"]["row_provenance"][85][
                "row_sha256"
            ] = duplicate_sha
            _rewrite_package(package_dir, package)
            with self.assertRaisesRegex(EttOfflinePlanError, "duplicate raw row hash"):
                build_offline_artifacts(package_dir)

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
        self.assertIn("retained_manifest_forms", schema)
        self.assertIn("retained_legacy_v1", schema["retained_manifest_forms"])
        self.assertIn("retained_extraction_row_fields", schema)

    def test_retained_json_formatting_and_flat_envelope_are_preserved(self):
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
                "schema_version": 1,
                "source_id": SOURCE_ID,
                "source_revision": SOURCE_REVISION,
                "source_sha256": package["source_object"]["sha256"],
                "source_size_bytes": package["source_object"]["size_bytes"],
                "extraction_sha256": extraction_sha,
                "extraction_size_bytes": len(extraction_bytes),
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

    def test_rejects_noncanonical_package_and_flat_manifest_numeric_types(self):
        with tempfile.TemporaryDirectory() as temporary:
            package_dir = Path(temporary) / "package"
            package = _build_package(package_dir)
            package["schema_version"] = True
            _rewrite_package(package_dir, package)
            with self.assertRaisesRegex(
                EttOfflinePlanError, "package schema_version mismatch"
            ):
                build_offline_artifacts(package_dir)

        for label, key, value in (
            ("schema bool", "schema_version", True),
            ("source size float", "source_size_bytes", float(len(SOURCE_BYTES))),
            ("extraction size float", "extraction_size_bytes", None),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                package_dir = Path(temporary) / "package"
                package = _build_package(package_dir)
                manifest_path = package_dir / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest[key] = (
                    float(manifest["extraction_size_bytes"])
                    if value is None
                    else value
                )
                _replace_manifest(package_dir, package, manifest)
                with self.assertRaisesRegex(EttOfflinePlanError, "flat_v1"):
                    build_offline_artifacts(package_dir)

    def test_retained_legacy_manifest_without_source_id_is_semantically_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            package_dir = Path(temporary) / "package"
            package = _build_package(package_dir)
            manifest = _legacy_manifest(package)
            self.assertNotIn("source_id", manifest)
            _replace_manifest(package_dir, package, manifest)
            plan, _ = build_offline_artifacts(package_dir)
        self.assertEqual(plan["expected_counts"]["raw"], 86)
        self.assertEqual(
            plan["retained_manifest"]["objects"]["original"]["sha256"],
            package["source_object"]["sha256"],
        )
        self.assertEqual(
            {
                key: plan["retained_manifest"]["objects"]["extraction"][key]
                for key in ("raw_count", "unique_count", "next_ordinal")
            },
            {"raw_count": 86, "unique_count": 86, "next_ordinal": 87},
        )
        self.assertEqual(
            plan["retained_manifest"]["admission"],
            {"normalized": 0, "verified": 0, "admitted": 0},
        )
        self.assertEqual(plan["retained_manifest"]["captured_at"][-1], "Z")

    def test_rejects_legacy_manifest_binding_substitutions(self):
        mutations = (
            (
                "original bucket",
                lambda manifest: manifest["objects"]["original"].__setitem__(
                    "bucket", "wrong-bucket"
                ),
            ),
            (
                "original key",
                lambda manifest: manifest["objects"]["original"].__setitem__(
                    "key", "wrong/original.pdf"
                ),
            ),
            (
                "original media_type",
                lambda manifest: manifest["objects"]["original"].__setitem__(
                    "media_type", "application/octet-stream"
                ),
            ),
            (
                "original sha256",
                lambda manifest: manifest["objects"]["original"].__setitem__(
                    "sha256", "0" * 64
                ),
            ),
            (
                "original size_bytes",
                lambda manifest: manifest["objects"]["original"].__setitem__(
                    "size_bytes", 1
                ),
            ),
            (
                "extraction bucket",
                lambda manifest: manifest["objects"]["extraction"].__setitem__(
                    "bucket", "wrong-bucket"
                ),
            ),
            (
                "extraction key",
                lambda manifest: manifest["objects"]["extraction"].__setitem__(
                    "key", "wrong/extraction.json"
                ),
            ),
            (
                "extraction media_type",
                lambda manifest: manifest["objects"]["extraction"].__setitem__(
                    "media_type", "text/plain"
                ),
            ),
            (
                "extraction sha256",
                lambda manifest: manifest["objects"]["extraction"].__setitem__(
                    "sha256", "0" * 64
                ),
            ),
            (
                "extraction size_bytes",
                lambda manifest: manifest["objects"]["extraction"].__setitem__(
                    "size_bytes", 1
                ),
            ),
            (
                "source_revision",
                lambda manifest: manifest.__setitem__(
                    "source_revision", "wrong-revision"
                ),
            ),
            (
                "source_url",
                lambda manifest: manifest.__setitem__(
                    "source_url", "https://example.invalid/wrong.pdf"
                ),
            ),
            (
                "authority",
                lambda manifest: manifest.__setitem__("authority", "wrong-authority"),
            ),
            (
                "dataset",
                lambda manifest: manifest.__setitem__("dataset", "wrong-dataset"),
            ),
            (
                "captured_at",
                lambda manifest: manifest.__setitem__(
                    "captured_at", "2026-01-01T00:00:01Z"
                ),
            ),
            (
                "chapter",
                lambda manifest: manifest.__setitem__("chapter", "02"),
            ),
            (
                "status",
                lambda manifest: manifest.__setitem__("status", "VERIFIED"),
            ),
        )
        for label, mutation in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                package_dir = Path(temporary) / "package"
                package = _build_package(package_dir)
                manifest = _legacy_manifest(package)
                mutation(manifest)
                _replace_manifest(package_dir, package, manifest)
                with self.assertRaisesRegex(EttOfflinePlanError, "manifest"):
                    build_offline_artifacts(package_dir)

    def test_rejects_invalid_or_naive_legacy_manifest_timestamps(self):
        for value, message in (
            ("not-a-timestamp", "valid ISO-8601"),
            ("2026-10-30T00:00:00", "include a timezone"),
        ):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temporary:
                package_dir = Path(temporary) / "package"
                package = _build_package(package_dir)
                manifest = _legacy_manifest(package)
                manifest["captured_at"] = value
                _replace_manifest(package_dir, package, manifest)
                with self.assertRaisesRegex(EttOfflinePlanError, message):
                    build_offline_artifacts(package_dir)

    def test_missing_or_legacy_group_scope_fails_without_key_error(self):
        for label, mutation in (
            ("missing", lambda scope: scope.pop("chapter")),
            (
                "group",
                lambda scope: scope.__setitem__("group", scope.pop("chapter")),
            ),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                package_dir = Path(temporary) / "package"
                package = _build_package(package_dir)
                manifest = _legacy_manifest(package)
                mutation(package["ingest_run"]["scope"])
                _rebind_scope_identity(package)
                _replace_manifest(package_dir, package, manifest)
                with self.assertRaisesRegex(
                    EttOfflinePlanError, "scope.chapter.*group is not a substitute"
                ):
                    build_offline_artifacts(package_dir)

    def test_rejects_noncanonical_upstream_counter_types(self):
        mutations = (
            (
                "stage bool",
                lambda package: package["ingest_run"]["scope"]["stage_counts"].__setitem__(
                    "normalized", False
                ),
                "stage_counts.normalized",
            ),
            (
                "stage float",
                lambda package: package["ingest_run"]["scope"]["stage_counts"].__setitem__(
                    "verified", 0.0
                ),
                "stage_counts.verified",
            ),
            (
                "cursor next float",
                lambda package: package["ingest_run"]["resume_cursor"].__setitem__(
                    "next_ordinal", 87.0
                ),
                "resume_cursor.next_ordinal",
            ),
            (
                "cursor raw float",
                lambda package: package["ingest_run"]["resume_cursor"].__setitem__(
                    "raw_count", 86.0
                ),
                "resume_cursor.raw_count",
            ),
            (
                "cursor complete integer",
                lambda package: package["ingest_run"]["resume_cursor"].__setitem__(
                    "complete", 1
                ),
                "resume_cursor.complete",
            ),
        )
        for label, mutation, message in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                package_dir = Path(temporary) / "package"
                package = _build_package(package_dir)
                manifest = _legacy_manifest(package)
                mutation(package)
                _replace_manifest(package_dir, package, manifest)
                with self.assertRaisesRegex(EttOfflinePlanError, message):
                    build_offline_artifacts(package_dir)

    def test_rejects_legacy_manifest_schema_shape_and_unrelated_matches(self):
        def wrong_schema(manifest, _package):
            manifest["schema_version"] = 2

        def wrong_objects(manifest, _package):
            manifest["objects"] = []

        def missing_required(manifest, _package):
            del manifest["objects"]["extraction"]["media_type"]

        def swapped_objects(manifest, _package):
            manifest["objects"]["original"], manifest["objects"]["extraction"] = (
                manifest["objects"]["extraction"],
                manifest["objects"]["original"],
            )

        def unrelated_scalar_match(manifest, package):
            correct = manifest["objects"]["original"]["sha256"]
            manifest["objects"]["original"]["sha256"] = "0" * 64
            manifest["admission"]["unrelated_source_sha256"] = correct
            manifest["objects"]["extraction"]["unrelated_source_id"] = package[
                "source_object"
            ]["source_id"]

        def wrong_admission_shape(manifest, _package):
            manifest["admission"] = []

        def wrong_raw_count(manifest, _package):
            manifest["objects"]["extraction"]["raw_count"] = 85

        def wrong_unique_count(manifest, _package):
            manifest["objects"]["extraction"]["unique_count"] = 85

        def wrong_next_ordinal(manifest, _package):
            manifest["objects"]["extraction"]["next_ordinal"] = 86

        def wrong_admission_count(manifest, _package):
            manifest["admission"]["normalized"] = 1

        def bool_admission_count(manifest, _package):
            manifest["admission"]["normalized"] = False

        def float_admission_count(manifest, _package):
            manifest["admission"]["normalized"] = 0.0

        def float_raw_count(manifest, _package):
            manifest["objects"]["extraction"]["raw_count"] = 86.0

        def float_unique_count(manifest, _package):
            manifest["objects"]["extraction"]["unique_count"] = 86.0

        def float_next_ordinal(manifest, _package):
            manifest["objects"]["extraction"]["next_ordinal"] = 87.0

        for label, mutation in (
            ("schema", wrong_schema),
            ("objects", wrong_objects),
            ("missing", missing_required),
            ("swapped", swapped_objects),
            ("unrelated", unrelated_scalar_match),
            ("admission", wrong_admission_shape),
            ("raw_count", wrong_raw_count),
            ("unique_count", wrong_unique_count),
            ("next_ordinal", wrong_next_ordinal),
            ("admission_count", wrong_admission_count),
            ("bool_admission_count", bool_admission_count),
            ("float_admission_count", float_admission_count),
            ("float_raw_count", float_raw_count),
            ("float_unique_count", float_unique_count),
            ("float_next_ordinal", float_next_ordinal),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                package_dir = Path(temporary) / "package"
                package = _build_package(package_dir)
                manifest = _legacy_manifest(package)
                mutation(manifest, package)
                _replace_manifest(package_dir, package, manifest)
                with self.assertRaisesRegex(EttOfflinePlanError, "manifest"):
                    build_offline_artifacts(package_dir)

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


