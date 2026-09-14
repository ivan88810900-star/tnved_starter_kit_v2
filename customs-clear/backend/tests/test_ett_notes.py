"""No effective dates are invented from tariff-note syntax or act citations."""
import hashlib
from pathlib import Path

import pymupdf
import pytest

from app.services import ett_notes as notes
from app.services.ett_pdf_evidence import extract_pdf_evidence


CORPUS = Path(__file__).resolve().parents[3] / "data/raw/tariff_cet/2025-01-01"
HISTORICAL_SHA = "bd4f4b8bab21d75e8fd69d832f84e9e53141639675d946c8a3bbfd47179929ac"


def _pdf(pages):
    with pymupdf.open() as document:
        for lines in pages:
            page = document.new_page(width=1500, height=600)
            # MuPDF's bundled font makes the synthetic Cyrillic fixtures portable
            # without downloading fonts or relying on system font installations.
            page.insert_font(fontname="fixture", fontbuffer=pymupdf.Font("cjk").buffer)
            for index, line in enumerate(lines):
                page.insert_text((60, 70 + index * 20), line, fontname="fixture", fontsize=10)
        return document.tobytes()


def _extract(*lines):
    return notes.extract_tariff_notes(_pdf([lines]), artifact_id="synthetic-notes")


def _one(*lines):
    return _extract(*lines)["notes"][0]


@pytest.fixture(scope="module")
def historical():
    body = (CORPUS / "Примечания%20к%20ЕТТ_21.09.2025.pdf").read_bytes()
    assert hashlib.sha256(body).hexdigest() == HISTORICAL_SHA
    return body, notes.extract_tariff_notes(body, artifact_id="historical-notes-2025")


def test_all_historical_note_ids_and_every_physical_row_are_preserved(historical):
    body, report = historical
    assert report["artifact_sha256"] == HISTORICAL_SHA
    assert report["note_count"] == report["unique_note_count"] == 105
    assert report["page_count"] == 7
    assert report["observed_note_ids"] == [f"{i}C" for i in range(1, 106)]
    assert report["notes"][70]["source_label"] == "71C)"
    assert report["notes"][69]["source_label"] == "70С)"
    assert report["duplicate_note_ids"] == report["numbering_gaps"] == []
    assert report["all_source_rows_accounted"] is True
    physical = extract_pdf_evidence(body, artifact_id="historical-notes-2025")
    actual = {(page["page"], row["row"]): row for page in physical["pages"] for row in page["rows"]}
    retained = [row for note in report["notes"] for row in note["source_rows"]]
    retained += report["unassigned_rows"] + [item["source_row"] for item in report["decoration_rows"]]
    assert len(retained) == len(actual) == report["source_row_count"]
    assert len({(row["page"], row["row"]) for row in retained}) == len(actual)
    for row in retained:
        assert row["artifact_sha256"] == HISTORICAL_SHA
        assert row["raw_text"] == actual[(row["page"], row["row"])]["raw_text"]
        assert row["raw_text_sha256"] == hashlib.sha256(row["raw_text"].encode()).hexdigest()
    assert report["pdf_parser"] == physical["parser"]
    assert report["parser"]["sha256"] == hashlib.sha256(Path(notes.__file__).read_bytes()).hexdigest()


def test_note_quotes_are_source_bound_without_claiming_legal_readiness(historical):
    _, report = historical
    note = report["notes"][1]
    clause = note["temporal_candidates"][0]
    assert clause["start_date_literal"] == "2022-01-01"
    assert clause["end_date_literal"] == "2023-04-30"
    assert clause["end_date_exclusive_arithmetic"] == "2023-05-01"
    assert clause["quote"] == "с 01.01.2022 по 30.04.2023 включительно"
    assert clause["source_rows"][0]["row"] == "p0001:r00006"
    assert clause["source_rows"][0]["artifact_sha256"] == HISTORICAL_SHA
    for item in [report, note, clause]:
        assert item["status"] == "review_required"
        assert item["legal_dates_verified"] is False
    assert note["can_compile_rate_rule"] is False
    assert report["legal_inventory_complete"] is report["can_promote"] is False
    assert report["legal_rates_resolved"] == 0


def test_act_date_is_not_used_as_entry_into_force_and_repeal_not_current_validity(historical):
    _, report = historical
    start = report["notes"][37]
    assert "act_entry_into_force_unresolved" in start["issues"]
    assert all(candidate["start_date_literal"] is None for candidate in start["temporal_candidates"])
    assert start["temporal_candidates"][0]["end_date_literal"] == "2023-12-31"
    assert start["date_mentions"][0]["date_literal"] == "2021-10-29"
    assert start["date_mentions"][0]["context"] == "unassigned_date_mention"
    repeal = report["notes"][0]
    assert repeal["temporal_candidates"] == []
    assert repeal["date_mentions"][0]["date_literal"] == "2022-04-19"
    assert "repeal_effective_date_unresolved" in repeal["issues"]
    assert not {"valid_from", "valid_to", "active", "duty", "vat"}.intersection(repeal)


def test_multiple_windows_and_country_context_remain_separate(historical):
    _, report = historical
    note64 = report["notes"][63]
    first, second = note64["temporal_candidates"]
    assert first["kind"] == "absolute_window"
    assert first["end_date_exclusive_arithmetic"] == "2022-10-01"
    assert second["kind"] == "absolute_start"
    assert second["start_date_literal"] == "2022-10-01"
    assert second["end_date_literal"] is None
    country = next(signal for signal in note64["context_signals"] if signal["kind"] == "country_mention")
    assert country["country"] == "RU" and country["scope_verified"] is False
    assert "multiple_temporal_clauses_preserved" in note64["issues"]
    assert "country_scope_unresolved" in note64["issues"]
    assert "country" not in first and "country" not in second
    note66 = report["notes"][65]
    assert [candidate["kind"] for candidate in note66["temporal_candidates"]] == ["absolute_window"] * 2
    assert [candidate["end_date_exclusive_arithmetic"] for candidate in note66["temporal_candidates"]] == ["2022-10-01", "2023-03-01"]


def test_real_spelled_month_and_leap_arithmetic(historical):
    _, report = historical
    note58 = report["notes"][57]
    assert note58["temporal_candidates"][0]["end_date_literal"] == "2025-04-30"
    assert "30 апреля 2025 г." in note58["temporal_candidates"][0]["quote"]
    assert report["notes"][71]["temporal_candidates"][0]["end_date_exclusive_arithmetic"] == "2024-03-01"


def test_older_historical_notes_do_not_acquire_newer_dates():
    body = (CORPUS / "Примечания%20к%20ЕТТ_08.02.2024.pdf").read_bytes()
    report = notes.extract_tariff_notes(body, artifact_id="historical-notes-2024")
    assert report["note_count"] == 86
    assert report["observed_note_ids"] == [f"{i}C" for i in range(1, 87)]
    assert report["artifact_sha256"] != HISTORICAL_SHA
    assert report["legal_dates_verified"] is False


def test_source_continuation_across_pages_preserves_quotes_and_boundaries():
    body = _pdf([["1C) Ставка применяется с 01.01.2026"], ["по 31.12.2026 включительно.", "3C) Другой текст."]])
    report = notes.extract_tariff_notes(body, artifact_id="cross-page")
    note = report["notes"][0]
    assert len(note["source_rows"]) == 2
    assert "\nпо" in note["raw_text"]
    candidate = note["temporal_candidates"][0]
    assert [row["page"] for row in candidate["source_rows"]] == [1, 2]
    assert candidate["end_date_exclusive_arithmetic"] == "2027-01-01"
    span = candidate["logical_text_span"]
    assert note["logical_text"][span["start"]:span["end"]] == candidate["quote"]


def test_noncontiguous_current_style_note_ids_do_not_imply_missing_documents():
    report = _extract(*(f"{i}C) Неинтерпретированный текст." for i in (119, 123, 124, 126, 128, 129)))
    assert report["observed_note_ids"] == ["119C", "123C", "124C", "126C", "128C", "129C"]
    assert report["numbering_gaps_imply_missing_source"] is False
    assert report["numbering_gaps"] == [{"after": "119C", "before": "123C"}, {"after": "124C", "before": "126C"}, {"after": "126C", "before": "128C"}]
    assert report["issues"] == []


def test_duplicate_aliases_and_nonascending_order_remain_visible():
    report = _extract("3С) Первая строка.", "3C) Другая строка.", "2C) Более ранний номер.")
    assert report["note_count"] == 3
    assert report["duplicate_note_ids"] == ["3C"]
    assert "note_number_order_unresolved" in report["issues"]
    assert all("duplicate_note_id" in note["issues"] for note in report["notes"][:2])
    assert report["notes"][0]["raw_text"] != report["notes"][1]["raw_text"]


@pytest.mark.parametrize(("clause", "start", "end"), [
    ("с 01.01.2026 по 31.12.2026 включительно", "2026-01-01", "2027-01-01"),
    ("с 1 января 2026 г. по 31 декабря 2026 г. включительно", "2026-01-01", "2027-01-01"),
    ("с 29 февраля 2028 года по 29 февраля 2028 года включительно", "2028-02-29", "2028-03-01"),
    ("с 01.07.2026 по 30 июня 2027 г. включительно", "2026-07-01", "2027-07-01"),
    ("С 1 МАРТА 2026 Г. ПО 30 АПРЕЛЯ 2026 Г. ВКЛЮЧИТЕЛЬНО", "2026-03-01", "2026-05-01"),
])
def test_absolute_calendar_syntax_only(clause, start, end):
    candidate = _one("1C) Применяется " + clause + ".")["temporal_candidates"][0]
    assert candidate["start_date_literal"] == start
    assert candidate["end_date_exclusive_arithmetic"] == end
    assert candidate["legal_dates_verified"] is False


@pytest.mark.parametrize(("clause", "issue"), [
    ("с 29.02.2027 по 31.12.2027 включительно", "invalid_start_calendar_date"),
    ("с 01.01.2026 по 31.04.2026 включительно", "invalid_end_calendar_date"),
    ("с 01.01.2027 по 31.12.2026 включительно", "reversed_date_window"),
    ("с 01.01.2026 по 31.12.2026", "end_inclusiveness_not_explicit"),
    ("с 01.01.9999 по 31.12.9999 включительно", "exclusive_end_out_of_calendar_range"),
    ("с 00.01.2026 по 31.12.2026 включительно", "invalid_start_calendar_date"),
])
def test_invalid_or_ambiguous_intervals_never_produce_converted_window(clause, issue):
    candidate = _one("1C) Применяется " + clause + ".")["temporal_candidates"][0]
    assert issue in candidate["issues"]
    assert candidate["end_date_exclusive_arithmetic"] is None


@pytest.mark.parametrize("clause", [
    "с момента официального опубликования", "в летний период 2026 года",
    "с 1.1.2026 до 31.12.2026", "с 01.01.20260", "с 01.01.2026x", "с 01.01.2026.01",
    "с 01 сентября по 31 декабря", "после принятия нового решения",
])
def test_unrecognized_clauses_remain_raw_without_inventing_boundaries(clause):
    note = _one("1C) Применяется " + clause + ".")
    assert clause in note["raw_text"]
    assert note["temporal_candidates"] == []
    assert "legal_applicability_unresolved" in note["issues"]


def test_unrecognized_note_marker_is_retained_and_reported():
    report = _extract("Заголовок документа", "1C) Первая строка", "2B) Неизвестный маркер", "3C) Третий номер")
    assert "unsupported_note_marker_retained" in report["issues"]
    assert "2B)" in report["notes"][0]["raw_text"]
    assert report["unassigned_rows"][0]["raw_text"] == "Заголовок документа"
    assert report["all_source_rows_accounted"] is True


def test_blank_document_cannot_establish_inventory():
    report = notes.extract_tariff_notes(_pdf([[]]), artifact_id="blank")
    assert report["note_count"] == 0
    assert "page_without_extractable_text" in report["issues"]
    assert "no_tariff_note_headers_identified" in report["issues"]
    assert report["legal_inventory_complete"] is False


@pytest.mark.parametrize("limit", ["MAX_NOTES", "MAX_NOTE_TEXT", "MAX_DATE_TOKENS", "MAX_REPORT_BYTES"])
def test_resource_limits_fail_instead_of_silently_truncating(monkeypatch, limit):
    monkeypatch.setattr(notes, limit, 0)
    with pytest.raises(notes.TariffNotesError, match="limit"):
        _extract("1C) Применяется с 01.01.2026 по 31.12.2026 включительно.")


def test_caller_text_is_not_accepted_as_pdf_evidence():
    with pytest.raises(notes.PDFEvidenceError):
        notes.extract_tariff_notes(b"1C) Primeniaetsia s 01.01.2026", artifact_id="not-pdf")
