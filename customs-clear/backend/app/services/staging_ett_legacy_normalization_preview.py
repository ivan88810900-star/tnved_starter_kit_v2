"""Pure offline normalization preview for a validated legacy ETT envelope."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from app.services.staging_ett_legacy_recovery import (
    EXPECTED_PARSER_BY_RANGE,
    EXPECTED_RAW_COUNT,
    EXPECTED_RUN_RANGES,
    FIRST20_PARSER_EVIDENCE,
    FIRST20_PARSER_VERSION,
    KIND as RECOVERY_KIND,
    LEGACY_PARSER_COMMIT,
    RESUMABLE_PARSER_VERSION,
    SOURCE_KEYS,
    EttLegacyRecoveryError,
    _run_range,
    _validate_rows,
    build_legacy_recovery_envelope,
)
from app.services.staging_ett_normalization_core import (
    ETT_NORMALIZER_VERSION,
    LEGAL_STATUS_UNVERIFIED,
    SYNTAX_PARSED,
    _parse_rate,
    canonical_json,
    sha256_json,
)


SCHEMA_VERSION = 1
KIND = "ETT_LEGACY_NORMALIZATION_PREVIEW_V1"
RECOVERY_STATUS = "READY_FOR_OFFLINE_PACKAGE_REVIEW"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ENVELOPE_KEYS = {
    "schema_version",
    "kind",
    "legacy_parser_commit",
    "legacy_parser_contracts",
    "status",
    "missing_evidence",
    "execution_performed",
    "sql_generated",
    "normalization_performed",
    "verified",
    "admitted",
    "observed",
    "derived",
    "envelope_sha256",
}
_PROVENANCE_KEYS = {
    "ordinal",
    "hs_code",
    "row_sha256",
    "source_line_number",
    "page_number",
    "line_number",
}


class EttLegacyPreviewError(ValueError):
    """The recovery envelope is not safe for an offline preview."""


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EttLegacyPreviewError(f"{label} must be an object")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise EttLegacyPreviewError(f"{label} must be a sequence")
    return value


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise EttLegacyPreviewError(f"{label} must be a positive integer")
    return value


def _sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise EttLegacyPreviewError(f"{label} must be a lowercase SHA-256")
    return value


def _copy(value: Any) -> Any:
    return json.loads(canonical_json(value))


def _validate_envelope_integrity(envelope: Mapping[str, Any]) -> str:
    if set(envelope) != _ENVELOPE_KEYS:
        raise EttLegacyPreviewError("recovery envelope fields mismatch")
    envelope_sha = _sha256(
        envelope.get("envelope_sha256"), "recovery envelope_sha256"
    )
    hash_payload = {key: value for key, value in envelope.items() if key != "envelope_sha256"}
    if sha256_json(hash_payload) != envelope_sha:
        raise EttLegacyPreviewError("recovery envelope SHA mismatch")
    if (
        type(envelope.get("schema_version")) is not int
        or envelope.get("schema_version") != 1
        or envelope.get("kind") != RECOVERY_KIND
    ):
        raise EttLegacyPreviewError("unsupported recovery envelope contract")
    expected_parser_contracts = {
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
    }
    if (
        envelope.get("legacy_parser_commit") != LEGACY_PARSER_COMMIT
        or envelope.get("legacy_parser_contracts") != expected_parser_contracts
    ):
        raise EttLegacyPreviewError("recovery parser contracts mismatch")
    if (
        envelope.get("status") != RECOVERY_STATUS
        or envelope.get("missing_evidence") != []
        or envelope.get("execution_performed") is not False
        or envelope.get("sql_generated") is not False
        or envelope.get("normalization_performed") is not False
        or type(envelope.get("verified")) is not int
        or envelope.get("verified") != 0
        or type(envelope.get("admitted")) is not int
        or envelope.get("admitted") != 0
    ):
        raise EttLegacyPreviewError("recovery evidence is incomplete or not raw-only")
    return envelope_sha


def _validate_runs(
    observed_runs: Sequence[Any],
    derived_ranges: Sequence[Any],
    *,
    source_id: str,
) -> list[dict[str, Any]]:
    if len(observed_runs) != 3 or len(derived_ranges) != 3:
        raise EttLegacyPreviewError("recovery run partition count mismatch")
    validated: list[dict[str, Any]] = []
    seen_run_ids: set[str] = set()
    actual_ranges: list[tuple[int, int, int]] = []
    for index, (run_value, range_value) in enumerate(
        zip(observed_runs, derived_ranges), start=1
    ):
        run = _mapping(run_value, f"observed run {index}")
        item = _mapping(range_value, f"derived run range {index}")
        validated_range, _ = _run_range(run, source_id=source_id, chapter="29")
        if dict(item) != validated_range:
            raise EttLegacyPreviewError("observed/derived legacy run binding mismatch")
        run_id = validated_range["run_id"]
        if not isinstance(run_id, str) or not run_id or run_id in seen_run_ids:
            raise EttLegacyPreviewError("legacy run IDs must be nonempty and unique")
        seen_run_ids.add(run_id)
        start = validated_range["start_ordinal"]
        end = validated_range["end_ordinal"]
        raw_count = validated_range["raw_count"]
        parser_version = validated_range["parser_version"]
        actual_ranges.append((start, end, raw_count))
        expected_parser = EXPECTED_PARSER_BY_RANGE.get((start, end))
        if parser_version != expected_parser:
            raise EttLegacyPreviewError("legacy parser/range contract mismatch")
        validated.append(
            {
                "run_id": run_id,
                "start_ordinal": start,
                "end_ordinal": end,
                "parser_version": parser_version,
            }
        )
    if tuple(actual_ranges) != EXPECTED_RUN_RANGES:
        raise EttLegacyPreviewError("legacy run ranges are not the reviewed partition")
    return validated


def _run_for_ordinal(runs: Sequence[Mapping[str, Any]], ordinal: int) -> Mapping[str, Any]:
    matches = [
        item
        for item in runs
        if item["start_ordinal"] <= ordinal <= item["end_ordinal"]
    ]
    if len(matches) != 1:
        raise EttLegacyPreviewError("legacy ordinal is not bound to exactly one run")
    return matches[0]


def build_legacy_normalization_preview(
    recovery_envelope: Mapping[str, Any],
    *,
    original_bytes: bytes,
    source_text_bytes: bytes,
) -> dict[str, Any]:
    """Reconcile exact evidence and return JSON-only technical results."""

    envelope = _mapping(recovery_envelope, "recovery envelope")
    recovery_sha = _validate_envelope_integrity(envelope)
    observed = _mapping(envelope.get("observed"), "recovery observed")
    derived = _mapping(envelope.get("derived"), "recovery derived")
    if set(observed) != {"source", "legacy_runs", "raw_rows"}:
        raise EttLegacyPreviewError("recovery observed fields mismatch")
    if set(derived) != {
        "run_ranges",
        "raw_count",
        "source_text_sha256",
        "provenance",
    }:
        raise EttLegacyPreviewError("recovery derived fields mismatch")
    source = _mapping(observed.get("source"), "recovery source")
    if set(source) != SOURCE_KEYS:
        raise EttLegacyPreviewError("recovery source fields mismatch")
    source_id = source.get("source_id")
    if not isinstance(source_id, str) or not source_id:
        raise EttLegacyPreviewError("recovery source_id is missing")
    if source.get("chapter") != "29":
        raise EttLegacyPreviewError("recovery source chapter mismatch")
    _sha256(source.get("sha256"), "recovery source sha256")
    _positive_int(source.get("size_bytes"), "recovery source size_bytes")
    page_count = _positive_int(source.get("page_count"), "recovery source page_count")
    _sha256(derived.get("source_text_sha256"), "recovery source text sha256")

    try:
        rebuilt = build_legacy_recovery_envelope(
            source=source,
            legacy_runs=_sequence(
                observed.get("legacy_runs"), "observed legacy_runs"
            ),
            raw_rows=_sequence(observed.get("raw_rows"), "observed raw_rows"),
            original_bytes=original_bytes,
            source_text_bytes=source_text_bytes,
        )
    except EttLegacyRecoveryError as exc:
        raise EttLegacyPreviewError(
            f"recovery envelope does not match exact evidence: {exc}"
        ) from exc
    if rebuilt != envelope:
        raise EttLegacyPreviewError(
            "recovery envelope does not equal the exact-evidence reconstruction"
        )

    observed_runs = _sequence(observed.get("legacy_runs"), "observed legacy_runs")
    derived_ranges = _sequence(derived.get("run_ranges"), "derived run_ranges")
    runs = _validate_runs(
        observed_runs, derived_ranges, source_id=source_id
    )
    raw_rows_input = _sequence(observed.get("raw_rows"), "observed raw_rows")
    raw_rows = _validate_rows(raw_rows_input, source_id=source_id, chapter="29")
    provenance_rows = _sequence(derived.get("provenance"), "derived provenance")
    derived_raw_count = _positive_int(
        derived.get("raw_count"), "recovery derived raw_count"
    )
    if (
        len(raw_rows) != EXPECTED_RAW_COUNT
        or len(provenance_rows) != EXPECTED_RAW_COUNT
        or derived_raw_count != EXPECTED_RAW_COUNT
    ):
        raise EttLegacyPreviewError("recovery complete row count mismatch")

    rows: list[dict[str, Any]] = []
    seen_raw_hashes: set[str] = set()
    previous_source_line = 0
    previous_page = 0
    previous_page_line = 0
    page_line_offsets: dict[int, int] = {}
    for ordinal, (raw_value, provenance_value) in enumerate(
        zip(raw_rows, provenance_rows), start=1
    ):
        raw = _mapping(raw_value, f"raw row {ordinal}")
        provenance = _mapping(provenance_value, f"provenance row {ordinal}")
        if set(provenance) != _PROVENANCE_KEYS:
            raise EttLegacyPreviewError(f"provenance row {ordinal} fields mismatch")
        row_sha = _sha256(raw.get("row_sha256"), f"raw row {ordinal} SHA")
        raw_line = raw.get("raw_line")
        if not isinstance(raw_line, str) or hashlib.sha256(
            raw_line.encode("utf-8")
        ).hexdigest() != row_sha:
            raise EttLegacyPreviewError(f"raw row {ordinal} identity mismatch")
        if row_sha in seen_raw_hashes:
            raise EttLegacyPreviewError("duplicate legacy raw identity")
        seen_raw_hashes.add(row_sha)
        hs_code = raw.get("hs_code")
        if (
            raw.get("ordinal") != ordinal
            or raw.get("source_id") != source_id
            or raw.get("status") != "COLLECTED_UNVERIFIED"
            or not isinstance(hs_code, str)
            or len(hs_code) != 10
            or not hs_code.isascii()
            or not hs_code.isdigit()
            or not hs_code.startswith("29")
        ):
            raise EttLegacyPreviewError(f"raw row {ordinal} binding mismatch")
        provenance_ordinal = _positive_int(
            provenance.get("ordinal"), f"provenance row {ordinal} ordinal"
        )
        if (
            provenance_ordinal != ordinal
            or provenance.get("hs_code") != hs_code
            or provenance.get("row_sha256") != row_sha
        ):
            raise EttLegacyPreviewError(f"provenance row {ordinal} identity mismatch")
        source_line = _positive_int(
            provenance.get("source_line_number"),
            f"provenance row {ordinal} source_line_number",
        )
        page_number = _positive_int(
            provenance.get("page_number"), f"provenance row {ordinal} page_number"
        )
        page_line = _positive_int(
            provenance.get("line_number"), f"provenance row {ordinal} line_number"
        )
        if page_number > page_count:
            raise EttLegacyPreviewError("provenance page exceeds recovery source page_count")
        if source_line <= previous_source_line:
            raise EttLegacyPreviewError("provenance source-line order is not strict")
        if page_number < previous_page:
            raise EttLegacyPreviewError("provenance page order is not monotonic")
        if page_number == previous_page and page_line <= previous_page_line:
            raise EttLegacyPreviewError("provenance page-line order is not strict")
        page_offset = source_line - page_line
        if page_number in page_line_offsets:
            if page_line_offsets[page_number] != page_offset:
                raise EttLegacyPreviewError(
                    "provenance page/source line mapping is incoherent"
                )
        else:
            page_line_offsets[page_number] = page_offset
        previous_source_line = source_line
        previous_page = page_number
        previous_page_line = page_line
        for key in ("description", "supplementary_unit", "duty_text"):
            if not isinstance(raw.get(key), str):
                raise EttLegacyPreviewError(f"raw row {ordinal} {key} must be a string")

        run = _run_for_ordinal(runs, ordinal)
        syntax_status, rate, ambiguous, reason = _parse_rate(raw["duty_text"])
        result_payload = {
            "source_id": source_id,
            "legacy_run_id": run["run_id"],
            "legacy_parser_version": run["parser_version"],
            "legacy_raw_row_sha256": row_sha,
            "ordinal": ordinal,
            "hs_code": hs_code,
            "original_description": raw["description"],
            "original_supplementary_unit": raw["supplementary_unit"],
            "original_duty_text": raw["duty_text"],
            "original_raw_line": raw_line,
            "provenance": _copy(provenance),
            "syntax_status": syntax_status,
            "normalized_rate_text": rate,
            "is_ambiguous": ambiguous,
            "ambiguity_reason": reason,
            "legal_status": LEGAL_STATUS_UNVERIFIED,
            "verified": False,
            "admitted": False,
        }
        rows.append(
            {**result_payload, "result_sha256": sha256_json(result_payload)}
        )

    parsed = sum(row["syntax_status"] == SYNTAX_PARSED for row in rows)
    ambiguous = sum(row["is_ambiguous"] for row in rows)
    preview: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "recovery_envelope_sha256": recovery_sha,
        "normalizer_version": ETT_NORMALIZER_VERSION,
        "source_id": source_id,
        "counts": {
            "raw": len(rows),
            "unique": len(seen_raw_hashes),
            "parsed": parsed,
            "ambiguous": ambiguous,
        },
        "legal_status": LEGAL_STATUS_UNVERIFIED,
        "verified": 0,
        "admitted": 0,
        "execution_performed": False,
        "sql_generated": False,
        "rows": rows,
    }
    preview["preview_sha256"] = sha256_json(preview)
    return preview


__all__ = [
    "EttLegacyPreviewError",
    "KIND",
    "build_legacy_normalization_preview",
]
