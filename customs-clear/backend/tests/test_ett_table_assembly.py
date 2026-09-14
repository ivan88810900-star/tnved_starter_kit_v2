"""Real PDF regressions for full cells, hierarchy and fail-closed boundaries."""
from functools import lru_cache
import hashlib
from pathlib import Path
import re

import pymupdf
import pytest

from app.services import ett_table_assembly as table


CORPUS = Path(__file__).resolve().parents[3] / "backend/app/services/source_sync/data"


@lru_cache(maxsize=16)
def _body(chapter):
    paths = list(CORPUS.glob(f"ru.{chapter}_*.pdf"))
    assert len(paths) == 1
    return paths[0].read_bytes()


@lru_cache(maxsize=16)
def _chapter(chapter):
    return table.assemble_pdf_table(_body(chapter), artifact_id=f"chapter-{chapter}", chapter=chapter)


def _record(report, code):
    return next(row for row in report["records"] if row["code"] == code)


def test_actual_source_bytes_and_parser_engine_remain_bound():
    report = _chapter("01")
    assert report["artifact_sha256"] == hashlib.sha256(_body("01")).hexdigest()
    assert report["assembler"]["sha256"] == hashlib.sha256(Path(table.__file__).read_bytes()).hexdigest()
    assert report["extraction_parser"]["engine"] == "pymupdf"
    assert report["record_count"] == report["unique_code_count"] == 86
    assert report["assembled_cell_count"] == report["resolved_description_count"] == 86
    assert report["legal_rates_resolved"] == 0
    assert report["can_promote"] is False
    assert report["current_edition_verified"] is False
    assert not {"valid_from", "valid_to", "duty", "vat", "approved"}.intersection(report)
    for row in report["records"]:
        assert row["percent_header_confirmed"] is True
        for source in row["source_rows"]:
            assert source["raw_text_sha256"] == hashlib.sha256(source["raw_text"].encode()).hexdigest()


def test_multiline_description_and_complete_heading_context():
    row = _record(_chapter("01"), "0101210000")
    assert row["leaf_description"] == "чистопородные племенные животные"
    assert row["full_description"] == "Лошади, ослы, мулы и лошаки живые / лошади / чистопородные племенные животные"
    assert row["unit_raw"] == "шт"
    assert row["duty_raw"] == "0"
    assert len(row["source_rows"]) == 2
    assert row["heading_contexts"][0]["source_rows"][1]["raw_text"] == "живые:"


def test_eight_digit_headings_are_never_misread_as_description_fragments():
    row = _record(_chapter("01"), "0106110010")
    assert "00 –" not in row["full_description"]
    assert any(h["code"] == "01061100" and h["depth"] == 2 for h in row["heading_contexts"])
    assert "приматы" in row["full_description"]


def test_superscript_typography_is_preserved_without_changing_raw_rate_text():
    row = _record(_chapter("01"), "0106410001")
    assert row["duty_raw"] == "563С)"
    spans = [span for cell in row["cell_rows"] for span in cell["duty_spans"]]
    base = next(s for s in spans if s["text"] == "5")
    marker = next(s for s in spans if s["text"] == "63С)")
    assert marker["size"] < base["size"]
    assert marker["origin"][1] < base["origin"][1]
    assert marker["span"].startswith("p0006:")


def test_multiline_specific_component_is_not_dropped():
    row = _record(_chapter("04"), "0406900100")
    assert row["duty_raw"].startswith("14, но не менее ")
    assert "евро за 1 кг" in row["duty_raw"]
    assert len([cell for cell in row["cell_rows"] if cell["duty_words"]]) > 1


def test_continuation_across_confirmed_page_headers_retains_both_pages():
    candidates = [r for r in _chapter("84")["records"] if len(r["header_pages"]) > 1]
    assert candidates
    for row in candidates:
        assert len({source["page"] for source in row["source_rows"]}) > 1
        assert row["cell_status"] == "assembled"
        assert row["full_description"]


def test_padded_legacy_heading_is_not_inserted_to_match_old_bundle_count():
    report = _chapter("04")
    assert any(row["code"] == "040690" for row in report["headings"])
    assert "0406900000" not in {row["code"] for row in report["records"]}
    assert "0406900100" in {row["code"] for row in report["records"]}


def test_bracketed_reserved_headings_do_not_end_the_following_table():
    report = _chapter("05")
    assert any(i["reason"] == "reserved_heading" for i in report["issues"])
    assert _record(report, "0504000000")["cell_status"] == "assembled"
    assert _record(report, "0510000000")["cell_status"] == "assembled"
    assert "0503000000" not in {row["code"] for row in report["records"]}


def test_note_mentions_and_cross_chapter_mentions_are_separate_from_table():
    report = _chapter("02")
    assert any(x["code"] == "0210111100" and x["page"] == 3 for x in report["excluded_candidates"])
    assert report["duplicate_codes"] == []
    assert all(row["code"].startswith("02") for row in report["records"])


def test_repeated_body_word_does_not_destroy_real_header_evidence():
    report = _chapter("85")
    assert any(h["page"] == 45 for h in report["headers"])
    assert _record(report, "8524110011")["cell_status"] == "assembled"


def test_indented_composition_bullets_stay_inside_product_description():
    row = _record(_chapter("29"), "2921511100")
    assert "- 1 мас.% или менее воды" in row["leaf_description"]
    assert "- 200 мг/кг или менее о-фенилендиамина" in row["leaf_description"]
    assert "- 450 мг/кг или менее п-фенилендиамина" in row["leaf_description"]
    following = _record(_chapter("29"), "2921511900")
    assert "450 мг" not in following["full_description"]


def test_roman_subchapter_titles_never_append_to_preceding_product():
    report = _chapter("29")
    sections = [h for h in report["headings"] if h["kind"] == "subchapter"]
    assert len(sections) > 1
    assert any("I. УГЛЕВОДОРОДЫ" in h["leaf_description"] for h in sections)
    assert not any(re.search(r"\b[IVX]+\. [А-ЯЁ]", r["leaf_description"]) for r in report["records"])
    assert _record(report, "2921511100")["subchapter_context"]["description"]


def test_title_only_opening_page_uses_agreeing_source_anchor_with_locator():
    report = _chapter("63")
    first = report["headers"][0]
    assert first["description_anchor_source"]["page"] > 1
    assert any(h["kind"] == "subchapter" and "ГОТОВЫЕ ТЕКСТИЛЬНЫЕ" in h["leaf_description"] for h in report["headings"])
    assert not any(i["reason"] == "orphan_table_continuation" for i in report["issues"])


def test_long_source_word_is_retained_in_description_padding():
    row = _record(_chapter("39"), "3909501000")
    assert "метилендициклогексилдиизоцианата" in row["leaf_description"]
    assert row["cell_status"] == "assembled"
    assert row["duty_raw"] == "6,5"


def test_wide_unit_does_not_leak_into_description_or_duty():
    row = _record(_chapter("27"), "2710124110")
    assert row["unit_raw"] == "1000 л"
    assert "1000 л" not in row["leaf_description"]
    assert row["duty_raw"] == "5114С)"


def test_no_header_cannot_create_rate_cells():
    with pymupdf.open() as document:
        document.new_page().insert_text((99, 100), "0101 21 000 0 Example power 735 kW")
        body = document.tobytes()
    report = table.assemble_pdf_table(body, artifact_id="synthetic", chapter="01")
    assert report["records"] == []
    assert report["excluded_candidates"][0]["reason"] == "outside_confirmed_table"
    assert report["source_pages_without_headers"] == [1]
    assert report["source_pages_without_text"] == []


@pytest.mark.parametrize("image_only", [False, True])
def test_blank_or_image_only_pdf_remains_visible_in_coverage_diagnostics(image_only):
    with pymupdf.open() as document:
        page = document.new_page()
        if image_only:
            pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 2, 2), False)
            pixmap.clear_with(255)
            page.insert_image(page.rect, stream=pixmap.tobytes("png"))
        body = document.tobytes()
    report = table.assemble_pdf_table(body, artifact_id="image-only" if image_only else "blank", chapter="01")
    assert report["record_count"] == 0
    assert report["source_pages_without_headers"] == report["source_pages_without_text"] == [1]
    assert report["can_promote"] is False


def test_headerless_note_pages_are_not_misreported_as_missing_text():
    report = _chapter("02")
    assert 3 in report["source_pages_without_headers"]
    assert report["source_pages_without_text"] == []


def test_missing_initial_page_does_not_invent_hierarchy_or_continuation():
    with pymupdf.open(stream=_body("04"), filetype="pdf") as original, pymupdf.open() as partial:
        partial.insert_pdf(original, from_page=15, to_page=15)
        body = partial.tobytes()
    report = table.assemble_pdf_table(body, artifact_id="partial", chapter="04")
    assert report["records"]
    assert any("hierarchy_unresolved" in row["issues"] for row in report["records"])
    assert report["resolved_description_count"] < report["record_count"]


def test_duplicate_source_table_occurrences_are_not_silently_deduplicated():
    with pymupdf.open(stream=_body("01"), filetype="pdf") as original, pymupdf.open() as duplicated:
        for _ in range(2):
            duplicated.insert_pdf(original, from_page=0, to_page=0)
        body = duplicated.tobytes()
    report = table.assemble_pdf_table(body, artifact_id="duplicate", chapter="01")
    rows = [r for r in report["records"] if r["code"] == "0101210000"]
    assert len(rows) == 2
    assert all(r["cell_status"] == "unresolved" and "duplicate_table_code" in r["issues"] for r in rows)


def test_empty_rate_after_source_redaction_stays_unresolved():
    with pymupdf.open(stream=_body("01"), filetype="pdf") as document:
        page = document[0]
        page.add_redact_annot(pymupdf.Rect(480, 574, 515, 590))
        page.apply_redactions()
        body = document.tobytes()
    row = _record(table.assemble_pdf_table(body, artifact_id="redacted", chapter="01"), "0101210000")
    assert row["duty_raw"] is None
    assert row["cell_status"] == "unresolved"
    assert "duty_cell_empty" in row["issues"]


def test_crossing_unit_rate_boundary_is_not_guessed():
    with pymupdf.open(stream=_body("01"), filetype="pdf") as document:
        document[0].insert_text((434, 587), "CROSS", fontsize=13)
        body = document.tobytes()
    row = _record(table.assemble_pdf_table(body, artifact_id="ambiguous", chapter="01"), "0101210000")
    assert "word_crosses_cell_boundary" in row["issues"]
    assert row["cell_status"] == "unresolved"


@pytest.mark.parametrize("chapter", [None, "1", "77", "98", 1, True])
def test_explicit_real_chapter_required(chapter):
    with pytest.raises(table.PDFEvidenceError, match="explicit chapter"):
        table.assemble_pdf_table(b"irrelevant", artifact_id="fixture", chapter=chapter)


def test_report_object_cannot_be_passed_as_verified_input():
    with pytest.raises(table.PDFEvidenceError, match="size"):
        table.assemble_pdf_table(_chapter("01"), artifact_id="fixture", chapter="01")


def test_assembly_output_is_bounded(monkeypatch):
    monkeypatch.setattr(table, "MAX_ASSEMBLY_BYTES", 20)
    with pytest.raises(table.PDFEvidenceError, match="output limit"):
        table.assemble_pdf_table(_body("01"), artifact_id="fixture", chapter="01")
