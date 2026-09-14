"""Bounded consistency checks and evidence-based spacing of ETT superscripts.

This function consumes a table assembler record, not original PDF bytes. It can
verify the record's internal agreement, but cannot certify source provenance.
Only the public byte-input assembler establishes the source extraction path.
Normalizing a reference never interprets its legal meaning or effective dates.
"""
from __future__ import annotations

import math
import re
import unicodedata
from copy import deepcopy
from typing import Any

from app.services.ett_duty_cells import MAX_CELL_CHARACTERS, parse_duty_cell


MAX_CELL_ROWS = 128
MAX_WORDS = 1024
MAX_SPANS = 2048
_SPACE = " \t\r\n\u00a0\u202f"
_MARKER = re.compile(r"([1-9][0-9]{0,3})[ \t\r\n\u00a0\u202f]*[СC]\)\Z")
_MARKER_ANY = re.compile(r"[0-9]+[ \t\r\n\u00a0\u202f]*[СC]\)")


class _InvalidEvidence(ValueError):
    pass


def _text(value: Any) -> str:
    if type(value) is not str or not value or len(value) > MAX_CELL_CHARACTERS:
        raise _InvalidEvidence("invalid_text")
    if any((unicodedata.category(c).startswith("C") or c.isspace()) and c not in _SPACE for c in value):
        raise _InvalidEvidence("invalid_text")
    return value


def _canonical_words(value: str) -> str:
    return re.sub("[ \\t\\r\\n\\u00a0\\u202f]+", " ", value).strip(" ")


def _numbers(value: Any, length: int) -> list[float]:
    if type(value) is not list or len(value) != length or any(type(n) not in (int, float) or abs(n) > 20000 or not math.isfinite(n) for n in value):
        raise _InvalidEvidence("invalid_geometry")
    return value


def _box(value: Any) -> list[float]:
    box = _numbers(value, 4)
    if box[0] < -1 or box[1] < -1 or box[2] <= box[0] or box[3] <= box[1]:
        raise _InvalidEvidence("invalid_geometry")
    return box


def _line_id(value: dict) -> tuple[int, int]:
    if any(type(value.get(k)) is not int or not 0 <= value[k] <= 200000 for k in ("block", "line")):
        raise _InvalidEvidence("invalid_line_identity")
    return value["block"], value["line"]


def _validate_line(words: list[dict], spans: list[dict]) -> None:
    """No omitted text, reversed runs, bad baselines or unrelated coordinates."""
    if not spans:
        raise _InvalidEvidence("missing_typography")
    if _canonical_words("".join(s["text"] for s in spans)) != " ".join(w["text"] for w in words):
        raise _InvalidEvidence("word_span_text_mismatch")
    nonblank = [s for s in spans if s["text"].strip(_SPACE)]
    if not nonblank:
        raise _InvalidEvidence("missing_typography")
    if any(a["bbox"][2] > b["bbox"][0] + .75 for a, b in zip(nonblank, nonblank[1:])):
        raise _InvalidEvidence("overlapping_or_reversed_spans")
    if any(a["bbox"][2] > b["bbox"][0] + .5 for a, b in zip(words, words[1:])):
        raise _InvalidEvidence("overlapping_or_reversed_words")
    envelope = [min(s["bbox"][0] for s in nonblank), min(s["bbox"][1] for s in nonblank),
                max(s["bbox"][2] for s in nonblank), max(s["bbox"][3] for s in nonblank)]
    word_envelope = [min(w["bbox"][0] for w in words), min(w["bbox"][1] for w in words),
                     max(w["bbox"][2] for w in words), max(w["bbox"][3] for w in words)]
    # Text spans can include trailing/leading spaces that get_text('words')
    # omits. Tolerance is limited to those explicitly retained space glyphs.
    left_spaces = len(nonblank[0]["text"]) - len(nonblank[0]["text"].lstrip(_SPACE))
    right_spaces = len(nonblank[-1]["text"]) - len(nonblank[-1]["text"].rstrip(_SPACE))
    tolerances = [.75 + min(left_spaces, 4) * nonblank[0]["size"], .75,
                  .75 + min(right_spaces, 4) * nonblank[-1]["size"], .75]
    if any(abs(a - b) > tolerance for a, b, tolerance in zip(envelope, word_envelope, tolerances)):
        raise _InvalidEvidence("word_span_geometry_mismatch")
    for word in words:
        if not any(s["bbox"][0] < word["bbox"][2] and s["bbox"][2] > word["bbox"][0]
                   and s["bbox"][1] < word["bbox"][3] and s["bbox"][3] > word["bbox"][1] for s in nonblank):
            raise _InvalidEvidence("word_span_geometry_mismatch")


def _raised(span: dict, base: dict) -> bool:
    ratio = span["size"] / base["size"]
    lift = base["origin"][1] - span["origin"][1]
    return (.45 <= ratio <= .82 and .15 * base["size"] <= lift <= .7 * base["size"]
            and span["font"] == base["font"])


def _normalize_line(spans: list[dict], page: int, row: str) -> tuple[str, list[dict]]:
    output: list[str] = []
    evidence: list[dict] = []
    body_spans: list[dict] = []
    index = 0
    while index < len(spans):
        span = spans[index]
        preceding = "".join(output).rstrip(_SPACE)
        bases = [s for s in body_spans if s["text"].strip(_SPACE)]
        base = max(bases, key=lambda s: (s["size"], s["bbox"][0])) if bases else None
        marker_spans = []
        marker_match = None
        # A separately drawn unit exponent is body text, never a note number.
        unit_exponent = preceding.endswith("м") and span["text"].strip(_SPACE) in {"2", "3", "²", "³"}
        if base is not None and not unit_exponent and _raised(span, base):
            for candidate in spans[index:index + 8]:
                if not candidate["text"].strip(_SPACE) or not _raised(candidate, base):
                    break
                if marker_spans and (abs(candidate["origin"][1] - marker_spans[0]["origin"][1]) > .75
                                     or abs(candidate["size"] - marker_spans[0]["size"]) > .75):
                    break
                marker_spans.append(candidate)
                marker_text = "".join(s["text"] for s in marker_spans).strip(_SPACE)
                marker_match = _MARKER.fullmatch(marker_text)
                if marker_match:
                    break
                if len(marker_text) > 12 or ")" in marker_text:
                    break
        if marker_match and not (preceding.endswith("м") and marker_match[1][0] in "23"):
            previous = next((s for s in reversed(body_spans) if s["text"].strip(_SPACE)), base)
            gap = marker_spans[0]["bbox"][0] - previous["bbox"][2]
            if not -.75 <= gap <= base["size"]:
                raise _InvalidEvidence("detached_superscript")
            # Only a space is inserted. Source glyphs, IDs and geometry survive.
            if output and not output[-1].endswith(tuple(_SPACE)):
                output.append(" ")
            source_text = "".join(s["text"] for s in marker_spans)
            output.append(source_text)
            evidence.append({"footnote_id": marker_match[1] + "C", "source_text": source_text,
                             "page": page, "row": row, "spans": deepcopy(marker_spans),
                             "base_span": deepcopy(base)})
            index += len(marker_spans)
            continue
        output.append(span["text"])
        body_spans.append(span)
        index += 1
    return _canonical_words("".join(output)), evidence


def normalize_duty_typography(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize only internally consistent, already assembled cell evidence."""
    result = {"status": "unresolved", "normalized_text": None, "source_text": None,
              "footnote_evidence": [], "issues": [], "source_provenance_verified": False,
              "legal_interpretation_verified": False, "can_promote": False}
    try:
        if type(record) is not dict or record.get("cell_status") != "assembled" or record.get("percent_header_confirmed") is not True:
            raise _InvalidEvidence("complete_confirmed_cell_required")
        source = _text(record.get("duty_raw"))
        result["source_text"] = source
        rows = record.get("cell_rows")
        if type(rows) is not list or not 1 <= len(rows) <= MAX_CELL_ROWS:
            raise _InvalidEvidence("invalid_cell_rows")
        source_rows = []
        normalized_rows = []
        evidence = []
        count_words = count_spans = 0
        seen_spans: set[str] = set()
        seen_words: set[tuple[int, int]] = set()
        seen_lines: set[tuple[int, int, int]] = set()
        seen_rows: set[tuple[int, str]] = set()
        for cell in rows:
            if type(cell) is not dict or type(cell.get("page")) is not int or not 1 <= cell["page"] <= 1000 or not re.fullmatch(rf"p{cell['page']:04d}:r[0-9]{{5}}", str(cell.get("row", ""))):
                raise _InvalidEvidence("invalid_row_identity")
            row_identity = cell["page"], cell["row"]
            if row_identity in seen_rows:
                raise _InvalidEvidence("duplicate_row_identity")
            seen_rows.add(row_identity)
            words, spans = cell.get("duty_words"), cell.get("duty_spans")
            if type(words) is not list or type(spans) is not list:
                raise _InvalidEvidence("invalid_typography_arrays")
            count_words += len(words)
            count_spans += len(spans)
            if count_words > MAX_WORDS or count_spans > MAX_SPANS:
                raise _InvalidEvidence("typography_size_limit")
            grouped_words: dict[tuple[int, int], list[dict]] = {}
            grouped_spans: dict[tuple[int, int], list[dict]] = {}
            previous_word_line = previous_span_line = None
            for word in words:
                if type(word) is not dict or type(word.get("source_index")) is not int or word["source_index"] < 0:
                    raise _InvalidEvidence("invalid_word_identity")
                _text(word.get("text")); _box(word.get("bbox"))
                word_identity = cell["page"], word["source_index"]
                if word_identity in seen_words or any(c in _SPACE for c in word["text"]):
                    raise _InvalidEvidence("duplicate_or_invalid_word")
                seen_words.add(word_identity)
                line = _line_id(word)
                if line != previous_word_line and line in grouped_words:
                    raise _InvalidEvidence("interleaved_word_lines")
                grouped_words.setdefault(line, []).append(word)
                previous_word_line = line
            for span in spans:
                if type(span) is not dict or not re.fullmatch(rf"p{cell['page']:04d}:s[0-9]{{5,6}}", str(span.get("span", ""))):
                    raise _InvalidEvidence("invalid_span_identity")
                _text(span.get("text")); box = _box(span.get("bbox")); origin = _numbers(span.get("origin"), 2)
                if span["span"] in seen_spans:
                    raise _InvalidEvidence("duplicate_span_identity")
                seen_spans.add(span["span"])
                size = span.get("size")
                if type(size) not in (int, float) or not 0 < size <= 1000 or not math.isfinite(size):
                    raise _InvalidEvidence("invalid_font_size")
                if type(span.get("font")) is not str or not 1 <= len(span["font"]) <= 512 or type(span.get("flags")) is not int or not 0 <= span["flags"] <= 65535:
                    raise _InvalidEvidence("invalid_font_metadata")
                if _numbers(span.get("direction"), 2) != [1, 0] or abs(origin[0] - box[0]) > .75 or not box[1] <= origin[1] <= box[3]:
                    raise _InvalidEvidence("invalid_baseline_or_direction")
                line = _line_id(span)
                if line != previous_span_line and line in grouped_spans:
                    raise _InvalidEvidence("interleaved_span_lines")
                grouped_spans.setdefault(line, []).append(span)
                previous_span_line = line
            if set(grouped_words) != set(grouped_spans):
                raise _InvalidEvidence("word_span_line_mismatch")
            if list(grouped_words) != list(grouped_spans):
                raise _InvalidEvidence("word_span_line_order_mismatch")
            source_rows.append(" ".join(word["text"] for word in words))
            line_texts = []
            for line_id, line_words in grouped_words.items():
                line_identity = cell["page"], *line_id
                if line_identity in seen_lines:
                    raise _InvalidEvidence("line_repeated_across_physical_rows")
                seen_lines.add(line_identity)
                line_spans = grouped_spans[line_id]
                _validate_line(line_words, line_spans)
                normalized, line_evidence = _normalize_line(line_spans, cell["page"], cell["row"])
                line_texts.append(normalized)
                evidence.extend(line_evidence)
            normalized_rows.append(" ".join(line_texts))
        if " ".join(t for t in source_rows if t) != source:
            raise _InvalidEvidence("cell_word_text_mismatch")
        normalized = " ".join(t for t in normalized_rows if t)
        lexical = parse_duty_cell(normalized, percent_header_confirmed=True)
        # A remaining fused marker cannot be made legible by guessing a split.
        if len(_MARKER_ANY.findall(normalized)) > len(lexical["footnote_markers"]):
            raise _InvalidEvidence("unresolved_superscript_boundary")
        result.update(status="normalized", normalized_text=normalized, footnote_evidence=evidence)
    except (_InvalidEvidence, ValueError, TypeError, KeyError, AttributeError) as exc:
        result["issues"] = [str(exc) if isinstance(exc, _InvalidEvidence) else "invalid_evidence_structure"]
    return result
