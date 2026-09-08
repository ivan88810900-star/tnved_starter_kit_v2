"""Synthetic decision-list layout tests; current raw pages are audited separately."""
from dataclasses import FrozenInstanceError
from datetime import date
import hashlib

import pytest

from app.services.ett_legal_list import ETTLegalListError, parse_legal_list, validate_list_url

URL = "https://docs.eaeunion.org/documents/399/"
PDF = "/upload/iblock/abc/opaque/observed.pdf"
CATEGORY = "Акты Евразийской экономической комиссии - Коллегия Евразийской экономической комиссии - Решения - 2022"


def row(number="206", document="7184", extra=""):
    return f'''<div class="DocSearchResult_Item">
<div class="DocSearchResult_Item__Date">{CATEGORY.replace(' - ', ' – ')}</div>
<a class="DocSearchResult_Item__Link" href="/documents/399/{document}/">Решение Коллегии ЕЭК №{number}</a>
<div class="DocSearchResult_Item__Text">Синтетическое название решения</div>
<div class="DocSearchResult_Item__Dates"><div class="DocSearchResult_Item__DatesLeft">
<div>Дата принятия документа: 27.12.2022</div><div>Дата опубликования документа: 09.01.2023</div>
</div><div class="DocSearchResult_Item__DatesRight"><div>Дата вступления в силу: 08.02.2023</div></div></div>
<div><a href="{PDF}">Рус</a><a href="{PDF}">Скачать</a>
<a href="/upload/iblock/abc/opaque/appendix.docx">Приложение</a></div>{extra}</div>'''


def page(rows=None, *, extra="", total=205):
    return f'''<!doctype html><html><head><title>{CATEGORY}</title></head><body>
<div class="SearchResult_Heading__Counter">Результаты: найдено <b>{total}</b></div>
<div class="DocSearchResult_Items">{row() if rows is None else rows}</div>
<a href="/documents/399/?sphrase_id=528328&amp;PAGEN_1=2">2</a>
<a href="/documents/399/?sphrase_id=528328&amp;PAGEN_1=2">След.</a>{extra}
</body></html>'''.encode()


def test_retains_named_identity_dates_as_unverified_metadata_and_original_source_hash():
    raw = page()
    result = parse_legal_list(raw, URL)
    assert result.source_sha256 == hashlib.sha256(raw).hexdigest()
    assert result.size_bytes == len(raw)
    assert result.issuing_body == "collegium"
    assert result.observed_year == 2022
    assert result.reported_result_count == 205
    assert len(result.documents) == 1
    document = result.documents[0]
    assert document.number == "206"
    assert document.observed_adoption_date == date(2022, 12, 27)
    assert document.observed_publication_date == date(2023, 1, 9)
    assert document.observed_entry_into_force_date == date(2023, 2, 8)
    assert document.document_link.url == URL + "7184/"
    assert document.document_link.href == "/documents/399/7184/"
    assert document.evidence.locator.startswith("html:list-row:1:line:")
    assert hashlib.sha256(document.evidence.text.encode()).hexdigest() == document.evidence.text_sha256
    assert document.legal_dates_verified is document.primary_body_verified is False
    assert result.all_pages_captured is result.legal_inventory_complete is result.primary_bodies_verified is False


def test_preserves_repeated_original_attachment_and_pagination_references():
    result = parse_legal_list(page(), URL)
    document = result.documents[0]
    assert [ref.url for ref in document.pdf_references] == ["https://docs.eaeunion.org" + PDF] * 2
    assert len(document.unsupported_references) == 1
    assert document.unsupported_references[0].url.endswith("appendix.docx")
    assert document.pdf_references[0].locator != document.pdf_references[1].locator
    assert [link.url for link in result.pagination_links] == [URL + "?sphrase_id=528328&PAGEN_1=2"] * 2
    assert [link.text for link in result.pagination_links] == ["2", "След."]


def test_optional_entry_into_force_is_not_filled_from_adoption_or_publication():
    raw = page().replace('<div>Дата вступления в силу: 08.02.2023</div>'.encode(), b'')
    assert parse_legal_list(raw, URL).documents[0].observed_entry_into_force_date is None


def test_observed_council_labels_can_omit_eec_when_full_category_supplies_identity():
    raw = page().replace('Коллегия'.encode(), 'Совет'.encode()).replace('Коллегии ЕЭК'.encode(), 'Совета'.encode())
    result = parse_legal_list(raw, URL)
    assert result.issuing_body == "council"
    assert result.documents[0].issuing_body == "council"


def test_no_rate_source_is_fabricated_when_row_has_no_attachment_links():
    raw = page().replace(f'<a href="{PDF}">Рус</a><a href="{PDF}">Скачать</a>'.encode(), b'')
    result = parse_legal_list(raw, URL)
    assert result.documents[0].pdf_references == ()
    assert result.primary_bodies_verified is False


@pytest.mark.parametrize("suffix", ["", "?PAGEN_1=2", "?sphrase_id=528328&PAGEN_1=2"])
def test_only_supported_supplied_pagination_urls(suffix):
    assert validate_list_url(URL + suffix) == URL + suffix


@pytest.mark.parametrize("url", [
    URL + "?", URL + "#", URL + "?PAGEN_1=0", URL + "?PAGEN_1=2&PAGEN_1=3",
    URL + "?sphrase_id=abc&PAGEN_1=2", URL + "?secret=1&PAGEN_1=2",
    URL + "?sphrase_id=1", URL + "?sphrase_id=1&PAGEN_2=2",
    URL.replace("https://", "http://"), URL.replace(".org", ".org:443"),
    URL.replace("docs.eaeunion.org", "eec.eaeunion.org"),
    URL.replace("/399/", "/399/6620/"), URL + "\n", None,
])
def test_unsupported_list_urls_are_rejected(url):
    with pytest.raises(ETTLegalListError):
        parse_legal_list(page(), url)


@pytest.mark.parametrize("old,new", [
    ('Решение Коллегии ЕЭК №206', 'Решение Совета ЕЭК №206'),
    ('Решение Коллегии ЕЭК №206', 'Рекомендация Коллегии ЕЭК №206'),
    ('Решение Коллегии ЕЭК №206', 'Решение Коллегии ЕЭК №0'),
    ('27.12.2022', '31.02.2022'), ('27.12.2022', '27.12.2021'),
    ('09.01.2023', '9 января 2023'),
    ('Дата принятия документа: 27.12.2022', 'Дата неизвестна: 27.12.2022'),
    ('Синтетическое название решения', ''),
    ('</html>', ''), ('<body>', '<body><base href="https://example.com/">'),
    ('<body>', '<body>\x00'),
    ('<!doctype html>', '<!DOCTYPE html [<!ENTITY x SYSTEM "file:///etc/passwd">]>'),
])
def test_incomplete_unknown_or_conflicting_fields_fail_closed(old, new):
    with pytest.raises(ETTLegalListError):
        parse_legal_list(page().decode().replace(old, new).encode(), URL)


def test_row_category_cannot_inherit_conflicting_list_year():
    raw = page().replace('Решения – 2022'.encode(), 'Решения – 2021'.encode())
    with pytest.raises(ETTLegalListError, match="category"):
        parse_legal_list(raw, URL)


@pytest.mark.parametrize("rows", [row() + row(), row() + row("207")])
def test_duplicate_act_or_document_url_is_rejected(rows):
    with pytest.raises(ETTLegalListError, match="duplicate"):
        parse_legal_list(page(rows), URL)


def test_duplicate_metadata_field_is_rejected():
    raw = page()
    field = '<div>Дата принятия документа: 27.12.2022</div>'
    with pytest.raises(ETTLegalListError, match="duplicated"):
        parse_legal_list(raw.decode().replace(field, field * 2).encode(), URL)


def test_nested_list_rows_are_rejected():
    with pytest.raises(ETTLegalListError):
        parse_legal_list(page(row(extra=row("207", "7185"))), URL)


@pytest.mark.parametrize("href", [
    'https://example.com/act.pdf', '/upload/iblock/abc/../act.pdf',
    '/upload/iblock/abc/a%2fb.pdf', '/upload/iblock/abc/act.pdf?download=1',
    ' https://example.com/act.pdf ',
])
def test_unsafe_attachment_is_not_omitted(href):
    with pytest.raises(ETTLegalListError):
        parse_legal_list(page().decode().replace(PDF, href).encode(), URL)


def test_pagination_cannot_switch_lists():
    raw = page().replace(b'/documents/399/?', b'/documents/401/?')
    with pytest.raises(ETTLegalListError, match="pagination"):
        parse_legal_list(raw, URL)


def test_percent_encoded_extension_still_identifies_observed_pdf_reference():
    raw = page().decode().replace(PDF, PDF.replace('.pdf', '%2epdf')).encode()
    assert len(parse_legal_list(raw, URL).documents[0].pdf_references) == 2


def test_page_result_counter_cannot_hide_rows():
    with pytest.raises(ETTLegalListError, match="result count"):
        parse_legal_list(page(total=0), URL)


def test_nested_output_cannot_be_mutated():
    result = parse_legal_list(page(), URL)
    with pytest.raises(FrozenInstanceError):
        result.all_pages_captured = True
    with pytest.raises(FrozenInstanceError):
        result.documents[0].legal_dates_verified = True


@pytest.mark.parametrize("raw", [b'', b'\xff', b'x' * (4 * 1024 * 1024 + 1), '<html></html>'])
def test_bad_source_bytes(raw):
    with pytest.raises(ETTLegalListError):
        parse_legal_list(raw, URL)


def test_row_and_attachment_budgets(monkeypatch):
    monkeypatch.setattr('app.services.ett_legal_list.MAX_LIST_DOCUMENTS', 1)
    with pytest.raises(ETTLegalListError, match="row bound"):
        parse_legal_list(page(row() + row('207', '7185')), URL)
    monkeypatch.setattr('app.services.ett_legal_list.MAX_ROW_REFERENCES', 1)
    with pytest.raises(ETTLegalListError, match="attachment count"):
        parse_legal_list(page(), URL)
