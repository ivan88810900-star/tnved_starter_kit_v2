from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from app.services.staging_ett_normalization_core import (
    COLLECTED_UNVERIFIED,
    ETT_NORMALIZER_VERSION,
    LEGAL_STATUS_UNVERIFIED,
    SYNTAX_PARSED,
    _parse_rate,
    canonical_json,
    sha256_json,
)
from app.services.staging_ett_offline_plan import (
    EttOfflinePlanError,
    LEGACY_APPEND_PARSER_VERSION,
    LEGACY_APPEND_PLAN_KIND,
    LEGACY_APPEND_PACKAGE_KIND,
    LEGACY_APPEND_FIXED_ROWS,
    LEGACY_APPEND_SOURCE_SHA256,
    LEGACY_APPEND_SOURCE_TEXT_SHA256,
    LEGACY_PACKAGE_KIND,
    _fixed_append_source_row,
    _render_legacy_append_sql,
    _validate_fixed_append_provenance,
    _validate_legacy_append_digests,
    build_offline_artifacts,
    write_offline_artifacts,
)
from tests.test_ett_legacy_recovery import (
    _build as _build_legacy_recovery,
    _fixture as _legacy_fixture,
    _historical_line,
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


def _build_legacy_package(root: Path, *, append_candidates: bool = False) -> dict:
    root.mkdir()
    fixture = _legacy_fixture()
    for ordinal, row in enumerate(fixture["raw_rows"], start=1):
        duty = "5 with note" if ordinal <= 170 else "5"
        row["duty_text"] = duty
        row["raw_line"] = _historical_line(
            row["hs_code"],
            row["description"],
            row["supplementary_unit"],
            duty,
        )
        row["row_sha256"] = hashlib.sha256(
            row["raw_line"].encode("utf-8")
        ).hexdigest()
    lines = [row["raw_line"] for row in fixture["raw_rows"]]
    candidate_specs = []
    if append_candidates:
        mixed = []
        candidate_after = {50, 100, 200, 300, 400}
        candidate_number = 0
        for base_ordinal, line in enumerate(lines, start=1):
            mixed.append(line)
            if base_ordinal in candidate_after:
                candidate_number += 1
                hs_code = (
                    "2999000000"
                    if candidate_number == 2
                    else f"2999{candidate_number:06d}"
                )
                description = (
                    "– append standalone candidate 2"
                    if candidate_number == 2
                    else f"– append candidate {candidate_number}"
                )
                duty = "5" if candidate_number <= 2 else (
                    "0" if candidate_number == 3 else "563С)"
                )
                continuation = f"continuation {candidate_number}"
                raw_line = "+ " + _historical_line(
                    hs_code, description, "–", duty
                )
                mixed.extend([raw_line, continuation])
                candidate_specs.append(
                    {
                        "hs_code": hs_code,
                        "description": description,
                        "duty_text": duty,
                        "raw_line": raw_line,
                        "parent_raw_line": line,
                        "parent_description": f"description {base_ordinal}",
                        "continuation": continuation,
                    }
                )
        lines = mixed
    first_cut = len(lines) // 3
    second_cut = first_cut * 2
    fixture["source_text_bytes"] = "\n\f".join(
        [
            "\n".join(lines[:first_cut]),
            "\n".join(lines[first_cut:second_cut]),
            "\n".join(lines[second_cut:]),
        ]
    ).encode("utf-8")
    source_text_sha = hashlib.sha256(fixture["source_text_bytes"]).hexdigest()
    fixture["legacy_runs"][1]["scope"]["source_text_sha256"] = source_text_sha
    fixture["legacy_runs"][2]["scope"]["source_text_sha256"] = source_text_sha
    recovery = _build_legacy_recovery(fixture)

    original_path = root / "original.bin"
    source_text_path = root / "source.txt"
    original_path.write_bytes(fixture["original_bytes"])
    source_text_path.write_bytes(fixture["source_text_bytes"])
    source = {
        "source_id": fixture["source"]["source_id"],
        "authority": "EEC",
        "dataset": "EEC-ETT",
        "source_url": "https://eec.eaeunion.org/synthetic/chapter29.pdf",
        "source_revision": "synthetic-chapter29",
        "object_bucket": "official-originals",
        "object_key": "ett/synthetic/chapter29/original.pdf",
        "sha256": fixture["source"]["sha256"],
        "size_bytes": fixture["source"]["size_bytes"],
        "media_type": "application/pdf",
        "captured_at": "2026-10-16T00:00:00Z",
        "status": COLLECTED_UNVERIFIED,
    }
    package = {
        "schema_version": 1,
        "kind": LEGACY_PACKAGE_KIND,
        "normalizer_version": ETT_NORMALIZER_VERSION,
        "source_object": source,
        "recovery_envelope": recovery,
        "artifacts": {
            "original_bytes": {
                "path": "original.bin",
                "sha256": hashlib.sha256(fixture["original_bytes"]).hexdigest(),
                "size_bytes": len(fixture["original_bytes"]),
            },
            "source_text_bytes": {
                "path": "source.txt",
                "sha256": source_text_sha,
                "size_bytes": len(fixture["source_text_bytes"]),
            },
        },
    }
    _write_canonical(root / "package.json", package)
    if append_candidates:
        source_text = fixture["source_text_bytes"].decode("utf-8")
        logical_lines = source_text.splitlines()
        chunks = source_text.splitlines(keepends=True)
        page = 1
        page_line = 1
        source_position = 0
        locations = []
        for line, chunk in zip(logical_lines, chunks):
            if line.lstrip().startswith("+") or line.lstrip()[:4].isdigit():
                source_position += 1
            locations.append((source_position, page, page_line))
            if "\f" in chunk:
                page += chunk.count("\f")
                page_line = 1
            else:
                page_line += 1
        append_rows = []
        for offset, spec in enumerate(candidate_specs, start=1):
            raw_index = logical_lines.index(spec["raw_line"])
            parent_index = logical_lines.index(spec["parent_raw_line"])
            continuation_index = logical_lines.index(spec["continuation"])
            position, page_number, line_number = locations[raw_index]
            append_rows.append(
                {
                    "storage_ordinal": 533 + offset,
                    "source_position": position,
                    "source_line_number": raw_index + 1,
                    "page_number": page_number,
                    "line_number": line_number,
                    "hs_code": spec["hs_code"],
                    "description": spec["description"],
                    "description_provenance": {
                        "text": f"{spec['description']} {spec['continuation']}",
                        "source_lines": [raw_index + 1, continuation_index + 1],
                        "fragments": [spec["description"], spec["continuation"]],
                    },
                    "parent_heading_provenance": {
                        "text": "" if offset == 2 else spec["parent_description"],
                        "source_lines": [] if offset == 2 else [parent_index + 1],
                        "fragments": [] if offset == 2 else [spec["parent_description"]],
                    },
                    "supplementary_unit": "–",
                    "duty_text": spec["duty_text"],
                    "raw_line": spec["raw_line"],
                    "row_sha256": hashlib.sha256(
                        spec["raw_line"].encode("utf-8")
                    ).hexdigest(),
                    "status": COLLECTED_UNVERIFIED,
                }
            )
        package["kind"] = LEGACY_APPEND_PACKAGE_KIND
        package["append_rows"] = append_rows
        _write_canonical(root / "package.json", package)
    return package


def _build_legacy_append_package(root: Path) -> dict:
    return _build_legacy_package(root, append_candidates=True)


def _build_synthetic_append_plan(root: Path) -> tuple[dict, str]:
    package = _build_legacy_append_package(root)
    append_rows = package["append_rows"]
    legacy_package = dict(package)
    legacy_package.pop("append_rows")
    legacy_package["kind"] = LEGACY_PACKAGE_KIND
    _write_canonical(root / "package.json", legacy_package)
    base_plan, _ = build_offline_artifacts(root)
    source = base_plan["source_object"]
    append_raw = []
    crosswalk = []
    append_results = []
    for item in append_rows:
        raw = {
            "source_id": source["source_id"],
            "hs_code": item["hs_code"],
            "description": item["description"],
            "supplementary_unit": item["supplementary_unit"],
            "duty_text": item["duty_text"],
            "raw_line": item["raw_line"],
            "row_sha256": item["row_sha256"],
            "status": item["status"],
            "ordinal": item["storage_ordinal"],
        }
        link = {
            "storage_ordinal": item["storage_ordinal"],
            "source_position": item["source_position"],
            "source_line_number": item["source_line_number"],
            "page_number": item["page_number"],
            "line_number": item["line_number"],
            "hs_code": item["hs_code"],
            "row_sha256": item["row_sha256"],
            "description_provenance": item["description_provenance"],
            "parent_heading_provenance": item["parent_heading_provenance"],
        }
        syntax_status, rate, ambiguous, reason = _parse_rate(raw["duty_text"])
        payload = {
            "source_id": source["source_id"],
            "raw_row_sha256": raw["row_sha256"],
            "ordinal": raw["ordinal"],
            "parser_version": ETT_NORMALIZER_VERSION,
            "source_revision": source["source_revision"],
            "hs_code": raw["hs_code"],
            "page_number": link["page_number"],
            "line_number": link["line_number"],
            "original_description": link["description_provenance"]["text"],
            "original_supplementary_unit": raw["supplementary_unit"],
            "original_duty_text": raw["duty_text"],
            "original_raw_line": raw["raw_line"],
            "syntax_status": syntax_status,
            "normalized_rate_text": rate,
            "is_ambiguous": ambiguous,
            "ambiguity_reason": reason,
            "legal_status": LEGAL_STATUS_UNVERIFIED,
            "verified": False,
            "admitted": False,
        }
        result = {**payload, "result_sha256": sha256_json(payload)}
        link["result_sha256"] = result["result_sha256"]
        append_raw.append(raw)
        crosswalk.append(link)
        append_results.append(result)
    crosswalk_hash = sha256_json(crosswalk)
    run_identity = {
        "source_id": source["source_id"],
        "source_sha256": source["sha256"],
        "parser_version": LEGACY_APPEND_PARSER_VERSION,
        "storage_range": [534, 538],
        "crosswalk_sha256": crosswalk_hash,
    }
    append_run = {
        "run_id": f"ett-append:{sha256_json(run_identity)}",
        "source_id": source["source_id"],
        "scope": {
            "chapter": "29",
            "append_contract": LEGACY_APPEND_PLAN_KIND,
            "source_identity": run_identity,
            "stage_counts": {"normalized": 0, "verified": 0, "admitted": 0},
            "append_crosswalk_sha256": crosswalk_hash,
            "append_crosswalk": crosswalk,
        },
        "parser_version": LEGACY_APPEND_PARSER_VERSION,
        "status": COLLECTED_UNVERIFIED,
        "raw_count": 5,
        "unique_count": 5,
        "normalized_count": 0,
        "rejected_count": 0,
        "resume_cursor": {"next_ordinal": 539, "raw_count": 5, "complete": True},
    }
    plan = {
        "schema_version": 1,
        "kind": LEGACY_APPEND_PLAN_KIND,
        "target": "tariff_staging.tariff_ingest",
        "transaction_owner": "CALLER",
        "execution_performed": False,
        "source_object": source,
        "base_ingest_runs": base_plan["ingest_runs"],
        "base_raw_rows": base_plan["raw_rows"],
        "base_results": base_plan["rows"],
        "append_ingest_run": append_run,
        "append_raw_rows": append_raw,
        "append_results": append_results,
        "append_crosswalk": crosswalk,
        "append_crosswalk_sha256": crosswalk_hash,
        "normalizer_version": ETT_NORMALIZER_VERSION,
        "expected_counts": {
            "before_results": 619, "after_results": 624, "base_raw": 533,
            "append_raw": 5, "parsed": 3, "ambiguous": 2,
            "legal": 0, "verified": 0, "admitted": 0,
        },
        "invariants": ["synthetic SQL renderer fixture only"],
    }
    plan["append_digest"] = sha256_json(
        {"run": append_run, "raw": append_raw, "results": append_results}
    )
    sql = _render_legacy_append_sql(plan)
    plan["sql_sha256"] = hashlib.sha256(sql.encode()).hexdigest()
    plan["plan_sha256"] = sha256_json(plan)
    return plan, sql


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

    def test_legacy_533_projection_preserves_crosswalk_without_ddl(self):
        with tempfile.TemporaryDirectory() as temporary:
            package_dir = Path(temporary) / "package"
            package = _build_legacy_package(package_dir)
            plan, sql = build_offline_artifacts(package_dir)
        self.assertEqual(
            plan["expected_counts"],
            {
                "raw": 533,
                "parsed": 363,
                "ambiguous": 170,
                "legal": 0,
                "verified": 0,
                "admitted": 0,
            },
        )
        self.assertEqual(len(plan["ingest_runs"]), 3)
        self.assertEqual(len(plan["rows"]), 533)
        self.assertEqual(len(plan["legacy_crosswalk"]), 533)
        self.assertEqual(
            [run["run_id"] for run in plan["ingest_runs"]],
            [
                "synthetic-cycle-one",
                "synthetic-cycle-two",
                "synthetic-cycle-three",
            ],
        )
        for raw, row, link in zip(
            package["recovery_envelope"]["observed"]["raw_rows"],
            plan["rows"],
            plan["legacy_crosswalk"],
        ):
            self.assertEqual(row["raw_row_sha256"], raw["row_sha256"])
            self.assertEqual(link["persisted_result_sha256"], row["result_sha256"])
            self.assertNotEqual(
                link["preview_result_sha256"], link["persisted_result_sha256"]
            )
            payload = dict(row)
            persisted = payload.pop("result_sha256")
            self.assertEqual(persisted, sha256_json(payload))
        self.assertNotIn("CREATE TABLE", sql)
        self.assertNotIn("$ett_ddl$", sql)
        self.assertIn("legacy normalization target table is missing", sql)
        self.assertIn("IN SHARE ROW EXCLUSIVE MODE", sql)
        self.assertEqual(
            sql.count("INSERT INTO tariff_ingest.ett_normalization_results"), 1
        )
        self.assertNotRegex(sql, r"(?im)^\s*(UPDATE|DELETE|ALTER|DROP|TRUNCATE)\b")
        self.assertNotRegex(
            sql,
            r"(?im)^\s*(START\s+TRANSACTION|BEGIN\s*;|COMMIT|ROLLBACK|\\connect)\b",
        )

    def test_legacy_append5_contract_is_insert_only_and_provenance_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            package_dir = Path(temporary) / "package"
            plan, sql = _build_synthetic_append_plan(package_dir)

        self.assertEqual(plan["kind"], "ETT_LEGACY_CHAPTER29_APPEND5_PLAN_V1")
        self.assertEqual(
            plan["expected_counts"],
            {
                "before_results": 619,
                "after_results": 624,
                "base_raw": 533,
                "append_raw": 5,
                "parsed": 3,
                "ambiguous": 2,
                "legal": 0,
                "verified": 0,
                "admitted": 0,
            },
        )
        self.assertEqual(len(plan["base_ingest_runs"]), 3)
        self.assertEqual(len(plan["base_raw_rows"]), 533)
        self.assertEqual(len(plan["base_results"]), 533)
        self.assertEqual(len(plan["append_raw_rows"]), 5)
        self.assertEqual(len(plan["append_results"]), 5)
        self.assertEqual(
            [row["ordinal"] for row in plan["append_raw_rows"]],
            [534, 535, 536, 537, 538],
        )
        self.assertNotEqual(
            [row["ordinal"] for row in plan["append_raw_rows"]],
            [row["source_position"] for row in plan["append_crosswalk"]],
        )
        self.assertEqual(
            plan["append_ingest_run"]["scope"]["append_crosswalk"],
            plan["append_crosswalk"],
        )
        self.assertEqual(
            plan["append_ingest_run"]["scope"]["append_crosswalk_sha256"],
            plan["append_crosswalk_sha256"],
        )
        self.assertEqual(
            sha256_json(plan["append_crosswalk"]),
            plan["append_crosswalk_sha256"],
        )
        for index, (result, link) in enumerate(
            zip(plan["append_results"], plan["append_crosswalk"]), start=1
        ):
            self.assertEqual(
                result["original_description"],
                link["description_provenance"]["text"],
            )
            if index == 2:
                self.assertEqual(
                    link["parent_heading_provenance"],
                    {"text": "", "source_lines": [], "fragments": []},
                )
            else:
                self.assertTrue(link["parent_heading_provenance"]["text"])
            self.assertEqual(result["legal_status"], "UNVERIFIED")
            self.assertFalse(result["verified"])
            self.assertFalse(result["admitted"])
        self.assertEqual(
            [row["normalized_rate_text"] for row in plan["append_results"][-2:]],
            [None, None],
        )
        self.assertEqual(
            [row["original_duty_text"] for row in plan["append_results"][-2:]],
            ["563С)", "563С)"],
        )
        self.assertEqual(sql.count("INSERT INTO tariff_ingest.ingest_runs"), 1)
        self.assertEqual(sql.count("INSERT INTO tariff_ingest.ett_collected_rows"), 1)
        self.assertEqual(
            sql.count("INSERT INTO tariff_ingest.ett_normalization_results"), 1
        )
        self.assertIn("IN SHARE ROW EXCLUSIVE MODE", sql)
        self.assertIn("append current state is partial or conflicting", sql)
        self.assertIn("expected_table_contracts", sql)
        self.assertIn("append write table column contract mismatch", sql)
        self.assertIn("append write table constraint contract mismatch", sql)
        self.assertRegex(
            sql,
            r"INSERT INTO tariff_ingest\.ett_collected_rows \(\s*source_id, hs_code,",
        )
        self.assertRegex(
            sql,
            r"INSERT INTO tariff_ingest\.ingest_runs \(\s*run_id, source_id,",
        )
        self.assertNotRegex(
            sql,
            r"(?im)^\s*(UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE)\b",
        )
        self.assertNotRegex(
            sql,
            r"(?im)^\s*(START\s+TRANSACTION|BEGIN\s*;|COMMIT|ROLLBACK|\\connect)\b",
        )

    def test_legacy_append5_tampering_fails_before_sql(self):
        with tempfile.TemporaryDirectory() as temporary:
            package_dir = Path(temporary) / "package"
            _build_legacy_append_package(package_dir)
            with mock.patch(
                "app.services.staging_ett_offline_plan._build_legacy_offline_artifacts"
            ) as legacy_builder:
                with self.assertRaisesRegex(
                    EttOfflinePlanError, "non-authoritative PDF SHA-256"
                ):
                    build_offline_artifacts(package_dir)
                legacy_builder.assert_not_called()

        _validate_legacy_append_digests(
            LEGACY_APPEND_SOURCE_SHA256,
            LEGACY_APPEND_SOURCE_SHA256,
            LEGACY_APPEND_SOURCE_TEXT_SHA256,
            LEGACY_APPEND_SOURCE_TEXT_SHA256,
        )
        with self.assertRaisesRegex(EttOfflinePlanError, "layout SHA-256"):
            _validate_legacy_append_digests(
                LEGACY_APPEND_SOURCE_SHA256,
                LEGACY_APPEND_SOURCE_SHA256,
                "0" * 64,
                LEGACY_APPEND_SOURCE_TEXT_SHA256,
            )
        with self.assertRaisesRegex(EttOfflinePlanError, "layout SHA-256"):
            _validate_legacy_append_digests(
                LEGACY_APPEND_SOURCE_SHA256,
                LEGACY_APPEND_SOURCE_SHA256,
                LEGACY_APPEND_SOURCE_TEXT_SHA256,
                "0" * 64,
            )
        with self.assertRaisesRegex(EttOfflinePlanError, "PDF SHA-256"):
            _validate_legacy_append_digests(
                LEGACY_APPEND_SOURCE_SHA256,
                "0" * 64,
                LEGACY_APPEND_SOURCE_TEXT_SHA256,
                LEGACY_APPEND_SOURCE_TEXT_SHA256,
            )

    @staticmethod
    def _fixed_span_fixture(parent_lines=(1, 2, 4)):
        lines = [
            "  2932 00 000 0   parent  heading A",
            "       parent continuation",
            "2910 next heading outside selected parent expansion",
            "  2932 90 000 0   parent  heading B",
            "+ 2999 01 000 1   – actual-like product            –            5",
            "       description continuation one",
            "       description continuation two",
            "2910 heading that must not enter description",
        ]
        raw_line = lines[4]
        contract = {
            "source_line_number": 5,
            "description_lines": (5, 6, 7),
            "parent_lines": tuple(parent_lines),
            "hs_code": "2999010001",
            "duty_text": "5",
            "row_sha256": hashlib.sha256(raw_line.encode()).hexdigest(),
        }
        recovered = _fixed_append_source_row(lines, contract)
        item = {
            "description_provenance": json.loads(
                json.dumps(recovered["description_provenance"], ensure_ascii=False)
            ),
            "parent_heading_provenance": json.loads(
                json.dumps(recovered["parent_heading_provenance"], ensure_ascii=False)
            ),
        }
        return lines, recovered, item

    def test_legacy_append5_fixed_spans_exclude_neighboring_headings(self):
        lines, recovered, _ = self._fixed_span_fixture()
        self.assertEqual(
            recovered["description_provenance"],
            {
                "text": (
                    "– actual-like product description continuation one "
                    "description continuation two"
                ),
                "source_lines": [5, 6, 7],
                "fragments": [
                    "– actual-like product",
                    "description continuation one",
                    "description continuation two",
                ],
            },
        )
        self.assertNotIn(lines[7].strip(), recovered["description_provenance"]["text"])
        self.assertEqual(recovered["parent_heading_provenance"]["source_lines"], [1, 2, 4])
        self.assertEqual(
            recovered["parent_heading_provenance"]["fragments"],
            [lines[0].strip(), lines[1].strip(), lines[3].strip()],
        )
        self.assertEqual(
            [row["hs_code"] for row in LEGACY_APPEND_FIXED_ROWS],
            ["2909600000", "2911000000", "2932990000", "2939490000", "2939790000"],
        )
        self.assertEqual(
            [row["description_lines"] for row in LEGACY_APPEND_FIXED_ROWS],
            [tuple(range(728, 733)), tuple(range(747, 754)), (1803,), (2308,), (2326,)],
        )
        self.assertEqual(LEGACY_APPEND_FIXED_ROWS[1]["parent_lines"], ())

    def test_legacy_append5_rejects_semantically_rebound_context(self):
        def drop_continuation(item, _lines):
            provenance = item["description_provenance"]
            provenance["source_lines"] = provenance["source_lines"][:1]
            provenance["fragments"] = provenance["fragments"][:1]
            provenance["text"] = provenance["fragments"][0]

        def substitute_wrong_parent(item, lines):
            item["parent_heading_provenance"] = {
                "text": lines[2].strip(),
                "source_lines": [3],
                "fragments": [lines[2].strip()],
            }

        def substitute_neighbor_heading(item, lines):
            provenance = item["description_provenance"]
            provenance["source_lines"][-1] = 8
            provenance["fragments"][-1] = lines[7].strip()
            provenance["text"] = " ".join(provenance["fragments"])

        cases = (
            (
                "missing continuation",
                drop_continuation,
                "description provenance does not match fixed source span",
            ),
            (
                "wrong but present parent",
                substitute_wrong_parent,
                "parent provenance does not match fixed source span",
            ),
            (
                "neighbor heading as continuation",
                substitute_neighbor_heading,
                "description provenance does not match fixed source span",
            ),
        )
        for label, mutate, error in cases:
            with self.subTest(label=label):
                lines, recovered, item = self._fixed_span_fixture()
                mutate(item, lines)
                with self.assertRaisesRegex(EttOfflinePlanError, error):
                    _validate_fixed_append_provenance(
                        item,
                        recovered,
                        label="append row test",
                        source_lines=lines,
                        parent_is_empty=False,
                    )

    def test_legacy_append5_no_parent_is_limited_to_standalone_root(self):
        lines, recovered, item = self._fixed_span_fixture(parent_lines=())
        _validate_fixed_append_provenance(
            item, recovered, label="standalone", source_lines=lines, parent_is_empty=True
        )
        item["parent_heading_provenance"] = {
            "text": lines[0].strip(), "source_lines": [1],
            "fragments": [lines[0].strip()],
        }
        with self.assertRaisesRegex(EttOfflinePlanError, "fixed source span"):
            _validate_fixed_append_provenance(
                item, recovered, label="standalone", source_lines=lines,
                parent_is_empty=True,
            )

        lines, recovered, item = self._fixed_span_fixture()
        item["parent_heading_provenance"] = {
            "text": "", "source_lines": [], "fragments": []
        }
        with self.assertRaisesRegex(EttOfflinePlanError, "cannot be empty"):
            _validate_fixed_append_provenance(
                item, recovered, label="child", source_lines=lines,
                parent_is_empty=False,
            )

    def test_legacy_package_contract_tampering_fails_before_sql(self):
        mutations = (
            (
                "normalizer",
                lambda package, _root: package.__setitem__(
                    "normalizer_version", "wrong"
                ),
                "normalizer_version",
            ),
            (
                "source identity",
                lambda package, _root: package["source_object"].__setitem__(
                    "source_id", "wrong"
                ),
                "recovery source source_id",
            ),
            (
                "recovery",
                lambda package, _root: package["recovery_envelope"]["derived"].__setitem__(
                    "raw_count", 532
                ),
                "envelope SHA mismatch",
            ),
            (
                "artifact descriptor",
                lambda package, _root: package["artifacts"][
                    "source_text_bytes"
                ].__setitem__("sha256", "0" * 64),
                "byte digest",
            ),
            (
                "artifact bytes",
                lambda _package, root: (root / "source.txt").write_bytes(b"wrong"),
                "byte digest",
            ),
        )
        for label, mutate, message in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                package_dir = Path(temporary) / "package"
                package = _build_legacy_package(package_dir)
                mutate(package, package_dir)
                _rewrite_package(package_dir, package)
                with self.assertRaisesRegex(EttOfflinePlanError, message):
                    build_offline_artifacts(package_dir)

    def test_legacy_package_rejects_duplicate_keys_and_nonfinite_numbers(self):
        with tempfile.TemporaryDirectory() as temporary:
            package_dir = Path(temporary) / "package"
            _build_legacy_package(package_dir)
            package_path = package_dir / "package.json"
            encoded = package_path.read_text(encoding="utf-8")
            package_path.write_text(
                encoded.replace(
                    "{",
                    '{"kind":"ETT_LEGACY_CHAPTER29_APPLY_PACKAGE_V1",',
                    1,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(EttOfflinePlanError, "duplicate JSON key"):
                build_offline_artifacts(package_dir)

        with tempfile.TemporaryDirectory() as temporary:
            package_dir = Path(temporary) / "package"
            _build_legacy_package(package_dir)
            package_path = package_dir / "package.json"
            encoded = package_path.read_text(encoding="utf-8")
            package_path.write_text(
                encoded.replace('"schema_version":1', '"schema_version":NaN', 1),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(EttOfflinePlanError, "non-finite JSON"):
                build_offline_artifacts(package_dir)

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
