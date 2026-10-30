"""Dependency-free deterministic core for technical ETT normalization."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence


ETT_NORMALIZER_VERSION = "ett-duty-syntax-v1"
COLLECTED_UNVERIFIED = "COLLECTED_UNVERIFIED"
LEGAL_STATUS_UNVERIFIED = "UNVERIFIED"
SYNTAX_PARSED = "PARSED"
SYNTAX_AMBIGUOUS = "AMBIGUOUS"
MAX_ETT_ROWS = 86

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_HS_CODE_RE = re.compile(r"^[0-9]{10}$")
_VERSION_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_PLAIN_RATE_RE = re.compile(r"^(?:0|[1-9][0-9]*)(?:[.,][0-9]+)?(?:[ \t]*%)?$")


class EttNormalizationError(ValueError):
    """The supplied immutable ETT package violates its fail-closed contract."""


@dataclass(frozen=True)
class NormalizedEttRow:
    source_id: str
    raw_row_sha256: str
    ordinal: int
    parser_version: str
    source_revision: str
    hs_code: str
    page_number: int
    line_number: int
    original_description: str
    original_supplementary_unit: str
    original_duty_text: str
    original_raw_line: str
    syntax_status: str
    normalized_rate_text: str | None
    is_ambiguous: bool
    ambiguity_reason: str | None
    legal_status: str
    verified: bool
    admitted: bool
    result_sha256: str

    def values(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class EttNormalizationPlan:
    source_id: str
    source_revision: str
    parser_version: str
    raw_count: int
    parsed_count: int
    ambiguous_count: int
    digest: str
    rows: tuple[NormalizedEttRow, ...]


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _required_string(value: Any, label: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        raise EttNormalizationError(f"{label} must be a string")
    return value


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise EttNormalizationError(f"{label} must be a positive integer")
    return value


def _parse_rate(duty_text: str) -> tuple[str, str | None, bool, str | None]:
    candidate = duty_text.strip()
    if not candidate or _PLAIN_RATE_RE.fullmatch(candidate) is None:
        return SYNTAX_AMBIGUOUS, None, True, "QUALIFIED_OR_UNKNOWN_TEXT"
    numeric = candidate[:-1].rstrip() if candidate.endswith("%") else candidate
    numeric = numeric.replace(",", ".")
    try:
        value = Decimal(numeric)
    except InvalidOperation as exc:
        raise EttNormalizationError("plain ETT rate is not a decimal") from exc
    canonical = format(value, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    return SYNTAX_PARSED, canonical, False, None


def _result_row(
    *,
    source_id: str,
    source_revision: str,
    parser_version: str,
    raw: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> NormalizedEttRow:
    syntax_status, rate, ambiguous, reason = _parse_rate(raw["duty_text"])
    payload = {
        "source_id": source_id,
        "raw_row_sha256": raw["row_sha256"],
        "ordinal": raw["ordinal"],
        "parser_version": parser_version,
        "source_revision": source_revision,
        "hs_code": raw["hs_code"],
        "page_number": provenance["page_number"],
        "line_number": provenance["line_number"],
        "original_description": raw["description"],
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
    return NormalizedEttRow(**payload, result_sha256=sha256_json(payload))


def build_ett_normalization_plan(
    *,
    source: Mapping[str, Any],
    ingest_run: Mapping[str, Any],
    raw_rows: Sequence[Mapping[str, Any]],
    parser_version: str = ETT_NORMALIZER_VERSION,
) -> EttNormalizationPlan:
    """Validate the complete package and return a pure deterministic plan."""

    source_id = _required_string(source.get("source_id"), "source_id")
    source_revision = _required_string(source.get("source_revision"), "source_revision")
    if not isinstance(parser_version, str) or _VERSION_RE.fullmatch(parser_version) is None:
        raise EttNormalizationError("parser_version is not canonical")
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)):
        raise EttNormalizationError("raw_rows must be a bounded sequence")
    if not raw_rows or len(raw_rows) > MAX_ETT_ROWS:
        raise EttNormalizationError(
            f"raw row count must be between 1 and {MAX_ETT_ROWS}"
        )
    if ingest_run.get("source_id") != source_id:
        raise EttNormalizationError("ingest run source_id mismatch")
    if ingest_run.get("status") != COLLECTED_UNVERIFIED:
        raise EttNormalizationError("raw ingest run is not COLLECTED_UNVERIFIED")
    if (
        ingest_run.get("raw_count") != len(raw_rows)
        or ingest_run.get("unique_count") != len(raw_rows)
    ):
        raise EttNormalizationError(
            "raw ingest counts do not match the complete package"
        )

    scope = ingest_run.get("scope")
    if not isinstance(scope, Mapping):
        raise EttNormalizationError("ingest run scope is missing")
    identity = scope.get("source_identity")
    if not isinstance(identity, Mapping):
        raise EttNormalizationError("complete scope source_identity is required")
    run_parser_version = _required_string(
        ingest_run.get("parser_version"), "raw ingest parser_version"
    )
    source_sha256 = _required_string(source.get("sha256"), "source sha256")
    if _SHA256_RE.fullmatch(source_sha256) is None:
        raise EttNormalizationError("source sha256 is malformed")
    source_size = _positive_int(source.get("size_bytes"), "source size_bytes")
    source_url = _required_string(source.get("source_url"), "source_url")
    object_bucket = _required_string(source.get("object_bucket"), "object_bucket")
    object_key = _required_string(source.get("object_key"), "object_key")
    source_scope = {
        key: value
        for key, value in scope.items()
        if key not in {"source_identity", "stage_counts", "row_provenance"}
    }
    expected_identity = {
        "source_id": source_id,
        "source_sha256": source_sha256,
        "source_size_bytes": source_size,
        "source_url": source_url,
        "source_revision": source_revision,
        "object_bucket": object_bucket,
        "object_key": object_key,
        "scope": source_scope,
        "parser_version": run_parser_version,
    }
    if set(identity) != set(expected_identity) or any(
        identity.get(key) != value for key, value in expected_identity.items()
    ):
        raise EttNormalizationError(
            "scope source_identity does not match source_objects"
        )
    if scope.get("stage_counts") != {
        "normalized": 0,
        "verified": 0,
        "admitted": 0,
    }:
        raise EttNormalizationError("raw ingest stage_counts are not zero")
    expected_run_id = f"ett:{sha256_json(expected_identity)}"
    if ingest_run.get("run_id") != expected_run_id:
        raise EttNormalizationError("deterministic raw ingest run_id mismatch")
    provenance_rows = scope.get("row_provenance")
    if not isinstance(provenance_rows, list) or len(provenance_rows) != len(raw_rows):
        raise EttNormalizationError("complete row_provenance is required")

    raw_input_ordinals = [
        _positive_int(item.get("ordinal"), "raw ordinal") for item in raw_rows
    ]
    provenance_input_ordinals = [
        _positive_int(
            item.get("ordinal") if isinstance(item, Mapping) else None,
            "provenance ordinal",
        )
        for item in provenance_rows
    ]
    ordered_raw = [
        item
        for _, item in sorted(
            zip(raw_input_ordinals, raw_rows), key=lambda pair: pair[0]
        )
    ]
    ordered_provenance = [
        item
        for _, item in sorted(
            zip(provenance_input_ordinals, provenance_rows),
            key=lambda pair: pair[0],
        )
    ]
    expected_ordinals = list(range(1, len(raw_rows) + 1))
    raw_ordinals = [item.get("ordinal") for item in ordered_raw]
    provenance_ordinals = [
        item.get("ordinal") if isinstance(item, Mapping) else None
        for item in ordered_provenance
    ]
    if raw_ordinals != expected_ordinals:
        raise EttNormalizationError(
            "raw ordinals must be unique and contiguous from 1"
        )
    if provenance_ordinals != expected_ordinals:
        raise EttNormalizationError(
            "provenance ordinals must be unique and contiguous from 1"
        )

    normalized: list[NormalizedEttRow] = []
    seen_hashes: set[str] = set()
    seen_codes: set[str] = set()
    for ordinal, (raw, provenance) in enumerate(
        zip(ordered_raw, ordered_provenance), start=1
    ):
        if raw.get("source_id") != source_id:
            raise EttNormalizationError("raw row source_id mismatch")
        if raw.get("status") != COLLECTED_UNVERIFIED:
            raise EttNormalizationError("raw row is not COLLECTED_UNVERIFIED")
        hs_code = _required_string(raw.get("hs_code"), "hs_code")
        if _HS_CODE_RE.fullmatch(hs_code) is None:
            raise EttNormalizationError(
                "hs_code must be an exact ASCII 10-digit string"
            )
        for name in (
            "description",
            "supplementary_unit",
            "duty_text",
            "raw_line",
        ):
            _required_string(
                raw.get(name),
                name,
                nonempty=name not in {"supplementary_unit", "duty_text"},
            )
        row_sha = _required_string(raw.get("row_sha256"), "row_sha256")
        if _SHA256_RE.fullmatch(row_sha) is None:
            raise EttNormalizationError("row_sha256 is malformed")
        if row_sha in seen_hashes or hs_code in seen_codes:
            raise EttNormalizationError("duplicate raw row hash or hs_code")
        seen_hashes.add(row_sha)
        seen_codes.add(hs_code)
        if not isinstance(provenance, Mapping):
            raise EttNormalizationError("row provenance entry must be a mapping")
        page_number = _positive_int(provenance.get("page_number"), "page_number")
        line_number = _positive_int(provenance.get("line_number"), "line_number")
        if (
            provenance.get("hs_code") != hs_code
            or provenance.get("row_sha256") != row_sha
        ):
            raise EttNormalizationError("row provenance identity mismatch")
        hash_payload = {
            "hs_code": hs_code,
            "description": raw["description"],
            "supplementary_unit": raw["supplementary_unit"],
            "duty_text": raw["duty_text"],
            "page_number": page_number,
            "line_number": line_number,
            "raw_line": raw["raw_line"],
        }
        if sha256_json(hash_payload) != row_sha:
            raise EttNormalizationError(
                f"canonical raw row SHA mismatch at ordinal {ordinal}"
            )
        normalized.append(
            _result_row(
                source_id=source_id,
                source_revision=source_revision,
                parser_version=parser_version,
                raw=raw,
                provenance=provenance,
            )
        )

    digest = sha256_json([row.values() for row in normalized])
    parsed = sum(row.syntax_status == SYNTAX_PARSED for row in normalized)
    ambiguous = sum(row.is_ambiguous for row in normalized)
    return EttNormalizationPlan(
        source_id=source_id,
        source_revision=source_revision,
        parser_version=parser_version,
        raw_count=len(normalized),
        parsed_count=parsed,
        ambiguous_count=ambiguous,
        digest=digest,
        rows=tuple(normalized),
    )

