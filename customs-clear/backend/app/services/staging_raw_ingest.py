"""Prepare bounded, raw-first ETT staging batches.

This module deliberately stops before database ingestion, normalization, or legal
admission.  It accepts the UTF-8 bytes emitted by ``pdftotext -layout``, extracts
only rows whose code has the exact ``4 2 3 1`` digit layout, and retains every
source row for provenance.  ``raw_line`` excludes the line terminator but keeps
all other characters, including leading/trailing whitespace; ``row_sha256`` is
calculated over precisely ``raw_line.encode("utf-8")``.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Any


PARSER_VERSION = "ett-pdftotext-layout-raw-v1"
ROW_STATUS = "COLLECTED_UNVERIFIED"
MAX_BATCH_SIZE = 10_000


class StagingRawIngestError(ValueError):
    """Base class for fail-closed source preparation errors."""


class InvalidUtf8SourceError(StagingRawIngestError):
    """Raised when input is not pristine UTF-8 text."""


class AmbiguousEttRowError(StagingRawIngestError):
    """Raised when a code-shaped source row cannot be split unambiguously."""


_CODE_SHAPED_RE = re.compile(
    r"^[ \t]*(?P<g1>\d{4})[ \t]+(?P<g2>\d{2})[ \t]+"
    r"(?P<g3>\d{3})[ \t]+(?P<g4>\d)(?P<tail>.*)$"
)
_COLUMN_SEPARATOR_RE = re.compile(r"[ \t]{2,}")


def _decode_utf8_strict(source_bytes: bytes) -> str:
    if not isinstance(source_bytes, bytes):
        raise TypeError("source_bytes must be bytes")
    try:
        text = source_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise InvalidUtf8SourceError(
            f"source is not valid UTF-8 at byte offset {exc.start}"
        ) from exc
    # U+FFFD is valid UTF-8, but its presence normally means that a previous
    # lossy decode has already destroyed provenance.  Reject it fail-closed.
    if "\ufffd" in text:
        raise InvalidUtf8SourceError("source contains Unicode replacement character U+FFFD")
    return text


def _parse_rows(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        match = _CODE_SHAPED_RE.match(raw_line)
        if match is None:
            continue

        tail = match.group("tail")
        if not tail or not tail[0].isspace():
            raise AmbiguousEttRowError(
                f"line {line_number}: code-shaped row has no column separator"
            )
        columns = _COLUMN_SEPARATOR_RE.split(tail.strip(" \t"))
        if len(columns) != 3 or any(not column for column in columns):
            raise AmbiguousEttRowError(
                f"line {line_number}: expected description, supplementary unit, "
                f"and duty columns; got {len(columns)}"
            )

        description, supplementary_unit, duty_text = columns
        hs_code = "".join(match.group(name) for name in ("g1", "g2", "g3", "g4"))
        raw_bytes = raw_line.encode("utf-8")
        rows.append(
            {
                "ordinal": len(rows) + 1,
                "source_line_number": line_number,
                "hs_code": hs_code,
                "description": description,
                "supplementary_unit": supplementary_unit,
                "duty_text": duty_text,
                "raw_line": raw_line,
                "row_sha256": hashlib.sha256(raw_bytes).hexdigest(),
                "status": ROW_STATUS,
            }
        )

    if not rows:
        raise StagingRawIngestError("no exact 10-digit ETT rows found")
    return rows


def _duplicate_evidence(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_hash: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_hash[row["row_sha256"]].append(row)
        by_code[row["hs_code"]].append(row)

    exact_rows = []
    for row_hash, occurrences in sorted(by_hash.items()):
        if len(occurrences) > 1:
            exact_rows.append(
                {
                    "row_sha256": row_hash,
                    "hs_code": occurrences[0]["hs_code"],
                    "occurrences": len(occurrences),
                    "ordinals": [row["ordinal"] for row in occurrences],
                }
            )

    duplicate_codes = []
    for hs_code, occurrences in sorted(by_code.items()):
        if len(occurrences) > 1:
            duplicate_codes.append(
                {
                    "hs_code": hs_code,
                    "occurrences": len(occurrences),
                    "ordinals": [row["ordinal"] for row in occurrences],
                    "row_sha256s": sorted({row["row_sha256"] for row in occurrences}),
                }
            )
    return {"exact_rows": exact_rows, "hs_codes": duplicate_codes}


def prepare_ett_staging_batch(
    source_bytes: bytes,
    *,
    start_ordinal: int = 1,
    batch_size: int = 100,
) -> dict[str, Any]:
    """Return a deterministic bounded raw batch and global duplicate evidence.

    ``start_ordinal`` is one-based and addresses raw source rows, not deduplicated
    rows.  Duplicate rows remain in ``batch.rows`` so the staging writer can keep
    complete provenance while using ``row_sha256`` for idempotence.
    """

    if isinstance(start_ordinal, bool) or not isinstance(start_ordinal, int):
        raise TypeError("start_ordinal must be an integer")
    if isinstance(batch_size, bool) or not isinstance(batch_size, int):
        raise TypeError("batch_size must be an integer")
    if start_ordinal < 1:
        raise StagingRawIngestError("start_ordinal must be at least 1")
    if batch_size < 1 or batch_size > MAX_BATCH_SIZE:
        raise StagingRawIngestError(
            f"batch_size must be between 1 and {MAX_BATCH_SIZE}"
        )

    text = _decode_utf8_strict(source_bytes)
    rows = _parse_rows(text)
    total_raw_count = len(rows)
    if start_ordinal > total_raw_count + 1:
        raise StagingRawIngestError(
            f"start_ordinal {start_ordinal} is beyond completion ordinal "
            f"{total_raw_count + 1}"
        )

    start_index = start_ordinal - 1
    batch_rows = rows[start_index : start_index + batch_size]
    batch_hashes = {row["row_sha256"] for row in batch_rows}
    total_hashes = {row["row_sha256"] for row in rows}
    next_ordinal = start_ordinal + len(batch_rows)
    complete = next_ordinal > total_raw_count

    return {
        "schema_version": 1,
        "parser_version": PARSER_VERSION,
        "source_text_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "row_status": ROW_STATUS,
        "normalization_performed": False,
        "legal_admission_performed": False,
        "totals": {
            "raw_count": total_raw_count,
            "unique_count": len(total_hashes),
            "duplicate_row_count": total_raw_count - len(total_hashes),
        },
        "batch": {
            "start_ordinal": start_ordinal,
            "end_ordinal": batch_rows[-1]["ordinal"] if batch_rows else None,
            "requested_size": batch_size,
            "raw_count": len(batch_rows),
            "unique_count": len(batch_hashes),
            "duplicate_row_count": len(batch_rows) - len(batch_hashes),
            "rows": batch_rows,
        },
        "resume_cursor": {
            "next_ordinal": next_ordinal,
            "complete": complete,
        },
        "duplicate_evidence": _duplicate_evidence(rows),
    }


__all__ = [
    "AmbiguousEttRowError",
    "InvalidUtf8SourceError",
    "MAX_BATCH_SIZE",
    "PARSER_VERSION",
    "ROW_STATUS",
    "StagingRawIngestError",
    "prepare_ett_staging_batch",
]
