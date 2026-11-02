"""Dependency-free validation and SQL planning for a local ETT package."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .staging_ett_legacy_normalization_preview import (
    EttLegacyPreviewError,
    build_legacy_normalization_preview,
)
from .staging_ett_legacy_recovery import EXPECTED_RAW_COUNT
from .staging_ett_normalization_core import (
    COLLECTED_UNVERIFIED,
    ETT_NORMALIZER_VERSION,
    LEGAL_STATUS_UNVERIFIED,
    SYNTAX_PARSED,
    EttNormalizationError,
    _parse_rate,
    build_ett_normalization_plan,
    canonical_json,
    sha256_json,
)


PACKAGE_SCHEMA_VERSION = 1
TARGET_SCHEMA = "tariff_ingest"
TARGET_TABLE = "ett_normalization_results"
LEGACY_PACKAGE_KIND = "ETT_LEGACY_CHAPTER29_APPLY_PACKAGE_V1"
LEGACY_PLAN_KIND = "ETT_LEGACY_CHAPTER29_NORMALIZATION_PLAN"
LEGACY_APPEND_PACKAGE_KIND = "ETT_LEGACY_CHAPTER29_APPEND5_PACKAGE_V1"
LEGACY_APPEND_PLAN_KIND = "ETT_LEGACY_CHAPTER29_APPEND5_PLAN_V1"
LEGACY_APPEND_PARSER_VERSION = "ett-pdftotext-layout-raw-v2-plus-append-v1"
LEGACY_APPEND_SOURCE_SHA256 = (
    "418666f5fc61db171a9d0bbcf068753504cd29ff04f0f4ac62d4e1147980b51a"
)
LEGACY_APPEND_SOURCE_TEXT_SHA256 = (
    "8555367965aabc91d0d9a7c288b8a89c24ea4771ab118ef6d4f5bd46421e0a5d"
)
LEGACY_APPEND_FIXED_ROWS = (
    {
        "storage_ordinal": 534, "hs_code": "2909600000", "source_line_number": 728,
        "source_position": 152, "page_number": 16, "line_number": 17,
        "description_lines": tuple(range(728, 733)),
        "parent_lines": tuple(range(630, 639)), "duty_text": "5",
        "row_sha256": "d7a650e9997ff8d318e09107f08fb5a457577453aa5ab306ae555c52a1a59dcf",
    },
    {
        "storage_ordinal": 535, "hs_code": "2911000000", "source_line_number": 747,
        "source_position": 159, "page_number": 16, "line_number": 36,
        "description_lines": tuple(range(747, 754)), "parent_lines": (),
        "duty_text": "5",
        "row_sha256": "ffa4e934873c19492f84719af4dc9a85be52c3bf0bfa1f51a8181cab0295a555",
    },
    {
        "storage_ordinal": 536, "hs_code": "2932990000", "source_line_number": 1803,
        "source_position": 408, "page_number": 38, "line_number": 12,
        "description_lines": (1803,), "parent_lines": (1738, 1739, 1740, 1782),
        "duty_text": "0",
        "row_sha256": "6a04bb94a3974c91d4b9781044c41fc06b55463dcb1db33901dc32f6421cb432",
    },
    {
        "storage_ordinal": 537, "hs_code": "2939490000", "source_line_number": 2308,
        "source_position": 513, "page_number": 48, "line_number": 20,
        "description_lines": (2308,),
        "parent_lines": (2265, 2266, 2267, 2268, 2285, 2286, 2287),
        "duty_text": "563С)",
        "row_sha256": "a15fbfeb7f475750511caad246602855fe44f4e4367fab4c39659ae8ee70a552",
    },
    {
        "storage_ordinal": 538, "hs_code": "2939790000", "source_line_number": 2326,
        "source_position": 521, "page_number": 48, "line_number": 38,
        "description_lines": (2326,),
        "parent_lines": (2265, 2266, 2267, 2268, 2322, 2323),
        "duty_text": "563С)",
        "row_sha256": "d8c1e205d234125d568b32461a07bd03d91a63f22e5c8f3234649261bbd43cf7",
    },
)

SOURCE_KEYS = {
    "source_id",
    "authority",
    "dataset",
    "source_url",
    "source_revision",
    "object_bucket",
    "object_key",
    "sha256",
    "size_bytes",
    "media_type",
    "captured_at",
    "status",
}
RUN_KEYS = {
    "run_id",
    "source_id",
    "scope",
    "parser_version",
    "status",
    "raw_count",
    "unique_count",
    "normalized_count",
    "rejected_count",
    "resume_cursor",
}
RAW_KEYS = {
    "source_id",
    "hs_code",
    "description",
    "supplementary_unit",
    "duty_text",
    "raw_line",
    "row_sha256",
    "status",
    "ordinal",
}
ARTIFACT_KEYS = {"path", "sha256", "size_bytes"}
ARTIFACT_NAMES = {"source_bytes", "retained_manifest", "retained_extraction"}
LEGACY_ARTIFACT_NAMES = {"original_bytes", "source_text_bytes"}
EXTRACTION_KEYS = {"schema_version", "source_id", "source_revision", "rows"}
EXTRACTION_ROW_KEYS = {
    "ordinal",
    "hs_code",
    "description",
    "supplementary_unit",
    "duty_text",
    "page_number",
    "line_number",
    "raw_line",
}
FLAT_MANIFEST_KEYS = {
    "schema_version",
    "source_id",
    "source_revision",
    "source_sha256",
    "source_size_bytes",
    "extraction_sha256",
    "extraction_size_bytes",
}
LEGACY_MANIFEST_KEYS = {
    "admission",
    "authority",
    "captured_at",
    "chapter",
    "dataset",
    "objects",
    "schema_version",
    "source_revision",
    "source_url",
    "status",
}
LEGACY_OBJECT_KEYS = {"original", "extraction"}
LEGACY_ADMISSION_KEYS = {"admitted", "normalized", "verified"}
LEGACY_ORIGINAL_KEYS = {"bucket", "key", "media_type", "sha256", "size_bytes"}
LEGACY_EXTRACTION_KEYS = LEGACY_ORIGINAL_KEYS | {
    "next_ordinal",
    "raw_count",
    "unique_count",
}
APPEND_ROW_KEYS = {
    "storage_ordinal",
    "source_position",
    "source_line_number",
    "page_number",
    "line_number",
    "hs_code",
    "description",
    "description_provenance",
    "parent_heading_provenance",
    "supplementary_unit",
    "duty_text",
    "raw_line",
    "row_sha256",
    "status",
}
TEXT_PROVENANCE_KEYS = {"text", "source_lines", "fragments"}
_APPEND_CODE_RE = re.compile(
    r"^[ \t]*\+[ \t]+(?P<g1>[0-9]{4})[ \t]+(?P<g2>[0-9]{2})[ \t]+"
    r"(?P<g3>[0-9]{3})[ \t]+(?P<g4>[0-9])(?P<tail>.*)$"
)
_SOURCE_CODE_RE = re.compile(
    r"^[ \t]*(?:\+[ \t]+)?[0-9]{4}[ \t]+[0-9]{2}[ \t]+"
    r"[0-9]{3}[ \t]+[0-9](?:[ \t]|$)"
)
_COLUMN_SEPARATOR_RE = re.compile(r"[ \t]{2,}")

PACKAGE_SCHEMA = {
    "schema_version": PACKAGE_SCHEMA_VERSION,
    "package_file": "package.json",
    "required_top_level": [
        "schema_version",
        "normalizer_version",
        "source_object",
        "ingest_run",
        "raw_rows",
        "artifacts",
    ],
    "source_object_fields": sorted(SOURCE_KEYS),
    "ingest_run_fields": sorted(RUN_KEYS),
    "raw_row_fields": sorted(RAW_KEYS),
    "artifacts": {
        name: sorted(ARTIFACT_KEYS) for name in sorted(ARTIFACT_NAMES)
    },
    "retained_manifest_forms": {
        "flat_v1": sorted(FLAT_MANIFEST_KEYS),
        "retained_legacy_v1": {
            "top_level": sorted(LEGACY_MANIFEST_KEYS),
            "admission": sorted(LEGACY_ADMISSION_KEYS),
            "objects": sorted(LEGACY_OBJECT_KEYS),
            "original": sorted(LEGACY_ORIGINAL_KEYS),
            "extraction": sorted(LEGACY_EXTRACTION_KEYS),
        },
    },
    "retained_extraction_forms": ["row array", "object containing rows"],
    "retained_extraction_row_fields": sorted(EXTRACTION_ROW_KEYS),
    "legacy_chapter29_v1": {
        "kind": LEGACY_PACKAGE_KIND,
        "required_top_level": [
            "schema_version",
            "kind",
            "normalizer_version",
            "source_object",
            "recovery_envelope",
            "artifacts",
        ],
        "artifacts": {
            name: sorted(ARTIFACT_KEYS)
            for name in sorted(LEGACY_ARTIFACT_NAMES)
        },
    },
    "legacy_chapter29_append5_v1": {
        "kind": LEGACY_APPEND_PACKAGE_KIND,
        "source_sha256": LEGACY_APPEND_SOURCE_SHA256,
        "source_text_sha256": LEGACY_APPEND_SOURCE_TEXT_SHA256,
        "fixed_rows": [
            {
                key: list(value) if isinstance(value, tuple) else value
                for key, value in row.items()
            }
            for row in LEGACY_APPEND_FIXED_ROWS
        ],
        "required_top_level": [
            "schema_version",
            "kind",
            "normalizer_version",
            "source_object",
            "recovery_envelope",
            "append_rows",
            "artifacts",
        ],
        "append_row_fields": sorted(APPEND_ROW_KEYS),
        "text_provenance_fields": sorted(TEXT_PROVENANCE_KEYS),
        "parent_heading_modes": {
            "fixed_source_spans": "exact reconstructed physical rows from the reviewed layout",
            "hs_2911000000_standalone": {
                "text": "",
                "source_lines": [],
                "fragments": [],
            },
        },
        "artifacts": {
            name: sorted(ARTIFACT_KEYS)
            for name in sorted(LEGACY_ARTIFACT_NAMES)
        },
    },
}


class EttOfflinePlanError(ValueError):
    """The explicit local package cannot produce a safe offline plan."""


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EttOfflinePlanError(f"{label} must be an object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise EttOfflinePlanError(
            f"{label} fields mismatch: missing={missing}, extra={extra}"
        )


def _strict_positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise EttOfflinePlanError(f"{label} must be a positive integer")
    return value


def _strict_nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EttOfflinePlanError(f"{label} must be a nonnegative integer")
    return value


def _aware_instant(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise EttOfflinePlanError(f"{label} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EttOfflinePlanError(
            f"{label} must be a valid ISO-8601 timestamp"
        ) from exc
    if parsed.utcoffset() is None:
        raise EttOfflinePlanError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _validate_source_object(value: Any) -> Mapping[str, Any]:
    source = _mapping(value, "source_object")
    _exact_keys(source, SOURCE_KEYS, "source_object")
    for field in SOURCE_KEYS - {"size_bytes"}:
        if not isinstance(source.get(field), str) or not source[field]:
            raise EttOfflinePlanError(f"source_object.{field} must be a string")
    _strict_positive_int(source.get("size_bytes"), "source_object.size_bytes")
    _aware_instant(source.get("captured_at"), "source_object.captured_at")
    if source.get("status") != COLLECTED_UNVERIFIED:
        raise EttOfflinePlanError(
            "source_object status is not COLLECTED_UNVERIFIED"
        )
    return source


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EttOfflinePlanError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise EttOfflinePlanError(f"non-finite JSON number is not allowed: {value}")


def _read_json_bytes(value: bytes, label: str) -> Any:
    try:
        decoded = value.decode("utf-8")
        parsed = json.loads(
            decoded,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except EttOfflinePlanError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EttOfflinePlanError(f"{label} must be canonical UTF-8 JSON") from exc
    return parsed


def _manifest_mismatch(label: str) -> None:
    raise EttOfflinePlanError(f"retained manifest {label} mismatch")


def _validate_flat_manifest(
    manifest: Mapping[str, Any],
    source: Mapping[str, Any],
    extraction_artifact: Mapping[str, Any],
) -> None:
    _exact_keys(manifest, FLAT_MANIFEST_KEYS, "retained manifest flat_v1")
    if type(manifest.get("schema_version")) is not int:
        raise EttOfflinePlanError(
            "retained manifest flat_v1.schema_version must be an integer"
        )
    for key in ("source_size_bytes", "extraction_size_bytes"):
        _strict_positive_int(
            manifest.get(key), f"retained manifest flat_v1.{key}"
        )
    expected = {
        "schema_version": 1,
        "source_id": source["source_id"],
        "source_revision": source["source_revision"],
        "source_sha256": source["sha256"],
        "source_size_bytes": source["size_bytes"],
        "extraction_sha256": extraction_artifact["sha256"],
        "extraction_size_bytes": extraction_artifact["size_bytes"],
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            _manifest_mismatch(f"flat_v1.{key}")


def _legacy_extraction_key(source_key: str) -> str:
    path = PurePosixPath(source_key)
    if path.name in {"", ".", ".."}:
        _manifest_mismatch("objects.original.key")
    return str(path.with_name("extraction.json"))


def _validate_legacy_manifest(
    manifest: Mapping[str, Any],
    source: Mapping[str, Any],
    ingest_run: Mapping[str, Any],
    extraction_artifact: Mapping[str, Any],
) -> None:
    _exact_keys(manifest, LEGACY_MANIFEST_KEYS, "retained manifest legacy_v1")
    scope = _mapping(ingest_run.get("scope"), "ingest_run.scope")
    chapter = scope.get("chapter")
    if not isinstance(chapter, str) or not chapter:
        raise EttOfflinePlanError(
            "ingest_run.scope.chapter must be a nonempty string; "
            "scope.group is not a substitute"
        )
    for key, value in {
        "schema_version": 1,
        "authority": source["authority"],
        "dataset": source["dataset"],
        "source_url": source["source_url"],
        "source_revision": source["source_revision"],
        "status": source["status"],
        "chapter": chapter,
    }.items():
        if manifest.get(key) != value:
            _manifest_mismatch(f"legacy_v1.{key}")
    manifest_instant = _aware_instant(
        manifest.get("captured_at"),
        "retained manifest legacy_v1.captured_at",
    )
    source_instant = _aware_instant(
        source.get("captured_at"), "source_object.captured_at"
    )
    if manifest_instant != source_instant:
        _manifest_mismatch("legacy_v1.captured_at")
    admission = _mapping(
        manifest.get("admission"), "retained manifest legacy_v1.admission"
    )
    _exact_keys(
        admission, LEGACY_ADMISSION_KEYS, "retained manifest legacy_v1.admission"
    )
    expected_admission = {
        "normalized": ingest_run["scope"]["stage_counts"]["normalized"],
        "verified": ingest_run["scope"]["stage_counts"]["verified"],
        "admitted": ingest_run["scope"]["stage_counts"]["admitted"],
    }
    for key in LEGACY_ADMISSION_KEYS:
        _strict_nonnegative_int(
            admission.get(key), f"retained manifest legacy_v1.admission.{key}"
        )
    if admission != expected_admission:
        _manifest_mismatch("legacy_v1.admission")
    objects = _mapping(
        manifest.get("objects"), "retained manifest legacy_v1.objects"
    )
    _exact_keys(objects, LEGACY_OBJECT_KEYS, "retained manifest legacy_v1.objects")
    original = _mapping(
        objects.get("original"), "retained manifest legacy_v1.objects.original"
    )
    _exact_keys(
        original,
        LEGACY_ORIGINAL_KEYS,
        "retained manifest legacy_v1.objects.original",
    )
    extraction = _mapping(
        objects.get("extraction"),
        "retained manifest legacy_v1.objects.extraction",
    )
    _exact_keys(
        extraction,
        LEGACY_EXTRACTION_KEYS,
        "retained manifest legacy_v1.objects.extraction",
    )
    expected_original = {
        "bucket": source["object_bucket"],
        "key": source["object_key"],
        "media_type": source["media_type"],
        "sha256": source["sha256"],
        "size_bytes": source["size_bytes"],
    }
    expected_extraction = {
        "bucket": source["object_bucket"],
        "key": _legacy_extraction_key(source["object_key"]),
        "media_type": "application/json",
        "sha256": extraction_artifact["sha256"],
        "size_bytes": extraction_artifact["size_bytes"],
        "raw_count": ingest_run["raw_count"],
        "unique_count": ingest_run["unique_count"],
        "next_ordinal": ingest_run["resume_cursor"]["next_ordinal"],
    }
    for key in ("raw_count", "unique_count", "next_ordinal"):
        _strict_positive_int(
            extraction.get(key),
            f"retained manifest legacy_v1.objects.extraction.{key}",
        )
    for key, value in expected_original.items():
        if original.get(key) != value:
            _manifest_mismatch(f"legacy_v1.objects.original.{key}")
    for key, value in expected_extraction.items():
        if extraction.get(key) != value:
            _manifest_mismatch(f"legacy_v1.objects.extraction.{key}")


def _validate_manifest_bindings(
    manifest: Mapping[str, Any],
    source: Mapping[str, Any],
    ingest_run: Mapping[str, Any],
    extraction_artifact: Mapping[str, Any],
) -> None:
    keys = set(manifest)
    if keys == FLAT_MANIFEST_KEYS:
        _validate_flat_manifest(manifest, source, extraction_artifact)
        return
    if keys == LEGACY_MANIFEST_KEYS:
        _validate_legacy_manifest(
            manifest, source, ingest_run, extraction_artifact
        )
        return
    raise EttOfflinePlanError(
        "retained manifest fields mismatch for supported schema_version=1 forms"
    )


def _artifact_path(package_dir: Path, relative: Any, label: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise EttOfflinePlanError(f"{label}.path must be a relative POSIX path")
    candidate = Path(relative)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise EttOfflinePlanError(f"{label}.path must stay inside the package")
    path = package_dir.joinpath(*candidate.parts)
    if path.is_symlink() or not path.is_file():
        raise EttOfflinePlanError(f"{label}.path must be a regular package file")
    if package_dir.resolve() not in path.resolve().parents:
        raise EttOfflinePlanError(f"{label}.path escapes the package")
    return path


def _read_artifact(
    package_dir: Path, descriptor: Any, label: str
) -> tuple[bytes, dict[str, Any]]:
    item = _mapping(descriptor, label)
    _exact_keys(item, ARTIFACT_KEYS, label)
    expected_size = _strict_positive_int(item.get("size_bytes"), f"{label}.size_bytes")
    expected_sha = item.get("sha256")
    if (
        not isinstance(expected_sha, str)
        or len(expected_sha) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha)
    ):
        raise EttOfflinePlanError(f"{label}.sha256 is malformed")
    path = _artifact_path(package_dir, item.get("path"), label)
    value = path.read_bytes()
    if len(value) != expected_size or _sha256_bytes(value) != expected_sha:
        raise EttOfflinePlanError(f"{label} byte digest or size mismatch")
    return value, dict(item)


def _validate_retained_artifacts(
    *,
    source: Mapping[str, Any],
    ingest_run: Mapping[str, Any],
    raw_rows: list[Mapping[str, Any]],
    artifacts: Mapping[str, tuple[bytes, dict[str, Any]]],
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    source_bytes, source_artifact = artifacts["source_bytes"]
    manifest_bytes, _ = artifacts["retained_manifest"]
    extraction_bytes, extraction_artifact = artifacts["retained_extraction"]
    if source.get("sha256") != _sha256_bytes(source_bytes):
        raise EttOfflinePlanError("source_objects sha256 does not match source bytes")
    if source.get("size_bytes") != len(source_bytes):
        raise EttOfflinePlanError("source_objects size_bytes does not match source bytes")
    if source_artifact["sha256"] != source.get("sha256"):
        raise EttOfflinePlanError("source artifact digest does not match source_objects")

    manifest = _mapping(
        _read_json_bytes(manifest_bytes, "retained_manifest"),
        "retained_manifest",
    )
    _validate_manifest_bindings(
        manifest, source, ingest_run, extraction_artifact
    )
    extraction = _read_json_bytes(extraction_bytes, "retained_extraction")
    if isinstance(extraction, Mapping):
        if "source_id" in extraction and extraction["source_id"] != source.get("source_id"):
            raise EttOfflinePlanError("retained extraction source_id mismatch")
        if (
            "source_revision" in extraction
            and extraction["source_revision"] != source.get("source_revision")
        ):
            raise EttOfflinePlanError("retained extraction source_revision mismatch")
        extraction_rows = extraction.get("rows")
    else:
        extraction_rows = extraction

    provenance = ingest_run["scope"]["row_provenance"]
    expected_rows = []
    for raw, row_provenance in zip(
        sorted(raw_rows, key=lambda row: row["ordinal"]),
        sorted(provenance, key=lambda row: row["ordinal"]),
    ):
        expected_rows.append(
            {
                "ordinal": raw["ordinal"],
                "hs_code": raw["hs_code"],
                "description": raw["description"],
                "supplementary_unit": raw["supplementary_unit"],
                "duty_text": raw["duty_text"],
                "page_number": row_provenance["page_number"],
                "line_number": row_provenance["line_number"],
                "raw_line": raw["raw_line"],
            }
        )
    if not isinstance(extraction_rows, list):
        raise EttOfflinePlanError("retained extraction rows must be an array")
    for index, row in enumerate(extraction_rows, start=1):
        item = _mapping(row, f"retained extraction row {index}")
        _exact_keys(item, EXTRACTION_ROW_KEYS, f"retained extraction row {index}")
    if extraction_rows != expected_rows:
        raise EttOfflinePlanError("retained extraction rows mismatch RAW/provenance")
    return manifest, extraction


def _json_hex(value: Any) -> str:
    return canonical_json(value).encode("utf-8").hex()


def _render_sql(plan: Mapping[str, Any]) -> str:
    legacy = plan.get("kind") == LEGACY_PLAN_KIND
    source_hex = _json_hex(plan["source_object"])
    run_hex = _json_hex(plan["ingest_runs"] if legacy else plan["ingest_run"])
    raw_hex = _json_hex(plan["raw_rows"])
    results_hex = _json_hex(plan["rows"])
    columns = [
        ["source_id", "text", True],
        ["raw_row_sha256", "text", True],
        ["ordinal", "integer", True],
        ["parser_version", "text", True],
        ["source_revision", "text", True],
        ["hs_code", "text", True],
        ["page_number", "integer", True],
        ["line_number", "integer", True],
        ["original_description", "text", True],
        ["original_supplementary_unit", "text", True],
        ["original_duty_text", "text", True],
        ["original_raw_line", "text", True],
        ["syntax_status", "text", True],
        ["normalized_rate_text", "text", False],
        ["is_ambiguous", "boolean", True],
        ["ambiguity_reason", "text", False],
        ["legal_status", "text", True],
        ["verified", "boolean", True],
        ["admitted", "boolean", True],
        ["result_sha256", "text", True],
    ]
    columns_hex = _json_hex(columns)
    if legacy:
        run_declaration = (
            "expected_runs jsonb := "
            f"convert_from(decode('{run_hex}', 'hex'), 'UTF8')::jsonb;"
        )
        run_preflight = """
    IF (SELECT count(*) FROM tariff_ingest.ingest_runs r
        WHERE r.source_id = expected_source->>'source_id')
       <> jsonb_array_length(expected_runs)
       OR EXISTS (
          SELECT 1 FROM jsonb_array_elements(expected_runs) e
          WHERE NOT EXISTS (
              SELECT 1 FROM tariff_ingest.ingest_runs r
              WHERE r.run_id = e->>'run_id'
                AND r.source_id = e->>'source_id'
                AND r.scope = e->'scope'
                AND r.parser_version = e->>'parser_version'
                AND r.status = e->>'status'
                AND r.raw_count = (e->>'raw_count')::integer
                AND r.unique_count = (e->>'unique_count')::integer
                AND r.normalized_count = (e->>'normalized_count')::integer
                AND r.rejected_count = (e->>'rejected_count')::integer
                AND r.resume_cursor = e->'resume_cursor'
          )
       ) THEN
        RAISE EXCEPTION 'legacy ingest_runs package mismatch';
    END IF;"""
        target_setup = """
    IF to_regclass('tariff_ingest.ett_normalization_results') IS NULL THEN
        RAISE EXCEPTION 'legacy normalization target table is missing';
    END IF;"""
    else:
        run_declaration = (
            "expected_run jsonb := "
            f"convert_from(decode('{run_hex}', 'hex'), 'UTF8')::jsonb;"
        )
        run_preflight = """
    IF (SELECT count(*) FROM tariff_ingest.ingest_runs r
        WHERE r.source_id = expected_source->>'source_id') <> 1 THEN
        RAISE EXCEPTION 'staged ETT source must have exactly one raw ingest run';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM tariff_ingest.ingest_runs r
        WHERE r.run_id = expected_run->>'run_id'
          AND r.source_id = expected_run->>'source_id'
          AND r.scope = expected_run->'scope'
          AND r.parser_version = expected_run->>'parser_version'
          AND r.status = expected_run->>'status'
          AND r.raw_count = (expected_run->>'raw_count')::integer
          AND r.unique_count = (expected_run->>'unique_count')::integer
          AND r.normalized_count = (expected_run->>'normalized_count')::integer
          AND r.rejected_count = (expected_run->>'rejected_count')::integer
          AND r.resume_cursor = expected_run->'resume_cursor'
    ) THEN RAISE EXCEPTION 'ingest_runs package mismatch'; END IF;"""
        target_setup = """
    IF to_regclass('tariff_ingest.ett_normalization_results') IS NULL THEN
        EXECUTE $ett_ddl$
            CREATE TABLE tariff_ingest.ett_normalization_results (
                source_id text NOT NULL,
                raw_row_sha256 text NOT NULL,
                ordinal integer NOT NULL,
                parser_version text NOT NULL,
                source_revision text NOT NULL,
                hs_code text NOT NULL,
                page_number integer NOT NULL,
                line_number integer NOT NULL,
                original_description text NOT NULL,
                original_supplementary_unit text NOT NULL,
                original_duty_text text NOT NULL,
                original_raw_line text NOT NULL,
                syntax_status text NOT NULL,
                normalized_rate_text text NULL,
                is_ambiguous boolean NOT NULL,
                ambiguity_reason text NULL,
                legal_status text NOT NULL,
                verified boolean NOT NULL,
                admitted boolean NOT NULL,
                result_sha256 text NOT NULL,
                PRIMARY KEY (source_id, raw_row_sha256, parser_version),
                CONSTRAINT uq_ett_normalization_source_ordinal_version
                    UNIQUE (source_id, ordinal, parser_version),
                CONSTRAINT uq_ett_normalization_result_sha256
                    UNIQUE (result_sha256),
                CONSTRAINT fk_ett_normalization_raw_row
                    FOREIGN KEY (source_id, raw_row_sha256)
                    REFERENCES tariff_ingest.ett_collected_rows
                        (source_id, row_sha256)
            )
        $ett_ddl$;
    END IF;"""
    return f"""-- Generated offline from a fully validated local package.
-- Execute only inside an explicit caller-owned transaction with scoped staging access.
-- This file has no connection settings and intentionally owns no transaction boundary.

DO $ett_offline_plan$
DECLARE
    expected_source jsonb := convert_from(decode('{source_hex}', 'hex'), 'UTF8')::jsonb;
    {run_declaration}
    expected_raw jsonb := convert_from(decode('{raw_hex}', 'hex'), 'UTF8')::jsonb;
    expected_results jsonb := convert_from(decode('{results_hex}', 'hex'), 'UTF8')::jsonb;
    expected_columns jsonb := convert_from(decode('{columns_hex}', 'hex'), 'UTF8')::jsonb;
    actual_columns jsonb;
    existing_count bigint;
    inserted_count bigint;
BEGIN
    IF current_database() <> 'tariff_staging' THEN
        RAISE EXCEPTION 'offline plan targets tariff_staging only';
    END IF;
    LOCK TABLE tariff_ingest.source_objects,
               tariff_ingest.ingest_runs,
               tariff_ingest.ett_collected_rows IN SHARE MODE;
    IF NOT EXISTS (
        SELECT 1 FROM tariff_ingest.source_objects s
        WHERE s.source_id = expected_source->>'source_id'
          AND s.authority = expected_source->>'authority'
          AND s.dataset = expected_source->>'dataset'
          AND s.source_url = expected_source->>'source_url'
          AND s.source_revision = expected_source->>'source_revision'
          AND s.object_bucket = expected_source->>'object_bucket'
          AND s.object_key = expected_source->>'object_key'
          AND s.sha256 = expected_source->>'sha256'
          AND s.size_bytes = (expected_source->>'size_bytes')::bigint
          AND s.media_type = expected_source->>'media_type'
          AND s.captured_at = (expected_source->>'captured_at')::timestamptz
          AND s.status = expected_source->>'status'
    ) THEN RAISE EXCEPTION 'source_objects package mismatch'; END IF;
{run_preflight}
    IF (SELECT count(*) FROM tariff_ingest.ett_collected_rows r
        WHERE r.source_id = expected_source->>'source_id')
       <> jsonb_array_length(expected_raw)
       OR EXISTS (
          SELECT 1 FROM jsonb_array_elements(expected_raw) e
          WHERE NOT EXISTS (
              SELECT 1 FROM tariff_ingest.ett_collected_rows r
              WHERE r.source_id = e->>'source_id'
                AND r.hs_code = e->>'hs_code'
                AND r.description = e->>'description'
                AND r.supplementary_unit = e->>'supplementary_unit'
                AND r.duty_text = e->>'duty_text'
                AND r.raw_line = e->>'raw_line'
                AND r.row_sha256 = e->>'row_sha256'
                AND r.status = e->>'status'
                AND r.ordinal = (e->>'ordinal')::integer
          )
       ) THEN RAISE EXCEPTION 'ett_collected_rows package mismatch'; END IF;

{target_setup}
    LOCK TABLE tariff_ingest.ett_normalization_results
        IN SHARE ROW EXCLUSIVE MODE;

    SELECT jsonb_agg(
        jsonb_build_array(a.attname, pg_catalog.format_type(a.atttypid, a.atttypmod), a.attnotnull)
        ORDER BY a.attnum
    ) INTO actual_columns
    FROM pg_catalog.pg_attribute a
    WHERE a.attrelid = 'tariff_ingest.ett_normalization_results'::regclass
      AND a.attnum > 0 AND NOT a.attisdropped;
    IF actual_columns IS DISTINCT FROM expected_columns THEN
        RAISE EXCEPTION 'conflicting ett_normalization_results column contract';
    END IF;

    IF (SELECT count(*) FROM pg_catalog.pg_constraint c
        WHERE c.conrelid = 'tariff_ingest.ett_normalization_results'::regclass
          AND c.contype = 'p') <> 1
       OR (SELECT count(*) FROM pg_catalog.pg_constraint c
           WHERE c.conrelid = 'tariff_ingest.ett_normalization_results'::regclass
             AND c.contype = 'u') <> 2
       OR (SELECT count(*) FROM pg_catalog.pg_constraint c
           WHERE c.conrelid = 'tariff_ingest.ett_normalization_results'::regclass
             AND c.contype = 'f') <> 1 THEN
        RAISE EXCEPTION 'conflicting normalization constraint count';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint c
        WHERE c.conrelid = 'tariff_ingest.ett_normalization_results'::regclass
          AND c.contype = 'p'
          AND NOT c.condeferrable AND NOT c.condeferred
          AND (SELECT array_agg(a.attname::text ORDER BY u.ord)
               FROM unnest(c.conkey) WITH ORDINALITY u(attnum, ord)
               JOIN pg_catalog.pg_attribute a
                 ON a.attrelid = c.conrelid AND a.attnum = u.attnum)
              = ARRAY['source_id', 'raw_row_sha256', 'parser_version']
    ) THEN RAISE EXCEPTION 'conflicting normalization primary key'; END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint c
        WHERE c.conrelid = 'tariff_ingest.ett_normalization_results'::regclass
          AND c.contype = 'u'
          AND c.conname = 'uq_ett_normalization_source_ordinal_version'
          AND NOT c.condeferrable AND NOT c.condeferred
          AND (SELECT array_agg(a.attname::text ORDER BY u.ord)
               FROM unnest(c.conkey) WITH ORDINALITY u(attnum, ord)
               JOIN pg_catalog.pg_attribute a
                 ON a.attrelid = c.conrelid AND a.attnum = u.attnum)
              = ARRAY['source_id', 'ordinal', 'parser_version']
    ) THEN RAISE EXCEPTION 'conflicting normalization source ordinal unique'; END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint c
        WHERE c.conrelid = 'tariff_ingest.ett_normalization_results'::regclass
          AND c.contype = 'u'
          AND c.conname = 'uq_ett_normalization_result_sha256'
          AND NOT c.condeferrable AND NOT c.condeferred
          AND (SELECT array_agg(a.attname::text ORDER BY u.ord)
               FROM unnest(c.conkey) WITH ORDINALITY u(attnum, ord)
               JOIN pg_catalog.pg_attribute a
                 ON a.attrelid = c.conrelid AND a.attnum = u.attnum)
              = ARRAY['result_sha256']
    ) THEN RAISE EXCEPTION 'conflicting normalization result digest unique'; END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint c
        WHERE c.conrelid = 'tariff_ingest.ett_normalization_results'::regclass
          AND c.contype = 'f' AND c.conname = 'fk_ett_normalization_raw_row'
          AND c.confrelid = 'tariff_ingest.ett_collected_rows'::regclass
          AND c.confdeltype = 'a' AND c.confupdtype = 'a'
          AND c.confmatchtype = 's' AND c.convalidated
          AND NOT c.condeferrable AND NOT c.condeferred
          AND (SELECT array_agg(a.attname::text ORDER BY u.ord)
               FROM unnest(c.conkey) WITH ORDINALITY u(attnum, ord)
               JOIN pg_catalog.pg_attribute a
                 ON a.attrelid = c.conrelid AND a.attnum = u.attnum)
              = ARRAY['source_id', 'raw_row_sha256']
          AND (SELECT array_agg(a.attname::text ORDER BY u.ord)
               FROM unnest(c.confkey) WITH ORDINALITY u(attnum, ord)
               JOIN pg_catalog.pg_attribute a
                 ON a.attrelid = c.confrelid AND a.attnum = u.attnum)
              = ARRAY['source_id', 'row_sha256']
    ) THEN RAISE EXCEPTION 'conflicting normalization raw row foreign key'; END IF;

    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_trigger t
        WHERE t.tgrelid = 'tariff_ingest.ett_normalization_results'::regclass
          AND NOT t.tgisinternal
    ) OR EXISTS (
        SELECT 1 FROM pg_catalog.pg_class c
        WHERE c.oid = 'tariff_ingest.ett_normalization_results'::regclass
          AND (c.relrowsecurity OR c.relforcerowsecurity)
    ) THEN
        RAISE EXCEPTION 'normalization target has unsupported triggers or RLS';
    END IF;

    SELECT count(*) INTO existing_count
    FROM tariff_ingest.ett_normalization_results r
    WHERE r.source_id = expected_source->>'source_id'
      AND r.parser_version = expected_results->0->>'parser_version';
    IF existing_count = jsonb_array_length(expected_results)
       AND NOT EXISTS (
          SELECT 1 FROM jsonb_array_elements(expected_results) e
          WHERE NOT EXISTS (
              SELECT 1 FROM tariff_ingest.ett_normalization_results r
              WHERE r.source_id = e->>'source_id'
                AND r.parser_version = e->>'parser_version'
                AND r.ordinal = (e->>'ordinal')::integer
                AND to_jsonb(r) = e
          )
       ) THEN
        RETURN;
    ELSIF existing_count <> 0 THEN
        RAISE EXCEPTION 'conflicting existing normalization version';
    END IF;

    INSERT INTO tariff_ingest.ett_normalization_results (
        source_id, raw_row_sha256, ordinal, parser_version, source_revision,
        hs_code, page_number, line_number, original_description,
        original_supplementary_unit, original_duty_text, original_raw_line,
        syntax_status, normalized_rate_text, is_ambiguous, ambiguity_reason,
        legal_status, verified, admitted, result_sha256
    )
    SELECT * FROM jsonb_to_recordset(expected_results) AS x(
        source_id text, raw_row_sha256 text, ordinal integer, parser_version text,
        source_revision text, hs_code text, page_number integer, line_number integer,
        original_description text, original_supplementary_unit text,
        original_duty_text text, original_raw_line text, syntax_status text,
        normalized_rate_text text, is_ambiguous boolean, ambiguity_reason text,
        legal_status text, verified boolean, admitted boolean, result_sha256 text
    );
    GET DIAGNOSTICS inserted_count = ROW_COUNT;
    IF inserted_count <> jsonb_array_length(expected_results)
       OR (SELECT count(*) FROM tariff_ingest.ett_normalization_results r
           WHERE r.source_id = expected_source->>'source_id'
             AND r.parser_version = expected_results->0->>'parser_version')
          <> jsonb_array_length(expected_results)
       OR EXISTS (
          SELECT 1 FROM jsonb_array_elements(expected_results) e
          WHERE NOT EXISTS (
              SELECT 1 FROM tariff_ingest.ett_normalization_results r
              WHERE r.source_id = e->>'source_id'
                AND r.parser_version = e->>'parser_version'
                AND r.ordinal = (e->>'ordinal')::integer
                AND r.legal_status = 'UNVERIFIED'
                AND NOT r.verified AND NOT r.admitted
                AND to_jsonb(r) = e
          )
       ) THEN
        RAISE EXCEPTION 'normalization post-insert verification failed';
    END IF;
END
$ett_offline_plan$;
"""


def _build_legacy_offline_artifacts(
    package_dir: Path, package: Mapping[str, Any]
) -> tuple[dict[str, Any], str]:
    top_keys = {
        "schema_version",
        "kind",
        "normalizer_version",
        "source_object",
        "recovery_envelope",
        "artifacts",
    }
    _exact_keys(package, top_keys, "legacy package.json")
    if (
        type(package.get("schema_version")) is not int
        or package["schema_version"] != PACKAGE_SCHEMA_VERSION
        or package.get("kind") != LEGACY_PACKAGE_KIND
    ):
        raise EttOfflinePlanError("legacy package contract mismatch")
    if package.get("normalizer_version") != ETT_NORMALIZER_VERSION:
        raise EttOfflinePlanError("normalizer_version mismatch")

    source = _validate_source_object(package.get("source_object"))
    descriptors = _mapping(package.get("artifacts"), "artifacts")
    _exact_keys(descriptors, LEGACY_ARTIFACT_NAMES, "legacy artifacts")
    artifacts = {
        name: _read_artifact(package_dir, descriptors[name], name)
        for name in sorted(LEGACY_ARTIFACT_NAMES)
    }
    original_bytes, original_descriptor = artifacts["original_bytes"]
    source_text_bytes, _ = artifacts["source_text_bytes"]
    if (
        source["sha256"] != _sha256_bytes(original_bytes)
        or source["size_bytes"] != len(original_bytes)
        or original_descriptor["sha256"] != source["sha256"]
    ):
        raise EttOfflinePlanError(
            "legacy original bytes do not match source_object identity"
        )

    recovery = _mapping(package.get("recovery_envelope"), "recovery_envelope")
    try:
        preview = build_legacy_normalization_preview(
            recovery,
            original_bytes=original_bytes,
            source_text_bytes=source_text_bytes,
        )
    except EttLegacyPreviewError as exc:
        raise EttOfflinePlanError(str(exc)) from exc
    observed = _mapping(recovery.get("observed"), "recovery observed")
    recovery_source = _mapping(observed.get("source"), "recovery source")
    for key in ("source_id", "sha256", "size_bytes"):
        if recovery_source.get(key) != source.get(key):
            raise EttOfflinePlanError(
                f"recovery source {key} does not match source_object"
            )
    if recovery_source.get("chapter") != "29":
        raise EttOfflinePlanError("recovery source chapter mismatch")

    ingest_runs_value = observed.get("legacy_runs")
    raw_rows_value = observed.get("raw_rows")
    if not isinstance(ingest_runs_value, list) or len(ingest_runs_value) != 3:
        raise EttOfflinePlanError("legacy package must contain exactly three runs")
    if not isinstance(raw_rows_value, list) or len(raw_rows_value) != EXPECTED_RAW_COUNT:
        raise EttOfflinePlanError("legacy package must contain exactly 533 RAW rows")
    ingest_runs = [dict(_mapping(run, "legacy ingest run")) for run in ingest_runs_value]
    raw_rows = [dict(_mapping(row, "legacy raw row")) for row in raw_rows_value]

    projected_rows: list[dict[str, Any]] = []
    crosswalk: list[dict[str, Any]] = []
    for preview_row in preview["rows"]:
        provenance = _mapping(preview_row["provenance"], "preview provenance")
        payload = {
            "source_id": source["source_id"],
            "raw_row_sha256": preview_row["legacy_raw_row_sha256"],
            "ordinal": preview_row["ordinal"],
            "parser_version": preview["normalizer_version"],
            "source_revision": source["source_revision"],
            "hs_code": preview_row["hs_code"],
            "page_number": provenance["page_number"],
            "line_number": provenance["line_number"],
            "original_description": preview_row["original_description"],
            "original_supplementary_unit": preview_row[
                "original_supplementary_unit"
            ],
            "original_duty_text": preview_row["original_duty_text"],
            "original_raw_line": preview_row["original_raw_line"],
            "syntax_status": preview_row["syntax_status"],
            "normalized_rate_text": preview_row["normalized_rate_text"],
            "is_ambiguous": preview_row["is_ambiguous"],
            "ambiguity_reason": preview_row["ambiguity_reason"],
            "legal_status": preview_row["legal_status"],
            "verified": preview_row["verified"],
            "admitted": preview_row["admitted"],
        }
        persisted_hash = sha256_json(payload)
        projected_rows.append({**payload, "result_sha256": persisted_hash})
        crosswalk.append(
            {
                "ordinal": preview_row["ordinal"],
                "persisted_result_sha256": persisted_hash,
                "preview_result_sha256": preview_row["result_sha256"],
                "legacy_run_id": preview_row["legacy_run_id"],
                "legacy_parser_version": preview_row["legacy_parser_version"],
                "provenance": dict(provenance),
            }
        )

    plan: dict[str, Any] = {
        "schema_version": 1,
        "kind": LEGACY_PLAN_KIND,
        "target": "tariff_staging.tariff_ingest.ett_normalization_results",
        "transaction_owner": "CALLER",
        "execution_performed": False,
        "source_object": dict(source),
        "ingest_runs": ingest_runs,
        "raw_rows": raw_rows,
        "retained_artifacts": {
            name: descriptor for name, (_, descriptor) in artifacts.items()
        },
        "recovery_envelope_sha256": recovery["envelope_sha256"],
        "preview_sha256": preview["preview_sha256"],
        "normalizer_version": preview["normalizer_version"],
        "expected_counts": {
            "raw": EXPECTED_RAW_COUNT,
            "parsed": preview["counts"]["parsed"],
            "ambiguous": preview["counts"]["ambiguous"],
            "legal": 0,
            "verified": 0,
            "admitted": 0,
        },
        "normalization_digest": sha256_json(projected_rows),
        "rows": projected_rows,
        "legacy_crosswalk": crosswalk,
        "invariants": [
            "exact retained bytes rebuild the reviewed recovery and preview",
            "exactly three reviewed legacy runs bind ordinals 1 through 533",
            "legacy RAW hashes and source/run identities are never rewritten",
            "persisted hashes cover the exact target-table row contract",
            "crosswalk binds persisted and preview hashes to legacy provenance",
            "target table must already exist; legacy SQL contains no DDL",
            "caller owns the transaction; generated SQL has no transaction boundary",
            "same-version exact replay mutates zero rows",
            "same-version conflict or incomplete replay fails closed",
            "all legal_status values are UNVERIFIED; verified and admitted are false",
        ],
    }
    sql = _render_sql(plan)
    plan["sql_sha256"] = _sha256_bytes(sql.encode("utf-8"))
    plan["plan_sha256"] = sha256_json(plan)
    return plan, sql


def _validate_text_provenance(
    value: Any,
    *,
    label: str,
    source_lines: list[str],
    allow_empty: bool = False,
) -> dict[str, Any]:
    provenance = _mapping(value, label)
    _exact_keys(provenance, TEXT_PROVENANCE_KEYS, label)
    text = provenance.get("text")
    lines = provenance.get("source_lines")
    fragments = provenance.get("fragments")
    if text == "" and lines == [] and fragments == []:
        if allow_empty:
            return {"text": "", "source_lines": [], "fragments": []}
        raise EttOfflinePlanError(f"{label} cannot be empty for a structural child")
    if not isinstance(text, str) or not text:
        raise EttOfflinePlanError(f"{label}.text must be a nonempty string")
    if (
        not isinstance(lines, list)
        or not isinstance(fragments, list)
        or not lines
        or len(lines) != len(fragments)
    ):
        raise EttOfflinePlanError(f"{label} line/fragment binding mismatch")
    if lines != sorted(set(lines)):
        raise EttOfflinePlanError(f"{label} source lines must be unique and ordered")
    for index, (line_number, fragment) in enumerate(
        zip(lines, fragments), start=1
    ):
        _strict_positive_int(line_number, f"{label}.source_lines[{index}]")
        if line_number > len(source_lines):
            raise EttOfflinePlanError(f"{label} source line is outside retained text")
        if not isinstance(fragment, str) or not fragment:
            raise EttOfflinePlanError(f"{label}.fragments[{index}] must be nonempty")
        if fragment not in source_lines[line_number - 1]:
            raise EttOfflinePlanError(f"{label} fragment is not present on source line")
    if text != " ".join(fragments):
        raise EttOfflinePlanError(f"{label}.text must equal its ordered fragments")
    return {
        "text": text,
        "source_lines": list(lines),
        "fragments": list(fragments),
    }


def _append_source_locations(source_text: str) -> tuple[list[str], list[dict[str, int]]]:
    logical_lines = source_text.splitlines()
    chunks = source_text.splitlines(keepends=True)
    if [chunk.splitlines()[0] for chunk in chunks] != logical_lines:
        raise EttOfflinePlanError("append source splitlines reconstruction mismatch")
    locations: list[dict[str, int]] = []
    page_number = 1
    page_line_number = 1
    source_position = 0
    for line, chunk in zip(logical_lines, chunks):
        if _SOURCE_CODE_RE.match(line) is not None:
            source_position += 1
        locations.append(
            {
                "page_number": page_number,
                "line_number": page_line_number,
                "source_position": source_position if _SOURCE_CODE_RE.match(line) else 0,
            }
        )
        form_feeds = chunk.count("\f")
        if form_feeds:
            page_number += form_feeds
            page_line_number = 1
        else:
            page_line_number += 1
    return logical_lines, locations


def _fixed_append_source_row(
    source_lines: list[str], contract: Mapping[str, Any]
) -> dict[str, Any]:
    source_line_number = contract["source_line_number"]
    referenced_lines = tuple(contract["description_lines"]) + tuple(
        contract["parent_lines"]
    )
    if not referenced_lines or max(referenced_lines) > len(source_lines):
        raise EttOfflinePlanError("fixed append span is outside exact source text")
    if tuple(contract["description_lines"])[0] != source_line_number:
        raise EttOfflinePlanError("fixed append description span is not row-anchored")
    raw_line = source_lines[source_line_number - 1]
    match = _APPEND_CODE_RE.match(raw_line)
    if match is None:
        raise EttOfflinePlanError("fixed append row does not retain its plus marker")
    columns = _COLUMN_SEPARATOR_RE.split(match.group("tail").strip(" \t"))
    if len(columns) != 3 or any(not column for column in columns):
        raise EttOfflinePlanError("fixed append row is not three-column product data")
    description, supplementary_unit, duty_text = columns
    hs_code = "".join(match.group(name) for name in ("g1", "g2", "g3", "g4"))
    row_hash = _sha256_bytes(raw_line.encode("utf-8"))
    if (
        hs_code != contract["hs_code"]
        or supplementary_unit != "–"
        or duty_text != contract["duty_text"]
        or row_hash != contract["row_sha256"]
    ):
        raise EttOfflinePlanError("fixed append row identity/columns/hash mismatch")
    description_lines = list(contract["description_lines"])
    description_fragments = [description]
    description_fragments.extend(
        source_lines[line_number - 1].strip()
        for line_number in description_lines[1:]
    )
    if any(not fragment for fragment in description_fragments):
        raise EttOfflinePlanError("fixed append description contains an empty fragment")
    parent_lines = list(contract["parent_lines"])
    parent_fragments = [
        source_lines[line_number - 1].strip() for line_number in parent_lines
    ]
    if any(not fragment for fragment in parent_fragments):
        raise EttOfflinePlanError("fixed append parent contains an empty physical row")
    return {
        "raw_line": raw_line,
        "row_sha256": row_hash,
        "hs_code": hs_code,
        "description": description,
        "supplementary_unit": supplementary_unit,
        "duty_text": duty_text,
        "description_provenance": {
            "text": " ".join(description_fragments),
            "source_lines": description_lines,
            "fragments": description_fragments,
        },
        "parent_heading_provenance": {
            "text": " ".join(parent_fragments),
            "source_lines": parent_lines,
            "fragments": parent_fragments,
        },
    }


def _validate_legacy_append_digests(
    pdf_sha256: Any, declared_text_sha256: Any, observed_text_sha256: str
) -> None:
    if pdf_sha256 != LEGACY_APPEND_SOURCE_SHA256:
        raise EttOfflinePlanError("legacy append rejects non-authoritative PDF SHA-256")
    if (
        declared_text_sha256 != LEGACY_APPEND_SOURCE_TEXT_SHA256
        or observed_text_sha256 != LEGACY_APPEND_SOURCE_TEXT_SHA256
    ):
        raise EttOfflinePlanError("legacy append rejects non-authoritative layout SHA-256")


def _validate_fixed_append_provenance(
    item: Mapping[str, Any],
    recovered: Mapping[str, Any],
    *,
    label: str,
    source_lines: list[str],
    parent_is_empty: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    description = _validate_text_provenance(
        item.get("description_provenance"),
        label=f"{label}.description_provenance",
        source_lines=source_lines,
    )
    if description != recovered["description_provenance"]:
        raise EttOfflinePlanError(
            "append description provenance does not match fixed source span"
        )
    parent = _validate_text_provenance(
        item.get("parent_heading_provenance"),
        label=f"{label}.parent_heading_provenance",
        source_lines=source_lines,
        allow_empty=parent_is_empty,
    )
    if parent != recovered["parent_heading_provenance"]:
        raise EttOfflinePlanError(
            "append parent provenance does not match fixed source span"
        )
    return description, parent


def _render_legacy_append_sql(plan: Mapping[str, Any]) -> str:
    source_hex = _json_hex(plan["source_object"])
    base_runs_hex = _json_hex(plan["base_ingest_runs"])
    base_raw_hex = _json_hex(plan["base_raw_rows"])
    base_results_hex = _json_hex(plan["base_results"])
    append_run_hex = _json_hex(plan["append_ingest_run"])
    append_raw_hex = _json_hex(plan["append_raw_rows"])
    append_results_hex = _json_hex(plan["append_results"])
    normalization_columns = [
            ["source_id", "text", True],
            ["raw_row_sha256", "text", True],
            ["ordinal", "integer", True],
            ["parser_version", "text", True],
            ["source_revision", "text", True],
            ["hs_code", "text", True],
            ["page_number", "integer", True],
            ["line_number", "integer", True],
            ["original_description", "text", True],
            ["original_supplementary_unit", "text", True],
            ["original_duty_text", "text", True],
            ["original_raw_line", "text", True],
            ["syntax_status", "text", True],
            ["normalized_rate_text", "text", False],
            ["is_ambiguous", "boolean", True],
            ["ambiguity_reason", "text", False],
            ["legal_status", "text", True],
            ["verified", "boolean", True],
            ["admitted", "boolean", True],
            ["result_sha256", "text", True],
        ]
    def constraint(
        kind: str,
        columns: list[str],
        *,
        referenced_table: str | None = None,
        referenced_columns: list[str] | None = None,
    ) -> dict[str, Any]:
        foreign = kind == "f"
        return {
            "type": kind,
            "columns": columns,
            "referenced_table": referenced_table,
            "referenced_columns": referenced_columns,
            "deferrable": False,
            "initially_deferred": False,
            "validated": True,
            "on_update": "a" if foreign else None,
            "on_delete": "a" if foreign else None,
            "match_type": "s" if foreign else None,
        }

    table_contracts = [
        {
            "table": "tariff_ingest.ingest_runs",
            "columns": [
                ["run_id", "text", True],
                ["source_id", "text", True],
                ["scope", "jsonb", True],
                ["parser_version", "text", True],
                ["status", "text", True],
                ["raw_count", "integer", True],
                ["unique_count", "integer", True],
                ["normalized_count", "integer", True],
                ["rejected_count", "integer", True],
                ["resume_cursor", "jsonb", True],
                ["started_at", "timestamp with time zone", True],
                ["completed_at", "timestamp with time zone", True],
                ["updated_at", "timestamp with time zone", True],
            ],
            "constraints": [constraint("p", ["run_id"])],
        },
        {
            "table": "tariff_ingest.ett_collected_rows",
            "columns": [
                ["source_id", "text", True],
                ["hs_code", "text", True],
                ["description", "text", True],
                ["supplementary_unit", "text", True],
                ["duty_text", "text", True],
                ["raw_line", "text", True],
                ["row_sha256", "text", True],
                ["status", "text", True],
                ["ordinal", "integer", True],
            ],
            "constraints": [
                constraint(
                    "f",
                    ["source_id"],
                    referenced_table="tariff_ingest.source_objects",
                    referenced_columns=["source_id"],
                ),
                constraint("p", ["source_id", "row_sha256"]),
                constraint("u", ["source_id", "hs_code"]),
            ],
        },
        {
            "table": "tariff_ingest.ett_normalization_results",
            "columns": normalization_columns,
            "constraints": [
                constraint(
                    "f",
                    ["source_id", "raw_row_sha256"],
                    referenced_table="tariff_ingest.ett_collected_rows",
                    referenced_columns=["source_id", "row_sha256"],
                ),
                constraint("p", ["source_id", "raw_row_sha256", "parser_version"]),
                constraint("u", ["result_sha256"]),
                constraint("u", ["source_id", "ordinal", "parser_version"]),
            ],
        },
    ]
    table_contracts_hex = _json_hex(table_contracts)
    return f"""-- Generated offline from an exact legacy append package.
-- Execute only inside an explicit caller-owned transaction against tariff_staging.
-- This file owns no connection or transaction boundary and contains INSERT only.

DO $ett_append_plan$
DECLARE
    expected_source jsonb := convert_from(decode('{source_hex}', 'hex'), 'UTF8')::jsonb;
    expected_base_runs jsonb := convert_from(decode('{base_runs_hex}', 'hex'), 'UTF8')::jsonb;
    expected_base_raw jsonb := convert_from(decode('{base_raw_hex}', 'hex'), 'UTF8')::jsonb;
    expected_base_results jsonb := convert_from(decode('{base_results_hex}', 'hex'), 'UTF8')::jsonb;
    expected_append_run jsonb := convert_from(decode('{append_run_hex}', 'hex'), 'UTF8')::jsonb;
    expected_append_raw jsonb := convert_from(decode('{append_raw_hex}', 'hex'), 'UTF8')::jsonb;
    expected_append_results jsonb := convert_from(decode('{append_results_hex}', 'hex'), 'UTF8')::jsonb;
    expected_table_contracts jsonb := convert_from(decode('{table_contracts_hex}', 'hex'), 'UTF8')::jsonb;
    expected_table jsonb;
    table_oid regclass;
    actual_columns jsonb;
    actual_constraints jsonb;
    source_run_count bigint;
    source_raw_count bigint;
    source_result_count bigint;
    inserted_count bigint;
BEGIN
    IF current_database() <> 'tariff_staging' THEN
        RAISE EXCEPTION 'offline plan targets tariff_staging only';
    END IF;
    IF to_regclass('tariff_ingest.ett_normalization_results') IS NULL THEN
        RAISE EXCEPTION 'append normalization target table is missing';
    END IF;
    LOCK TABLE tariff_ingest.source_objects,
               tariff_ingest.ingest_runs,
               tariff_ingest.ett_collected_rows,
               tariff_ingest.ett_normalization_results
        IN SHARE ROW EXCLUSIVE MODE;
    IF NOT EXISTS (
        SELECT 1 FROM tariff_ingest.source_objects s
        WHERE s.source_id = expected_source->>'source_id'
          AND s.authority = expected_source->>'authority'
          AND s.dataset = expected_source->>'dataset'
          AND s.source_url = expected_source->>'source_url'
          AND s.source_revision = expected_source->>'source_revision'
          AND s.object_bucket = expected_source->>'object_bucket'
          AND s.object_key = expected_source->>'object_key'
          AND s.sha256 = expected_source->>'sha256'
          AND s.size_bytes = (expected_source->>'size_bytes')::bigint
          AND s.media_type = expected_source->>'media_type'
          AND s.captured_at = (expected_source->>'captured_at')::timestamptz
          AND s.status = expected_source->>'status'
    ) THEN RAISE EXCEPTION 'source_objects package mismatch'; END IF;

    FOR expected_table IN
        SELECT value FROM jsonb_array_elements(expected_table_contracts)
    LOOP
        table_oid := to_regclass(expected_table->>'table');
        IF table_oid IS NULL THEN
            RAISE EXCEPTION 'append write table is missing: %', expected_table->>'table';
        END IF;
        SELECT jsonb_agg(
            jsonb_build_array(
                a.attname,
                pg_catalog.format_type(a.atttypid, a.atttypmod),
                a.attnotnull
            ) ORDER BY a.attnum
        ) INTO actual_columns
        FROM pg_catalog.pg_attribute a
        WHERE a.attrelid = table_oid AND a.attnum > 0 AND NOT a.attisdropped;
        IF actual_columns IS DISTINCT FROM expected_table->'columns' THEN
            RAISE EXCEPTION 'append write table column contract mismatch: %',
                expected_table->>'table';
        END IF;

        SELECT COALESCE(jsonb_agg(q.contract ORDER BY q.constraint_type, q.column_key), '[]'::jsonb)
          INTO actual_constraints
        FROM (
            SELECT c.contype::text AS constraint_type,
                   (SELECT string_agg(a.attname::text, ',' ORDER BY u.ord)
                    FROM unnest(c.conkey) WITH ORDINALITY u(attnum, ord)
                    JOIN pg_catalog.pg_attribute a
                      ON a.attrelid = c.conrelid AND a.attnum = u.attnum) AS column_key,
                   jsonb_build_object(
                       'type', c.contype::text,
                       'columns', (SELECT jsonb_agg(a.attname::text ORDER BY u.ord)
                                   FROM unnest(c.conkey) WITH ORDINALITY u(attnum, ord)
                                   JOIN pg_catalog.pg_attribute a
                                     ON a.attrelid = c.conrelid AND a.attnum = u.attnum),
                       'referenced_table', CASE WHEN c.contype = 'f'
                           THEN c.confrelid::regclass::text ELSE NULL END,
                       'referenced_columns', CASE WHEN c.contype = 'f' THEN
                           (SELECT jsonb_agg(a.attname::text ORDER BY u.ord)
                            FROM unnest(c.confkey) WITH ORDINALITY u(attnum, ord)
                            JOIN pg_catalog.pg_attribute a
                              ON a.attrelid = c.confrelid AND a.attnum = u.attnum)
                           ELSE NULL END,
                       'deferrable', c.condeferrable,
                       'initially_deferred', c.condeferred,
                       'validated', c.convalidated,
                       'on_update', CASE WHEN c.contype = 'f' THEN c.confupdtype::text ELSE NULL END,
                       'on_delete', CASE WHEN c.contype = 'f' THEN c.confdeltype::text ELSE NULL END,
                       'match_type', CASE WHEN c.contype = 'f' THEN c.confmatchtype::text ELSE NULL END
                   ) AS contract
            FROM pg_catalog.pg_constraint c
            WHERE c.conrelid = table_oid AND c.contype IN ('p', 'u', 'f')
        ) q;
        IF actual_constraints IS DISTINCT FROM expected_table->'constraints' THEN
            RAISE EXCEPTION 'append write table constraint contract mismatch: %',
                expected_table->>'table';
        END IF;
    END LOOP;

    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_trigger t
        WHERE t.tgrelid IN (
            'tariff_ingest.ingest_runs'::regclass,
            'tariff_ingest.ett_collected_rows'::regclass,
            'tariff_ingest.ett_normalization_results'::regclass
        ) AND NOT t.tgisinternal
    ) OR EXISTS (
        SELECT 1 FROM pg_catalog.pg_class c
        WHERE c.oid IN (
            'tariff_ingest.ingest_runs'::regclass,
            'tariff_ingest.ett_collected_rows'::regclass,
            'tariff_ingest.ett_normalization_results'::regclass
        ) AND (c.relrowsecurity OR c.relforcerowsecurity)
    ) THEN RAISE EXCEPTION 'append targets have unsupported triggers or RLS'; END IF;

    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(expected_base_runs) e
        WHERE NOT EXISTS (
            SELECT 1 FROM tariff_ingest.ingest_runs r
            WHERE r.run_id = e->>'run_id' AND r.source_id = e->>'source_id'
              AND r.scope = e->'scope' AND r.parser_version = e->>'parser_version'
              AND r.status = e->>'status'
              AND r.raw_count = (e->>'raw_count')::integer
              AND r.unique_count = (e->>'unique_count')::integer
              AND r.normalized_count = (e->>'normalized_count')::integer
              AND r.rejected_count = (e->>'rejected_count')::integer
              AND r.resume_cursor = e->'resume_cursor'
        )
    ) THEN RAISE EXCEPTION 'append base ingest_runs mismatch'; END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(expected_base_raw) e
        WHERE NOT EXISTS (
            SELECT 1 FROM tariff_ingest.ett_collected_rows r
            WHERE r.source_id = e->>'source_id' AND r.hs_code = e->>'hs_code'
              AND r.description = e->>'description'
              AND r.supplementary_unit = e->>'supplementary_unit'
              AND r.duty_text = e->>'duty_text' AND r.raw_line = e->>'raw_line'
              AND r.row_sha256 = e->>'row_sha256' AND r.status = e->>'status'
              AND r.ordinal = (e->>'ordinal')::integer
        )
    ) THEN RAISE EXCEPTION 'append base RAW mismatch'; END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(expected_base_results) e
        WHERE NOT EXISTS (
            SELECT 1 FROM tariff_ingest.ett_normalization_results r
            WHERE r.source_id = e->>'source_id'
              AND r.raw_row_sha256 = e->>'raw_row_sha256'
              AND r.parser_version = e->>'parser_version' AND to_jsonb(r) = e
        )
    ) THEN RAISE EXCEPTION 'append base normalization mismatch'; END IF;

    SELECT count(*) INTO source_run_count FROM tariff_ingest.ingest_runs
      WHERE source_id = expected_source->>'source_id';
    SELECT count(*) INTO source_raw_count FROM tariff_ingest.ett_collected_rows
      WHERE source_id = expected_source->>'source_id';
    SELECT count(*) INTO source_result_count
      FROM tariff_ingest.ett_normalization_results
      WHERE source_id = expected_source->>'source_id'
        AND parser_version = expected_append_results->0->>'parser_version';

    IF source_run_count = 4 AND source_raw_count = 538 AND source_result_count = 538
       AND EXISTS (
          SELECT 1 FROM tariff_ingest.ingest_runs r
          WHERE r.run_id = expected_append_run->>'run_id'
            AND r.source_id = expected_append_run->>'source_id'
            AND r.scope = expected_append_run->'scope'
            AND r.parser_version = expected_append_run->>'parser_version'
            AND r.status = expected_append_run->>'status'
            AND r.raw_count = 5 AND r.unique_count = 5
            AND r.normalized_count = 0 AND r.rejected_count = 0
            AND r.resume_cursor = expected_append_run->'resume_cursor'
       )
       AND NOT EXISTS (
          SELECT 1 FROM jsonb_array_elements(expected_append_raw) e
          WHERE NOT EXISTS (
              SELECT 1 FROM tariff_ingest.ett_collected_rows r
              WHERE r.source_id = e->>'source_id' AND r.row_sha256 = e->>'row_sha256'
                AND r.hs_code = e->>'hs_code' AND r.description = e->>'description'
                AND r.supplementary_unit = e->>'supplementary_unit'
                AND r.duty_text = e->>'duty_text' AND r.raw_line = e->>'raw_line'
                AND r.status = e->>'status' AND r.ordinal = (e->>'ordinal')::integer
          )
       )
       AND NOT EXISTS (
          SELECT 1 FROM jsonb_array_elements(expected_append_results) e
          WHERE NOT EXISTS (
              SELECT 1 FROM tariff_ingest.ett_normalization_results r
              WHERE r.source_id = e->>'source_id'
                AND r.raw_row_sha256 = e->>'raw_row_sha256'
                AND r.parser_version = e->>'parser_version' AND to_jsonb(r) = e
          )
       ) THEN RETURN;
    END IF;
    IF source_run_count <> 3 OR source_raw_count <> 533 OR source_result_count <> 533 THEN
        RAISE EXCEPTION 'append current state is partial or conflicting';
    END IF;

    IF EXISTS (
        SELECT 1 FROM tariff_ingest.ingest_runs r
        WHERE r.run_id = expected_append_run->>'run_id'
    ) OR EXISTS (
        SELECT 1 FROM jsonb_array_elements(expected_append_raw) e
        JOIN tariff_ingest.ett_collected_rows r
          ON r.source_id = expected_source->>'source_id'
         AND (r.row_sha256 = e->>'row_sha256' OR r.hs_code = e->>'hs_code'
              OR r.ordinal = (e->>'ordinal')::integer)
    ) OR EXISTS (
        SELECT 1 FROM jsonb_array_elements(expected_append_results) e
        JOIN tariff_ingest.ett_normalization_results r
          ON r.source_id = expected_source->>'source_id'
         AND r.parser_version = e->>'parser_version'
         AND (r.raw_row_sha256 = e->>'raw_row_sha256'
              OR r.ordinal = (e->>'ordinal')::integer
              OR r.result_sha256 = e->>'result_sha256')
    ) THEN RAISE EXCEPTION 'append identity already exists in conflicting state'; END IF;

    INSERT INTO tariff_ingest.ingest_runs (
        run_id, source_id, scope, parser_version, status, raw_count, unique_count,
        normalized_count, rejected_count, resume_cursor
    ) SELECT x.run_id, x.source_id, x.scope, x.parser_version, x.status,
             x.raw_count, x.unique_count, x.normalized_count, x.rejected_count,
             x.resume_cursor
      FROM jsonb_to_record(expected_append_run) AS x(
        run_id text, source_id text, scope jsonb, parser_version text, status text,
        raw_count integer, unique_count integer, normalized_count integer,
        rejected_count integer, resume_cursor jsonb
      );
    GET DIAGNOSTICS inserted_count = ROW_COUNT;
    IF inserted_count <> 1 THEN RAISE EXCEPTION 'append run insert count mismatch'; END IF;

    INSERT INTO tariff_ingest.ett_collected_rows (
        source_id, hs_code, description, supplementary_unit, duty_text,
        raw_line, row_sha256, status, ordinal
    )
    SELECT * FROM jsonb_to_recordset(expected_append_raw) AS x(
      source_id text, hs_code text, description text, supplementary_unit text,
      duty_text text, raw_line text, row_sha256 text, status text, ordinal integer
    );
    GET DIAGNOSTICS inserted_count = ROW_COUNT;
    IF inserted_count <> 5 THEN RAISE EXCEPTION 'append RAW insert count mismatch'; END IF;

    INSERT INTO tariff_ingest.ett_normalization_results (
        source_id, raw_row_sha256, ordinal, parser_version, source_revision,
        hs_code, page_number, line_number, original_description,
        original_supplementary_unit, original_duty_text, original_raw_line,
        syntax_status, normalized_rate_text, is_ambiguous, ambiguity_reason,
        legal_status, verified, admitted, result_sha256
    ) SELECT * FROM jsonb_to_recordset(expected_append_results) AS x(
        source_id text, raw_row_sha256 text, ordinal integer, parser_version text,
        source_revision text, hs_code text, page_number integer, line_number integer,
        original_description text, original_supplementary_unit text,
        original_duty_text text, original_raw_line text, syntax_status text,
        normalized_rate_text text, is_ambiguous boolean, ambiguity_reason text,
        legal_status text, verified boolean, admitted boolean, result_sha256 text
    );
    GET DIAGNOSTICS inserted_count = ROW_COUNT;
    IF inserted_count <> 5 THEN RAISE EXCEPTION 'append normalization insert count mismatch'; END IF;

    IF (SELECT count(*) FROM tariff_ingest.ingest_runs
        WHERE source_id = expected_source->>'source_id') <> 4
       OR (SELECT count(*) FROM tariff_ingest.ett_collected_rows
           WHERE source_id = expected_source->>'source_id') <> 538
       OR (SELECT count(*) FROM tariff_ingest.ett_normalization_results
           WHERE source_id = expected_source->>'source_id'
             AND parser_version = expected_append_results->0->>'parser_version') <> 538
       OR EXISTS (
          SELECT 1 FROM jsonb_array_elements(expected_append_results) e
          WHERE NOT EXISTS (
              SELECT 1 FROM tariff_ingest.ett_normalization_results r
              WHERE r.source_id = e->>'source_id'
                AND r.raw_row_sha256 = e->>'raw_row_sha256'
                AND r.parser_version = e->>'parser_version'
                AND r.legal_status = 'UNVERIFIED' AND NOT r.verified AND NOT r.admitted
                AND to_jsonb(r) = e
          )
       ) THEN RAISE EXCEPTION 'append post-insert verification failed'; END IF;
END
$ett_append_plan$;
"""


def _build_legacy_append_offline_artifacts(
    package_dir: Path, package: Mapping[str, Any]
) -> tuple[dict[str, Any], str]:
    top_keys = {
        "schema_version",
        "kind",
        "normalizer_version",
        "source_object",
        "recovery_envelope",
        "append_rows",
        "artifacts",
    }
    _exact_keys(package, top_keys, "legacy append package.json")
    if (
        type(package.get("schema_version")) is not int
        or package["schema_version"] != PACKAGE_SCHEMA_VERSION
        or package.get("kind") != LEGACY_APPEND_PACKAGE_KIND
        or package.get("normalizer_version") != ETT_NORMALIZER_VERSION
    ):
        raise EttOfflinePlanError("legacy append package contract mismatch")

    legacy_package = dict(package)
    legacy_package.pop("append_rows")
    legacy_package["kind"] = LEGACY_PACKAGE_KIND
    base_plan, _ = _build_legacy_offline_artifacts(package_dir, legacy_package)
    source = base_plan["source_object"]
    source_text_descriptor = _mapping(package["artifacts"], "artifacts")[
        "source_text_bytes"
    ]
    source_text_bytes, _ = _read_artifact(
        package_dir, source_text_descriptor, "source_text_bytes"
    )
    _validate_legacy_append_digests(
        source["sha256"],
        source_text_descriptor.get("sha256"),
        _sha256_bytes(source_text_bytes),
    )
    try:
        source_text = source_text_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise EttOfflinePlanError("append source text is not strict UTF-8") from exc
    if "\ufffd" in source_text:
        raise EttOfflinePlanError("append source text contains replacement characters")
    logical_lines, locations = _append_source_locations(source_text)
    authoritative_plus_lines = [
        index
        for index, line in enumerate(logical_lines, start=1)
        if _APPEND_CODE_RE.match(line) is not None
    ]
    fixed_plus_lines = [row["source_line_number"] for row in LEGACY_APPEND_FIXED_ROWS]
    if authoritative_plus_lines != fixed_plus_lines:
        raise EttOfflinePlanError(
            "retained source plus rows do not match the fixed append contract"
        )

    append_values = package.get("append_rows")
    if not isinstance(append_values, list) or len(append_values) != 5:
        raise EttOfflinePlanError("legacy append package must contain exactly five rows")
    append_raw: list[dict[str, Any]] = []
    crosswalk: list[dict[str, Any]] = []
    base_hs = {row["hs_code"] for row in base_plan["raw_rows"]}
    base_hashes = {row["row_sha256"] for row in base_plan["raw_rows"]}
    expected_storage = [row["storage_ordinal"] for row in LEGACY_APPEND_FIXED_ROWS]
    for index, (value, fixed) in enumerate(
        zip(append_values, LEGACY_APPEND_FIXED_ROWS), start=1
    ):
        label = f"append row {index}"
        item = _mapping(value, label)
        _exact_keys(item, APPEND_ROW_KEYS, label)
        storage_ordinal = _strict_positive_int(
            item.get("storage_ordinal"), f"{label}.storage_ordinal"
        )
        if storage_ordinal != fixed["storage_ordinal"]:
            raise EttOfflinePlanError("append storage ordinal violates fixed contract")
        source_position = _strict_positive_int(
            item.get("source_position"), f"{label}.source_position"
        )
        source_line_number = _strict_positive_int(
            item.get("source_line_number"), f"{label}.source_line_number"
        )
        page_number = _strict_positive_int(
            item.get("page_number"), f"{label}.page_number"
        )
        line_number = _strict_positive_int(
            item.get("line_number"), f"{label}.line_number"
        )
        if (
            source_position != fixed["source_position"]
            or source_line_number != fixed["source_line_number"]
            or page_number != fixed["page_number"]
            or line_number != fixed["line_number"]
        ):
            raise EttOfflinePlanError("append coordinates violate fixed contract")
        location = locations[source_line_number - 1]
        if location != {
            "source_position": source_position,
            "page_number": page_number,
            "line_number": line_number,
        }:
            raise EttOfflinePlanError("append source position/page/line mismatch")
        recovered = _fixed_append_source_row(logical_lines, fixed)
        raw_line = recovered["raw_line"]
        row_hash = recovered["row_sha256"]
        hs_code = recovered["hs_code"]
        description = recovered["description"]
        supplementary_unit = recovered["supplementary_unit"]
        duty_text = recovered["duty_text"]
        for field in (
            "raw_line", "row_sha256", "hs_code", "description",
            "supplementary_unit", "duty_text",
        ):
            if item.get(field) != recovered[field]:
                raise EttOfflinePlanError(
                    f"append {field} does not match fixed-source reconstruction"
                )
        if item.get("status") != COLLECTED_UNVERIFIED:
            raise EttOfflinePlanError("append row status mismatch")
        if hs_code in base_hs or row_hash in base_hashes:
            raise EttOfflinePlanError("append row duplicates base or append identity")
        description_provenance, parent_heading = _validate_fixed_append_provenance(
            item,
            recovered,
            label=label,
            source_lines=logical_lines,
            parent_is_empty=not fixed["parent_lines"],
        )
        append_raw.append(
            {
                "source_id": source["source_id"],
                "hs_code": hs_code,
                "description": description,
                "supplementary_unit": supplementary_unit,
                "duty_text": duty_text,
                "raw_line": raw_line,
                "row_sha256": row_hash,
                "status": COLLECTED_UNVERIFIED,
                "ordinal": storage_ordinal,
            }
        )
        crosswalk.append(
            {
                "storage_ordinal": storage_ordinal,
                "source_position": source_position,
                "source_line_number": source_line_number,
                "page_number": page_number,
                "line_number": line_number,
                "hs_code": hs_code,
                "row_sha256": row_hash,
                "description_provenance": description_provenance,
                "parent_heading_provenance": parent_heading,
            }
        )
    if [row["source_line_number"] for row in crosswalk] != fixed_plus_lines:
        raise EttOfflinePlanError(
            "append rows do not cover the complete authoritative plus sequence"
        )

    append_results: list[dict[str, Any]] = []
    for raw, link in zip(append_raw, crosswalk):
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
        result_hash = sha256_json(payload)
        append_results.append({**payload, "result_sha256": result_hash})
        link["result_sha256"] = result_hash
    parsed = sum(row["syntax_status"] == SYNTAX_PARSED for row in append_results)
    ambiguous = sum(row["is_ambiguous"] for row in append_results)
    if (parsed, ambiguous) != (3, 2):
        raise EttOfflinePlanError("append reviewed parser counts must be 3 parsed / 2 ambiguous")

    crosswalk_hash = sha256_json(crosswalk)
    run_identity = {
        "source_id": source["source_id"],
        "source_sha256": source["sha256"],
        "parser_version": LEGACY_APPEND_PARSER_VERSION,
        "storage_range": [expected_storage[0], expected_storage[-1]],
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
        "resume_cursor": {
            "next_ordinal": EXPECTED_RAW_COUNT + 6,
            "raw_count": 5,
            "complete": True,
        },
    }
    plan: dict[str, Any] = {
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
            "before_results": 619,
            "after_results": 624,
            "base_raw": 533,
            "append_raw": 5,
            "parsed": parsed,
            "ambiguous": ambiguous,
            "legal": 0,
            "verified": 0,
            "admitted": 0,
        },
        "invariants": [
            "existing source, three runs, 533 RAW rows, and 533 results remain exact",
            "storage ordinals 534 through 538 never stand for PDF source positions",
            "fourth-run crosswalk binds storage/source/global/page/line provenance",
            "multiline descriptions and parent headings equal the fixed reviewed source spans",
            "only HS 2911000000 uses the reviewed explicit empty parent provenance",
            "only one run, five RAW rows, and five normalization rows may be inserted",
            "replay performs zero DML and partial or conflicting state fails closed",
            "all legal_status values are UNVERIFIED; verified and admitted are false",
        ],
    }
    plan["append_digest"] = sha256_json(
        {"run": append_run, "raw": append_raw, "results": append_results}
    )
    sql = _render_legacy_append_sql(plan)
    plan["sql_sha256"] = _sha256_bytes(sql.encode("utf-8"))
    plan["plan_sha256"] = sha256_json(plan)
    return plan, sql


def build_offline_artifacts(package_dir: Path) -> tuple[dict[str, Any], str]:
    """Fully validate an explicit local package before returning plan and SQL."""

    package_dir = Path(package_dir)
    if package_dir.is_symlink() or not package_dir.is_dir():
        raise EttOfflinePlanError("package must be a real local directory")
    package_path = package_dir / "package.json"
    if package_path.is_symlink() or not package_path.is_file():
        raise EttOfflinePlanError("package.json is required")
    package = _mapping(
        _read_json_bytes(package_path.read_bytes(), "package.json"),
        "package.json",
    )
    if package.get("kind") == LEGACY_APPEND_PACKAGE_KIND:
        return _build_legacy_append_offline_artifacts(package_dir, package)
    if package.get("kind") == LEGACY_PACKAGE_KIND:
        return _build_legacy_offline_artifacts(package_dir, package)
    top_keys = {
        "schema_version",
        "normalizer_version",
        "source_object",
        "ingest_run",
        "raw_rows",
        "artifacts",
    }
    _exact_keys(package, top_keys, "package.json")
    if (
        type(package.get("schema_version")) is not int
        or package["schema_version"] != PACKAGE_SCHEMA_VERSION
    ):
        raise EttOfflinePlanError("package schema_version mismatch")
    if package.get("normalizer_version") != ETT_NORMALIZER_VERSION:
        raise EttOfflinePlanError("normalizer_version mismatch")

    source = _validate_source_object(package.get("source_object"))
    ingest_run = _mapping(package.get("ingest_run"), "ingest_run")
    _exact_keys(ingest_run, RUN_KEYS, "ingest_run")
    for field in ("raw_count", "unique_count"):
        _strict_positive_int(ingest_run.get(field), f"ingest_run.{field}")
    for field in ("normalized_count", "rejected_count"):
        value = ingest_run.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise EttOfflinePlanError(
                f"ingest_run.{field} must be a nonnegative integer"
            )
    if not isinstance(ingest_run.get("resume_cursor"), Mapping):
        raise EttOfflinePlanError("ingest_run.resume_cursor must be an object")
    resume_cursor = ingest_run["resume_cursor"]
    _exact_keys(
        resume_cursor,
        {"next_ordinal", "raw_count", "complete"},
        "ingest_run.resume_cursor",
    )
    _strict_positive_int(
        resume_cursor.get("next_ordinal"), "ingest_run.resume_cursor.next_ordinal"
    )
    _strict_positive_int(
        resume_cursor.get("raw_count"), "ingest_run.resume_cursor.raw_count"
    )
    if type(resume_cursor.get("complete")) is not bool:
        raise EttOfflinePlanError(
            "ingest_run.resume_cursor.complete must be a boolean"
        )
    expected_cursor = {
        "next_ordinal": ingest_run["raw_count"] + 1,
        "raw_count": ingest_run["raw_count"],
        "complete": True,
    }
    if resume_cursor != expected_cursor:
        raise EttOfflinePlanError("ingest_run.resume_cursor mismatch")
    if ingest_run.get("normalized_count") != 0 or ingest_run.get("rejected_count") != 0:
        raise EttOfflinePlanError("ingest run must precede normalization")
    scope = _mapping(ingest_run.get("scope"), "ingest_run.scope")
    stage_counts = _mapping(
        scope.get("stage_counts"), "ingest_run.scope.stage_counts"
    )
    _exact_keys(
        stage_counts,
        {"normalized", "verified", "admitted"},
        "ingest_run.scope.stage_counts",
    )
    for key in ("normalized", "verified", "admitted"):
        _strict_nonnegative_int(
            stage_counts.get(key), f"ingest_run.scope.stage_counts.{key}"
        )
    if stage_counts != {"normalized": 0, "verified": 0, "admitted": 0}:
        raise EttOfflinePlanError("ingest_run.scope.stage_counts are not zero")
    raw_rows_value = package.get("raw_rows")
    if not isinstance(raw_rows_value, list):
        raise EttOfflinePlanError("raw_rows must be an array")
    raw_rows: list[Mapping[str, Any]] = []
    for index, raw in enumerate(raw_rows_value, start=1):
        item = _mapping(raw, f"raw row {index}")
        _exact_keys(item, RAW_KEYS, f"raw row {index}")
        raw_rows.append(item)

    artifact_descriptors = _mapping(package.get("artifacts"), "artifacts")
    _exact_keys(artifact_descriptors, ARTIFACT_NAMES, "artifacts")
    artifacts = {
        name: _read_artifact(package_dir, artifact_descriptors[name], name)
        for name in sorted(ARTIFACT_NAMES)
    }
    try:
        normalized = build_ett_normalization_plan(
            source=source,
            ingest_run=ingest_run,
            raw_rows=raw_rows,
            parser_version=package["normalizer_version"],
        )
    except EttNormalizationError as exc:
        raise EttOfflinePlanError(str(exc)) from exc
    manifest, extraction = _validate_retained_artifacts(
        source=source,
        ingest_run=ingest_run,
        raw_rows=raw_rows,
        artifacts=artifacts,
    )

    plan: dict[str, Any] = {
        "schema_version": 1,
        "kind": "ETT_TECHNICAL_NORMALIZATION_PLAN",
        "target": "tariff_staging.tariff_ingest.ett_normalization_results",
        "transaction_owner": "CALLER",
        "execution_performed": False,
        "source_object": dict(source),
        "ingest_run": dict(ingest_run),
        "raw_rows": [dict(row) for row in raw_rows],
        "retained_artifacts": {
            name: descriptor for name, (_, descriptor) in artifacts.items()
        },
        "retained_manifest": dict(manifest),
        "retained_extraction_digest": sha256_json(extraction),
        "normalizer_version": normalized.parser_version,
        "expected_counts": {
            "raw": normalized.raw_count,
            "parsed": normalized.parsed_count,
            "ambiguous": normalized.ambiguous_count,
            "verified": 0,
            "admitted": 0,
        },
        "normalization_digest": normalized.digest,
        "rows": [row.values() for row in normalized.rows],
        "invariants": [
            "all package bytes and canonical JSON digests verified before output",
            "only tariff_staging.tariff_ingest is targeted",
            "caller owns the transaction; generated SQL has no transaction boundary",
            "same-version exact replay mutates zero rows",
            "same-version conflict or incomplete replay fails closed",
            "new parser versions append history without changing RAW",
            "all legal_status values are UNVERIFIED; verified and admitted are false",
            "ambiguous duty text has no normalized calculation rate",
        ],
    }
    sql = _render_sql(plan)
    plan["sql_sha256"] = _sha256_bytes(sql.encode("utf-8"))
    plan["plan_sha256"] = sha256_json(plan)
    return plan, sql


def write_offline_artifacts(package_dir: Path, output_dir: Path) -> dict[str, Any]:
    """Atomically publish a validated plan directory; never execute it."""

    plan, sql = build_offline_artifacts(package_dir)
    output_dir = Path(output_dir)
    if output_dir.exists() or output_dir.is_symlink():
        raise EttOfflinePlanError("output directory must not already exist")
    parent = output_dir.parent
    if not parent.is_dir():
        raise EttOfflinePlanError("output parent directory does not exist")
    temporary = Path(tempfile.mkdtemp(prefix=".ett-plan-", dir=parent))
    try:
        (temporary / "plan.json").write_text(
            json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        (temporary / "apply.sql").write_text(sql, encoding="utf-8")
        os.replace(temporary, output_dir)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return plan



