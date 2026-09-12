"""Synthetic search-result DOM tests; no search is issued by these tests."""
from dataclasses import FrozenInstanceError
from datetime import date
import hashlib
from html import escape
from urllib.parse import urlencode

import pytest

from app.services.ett_legal_search import (
    EMPTY_RESULT_NOTICE, ETTLegalSearchError, parse_legal_search, validate_search_result_url,
)

BASE = "https://docs.eaeunion.org/documents/search/"
QUERY = "Единого таможенного тарифа"
URL = BASE + "?" + urlencode({"q": QUERY})
PDF = "/upload/iblock/abc/name/observed.pdf"
CATEGORY = "Акты Евразийской экономической комиссии – Коллегия Евразийской экономической комиссии – Решения – 2026"


def row(number="53", document="10654", category=CATEGORY, label=None, adopted="12.05.2026", extra=""):
    label = label or f"Решение Коллегии ЕЭК № {number}"
    return f'''<div class="DocSearchResult_Item"><div class="DocSearchResult_Item__Date">{category}</div>
<a class="DocSearchResult_Item__Link" href="/documents/463/{document}/" onclick="throw Error('must never execute')">{label}</a>
<div class="DocSearchResult_Item__Text">Синтетическое полное название</div>
<div class="DocSearchResult_Item__Dates"><div><div>Дата принятия документа: {adopted}</div>
<div>Дата опубликования документа: 15.05.2026</div></div><div><div>Дата вступления в силу: 14.06.2026</div></div></div>
<a href="{PDF}">Рус</a><a href="{PDF}">Скачать</a>
<a href="/upload/iblock/abc/name/appendix.docx">Приложение</a>{extra}</div>'''


def page(rows=None, *, query=QUERY, pagination=True, empty=False, extra=""):
    links = ""
    if pagination:
        href = '/documents/search/?' + urlencode({'q': query}) + '&PAGEN_1=2'
        links = f'<a href="{escape(href)}">2</a><a href="{escape(href)}">След.</a>'
    notice = f'<font class="notetext">{EMPTY_RESULT_NOTICE}</font>' if empty else ''
    return f'''<!doctype html><html><head><title>Правовой портал</title></head><body>
<form class="SearchForm _documents" action="/documents/search/" target="_self"><input name="q" type="text" value="{escape(query)}"></form>
<div class="DocSearchResult_Items">{row() if rows is None else rows}{notice}</div>{links}{extra}</body></html>'''.encode()


def test_original_query_source_and_explicit_decision_identity_are_bound_without_legal_verification():
    raw = page()
    result = parse_legal_search(raw, URL)
    assert result.source_sha256 == hashlib.sha256(raw).hexdigest()
    assert result.size_bytes == len(raw)
    assert result.observed_query == QUERY
    assert result.requested_page_literal is None
    assert result.observed_identity_count == 1
    document = result.documents[0]
    assert document.issuing_body == "collegium"
    assert document.number == "53"
    assert document.identity_status == "observed_decision_identity"
    assert document.observed_adoption_date == date(2026, 5, 12)
    assert document.observed_publication_date == date(2026, 5, 15)
    assert document.observed_entry_into_force_date == date(2026, 6, 14)
    assert document.document_link.url == "https://docs.eaeunion.org/documents/463/10654/"
    assert hashlib.sha256(document.evidence.text.encode()).hexdigest() == document.evidence.text_sha256
    assert document.evidence.locator.startswith("html:search-row:1:")
    assert document.legal_dates_verified is document.primary_body_verified is False
    assert result.reported_result_count is None
    assert result.all_pages_captured is result.legal_inventory_complete is result.document_absence_verified is False


def test_mixed_document_types_and_generic_old_labels_remain_visible_unresolved_rows():
    rows = row() + row(document="2", category="Международные договоры – Архив", label="Протокол") + row(document="3", label="Решение № 53")
    result = parse_legal_search(page(rows), URL)
    assert len(result.documents) == 3
    assert result.observed_identity_count == 1
    assert [d.identity_status for d in result.documents] == ["observed_decision_identity", "outside_supported_decision_category", "unresolved_decision_identity"]
    assert result.documents[1].issuing_body is result.documents[1].number is None
    assert result.documents[2].issuing_body is result.documents[2].number is None
    assert result.documents[2].issues == ("decision_identity_or_adoption_metadata_conflict",)


@pytest.mark.parametrize("changes", [
    {"adopted": "12.05.2025"}, {"adopted": "31.02.2026"},
    {"adopted": "нет даты"}, {"label": "Решение Совета ЕЭК № 53"},
])
def test_conflicting_or_invalid_metadata_cannot_create_a_match(changes):
    result = parse_legal_search(page(row(**changes)), URL)
    assert result.observed_identity_count == 0
    assert result.documents[0].identity_status == "unresolved_decision_identity"
    assert result.documents[0].issuing_body is result.documents[0].number is None
    assert result.documents[0].issues


def test_no_results_is_not_document_absence_and_does_not_invent_count_or_pagination():
    raw = page("", query="09.07.2026", empty=True, pagination=False)
    result = parse_legal_search(raw, BASE + "?q=09.07.2026")
    assert result.documents == result.pagination_links == ()
    assert result.empty_result_notice is True
    assert result.reported_result_count is None
    assert result.document_absence_verified is result.all_pages_captured is False


def test_observed_repeated_links_and_pagination_are_preserved():
    result = parse_legal_search(page(), URL)
    refs = result.documents[0].pdf_references
    assert len(refs) == 2 and refs[0].url == refs[1].url
    assert refs[0].locator != refs[1].locator
    assert len(result.documents[0].unsupported_references) == 1
    assert [r.url for r in result.pagination_links] == [URL + "&PAGEN_1=2"] * 2
    assert [r.text for r in result.pagination_links] == ["2", "След."]


def test_supplied_page_number_is_retained_as_a_literal():
    result = parse_legal_search(page(), URL + "&PAGEN_1=2")
    assert result.requested_page_literal == 2
    assert validate_search_result_url(URL + "&PAGEN_1=10") == (QUERY, 10)


@pytest.mark.parametrize("url", [
    None, BASE, "https://docs.eaeunion.org/documents/401/7135/",
    URL + "&other=2", URL + "&PAGEN_1=0", URL + "&PAGEN_1=-1",
    URL + "&PAGEN_1=2&PAGEN_1=3", URL + "&PAGEN_1=2#x",
    URL + "&PAGEN_1=２", URL + "\n", BASE + "?q=one%20two",
    URL.replace("https:", "http:"), URL.replace(".org", ".org:443"),
])
def test_unobserved_url_contracts_are_rejected(url):
    with pytest.raises(ETTLegalSearchError):
        parse_legal_search(page(), url)


def test_search_query_echo_must_equal_requested_query():
    with pytest.raises(ETTLegalSearchError, match="echo"):
        parse_legal_search(page(query="168"), URL)


def test_decoded_ampersand_quote_and_cyrillic_query_are_bound_without_reencoding_source():
    query = 'акт "А" & Б'
    result = parse_legal_search(page(query=query), BASE + '?' + urlencode({'q': query}))
    assert result.observed_query == query


def test_pagination_cannot_change_query():
    raw = page().replace(b'&amp;PAGEN_1=2', b'x&amp;PAGEN_1=2')
    with pytest.raises(ETTLegalSearchError, match="changes"):
        parse_legal_search(raw, URL)


@pytest.mark.parametrize("raw", [page("", pagination=False), page(empty=True), page("", empty=True).replace(b'class="notetext"', b'class="notetext" hidden')])
def test_missing_or_contradictory_empty_result_marker_fails(raw):
    with pytest.raises(ETTLegalSearchError, match="inconsistent"):
        parse_legal_search(raw, URL)


@pytest.mark.parametrize("old,new", [
    ('</html>', ''), ('<body>', '<body><base href="https://example.com/">'),
    ('Правовой портал</title>', 'Challenge</title>'),
    ('<body>', '<body>\x00'),
    ('<!doctype html>', '<!DOCTYPE html [<!ENTITY x SYSTEM "file:///etc/passwd">]>'),
    ('action="/documents/search/"', 'action="/documents/search/" method="post"'),
    ('name="q"', 'name="query"'),
    ('class="DocSearchResult_Item__Link"', 'class="Unknown"'),
])
def test_wrong_identity_malformed_html_and_fields_fail(old, new):
    with pytest.raises(ETTLegalSearchError):
        parse_legal_search(page().decode().replace(old, new).encode(), URL)


@pytest.mark.parametrize("href", ['https://example.com/act.pdf', '/upload/iblock/abc/../act.pdf', PDF + '?download=1', ' https://example.com/act.pdf '])
def test_unsafe_attachment_is_not_dropped(href):
    with pytest.raises(ETTLegalSearchError):
        parse_legal_search(page().decode().replace(PDF, href).encode(), URL)


def test_duplicate_document_url_and_duplicate_date_metadata_fail_closed():
    with pytest.raises(ETTLegalSearchError, match="repeats"):
        parse_legal_search(page(row() + row()), URL)
    literal = '<div>Дата принятия документа: 12.05.2026</div>'
    with pytest.raises(ETTLegalSearchError, match="duplicated"):
        parse_legal_search(page().decode().replace(literal, literal * 2).encode(), URL)


def test_missing_adoption_metadata_cannot_be_derived_from_other_fields_or_filename():
    literal = '<div>Дата принятия документа: 12.05.2026</div>'
    result = parse_legal_search(page().decode().replace(literal, '').encode(), URL)
    assert result.documents[0].observed_adoption_date is None
    assert result.documents[0].number is None


def test_unknown_date_metadata_remains_in_raw_evidence_with_issue():
    raw = page().decode().replace('Дата вступления в силу:', 'Дата прекращения действия:').encode()
    result = parse_legal_search(raw, URL)
    assert result.documents[0].observed_entry_into_force_date is None
    assert 'unsupported_date_metadata' in result.documents[0].issues
    assert 'Дата прекращения действия' in result.documents[0].evidence.text


def test_mutation_cannot_change_legal_or_absence_flags():
    result = parse_legal_search(page(), URL)
    with pytest.raises(FrozenInstanceError):
        result.document_absence_verified = True
    with pytest.raises(FrozenInstanceError):
        result.documents[0].legal_dates_verified = True


@pytest.mark.parametrize("raw", [b'', b'\xff', b'x' * (4 * 1024 * 1024 + 1), '<html></html>'])
def test_bad_input_bytes(raw):
    with pytest.raises(ETTLegalSearchError):
        parse_legal_search(raw, URL)


def test_row_and_attachment_bounds(monkeypatch):
    monkeypatch.setattr('app.services.ett_legal_search.MAX_SEARCH_ROWS', 1)
    with pytest.raises(ETTLegalSearchError, match="row bound"):
        parse_legal_search(page(row() + row(document='2')), URL)
    monkeypatch.setattr('app.services.ett_legal_search.MAX_ROW_REFERENCES', 1)
    with pytest.raises(ETTLegalSearchError, match="attachment count"):
        parse_legal_search(page(), URL)
