"""Fail-closed recovery envelope for legacy multi-run ETT collection."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1
KIND = "ETT_LEGACY_RECOVERY_ENVELOPE_V1"
FIRST20_PARSER_VERSION = "pdftotext-layout+line-v1"
RESUMABLE_PARSER_VERSION = "ett-pdftotext-layout-raw-v1"
LEGACY_PARSER_COMMIT = "0320a7d268b33413c48dffc963cde6b0ec051ab1"
FIRST20_PARSER_EVIDENCE = (
    ".ai/orchestration/evidence/cycle285_first_persistent_staging_ingest.json"
)
ROW_STATUS = "COLLECTED_UNVERIFIED"
RECOVERY_CHAPTER = "29"
EXPECTED_RUN_RANGES = (
    (1, 20, 20),
    (21, 220, 200),
    (221, 533, 313),
)
EXPECTED_RAW_COUNT = 533
EXPECTED_PARSER_BY_RANGE = {
    (1, 20): FIRST20_PARSER_VERSION,
    (21, 220): RESUMABLE_PARSER_VERSION,
    (221, 533): RESUMABLE_PARSER_VERSION,
}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CHAPTER_RE = re.compile(r"^[0-9]{2}$")
_HS_CODE_RE = re.compile(r"^[0-9]{10}$")
_LEGACY_CODE_SHAPED_RE = re.compile(
    r"^[ \t]*(?P<g1>[0-9]{4})[ \t]+(?P<g2>[0-9]{2})[ \t]+"
    r"(?P<g3>[0-9]{3})[ \t]+(?P<g4>[0-9])(?P<tail>.*)$"
)
_LEGACY_COLUMN_SEPARATOR_RE = re.compile(r"[ \t]{2,}")

SOURCE_KEYS = {"source_id", "sha256", "size_bytes", "page_count", "chapter"}
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


class EttLegacyRecoveryError(ValueError):
    """Legacy evidence is internally inconsistent or corrupted."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_copy(value: Any) -> Any:
    return json.loads(_canonical_json(value))


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EttLegacyRecoveryError(f"{label} must be an object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise EttLegacyRecoveryError(f"{label} fields mismatch")


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise EttLegacyRecoveryError(f"{label} must be a positive integer")
    return value


def _nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EttLegacyRecoveryError(f"{label} must be a nonnegative integer")
    return value


def _required_string(value: Any, label: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        raise EttLegacyRecoveryError(f"{label} must be a string")
    return value


def _sha256(value: Any, label: str) -> str:
    digest = _required_string(value, label)
    if _SHA256_RE.fullmatch(digest) is None:
        raise EttLegacyRecoveryError(f"{label} must be a lowercase SHA-256")
    return digest


def _legacy_chapter(value: Any, label: str) -> str:
    if isinstance(value, str) and _CHAPTER_RE.fullmatch(value):
        return value
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 99:
        return f"{value:02d}"
    raise EttLegacyRecoveryError(f"{label} is not a legacy two-digit chapter")


def _run_range(
    run: Mapping[str, Any],
    *,
    source_id: str,
    chapter: str,
) -> tuple[dict[str, Any], str | None]:
    _exact_keys(run, RUN_KEYS, "legacy run")
    run_id = _required_string(run.get("run_id"), "legacy run_id")
    if run.get("source_id") != source_id:
        raise EttLegacyRecoveryError(f"legacy run {run_id} source_id mismatch")
    parser_version = _required_string(
        run.get("parser_version"), f"legacy run {run_id} parser_version"
    )
    if run.get("status") != ROW_STATUS:
        raise EttLegacyRecoveryError(f"legacy run {run_id} status mismatch")
    raw_count = _positive_int(run.get("raw_count"), f"legacy run {run_id} raw_count")
    unique_count = _positive_int(
        run.get("unique_count"), f"legacy run {run_id} unique_count"
    )
    if unique_count != raw_count:
        raise EttLegacyRecoveryError(f"legacy run {run_id} identity count mismatch")
    if (
        _nonnegative_int(
            run.get("normalized_count"), f"legacy run {run_id} normalized_count"
        )
        != 0
        or _nonnegative_int(
            run.get("rejected_count"), f"legacy run {run_id} rejected_count"
        )
        != 0
    ):
        raise EttLegacyRecoveryError(f"legacy run {run_id} is not raw-only")

    scope = _mapping(run.get("scope"), f"legacy run {run_id} scope")
    observed_chapter = scope.get("chapter")
    if observed_chapter is not None and _legacy_chapter(
        observed_chapter, f"legacy run {run_id} scope.chapter"
    ) != chapter:
        raise EttLegacyRecoveryError(f"legacy run {run_id} chapter mismatch")

    cursor = _mapping(run.get("resume_cursor"), f"legacy run {run_id} cursor")
    if "bounded_rows" in scope:
        start = 1
        end = _positive_int(
            scope.get("bounded_rows"), f"legacy run {run_id} bounded_rows"
        )
        last_ordinal = _positive_int(
            cursor.get("last_ordinal"), f"legacy run {run_id} cursor.last_ordinal"
        )
        if last_ordinal != end:
            raise EttLegacyRecoveryError(f"legacy run {run_id} cursor mismatch")
    else:
        start = _positive_int(
            scope.get("start_ordinal"), f"legacy run {run_id} start_ordinal"
        )
        end = _positive_int(
            scope.get("end_ordinal"), f"legacy run {run_id} end_ordinal"
        )
        next_ordinal = _positive_int(
            cursor.get("next_ordinal"), f"legacy run {run_id} cursor.next_ordinal"
        )
        if next_ordinal != end + 1:
            raise EttLegacyRecoveryError(f"legacy run {run_id} cursor mismatch")
    if end < start or end - start + 1 != raw_count:
        raise EttLegacyRecoveryError(f"legacy run {run_id} range/count mismatch")
    if "raw_count" in cursor:
        cursor_count = _positive_int(
            cursor["raw_count"], f"legacy run {run_id} cursor.raw_count"
        )
        if cursor_count != raw_count:
            raise EttLegacyRecoveryError(f"legacy run {run_id} cursor count mismatch")
    if "complete" in cursor and type(cursor["complete"]) is not bool:
        raise EttLegacyRecoveryError(f"legacy run {run_id} cursor.complete invalid")

    text_digest = scope.get("source_text_sha256")
    if text_digest is not None:
        text_digest = _sha256(
            text_digest, f"legacy run {run_id} source_text_sha256"
        )
    return {
        "run_id": run_id,
        "start_ordinal": start,
        "end_ordinal": end,
        "raw_count": raw_count,
        "parser_version": parser_version,
        "chapter_observed": observed_chapter is not None,
    }, text_digest


def _validate_rows(
    raw_rows: Sequence[Mapping[str, Any]],
    *,
    source_id: str,
    chapter: str,
) -> list[dict[str, Any]]:
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)):
        raise EttLegacyRecoveryError("raw_rows must be a sequence")
    if not raw_rows:
        raise EttLegacyRecoveryError("raw_rows must not be empty")
    rows: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for ordinal, value in enumerate(raw_rows, start=1):
        row = _mapping(value, f"raw row {ordinal}")
        _exact_keys(row, RAW_KEYS, f"raw row {ordinal}")
        row_ordinal = _positive_int(row.get("ordinal"), f"raw row {ordinal} ordinal")
        if row_ordinal != ordinal:
            raise EttLegacyRecoveryError("raw ordinals must be contiguous from 1")
        if row.get("source_id") != source_id:
            raise EttLegacyRecoveryError(f"raw row {ordinal} source_id mismatch")
        if row.get("status") != ROW_STATUS:
            raise EttLegacyRecoveryError(f"raw row {ordinal} status mismatch")
        hs_code = _required_string(row.get("hs_code"), f"raw row {ordinal} hs_code")
        if _HS_CODE_RE.fullmatch(hs_code) is None or not hs_code.startswith(chapter):
            raise EttLegacyRecoveryError(f"raw row {ordinal} chapter/HS mismatch")
        for key in ("description", "supplementary_unit", "duty_text", "raw_line"):
            _required_string(
                row.get(key),
                f"raw row {ordinal} {key}",
                nonempty=key not in {"supplementary_unit", "duty_text"},
            )
        row_hash = _sha256(row.get("row_sha256"), f"raw row {ordinal} row_sha256")
        if row_hash != _sha256_bytes(row["raw_line"].encode("utf-8")):
            raise EttLegacyRecoveryError(f"raw row {ordinal} raw_line SHA mismatch")
        if row_hash in seen_hashes:
            raise EttLegacyRecoveryError("duplicate legacy raw identity")
        seen_hashes.add(row_hash)
        rows.append(_json_copy(row))
    return rows


def _derive_page_provenance(
    *,
    source_text_bytes: bytes,
    page_count: int,
    rows: Sequence[Mapping[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    try:
        text = source_text_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise EttLegacyRecoveryError("source text is not strict UTF-8") from exc
    if "\ufffd" in text:
        raise EttLegacyRecoveryError("source text contains replacement characters")

    pages = text.split("\f")
    if pages and pages[-1] == "":
        pages.pop()
    if len(pages) != page_count:
        raise EttLegacyRecoveryError("page-aware source page count mismatch")

    logical_lines = text.splitlines()
    chunks = text.splitlines(keepends=True)
    chunk_lines = [chunk.splitlines()[0] for chunk in chunks]
    if chunk_lines != logical_lines:
        raise EttLegacyRecoveryError("source splitlines reconstruction mismatch")

    line_locations: list[dict[str, int]] = []
    page_number = 1
    page_line_number = 1
    for chunk in chunks:
        line_locations.append(
            {
                "source_line_number": len(line_locations) + 1,
                "page_number": page_number,
                "line_number": page_line_number,
            }
        )
        form_feeds = chunk.count("\f")
        if form_feeds:
            page_number += form_feeds
            page_line_number = 1
        else:
            page_line_number += 1

    parsed_rows: list[dict[str, Any]] = []
    for source_line_number, raw_line in enumerate(logical_lines, start=1):
        match = _LEGACY_CODE_SHAPED_RE.match(raw_line)
        if match is None:
            continue
        tail = match.group("tail")
        if not tail or not tail[0].isspace():
            raise EttLegacyRecoveryError(
                f"historical parser line {source_line_number} has no column separator"
            )
        columns = _LEGACY_COLUMN_SEPARATOR_RE.split(tail.strip(" \t"))
        if len(columns) != 3 or any(not column for column in columns):
            raise EttLegacyRecoveryError(
                f"historical parser line {source_line_number} has ambiguous columns"
            )
        description, supplementary_unit, duty_text = columns
        parsed_rows.append(
            {
                "ordinal": len(parsed_rows) + 1,
                "hs_code": "".join(
                    match.group(name) for name in ("g1", "g2", "g3", "g4")
                ),
                "description": description,
                "supplementary_unit": supplementary_unit,
                "duty_text": duty_text,
                "raw_line": raw_line,
                "row_sha256": _sha256_bytes(raw_line.encode("utf-8")),
                **line_locations[source_line_number - 1],
            }
        )

    if len(parsed_rows) != EXPECTED_RAW_COUNT or len(rows) != EXPECTED_RAW_COUNT:
        raise EttLegacyRecoveryError(
            "historical parser exact complete sequence count mismatch: "
            f"expected={EXPECTED_RAW_COUNT}, parsed={len(parsed_rows)}, raw={len(rows)}"
        )

    provenance: list[dict[str, Any]] = []
    bound_fields = (
        "ordinal",
        "hs_code",
        "description",
        "supplementary_unit",
        "duty_text",
        "raw_line",
        "row_sha256",
    )
    previous_source_line = 0
    for row, parsed in zip(rows, parsed_rows):
        if parsed["source_line_number"] <= previous_source_line:
            raise EttLegacyRecoveryError(
                "historical parser global source line sequence is not strict"
            )
        previous_source_line = parsed["source_line_number"]
        mismatched = [name for name in bound_fields if row[name] != parsed[name]]
        if mismatched:
            raise EttLegacyRecoveryError(
                f"raw row {row['ordinal']} does not match historical parser "
                f"sequence/fields: {','.join(mismatched)}"
            )
        provenance.append(
            {
                "ordinal": row["ordinal"],
                "hs_code": row["hs_code"],
                "row_sha256": row["row_sha256"],
                "source_line_number": parsed["source_line_number"],
                "page_number": parsed["page_number"],
                "line_number": parsed["line_number"],
            }
        )
    return _sha256_bytes(source_text_bytes), provenance


def build_legacy_recovery_envelope(
    *,
    source: Mapping[str, Any],
    legacy_runs: Sequence[Mapping[str, Any]],
    raw_rows: Sequence[Mapping[str, Any]],
    original_bytes: bytes | None,
    source_text_bytes: bytes | None,
) -> dict[str, Any]:
    """Validate legacy facts and return a non-executable recovery envelope."""

    source = _mapping(source, "source")
    _exact_keys(source, SOURCE_KEYS, "source")
    source_id = _required_string(source.get("source_id"), "source.source_id")
    source_sha = _sha256(source.get("sha256"), "source.sha256")
    source_size = _positive_int(source.get("size_bytes"), "source.size_bytes")
    page_count = _positive_int(source.get("page_count"), "source.page_count")
    chapter = _required_string(source.get("chapter"), "source.chapter")
    if _CHAPTER_RE.fullmatch(chapter) is None:
        raise EttLegacyRecoveryError("source.chapter must be exact ASCII digits")
    if chapter != RECOVERY_CHAPTER:
        raise EttLegacyRecoveryError("legacy recovery contract is limited to chapter 29")
    if not isinstance(legacy_runs, Sequence) or isinstance(legacy_runs, (str, bytes)):
        raise EttLegacyRecoveryError("legacy_runs must be a sequence")
    if not legacy_runs:
        raise EttLegacyRecoveryError("legacy_runs must not be empty")

    ranges: list[dict[str, Any]] = []
    run_ids: set[str] = set()
    text_digests: set[str] = set()
    for run in legacy_runs:
        item = _mapping(run, "legacy run")
        run_range, text_digest = _run_range(
            item, source_id=source_id, chapter=chapter
        )
        if run_range["run_id"] in run_ids:
            raise EttLegacyRecoveryError("duplicate legacy run_id")
        run_ids.add(run_range["run_id"])
        ranges.append(run_range)
        if text_digest is not None:
            text_digests.add(text_digest)
    if ranges != sorted(ranges, key=lambda item: item["start_ordinal"]):
        raise EttLegacyRecoveryError("legacy runs must be ordered by range")
    expected_start = 1
    for item in ranges:
        if item["start_ordinal"] != expected_start:
            raise EttLegacyRecoveryError("legacy run ranges contain a gap or overlap")
        expected_start = item["end_ordinal"] + 1
    actual_ranges = tuple(
        (item["start_ordinal"], item["end_ordinal"], item["raw_count"])
        for item in ranges
    )
    if actual_ranges != EXPECTED_RUN_RANGES:
        raise EttLegacyRecoveryError("legacy run bundle does not match fixed recovery ranges")
    for item in ranges:
        start = item["start_ordinal"]
        end = item["end_ordinal"]
        expected_parser = EXPECTED_PARSER_BY_RANGE[(start, end)]
        if item["parser_version"] != expected_parser:
            raise EttLegacyRecoveryError(
                f"legacy run {item['run_id']} parser_version mismatch "
                f"for range {start}-{end}"
            )

    rows = _validate_rows(raw_rows, source_id=source_id, chapter=chapter)
    if expected_start != len(rows) + 1:
        raise EttLegacyRecoveryError("legacy run bundle count mismatch")
    last_cursor = _mapping(legacy_runs[-1].get("resume_cursor"), "final cursor")
    if last_cursor.get("complete") is not True:
        raise EttLegacyRecoveryError("final legacy run is not complete")
    if len(text_digests) > 1:
        raise EttLegacyRecoveryError("legacy source text identities conflict")

    missing_evidence: list[str] = []
    if original_bytes is None:
        missing_evidence.append("exact_original_bytes")
    else:
        if not isinstance(original_bytes, bytes):
            raise EttLegacyRecoveryError("original_bytes must be bytes")
        if len(original_bytes) != source_size or _sha256_bytes(original_bytes) != source_sha:
            raise EttLegacyRecoveryError("original source bytes mismatch")

    provenance: list[dict[str, Any]] = []
    derived_text_sha: str | None = None
    if source_text_bytes is None:
        missing_evidence.extend(["exact_source_text_bytes", "page_aware_mapping"])
    else:
        if not isinstance(source_text_bytes, bytes):
            raise EttLegacyRecoveryError("source_text_bytes must be bytes")
        derived_text_sha, provenance = _derive_page_provenance(
            source_text_bytes=source_text_bytes,
            page_count=page_count,
            rows=rows,
        )
        if not text_digests:
            missing_evidence.append("legacy_source_text_identity")
        elif derived_text_sha not in text_digests:
            raise EttLegacyRecoveryError("source text SHA mismatch")

    status = "BLOCKED" if missing_evidence else "READY_FOR_OFFLINE_PACKAGE_REVIEW"
    envelope: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "legacy_parser_commit": LEGACY_PARSER_COMMIT,
        "legacy_parser_contracts": {
            FIRST20_PARSER_VERSION: {
                "ranges": [[1, 20]],
                "semantics": "bounded line extraction reconciled against complete grammar",
                "evidence": FIRST20_PARSER_EVIDENCE,
            },
            RESUMABLE_PARSER_VERSION: {
                "ranges": [[21, 220], [221, 533]],
                "semantics": "strict reusable raw-first historical grammar",
                "implementation_commit": LEGACY_PARSER_COMMIT,
            },
        },
        "status": status,
        "missing_evidence": sorted(set(missing_evidence)),
        "execution_performed": False,
        "sql_generated": False,
        "normalization_performed": False,
        "verified": 0,
        "admitted": 0,
        "observed": {
            "source": _json_copy(source),
            "legacy_runs": _json_copy(legacy_runs),
            "raw_rows": rows,
        },
        "derived": {
            "run_ranges": ranges,
            "raw_count": len(rows),
            "source_text_sha256": derived_text_sha,
            "provenance": provenance,
        },
    }
    envelope["envelope_sha256"] = _sha256_bytes(
        _canonical_json(envelope).encode("utf-8")
    )
    return envelope


__all__ = [
    "EttLegacyRecoveryError",
    "KIND",
    "build_legacy_recovery_envelope",
]
