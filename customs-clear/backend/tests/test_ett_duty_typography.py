"""Superscript spacing requires matching source words, spans and geometry."""
from copy import deepcopy
from pathlib import Path

import pytest

from app.services.ett_duty_cells import parse_duty_cell
from app.services.ett_duty_typography import normalize_duty_typography
from app.services.ett_table_assembly import assemble_pdf_table


def _span(text, left, right, *, size=12, baseline=102, number=1, line=0):
    return {"span": f"p0001:s{number:05d}", "text": text,
            "bbox": [left, baseline - size, right, baseline + size / 4],
            "origin": [left, baseline], "size": size, "font": "Synthetic Roman",
            "flags": 4, "direction": [1, 0], "block": 0, "line": line,
            "source_index": number - 1}


def _record(spans=None):
    if spans is None:
        spans = [_span("5", 100, 108), _span("63С)", 108, 130, size=8, baseline=96, number=2)]
    text = "".join(s["text"] for s in spans)
    box = [min(s["bbox"][0] for s in spans), min(s["bbox"][1] for s in spans),
           max(s["bbox"][2] for s in spans), max(s["bbox"][3] for s in spans)]
    return {"cell_status": "assembled", "percent_header_confirmed": True, "duty_raw": text,
            "cell_rows": [{"page": 1, "row": "p0001:r00001", "duty_words": [
                {"text": text, "bbox": box, "block": 0, "line": 0, "source_index": 0, "word": 0}],
                "duty_spans": spans}]}


def test_fused_rate_is_spaced_only_at_proven_size_and_baseline_change():
    source = _record()
    before = deepcopy(source)
    result = normalize_duty_typography(source)
    assert source == before
    assert result["status"] == "normalized"
    assert result["source_text"] == "563С)"
    assert result["normalized_text"] == "5 63С)"
    evidence = result["footnote_evidence"][0]
    assert evidence["footnote_id"] == "63C"
    assert evidence["spans"] == source["cell_rows"][0]["duty_spans"][1:]
    assert evidence["base_span"] == source["cell_rows"][0]["duty_spans"][0]
    parsed = parse_duty_cell(result["normalized_text"], percent_header_confirmed=True)
    assert parsed["duty"]["ad_valorem_percent"] == "5"
    assert parsed["footnote_ids"] == ["63C"]
    assert result["source_provenance_verified"] is False
    assert result["legal_interpretation_verified"] is False
    assert result["can_promote"] is False


@pytest.mark.parametrize("base,marker,expected", [("0", "9С)", "0 9С)"), ("10", "63C)", "10 63C)"), ("6,5", "63С)", "6,5 63С)")])
def test_exact_numeric_glyphs_determine_the_split_without_rate_or_note_allowlists(base, marker, expected):
    result = normalize_duty_typography(_record([_span(base, 100, 120), _span(marker, 120, 140, size=8, baseline=96, number=2)]))
    assert result["normalized_text"] == expected


def test_multispan_raised_marker_requires_the_entire_exact_number_and_suffix():
    result = normalize_duty_typography(_record([
        _span("5", 100, 108), _span("6", 108, 113, size=8, baseline=96, number=2),
        _span("3С)", 113, 128, size=8, baseline=96, number=3)]))
    assert result["normalized_text"] == "5 63С)"
    assert len(result["footnote_evidence"][0]["spans"]) == 2


def test_one_fused_span_has_no_evidence_of_a_digit_boundary():
    result = normalize_duty_typography(_record([_span("563С)", 100, 130)]))
    assert result["status"] == "unresolved"
    assert result["normalized_text"] is None
    assert result["issues"] == ["unresolved_superscript_boundary"]


@pytest.mark.parametrize("size,baseline,flags,font", [
    (12, 102, 5, "Synthetic Roman"),  # a superscript flag alone proves nothing
    (12, 96, 5, "Synthetic Roman"),   # raised without smaller type
    (8, 102, 5, "Synthetic Roman"),   # smaller without a raised baseline
    (8, 108, 5, "Synthetic Roman"),   # subscript
    (8, 96, 5, "Unrelated font"),
    (2, 96, 5, "Synthetic Roman"),
])
def test_size_position_and_font_are_required_together(size, baseline, flags, font):
    marker = _span("63С)", 108, 130, size=size, baseline=baseline, number=2)
    marker.update(flags=flags, font=font)
    result = normalize_duty_typography(_record([_span("5", 100, 108), marker]))
    assert result["status"] == "unresolved"


def test_same_source_text_can_have_different_proven_splits_but_no_legal_approval():
    first = normalize_duty_typography(_record())
    second = normalize_duty_typography(_record([_span("56", 100, 116), _span("3С)", 116, 130, size=8, baseline=96, number=2)]))
    assert first["source_text"] == second["source_text"] == "563С)"
    assert first["normalized_text"] == "5 63С)"
    assert second["normalized_text"] == "56 3С)"
    assert second["source_provenance_verified"] is False


def test_unit_exponent_and_note_number_must_be_separate_source_spans():
    source = _record([_span("м", 100, 110), _span("2", 110, 115, size=8, baseline=96, number=2),
                      _span("63С)", 115, 135, size=8, baseline=96, number=3)])
    result = normalize_duty_typography(source)
    assert result["normalized_text"] == "м2 63С)"
    assert [e["footnote_id"] for e in result["footnote_evidence"]] == ["63C"]
    ambiguous = normalize_duty_typography(_record([_span("м", 100, 110), _span("263С)", 110, 135, size=8, baseline=96, number=2)]))
    assert ambiguous["status"] == "unresolved"


def test_ordinary_unit_superscript_never_becomes_a_footnote():
    result = normalize_duty_typography(_record([_span("м", 100, 110), _span("2", 110, 115, size=8, baseline=96, number=2)]))
    assert result["normalized_text"] == "м2"
    assert result["footnote_evidence"] == []


@pytest.mark.parametrize("mutation", [
    "cell_status", "header", "raw_text", "word_text", "span_text", "word_geometry",
    "span_geometry", "span_origin", "span_order", "span_direction", "span_page",
    "span_line", "missing_span", "extra_span", "duplicate_span", "duplicate_word",
    "duplicate_row", "empty_rows", "bad_size", "nan_coordinate", "infinite_origin",
    "row_page", "row_locator", "bad_words", "missing_spans", "extra_blank_span_bad_line",
])
def test_inconsistent_or_malformed_evidence_is_not_normalized(mutation):
    record = _record()
    cell = record["cell_rows"][0]
    span = cell["duty_spans"][1]
    if mutation == "cell_status": record["cell_status"] = "unresolved"
    elif mutation == "header": record["percent_header_confirmed"] = 1
    elif mutation == "raw_text": record["duty_raw"] = "063С)"
    elif mutation == "word_text": cell["duty_words"][0]["text"] = "063С)"
    elif mutation == "span_text": span["text"] = "64С)"
    elif mutation == "word_geometry": cell["duty_words"][0]["bbox"][0] -= 20
    elif mutation == "span_geometry": span["bbox"][2] += 20
    elif mutation == "span_origin": span["origin"][0] += 20
    elif mutation == "span_order": cell["duty_spans"].reverse()
    elif mutation == "span_direction": span["direction"] = [0, 1]
    elif mutation == "span_page": span["span"] = "p0002:s00002"
    elif mutation == "span_line": span["line"] = 1
    elif mutation == "missing_span": cell["duty_spans"].pop()
    elif mutation == "extra_span": cell["duty_spans"].append(_span("4", 130, 135, number=3))
    elif mutation == "duplicate_span": cell["duty_spans"].append(deepcopy(span))
    elif mutation == "duplicate_word": cell["duty_words"].append(deepcopy(cell["duty_words"][0]))
    elif mutation == "duplicate_row": record["cell_rows"].append(deepcopy(cell))
    elif mutation == "empty_rows": record["cell_rows"] = []
    elif mutation == "bad_size": span["size"] = True
    elif mutation == "nan_coordinate": span["bbox"][0] = float("nan")
    elif mutation == "infinite_origin": span["origin"][0] = float("inf")
    elif mutation == "row_page": cell["page"] = True
    elif mutation == "row_locator": cell["row"] = "p0002:r00001"
    elif mutation == "bad_words": cell["duty_words"] = "563С)"
    elif mutation == "missing_spans": del cell["duty_spans"]
    elif mutation == "extra_blank_span_bad_line": cell["duty_spans"].append(_span(" ", 130, 134, number=3, line=1))
    result = normalize_duty_typography(record)
    assert result["status"] == "unresolved"
    assert result["normalized_text"] is None
    assert result["issues"]


@pytest.mark.parametrize("value", [None, True, [], "assembled", {}])
def test_invalid_public_arguments_return_bounded_unresolved_status(value):
    result = normalize_duty_typography(value)
    assert result["status"] == "unresolved"
    assert result["can_promote"] is False


def test_resource_limits_are_checked_before_iterating_large_arrays():
    record = _record()
    record["cell_rows"][0]["duty_spans"] *= 2049
    assert normalize_duty_typography(record)["issues"] == ["typography_size_limit"]
    record = _record()
    record["cell_rows"] *= 129
    assert normalize_duty_typography(record)["issues"] == ["invalid_cell_rows"]


@pytest.mark.parametrize("field", ["bbox", "origin", "size", "flags"])
def test_huge_integer_metadata_fails_without_float_conversion_overflow(field):
    record = _record()
    span = record["cell_rows"][0]["duty_spans"][0]
    if field in {"bbox", "origin"}:
        span[field][0] = 10 ** 1000
    else:
        span[field] = 10 ** 1000
    assert normalize_duty_typography(record)["status"] == "unresolved"


def test_returned_marker_evidence_cannot_mutate_the_source_arrays():
    record = _record()
    before = deepcopy(record)
    result = normalize_duty_typography(record)
    result["footnote_evidence"][0]["spans"][0]["bbox"][0] = -999
    result["footnote_evidence"][0]["base_span"]["origin"][1] = -999
    assert record == before


@pytest.mark.parametrize("text", ["5\u200b", "\u202e5", "5\ud800", "5\u2009"])
def test_invisible_or_unencodable_glyphs_cannot_be_normalized_away(text):
    assert normalize_duty_typography(_record([_span(text, 100, 130)]))["status"] == "unresolved"


@pytest.fixture(scope="module")
def historical_chapters():
    corpus = Path(__file__).resolve().parents[3] / "backend/app/services/source_sync/data"
    result = {}
    for chapter in ("01", "30", "57", "59"):
        paths = list(corpus.glob(f"ru.{chapter}_*.pdf"))
        assert len(paths) == 1
        result[chapter] = assemble_pdf_table(paths[0].read_bytes(), artifact_id=f"chapter-{chapter}", chapter=chapter)
    return result


@pytest.mark.parametrize("chapter,code,raw,normalized", [
    ("01", "0106410001", "563С)", "5 63С)"),
    ("30", "3001902000", "6,563С)", "6,5 63С)"),
    ("57", "5701101000", "0,38 евро за 1 м2", "0,38 евро за 1 м2"),
    ("59", "5903101000", "563С)", "5 63С)"),
])
def test_actual_historical_pdf_glyphs_prove_the_boundary(chapter, code, raw, normalized, historical_chapters):
    record = next(r for r in historical_chapters[chapter]["records"] if r["code"] == code)
    assert record["duty_raw"] == raw
    result = normalize_duty_typography(record)
    assert result["status"] == "normalized"
    assert result["normalized_text"] == normalized
    assert parse_duty_cell(normalized, percent_header_confirmed=True)["status"] == "parsed"
    assert result["can_promote"] is False


def test_all_four_historical_chapters_pass_internal_typography_consistency(historical_chapters):
    # Real layout regression, not a claim about current rates or legal validity.
    for report in historical_chapters.values():
        for record in report["records"]:
            if record["cell_status"] == "assembled":
                normalized = normalize_duty_typography(record)
                assert normalized["status"] == "normalized", (record["code"], normalized["issues"])
