"""Labelled metadata evidence never borrows dates from unrelated page content."""
import hashlib
from html import escape

import pytest

from app.services.ett_legal_metadata import ETTLegalMetadataError, parse_legal_metadata
from tests.test_ett_legal_portal_live import CASES, FIXTURES

URL = "https://docs.eaeunion.org/documents/399/6620/"


def row(label, value):
    return f'<div class="DocDetail_Row"><div class="DocDetail_Col _title">{label}</div><div class="DocDetail_Col _value">{value}</div></div>'


def page(rows=None, *, extra="", container_extra=""):
    if rows is None:
        rows = row("Короткий заголовок документа", "Решение Коллегии ЕЭК № 66") + row("Номер документа", "66")
        rows += row("Дата принятия документа", "19.04.2022") + row("Дата опубликования", "28.04.2022")
    return f'''<!doctype html><html><head><title>Решение от 01.01.2000</title></head><body>
<div class="Header_Bottom__Title">Правовой портал</div><div class="Header_Bottom__Date">Сегодня 08.09.2026</div>
<div class="Box_Title">Информация о документе</div><div class="DocDetail_Info">{rows}</div>{container_extra}{extra}</body></html>'''.encode()


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["stem"])
def test_original_portal_field_values_bound_to_original_sha_and_dom_positions(case):
    raw = (FIXTURES / (case["stem"] + ".html")).read_bytes()
    result = parse_legal_metadata(raw, case["url"])
    assert result["source_sha256"] == case["sha256"]
    assert result["size_bytes"] == case["size_bytes"]
    assert result["container_count"] == 1
    assert result["fields"]["publication_date"]["observed_text"] == "28.04.2022"
    assert result["fields"]["publication_date"]["observed_iso_date"] == "2022-04-28"
    assert result["fields"]["entry_into_force_date_metadata"]["observed_iso_date"] == "2022-05-08"
    assert result["fields"]["short_title"]["observed_text"] == case["identity"]
    assert result["official_publication_event_verified"] is result["effective_dates_verified"] is False
    for observation in result["rows"]:
        for evidence in [observation["row_evidence"], *observation["labels"], *observation["values"]]:
            assert hashlib.sha256(evidence["raw_text"].encode()).hexdigest() == evidence["raw_text_sha256"]
            assert ":line:" in evidence["locator"] and ":column:" in evidence["locator"]
            assert evidence["text"] == " ".join(evidence["raw_text"].split())
    assert "2026-09-08" not in str(result["fields"])


def test_actual_retroactive_comment_is_retained_without_computing_a_legal_interval():
    case = CASES[0]
    result = parse_legal_metadata((FIXTURES / (case["stem"] + ".html")).read_bytes(), case["url"])
    comment = result["fields"]["comment"]["observed_text"]
    assert "10 календарных дней" in comment and "28 марта 2022 г." in comment
    assert result["fields"]["comment"]["observed_iso_date"] is None
    assert result["effective_dates_verified"] is False


def test_dates_never_fallback_to_title_siteclock_links_comments_or_unknown_update_label():
    rows = row("Дата принятия документа", "19.04.2022")
    rows += row("Дата обновления", "08.09.2026") + row("Комментарий", "Опубликовано 28.04.2022")
    raw = page(rows, extra='<a href="/28.04.2022.pdf">Дата опубликования 28.04.2022</a>')
    result = parse_legal_metadata(raw, URL)
    assert result["fields"]["publication_date"]["status"] == "missing"
    assert result["fields"]["publication_date"]["observed_iso_date"] is None
    assert result["unknown_row_indices"] == [2]
    assert result["rows"][1]["values"][0]["text"] == "08.09.2026"


@pytest.mark.parametrize("value", ["", "31.02.2022", "28 апреля 2022", "28.04.2022 / 29.04.2022", "2022-04-28", "28.04.0000"])
def test_empty_invalid_or_compound_date_is_retained_without_guessing(value):
    result = parse_legal_metadata(page(row("Дата опубликования", escape(value))), URL)
    field = result["fields"]["publication_date"]
    assert field["status"] == ("unresolved_date_literal" if value else "empty")
    assert field["observed_iso_date"] is None
    assert field["observed_text"] == value


@pytest.mark.parametrize("second", ["28.04.2022", "29.04.2022"])
def test_even_identical_duplicate_metadata_labels_remain_ambiguous(second):
    result = parse_legal_metadata(page(row("Дата опубликования", "28.04.2022") + row("Дата опубликования", second)), URL)
    field = result["fields"]["publication_date"]
    assert field["status"] == "ambiguous"
    assert field["observed_iso_date"] is field["observed_text"] is None
    assert field["observation_rows"] == [1, 2]


def test_multiple_value_cells_and_nested_rows_preserve_evidence_without_assignment():
    raw = page(row("Дата опубликования", "28.04.2022").replace('</div></div>', '</div><div class="DocDetail_Col _value">29.04.2022</div></div>'))
    result = parse_legal_metadata(raw, URL)
    assert result["fields"]["publication_date"]["status"] == "ambiguous"
    assert len(result["rows"][0]["values"]) == 2
    nested = row("Комментарий", row("Дата опубликования", "28.04.2022"))
    result = parse_legal_metadata(page(nested), URL)
    assert result["fields"]["publication_date"]["status"] == "ambiguous"


def test_multiple_metadata_containers_and_missing_container_cannot_choose_a_value():
    result = parse_legal_metadata(page(container_extra='<div class="DocDetail_Info">' + row("Комментарий", "Другой документ") + '</div>'), URL)
    assert result["fields"]["publication_date"]["status"] == "ambiguous"
    missing = page().replace(b'class="DocDetail_Info"', b'class="Absent"')
    result = parse_legal_metadata(missing, URL)
    assert result["fields"]["publication_date"]["status"] == "missing"
    assert "metadata_container_missing" in result["issues"]


def test_hidden_values_cannot_contaminate_visible_field_and_entities_remain_decoded_evidence():
    raw = page(row("Дата опубликования", '  28.04.2022<span hidden>01.01.1900</span>\n') + row("Комментарий", "А&amp;Б&nbsp;– документ"))
    result = parse_legal_metadata(raw, URL)
    assert result["fields"]["publication_date"]["observed_iso_date"] == "2022-04-28"
    assert result["rows"][0]["values"][0]["raw_text"] == "  28.04.2022\n"
    assert result["rows"][1]["values"][0]["raw_text"] == "А&Б\u00a0– документ"


@pytest.mark.parametrize("change", [lambda raw: raw[:-7], lambda raw: raw.replace(b'</div>', b'', 1),
                                   lambda raw: raw.replace(b'class="DocDetail_Info"', b'class="DocDetail_Info" class="Other"'),
                                   lambda raw: raw.replace(b'<head>', b'<head><base href="https://evil.invalid/">')])
def test_malformed_source_cannot_be_repaired_into_metadata(change):
    with pytest.raises(ETTLegalMetadataError):
        parse_legal_metadata(change(page()), URL)


@pytest.mark.parametrize("url", ["http://docs.eaeunion.org/documents/399/6620/", URL + "?date=28.04.2022", "https://other.invalid/documents/399/6620/"])
def test_metadata_url_is_a_bounded_exact_official_document_reference(url):
    with pytest.raises(ETTLegalMetadataError):
        parse_legal_metadata(page(), url)
