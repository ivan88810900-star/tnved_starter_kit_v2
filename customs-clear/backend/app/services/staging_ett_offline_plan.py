"""Dependency-free validation and SQL planning for a local ETT package."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .staging_ett_normalization_core import (
    COLLECTED_UNVERIFIED,
    ETT_NORMALIZER_VERSION,
    EttNormalizationError,
    build_ett_normalization_plan,
    canonical_json,
    sha256_json,
)


PACKAGE_SCHEMA_VERSION = 1
TARGET_SCHEMA = "tariff_ingest"
TARGET_TABLE = "ett_normalization_results"

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
    "retained_manifest_required_bindings": [
        "source_id",
        "source_revision",
        "source_sha256",
        "source_size_bytes",
        "extraction_sha256",
        "extraction_size_bytes",
    ],
    "retained_extraction_forms": ["row array", "object containing rows"],
    "retained_extraction_row_fields": sorted(EXTRACTION_ROW_KEYS),
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


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_json_bytes(value: bytes, label: str) -> Any:
    try:
        decoded = value.decode("utf-8")
        parsed = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EttOfflinePlanError(f"{label} must be canonical UTF-8 JSON") from exc
    return parsed


def _scalar_values(value: Any):
    if isinstance(value, Mapping):
        for item in value.values():
            yield from _scalar_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _scalar_values(item)
    elif value is not None and not isinstance(value, (dict, list)):
        yield value


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
    required_manifest_values = {
        source.get("source_id"),
        source.get("source_revision"),
        source.get("sha256"),
        source.get("size_bytes"),
        extraction_artifact["sha256"],
        extraction_artifact["size_bytes"],
    }
    manifest_values = set(_scalar_values(manifest))
    if not required_manifest_values <= manifest_values:
        raise EttOfflinePlanError("retained manifest identity or digests mismatch")
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
    source_hex = _json_hex(plan["source_object"])
    run_hex = _json_hex(plan["ingest_run"])
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
    return f"""-- Generated offline from a fully validated local package.
-- Execute only inside an explicit caller-owned transaction with scoped staging access.
-- This file has no connection settings and intentionally owns no transaction boundary.

DO $ett_offline_plan$
DECLARE
    expected_source jsonb := convert_from(decode('{source_hex}', 'hex'), 'UTF8')::jsonb;
    expected_run jsonb := convert_from(decode('{run_hex}', 'hex'), 'UTF8')::jsonb;
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
    IF (SELECT count(*) FROM tariff_ingest.ingest_runs r
        WHERE r.source_id = expected_source->>'source_id') <> 1 THEN
        RAISE EXCEPTION 'staged ETT source must have exactly one raw ingest run';
    END IF;
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
    ) THEN RAISE EXCEPTION 'ingest_runs package mismatch'; END IF;
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
    END IF;

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
          AND (SELECT array_agg(a.attname ORDER BY u.ord)
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
          AND (SELECT array_agg(a.attname ORDER BY u.ord)
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
          AND (SELECT array_agg(a.attname ORDER BY u.ord)
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
          AND (SELECT array_agg(a.attname ORDER BY u.ord)
               FROM unnest(c.conkey) WITH ORDINALITY u(attnum, ord)
               JOIN pg_catalog.pg_attribute a
                 ON a.attrelid = c.conrelid AND a.attnum = u.attnum)
              = ARRAY['source_id', 'raw_row_sha256']
          AND (SELECT array_agg(a.attname ORDER BY u.ord)
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
    top_keys = {
        "schema_version",
        "normalizer_version",
        "source_object",
        "ingest_run",
        "raw_rows",
        "artifacts",
    }
    _exact_keys(package, top_keys, "package.json")
    if package.get("schema_version") != PACKAGE_SCHEMA_VERSION:
        raise EttOfflinePlanError("package schema_version mismatch")
    if package.get("normalizer_version") != ETT_NORMALIZER_VERSION:
        raise EttOfflinePlanError("normalizer_version mismatch")

    source = _mapping(package.get("source_object"), "source_object")
    _exact_keys(source, SOURCE_KEYS, "source_object")
    for field in SOURCE_KEYS - {"size_bytes"}:
        if not isinstance(source.get(field), str) or not source[field]:
            raise EttOfflinePlanError(f"source_object.{field} must be a string")
    _strict_positive_int(source.get("size_bytes"), "source_object.size_bytes")
    try:
        captured_at = datetime.fromisoformat(
            source["captured_at"].replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise EttOfflinePlanError(
            "source_object.captured_at is not ISO-8601"
        ) from exc
    if captured_at.utcoffset() is None:
        raise EttOfflinePlanError(
            "source_object.captured_at must include a timezone"
        )
    if source.get("status") != COLLECTED_UNVERIFIED:
        raise EttOfflinePlanError("source_object status is not COLLECTED_UNVERIFIED")
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
    expected_cursor = {
        "next_ordinal": ingest_run["raw_count"] + 1,
        "raw_count": ingest_run["raw_count"],
        "complete": True,
    }
    if ingest_run["resume_cursor"] != expected_cursor:
        raise EttOfflinePlanError("ingest_run.resume_cursor mismatch")
    if ingest_run.get("normalized_count") != 0 or ingest_run.get("rejected_count") != 0:
        raise EttOfflinePlanError("ingest run must precede normalization")
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

