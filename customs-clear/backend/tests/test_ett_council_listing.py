"""Observed-link traversal and unresolved-list boundaries; synthetic HTML."""
from dataclasses import replace
from datetime import datetime, timezone
import hashlib

import httpx
import pytest

from app.services.ett_artifacts import LocalArtifactStore
from app.services.ett_legal_list import ETTLegalListError
from app.services.ett_council_listing import (
    CouncilListingError, DETAIL_URL, LIST_URL, capture_council_listing,
    fetch_council_list_page, observed_parent_link,
)
from app.services.ett_transport import OfficialResponse, OfficialTransportError

CATEGORY = "Акты Евразийской экономической комиссии - Совет Евразийской экономической комиссии - Решения - 2026"
BOOTSTRAP = b'<!doctype html><html><body><a href="/documents/461/" onclick="untrusted();">Back</a></body></html>'


def row(number):
    return f'''<div class="DocSearchResult_Item">
<div class="DocSearchResult_Item__Date">{CATEGORY}</div>
<a class="DocSearchResult_Item__Link" href="/documents/461/900{number}/">Решение Совета ЕЭК №{number}</a>
<div class="DocSearchResult_Item__Text">Synthetic observed decision {number}</div>
<div class="DocSearchResult_Item__Dates"><div>Дата принятия документа: 30.01.2026</div>
<div>Дата опубликования документа: 07.08.2026</div></div>
<a href="/upload/iblock/abc/observed/decision-{number}.pdf">Рус</a></div>'''


def listing(numbers=("75", "77", "80"), *, links=(), total=80):
    return (f'<!doctype html><html><head><title>{CATEGORY}</title></head><body>'
            f'<div class="SearchResult_Heading__Counter">Результаты: найдено {total}</div>'
            '<div class="DocSearchResult_Items">' + ''.join(row(n) for n in numbers) + '</div>'
            + ''.join(f'<a href="{url}">Next</a>' for url in links) + '</body></html>').encode()


def response(url, raw):
    return OfficialResponse(url=url, requested_url=url, content=raw, media_type="text/html",
                            retrieved_at=datetime(2026, 9, 11, tzinfo=timezone.utc), redirect_chain=())


def capture(tmp_path, pages, *, bootstrap=BOOTSTRAP, transform=None):
    requested = []

    def fetch(url, **kwargs):
        requested.append(url)
        result = response(url, bootstrap if url == DETAIL_URL else pages[url])
        return transform(result) if transform else result

    result = capture_council_listing(LocalArtifactStore(tmp_path / 'store'), fetch=fetch, fetch_page=fetch)
    return result, requested


def test_bootstrap_preserves_parent_literal_and_ignores_script():
    link = observed_parent_link(BOOTSTRAP)
    assert link['href'] == '/documents/461/'
    assert link['url'] == LIST_URL
    assert link['page_sha256'] == hashlib.sha256(BOOTSTRAP).hexdigest()
    assert 'untrusted();' in link['raw_start_tag']


@pytest.mark.parametrize('raw', [
    BOOTSTRAP.replace(b'/documents/461/', b'/documents/462/'),
    BOOTSTRAP.replace(b'<a ', b'<a href="https://example.org/" '),
    BOOTSTRAP.replace(b'</body>', b'<a href="/documents/461/">Duplicate</a></body>'),
    BOOTSTRAP.replace(b'<body>', b'<body><base href="https://example.org/">'),
])
def test_missing_ambiguous_or_based_parent_never_fetches_listing(tmp_path, raw):
    result, calls = capture(tmp_path, {}, bootstrap=raw)
    assert calls == [DETAIL_URL]
    assert result['status'] == 'incomplete'
    assert not result['selected_target_urls_observed']


def test_exact_targets_bind_rows_and_pdfs_to_retained_parent_without_download(tmp_path):
    raw = listing()
    result, calls = capture(tmp_path, {LIST_URL: raw})
    assert calls == [DETAIL_URL, LIST_URL]
    assert result['selected_target_urls_observed']
    assert result['stop_reason'] == 'selected_targets_observed'
    assert result['accepted_list_pages'] == 1
    assert result['unobserved_target_numbers'] == []
    assert [c['number'] for c in result['candidates']] == ['75', '77', '80']
    for candidate in result['candidates']:
        assert candidate['parent_page_sha256'] == hashlib.sha256(raw).hexdigest()
        assert candidate['document_link']['url'].startswith(LIST_URL)
        assert candidate['pdf_references'][0]['raw_href']
        assert candidate['primary_body_verified'] is False
    for flag in ('legal_inventory_complete', 'source_identity_verified', 'adoption_dates_verified',
                 'effective_dates_verified', 'production_ready', 'can_promote', 'active_rates_written',
                 'document_absence_verified', 'durable_legal_retention_attested'):
        assert result[flag] is False


def test_next_page_is_only_replayed_literal_link_and_no_extra_fetch_after_targets(tmp_path):
    next_url = LIST_URL + '?sphrase_id=528328&PAGEN_1=2'
    result, calls = capture(tmp_path, {
        LIST_URL: listing(('80',), links=('/documents/461/?sphrase_id=528328&amp;PAGEN_1=2',)),
        next_url: listing(('77', '75'), links=('/documents/461/?PAGEN_1=3',)),
    })
    assert result['selected_target_urls_observed']
    assert calls == [DETAIL_URL, LIST_URL, next_url]
    parent = result['records'][2]['followed_from']
    assert parent['link']['url'] == next_url
    assert parent['page_sha256'] == result['records'][1]['sha256']


def test_missing_intermediate_page_is_not_synthesized(tmp_path):
    result, calls = capture(tmp_path, {LIST_URL: listing(('80',), links=('/documents/461/?PAGEN_1=3',))})
    assert calls == [DETAIL_URL, LIST_URL]
    assert result['stop_reason'] == 'observed_next_page_link_missing'
    assert result['unobserved_target_numbers'] == ['75', '77']


def test_end_of_list_is_not_absence_or_legal_completeness(tmp_path):
    result, calls = capture(tmp_path, {LIST_URL: listing(('80',))})
    assert result['observed_chain_exhausted']
    assert result['status'] == 'incomplete'
    assert not result['document_absence_verified']


@pytest.mark.parametrize('changed,reason', [
    (listing(('80', '75')), 'repeated_document_rows'),
    (listing(('77', '75'), total=81), 'reported_result_count_changed'),
    (listing(('77', '75')).replace(b'2026', b'2025'), 'list_category_changed'),
])
def test_cross_page_drift_stops_before_accepting_conflicting_rows(tmp_path, changed, reason):
    next_url = LIST_URL + '?PAGEN_1=2'
    result, calls = capture(tmp_path, {
        LIST_URL: listing(('80',), links=('/documents/461/?PAGEN_1=2',)), next_url: changed,
    })
    assert result['stop_reason'] == reason
    assert result['status'] == 'incomplete'
    assert len(result['candidates']) == 1


def test_response_redirect_or_identity_change_is_rejected(tmp_path):
    result, calls = capture(tmp_path, {}, transform=lambda r: replace(r, url=LIST_URL))
    assert result['stop_reason'] == 'source_binding_failed'
    assert result['captured_sources'] == 0


def test_failed_transport_is_sanitized_and_not_retried(tmp_path):
    def fetch(*args, **kwargs):
        raise OfficialTransportError('SECRET diagnostic')
    result = capture_council_listing(LocalArtifactStore(tmp_path / 'store'), fetch=fetch)
    assert result['stop_reason'] == 'official_transport_failure'
    assert len(result['records']) == 1
    assert 'SECRET' not in str(result)


@pytest.mark.parametrize('limit,value,reason', [
    ('MAX_PAGES', 0, 'page_budget_exceeded'), ('MAX_ROWS', 0, 'row_budget_exceeded'),
    ('MAX_TOTAL_BYTES', 0, 'byte_budget_exceeded'), ('MAX_ELAPSED_SECONDS', 0, 'elapsed_time_budget'),
])
def test_bounds_stop_capture_without_inventing_more_sources(tmp_path, monkeypatch, limit, value, reason):
    monkeypatch.setattr('app.services.ett_council_listing.' + limit, value)
    result, _ = capture(tmp_path, {LIST_URL: listing()})
    assert result['stop_reason'] == reason
    assert not result['selected_target_urls_observed']


def test_listing_transport_accepts_only_supplied_category_and_page():
    requested = []
    def transport(request):
        requested.append(str(request.url))
        return httpx.Response(200, headers={'content-type': 'text/html'}, stream=httpx.ByteStream(listing()))
    url = LIST_URL + '?PAGEN_1=2'
    result = fetch_council_list_page(url, _transport=httpx.MockTransport(transport))
    assert result.url == url
    assert requested == [url]
    with pytest.raises((CouncilListingError, ETTLegalListError, OfficialTransportError)):
        fetch_council_list_page(LIST_URL.replace('/461/', '/462/'), _transport=httpx.MockTransport(transport))


@pytest.mark.parametrize('location', [
    '/documents/461/?PAGEN_1=3', '/documents/462/?PAGEN_1=2',
    'https://example.org/documents/461/?PAGEN_1=2',
    '/documents/461/../461/?PAGEN_1=2', '//example.org/',
])
def test_listing_transport_does_not_follow_changed_redirects(location):
    requests = []
    def transport(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={'location': location})
    with pytest.raises((CouncilListingError, ETTLegalListError, OfficialTransportError)):
        fetch_council_list_page(LIST_URL + '?PAGEN_1=2', _transport=httpx.MockTransport(transport))
    assert len(requests) == 1
