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
PLUS_PARSER_VERSION = "ett-pdftotext-layout-raw-v2-plus"
CHAPTER30_PARSER_VERSION = (
    "ett-pdftotext-layout-raw-v2-plus-chapter30-multiline-v2"
)
CHAPTER30_SOURCE_TEXT_SHA256 = (
    "90554ea32706876c28d479b42d8f0dfb7d9032311550f63553066c6d5d40b536"
)
CHAPTER30_EXPECTED_ROWS = 82
CHAPTER30_EXPECTED_PLUS_ROWS = 16
CHAPTER30_REVIEWED_DUTY_NOTE_BINDINGS = (
    {
        "marker_source_line": 551,
        "marker": "63С)",
        "page_number": 12,
        "target_hs_code": "3005905000",
        "target_source_line": 552,
        "previous_hs_code": "3005903100",
        "previous_source_line": 550,
        "marker_y": (311.538680, 320.970320),
        "target_y": (314.838320, 326.502320),
        "previous_y": (297.918320, 309.582320),
        "binding_basis": "reviewed_pdf_page_bbox_vertical_overlap",
    },
)
ROW_STATUS = "COLLECTED_UNVERIFIED"
MAX_BATCH_SIZE = 10_000


class StagingRawIngestError(ValueError):
    """Base class for fail-closed source preparation errors."""


class InvalidUtf8SourceError(StagingRawIngestError):
    """Raised when input is not pristine UTF-8 text."""


class AmbiguousEttRowError(StagingRawIngestError):
    """Raised when a code-shaped source row cannot be split unambiguously."""


_CODE_SHAPED_RE = re.compile(
    r"^[ \t]*(?P<g1>[0-9]{4})[ \t]+(?P<g2>[0-9]{2})[ \t]+"
    r"(?P<g3>[0-9]{3})[ \t]+(?P<g4>[0-9])(?P<tail>.*)$"
)
_PLUS_CODE_SHAPED_RE = re.compile(
    r"^[ \t]*(?:\+[ \t]+)?(?P<g1>[0-9]{4})[ \t]+(?P<g2>[0-9]{2})[ \t]+"
    r"(?P<g3>[0-9]{3})[ \t]+(?P<g4>[0-9])(?P<tail>.*)$"
)
_UNSUPPORTED_PREFIX_RE = re.compile(
    r"^[ \t]*(?P<prefix>[^\w\s]+)[^\S\r\n]*[0-9]{4}[ \t]+[0-9]{2}[ \t]+"
    r"[0-9]{3}[ \t]+[0-9](?:[ \t]|$)"
)
_COLUMN_SEPARATOR_RE = re.compile(r"[ \t]{2,}")
_PARTIAL_CODE_RE = re.compile(
    r"^[ \t]*[0-9]{4}(?:[ \t]+[0-9]{2}(?:[ \t]+[0-9]{3})?)?"
    r"[ \t]{2,}\S"
)
_TOP_HEADING_RE = re.compile(r"^[ \t]*(?P<code>[0-9]{4})[ \t]{2,}\S")
_PAGE_FURNITURE = {
    "Ставка ввозной",
    "таможенной",
    "пошлины",
    "Доп.",
    "Код",
    "Наименование позиции            ед.",
    "Наименование позиции             ед.",
    "Наименование позиции           ед.",
    "ТН ВЭД",
    "изм.",
    "стоимости либо",
    "в евро, либо",
    "в долларах США)",
}


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


def _parse_rows(text: str, *, allow_leading_plus: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    row_pattern = _PLUS_CODE_SHAPED_RE if allow_leading_plus else _CODE_SHAPED_RE
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        match = row_pattern.match(raw_line)
        if match is None:
            prefixed = (
                _UNSUPPORTED_PREFIX_RE.match(raw_line)
                if allow_leading_plus
                else None
            )
            if prefixed is not None:
                raise AmbiguousEttRowError(
                    f"line {line_number}: unsupported code prefix "
                    f"{prefixed.group('prefix')!r}"
                )
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


def _leading_width(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _is_page_furniture(line: str) -> bool:
    stripped = line.strip(" \t")
    if not stripped:
        return True
    if stripped in _PAGE_FURNITURE:
        return True
    return stripped.startswith(
        ("Код ", "Наименование позиции ", "ТН ВЭД ", "(в процентах", "от таможенной")
    )


def _provenance(
    source_lines: list[int], fragments: list[str]
) -> dict[str, Any]:
    return {
        "text": " ".join(fragments),
        "source_lines": source_lines,
        "fragments": fragments,
    }


def _row_semantic_column(row: dict[str, Any]) -> int:
    match = _PLUS_CODE_SHAPED_RE.match(row["raw_line"])
    if match is None:
        raise AmbiguousEttRowError(
            f"line {row['source_line_number']}: reviewed row no longer matches"
        )
    tail = match.group("tail")
    description_offset = tail.find(row["description"])
    if description_offset < 0:
        raise AmbiguousEttRowError(
            f"line {row['source_line_number']}: description column cannot be located"
        )
    hierarchy = re.match(r"(?:–[ \t]+)*", row["description"])
    return match.start("tail") + description_offset + len(hierarchy.group(0))


def _validate_context_lines(
    lines: list[str], indexes: list[int]
) -> tuple[list[int], list[str]]:
    source_lines: list[int] = []
    fragments: list[str] = []
    context_open = False
    for index in indexes:
        line = lines[index]
        if _is_page_furniture(line):
            continue
        stripped = line.strip(" \t")
        starts_context = bool(_PARTIAL_CODE_RE.match(line)) or stripped.startswith("–")
        if starts_context:
            context_open = True
        elif not context_open or _leading_width(line) == 0:
            raise AmbiguousEttRowError(
                f"line {index + 1}: unclassified chapter-30 table context"
            )
        source_lines.append(index + 1)
        fragments.append(stripped)
    return source_lines, fragments


def _vertical_overlap(first: tuple[float, float], second: tuple[float, float]) -> float:
    return max(0.0, min(first[1], second[1]) - max(first[0], second[0]))


def _reviewed_duty_note_bindings(
    text: str, lines: list[str], rows: list[dict[str, Any]]
) -> tuple[dict[int, dict[str, Any]], dict[str, dict[str, Any]]]:
    rows_by_hs = {row["hs_code"]: row for row in rows}
    by_marker_index: dict[int, dict[str, Any]] = {}
    by_target_hs: dict[str, dict[str, Any]] = {}
    source_parts = text.splitlines(keepends=True)
    for value in CHAPTER30_REVIEWED_DUTY_NOTE_BINDINGS:
        binding = dict(value)
        marker_line = binding["marker_source_line"]
        target_line = binding["target_source_line"]
        previous_line = binding["previous_source_line"]
        marker_index = marker_line - 1
        target = rows_by_hs.get(binding["target_hs_code"])
        previous = rows_by_hs.get(binding["previous_hs_code"])
        if (
            marker_line + 1 != target_line
            or previous_line + 1 != marker_line
            or marker_index < 0
            or marker_index >= len(lines)
            or lines[marker_index].strip(" \t") != binding["marker"]
            or target is None
            or previous is None
            or target["source_line_number"] != target_line
            or previous["source_line_number"] != previous_line
        ):
            raise AmbiguousEttRowError(
                "chapter-30 reviewed duty-note source binding mismatch"
            )
        page_number = 1 + sum(
            part.count("\f") for part in source_parts[:marker_index]
        )
        if page_number != binding["page_number"]:
            raise AmbiguousEttRowError(
                "chapter-30 reviewed duty-note page binding mismatch"
            )
        if (
            _vertical_overlap(binding["marker_y"], binding["target_y"]) <= 0
            or _vertical_overlap(binding["marker_y"], binding["previous_y"]) != 0
        ):
            raise AmbiguousEttRowError(
                "chapter-30 reviewed duty-note geometry is not exclusive"
            )
        if marker_index in by_marker_index or target["hs_code"] in by_target_hs:
            raise AmbiguousEttRowError(
                "chapter-30 reviewed duty-note binding is duplicated"
            )
        by_marker_index[marker_index] = binding
        by_target_hs[target["hs_code"]] = binding
    return by_marker_index, by_target_hs


def _bind_chapter30_multiline(
    text: str, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    source_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if source_sha256 != CHAPTER30_SOURCE_TEXT_SHA256:
        raise StagingRawIngestError(
            "chapter-30 multiline profile rejects non-reviewed source layout"
        )
    plus_rows = sum(row["raw_line"].lstrip(" \t").startswith("+ ") for row in rows)
    if len(rows) != CHAPTER30_EXPECTED_ROWS or plus_rows != CHAPTER30_EXPECTED_PLUS_ROWS:
        raise StagingRawIngestError(
            "chapter-30 reviewed code-line completeness mismatch"
        )
    if any(row["supplementary_unit"] != "–" for row in rows):
        raise StagingRawIngestError("chapter-30 supplementary-unit contract mismatch")

    lines = text.splitlines()
    row_indexes = [row["source_line_number"] - 1 for row in rows]
    row_index_set = set(row_indexes)
    if len(row_index_set) != len(rows):
        raise AmbiguousEttRowError("chapter-30 row line binding is not unique")
    duty_notes_by_index, duty_notes_by_target = _reviewed_duty_note_bindings(
        text, lines, rows
    )

    first_index = row_indexes[0]
    context_start = None
    for index in range(first_index):
        heading = _TOP_HEADING_RE.match(lines[index])
        if heading is not None and heading.group("code") == rows[0]["hs_code"][:4]:
            context_start = index
            break
    if context_start is None:
        raise AmbiguousEttRowError(
            "chapter-30 first row has no matching top-level heading"
        )
    pending_indexes = list(range(context_start, first_index))
    description_continuation_count = 0
    reviewed_duty_note_binding_count = 0
    context_line_count = 0

    for position, row in enumerate(rows):
        row_index = row_indexes[position]
        if row_index not in row_index_set or lines[row_index] != row["raw_line"]:
            raise AmbiguousEttRowError(
                f"line {row_index + 1}: row provenance does not match source text"
            )
        context_lines, context_fragments = _validate_context_lines(
            lines, pending_indexes
        )
        context_line_count += len(context_lines)
        row["preceding_context_provenance"] = _provenance(
            context_lines, context_fragments
        )

        semantic_column = _row_semantic_column(row)
        description_lines = [row_index + 1]
        description_fragments = [row["description"]]
        next_index = (
            row_indexes[position + 1] if position + 1 < len(rows) else len(lines)
        )
        following_context: list[int] = []
        context_started = False
        for index in range(row_index + 1, next_index):
            line = lines[index]
            if _is_page_furniture(line):
                continue
            if index in duty_notes_by_index:
                continue
            stripped = line.strip(" \t")
            if (
                not context_started
                and _leading_width(line) == semantic_column
                and not stripped.startswith("–")
                and not _PARTIAL_CODE_RE.match(line)
            ):
                description_lines.append(index + 1)
                description_fragments.append(stripped)
                description_continuation_count += 1
                continue
            context_started = True
            following_context.append(index)

        row["description_provenance"] = _provenance(
            description_lines, description_fragments
        )
        row["description"] = row["description_provenance"]["text"]
        row["duty_provenance"] = _provenance(
            [row_index + 1], [row["duty_text"]]
        )
        row["duty_provenance"]["rendered_text"] = row["duty_text"]
        note_binding = duty_notes_by_target.get(row["hs_code"])
        if note_binding is not None:
            qualified_duty_text = (
                f"{row['duty_text']} {note_binding['marker']}"
            )
            row["duty_provenance"] = _provenance(
                [row_index + 1, note_binding["marker_source_line"]],
                [row["duty_text"], note_binding["marker"]],
            )
            row["duty_provenance"]["rendered_text"] = qualified_duty_text
            row["duty_provenance"]["physical_source_order_lines"] = sorted(
                row["duty_provenance"]["source_lines"]
            )
            row["duty_provenance"]["note_marker"] = {
                key: note_binding[key]
                for key in (
                    "marker_source_line",
                    "marker",
                    "page_number",
                    "target_hs_code",
                    "target_source_line",
                    "previous_hs_code",
                    "previous_source_line",
                    "marker_y",
                    "target_y",
                    "previous_y",
                    "binding_basis",
                )
            }
            row["duty_text"] = qualified_duty_text
            if row["duty_text"] != row["duty_provenance"]["text"]:
                raise AmbiguousEttRowError(
                    "chapter-30 qualified duty text is not provenance-bound"
                )
            reviewed_duty_note_binding_count += 1
        pending_indexes = following_context

    trailing_lines, trailing_fragments = _validate_context_lines(lines, pending_indexes)
    if trailing_lines or trailing_fragments:
        raise AmbiguousEttRowError(
            "chapter-30 structural context remains after the final code row"
        )

    return {
        "status": "COMPLETE_REVIEWED_SNAPSHOT",
        "source_layout_verified": True,
        "official_current_bytes_verified": False,
        "multiline_continuations_collected": True,
        "code_line_count": len(rows),
        "plus_line_count": plus_rows,
        "description_continuation_line_count": description_continuation_count,
        "duty_continuation_line_count": 0,
        "reviewed_duty_note_binding_count": reviewed_duty_note_binding_count,
        "structural_context_line_count": context_line_count,
        "record_outcomes": {
            "complete": len(rows),
            "ambiguous": 0,
            "errors": 0,
        },
    }


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
    allow_leading_plus: bool = False,
    bind_chapter30_multiline: bool = False,
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
    if type(allow_leading_plus) is not bool:
        raise TypeError("allow_leading_plus must be a boolean")
    if type(bind_chapter30_multiline) is not bool:
        raise TypeError("bind_chapter30_multiline must be a boolean")
    if bind_chapter30_multiline and not allow_leading_plus:
        raise StagingRawIngestError(
            "chapter-30 multiline profile requires allow_leading_plus"
        )
    if start_ordinal < 1:
        raise StagingRawIngestError("start_ordinal must be at least 1")
    if batch_size < 1 or batch_size > MAX_BATCH_SIZE:
        raise StagingRawIngestError(
            f"batch_size must be between 1 and {MAX_BATCH_SIZE}"
        )

    text = _decode_utf8_strict(source_bytes)
    if (
        bind_chapter30_multiline
        and hashlib.sha256(source_bytes).hexdigest()
        != CHAPTER30_SOURCE_TEXT_SHA256
    ):
        raise StagingRawIngestError(
            "chapter-30 multiline profile rejects non-reviewed source layout"
        )
    rows = _parse_rows(text, allow_leading_plus=allow_leading_plus)
    chapter30_completeness = (
        _bind_chapter30_multiline(text, rows)
        if bind_chapter30_multiline
        else None
    )
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

    payload = {
        "schema_version": 1,
        "parser_version": (
            CHAPTER30_PARSER_VERSION
            if bind_chapter30_multiline
            else PLUS_PARSER_VERSION if allow_leading_plus else PARSER_VERSION
        ),
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
    if allow_leading_plus:
        payload["allow_leading_plus"] = True
        payload["completeness"] = {
            "status": "BLOCKED",
            "source_provenance_verified": False,
            "multiline_continuations_collected": False,
        }
    if chapter30_completeness is not None:
        payload["completeness"] = chapter30_completeness
    return payload


__all__ = [
    "AmbiguousEttRowError",
    "CHAPTER30_EXPECTED_PLUS_ROWS",
    "CHAPTER30_EXPECTED_ROWS",
    "CHAPTER30_PARSER_VERSION",
    "CHAPTER30_REVIEWED_DUTY_NOTE_BINDINGS",
    "CHAPTER30_SOURCE_TEXT_SHA256",
    "InvalidUtf8SourceError",
    "MAX_BATCH_SIZE",
    "PARSER_VERSION",
    "PLUS_PARSER_VERSION",
    "ROW_STATUS",
    "StagingRawIngestError",
    "prepare_ett_staging_batch",
]


