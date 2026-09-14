from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
import pytest

from app.services import ett_portal_search as search
from app.services import ett_transport as transport


BASE = search.PORTAL_SEARCH_URL
QUERY = "Решение Совета ЕЭК № 76"
FIRST = BASE + "?" + urlencode({"q": QUERY})
SECOND = FIRST + "&PAGEN_1=2"
HTML = b"\xef\xbb\xbf<!DOCTYPE html><html><body>synthetic page</body></html>\r\n"


class ObservedStream(httpx.SyncByteStream):
    def __init__(self, chunks=()):
        self.chunks = chunks
        self.iterated = False
        self.closed = False

    def __iter__(self):
        self.iterated = True
        yield from self.chunks

    def close(self):
        self.closed = True


def response(content=HTML, *, status=200, headers=None):
    return httpx.Response(
        status,
        headers={"Content-Type": "text/html; charset=utf-8", **(headers or {})},
        stream=httpx.ByteStream(content),
    )


def fetch(handler, *, url=SECOND):
    return search.fetch_portal_search_page(url, _transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("url", [
    FIRST, FIRST + "&PAGEN_1=1", SECOND, FIRST + "&PAGEN_1=999999",
    BASE + "?q=a", BASE + "?" + urlencode({"q": "a" * 200}) + "&PAGEN_1=2",
    BASE + "?" + urlencode({"q": "文本 № 76 &PAGEN_1=999"}),
])
def test_page_validator_accepts_only_canonical_spelling_without_claiming_page_exists(url):
    assert search.validate_portal_search_page_url(url) == url


@pytest.mark.parametrize("url", [
    None, 1, b"https://docs.eaeunion.org/documents/search/?q=76", "", " " + FIRST,
    FIRST + "&PAGEN_1=", FIRST + "&PAGEN_1=0", FIRST + "&PAGEN_1=-1",
    FIRST + "&PAGEN_1=+1", FIRST + "&PAGEN_1=01", FIRST + "&PAGEN_1=1.0",
    FIRST + "&PAGEN_1=1e2", FIRST + "&PAGEN_1=%32", FIRST + "&PAGEN_1=٢",
    FIRST + "&PAGEN_1=２", FIRST + "&PAGEN_1=2 ", FIRST + "&PAGEN_1=2\n",
    FIRST + "&PAGEN_1=" + "1" * 4096,
    SECOND + "&PAGEN_1=3", SECOND + "&q=76", SECOND + "&page=3", SECOND + "&",
    FIRST + "&pagen_1=2", FIRST + "&PAGEN_2=2", FIRST + "&PAGEN%5F1=2",
    BASE + "?PAGEN_1=2&q=76", BASE + "?q=76&PAGEN_1=2&extra=1",
    BASE + "?q=76&q=77&PAGEN_1=2", BASE + "?q=&PAGEN_1=2",
    BASE + "?q=++&PAGEN_1=2", BASE + "?q=%0A76&PAGEN_1=2",
    BASE + "?q=..%2F76&PAGEN_1=2", BASE + "?q=76%2077&PAGEN_1=2",
    BASE + "?q=%FF&PAGEN_1=2", BASE + "?q=%GG&PAGEN_1=2",
    BASE + "?q=" + "a" * 201 + "&PAGEN_1=2",
    "https://docs.eaeunion.org/documents/399/6620/",
    "https://docs.eaeunion.org/documents/399/6620/?q=76&PAGEN_1=2",
    "https://docs.eaeunion.org/docs/ru-ru/01232479/err_28042022_76",
    "https://docs.eaeunion.org/api/documents/search/?q=76&PAGEN_1=2",
    "https://docs.eaeunion.org/documents/search?q=76&PAGEN_1=2",
    "https://docs.eaeunion.org/documents/../documents/search/?q=76&PAGEN_1=2",
    "https://docs.eaeunion.org/documents/%2e%2e/documents/search/?q=76&PAGEN_1=2",
    "https://docs.eaeunion.org/documents\\search/?q=76&PAGEN_1=2",
    "https://user:SECRET@docs.eaeunion.org/documents/search/?q=76&PAGEN_1=2",
    "https://docs.eaeunion.org:443/documents/search/?q=76&PAGEN_1=2",
    "https://docs.eaeunion.org:8443/documents/search/?q=76&PAGEN_1=2",
    "https://DOCS.EAEUNION.ORG/documents/search/?q=76&PAGEN_1=2",
    "http://docs.eaeunion.org/documents/search/?q=76&PAGEN_1=2",
    "https://evil.example/documents/search/?q=76&PAGEN_1=2",
    FIRST + "#fragment", SECOND + "#fragment",
])
def test_invalid_page_url_is_rejected_by_validator_and_before_network(url):
    with pytest.raises(transport.OfficialTransportError):
        search.validate_portal_search_page_url(url)
    with pytest.raises(transport.OfficialTransportError):
        fetch(lambda request: pytest.fail("invalid page reached the network"), url=url)


def test_literal_encoded_pagination_text_does_not_override_real_page_suffix():
    query = "76&PAGEN_1=999"
    url = BASE + "?" + urlencode({"q": query}) + "&PAGEN_1=2"
    seen = []

    def handler(request):
        seen.append(request)
        assert request.url.params.multi_items() == [("q", query), ("PAGEN_1", "2")]
        return response()

    result = fetch(handler, url=url)
    assert len(seen) == 1
    assert result.url == result.requested_url == url


def test_page_capture_retains_raw_bytes_exact_url_and_utc_provenance():
    seen = []

    def handler(request):
        seen.append(request)
        assert request.method == "GET"
        assert request.content == b""
        assert str(request.url) == SECOND
        assert request.headers["Accept"] == "text/html"
        assert request.headers["Accept-Encoding"] == "identity"
        assert request.extensions["timeout"] == {"connect": 5.0, "read": 5.0, "write": 5.0, "pool": 5.0}
        assert not any(name in request.headers for name in ("Cookie", "Authorization", "Proxy-Authorization"))
        return response(headers={"Content-Length": str(len(HTML))})

    before = datetime.now(timezone.utc)
    result = fetch(handler)
    after = datetime.now(timezone.utc)
    assert len(seen) == 1
    assert result.url == result.requested_url == SECOND
    assert result.redirect_chain == ()
    assert result.content == HTML
    assert result.media_type == "text/html"
    assert result.retrieved_at.tzinfo == timezone.utc
    assert before <= result.retrieved_at <= after


@pytest.mark.parametrize("source,target", [
    (FIRST, FIRST + "&PAGEN_1=1"),
    (FIRST + "&PAGEN_1=1", FIRST),
])
@pytest.mark.parametrize("relative", [False, True])
def test_implicit_first_page_and_explicit_one_can_redirect_without_identity_change(source, target, relative):
    seen = []
    redirect_stream = ObservedStream([b"must not read redirect body"])

    def handler(request):
        seen.append(request)
        assert not any(name in request.headers for name in ("Cookie", "Authorization", "Proxy-Authorization"))
        if len(seen) == 1:
            location = target.removeprefix("https://docs.eaeunion.org") if relative else target
            return httpx.Response(302, headers={"Location": location, "Set-Cookie": "SECRET=value; Path=/"}, stream=redirect_stream)
        return response()

    result = fetch(handler, url=source)
    assert [str(request.url) for request in seen] == [source, target]
    assert result.requested_url == source
    assert result.url == target
    assert result.redirect_chain == (target,)
    assert result.content == HTML
    assert not redirect_stream.iterated
    assert redirect_stream.closed


@pytest.mark.parametrize("location", [
    FIRST, FIRST + "&PAGEN_1=1", FIRST + "&PAGEN_1=3",
    BASE + "?q=76&PAGEN_1=2", BASE + "?" + urlencode({"q": QUERY + " "}) + "&PAGEN_1=2",
    BASE + "?" + urlencode({"q": QUERY.replace("ЕЭК", "еэк")}) + "&PAGEN_1=2",
    "/documents/399/6620/", "/docs/ru-ru/01232479/err_28042022_76",
    SECOND + "&extra=1", SECOND + "&q=76", SECOND + "&PAGEN_1=2",
    "/documents/../documents/search/?q=76&PAGEN_1=2",
    "//docs.eaeunion.org/documents/search/?q=76&PAGEN_1=2",
    "?q=76&PAGEN_1=2", "documents/search/?q=76&PAGEN_1=2",
    "https://eec.eaeunion.org/documents/search/?q=76&PAGEN_1=2",
    "https://user:SECRET@docs.eaeunion.org/documents/search/?q=76&PAGEN_1=2",
    "https://docs.eaeunion.org:443/documents/search/?q=76&PAGEN_1=2",
])
def test_page_redirect_cannot_change_identity_or_expand_route_before_following(location):
    seen = []
    stream = ObservedStream([b"SECRET body"])

    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={"Location": location}, stream=stream)

    with pytest.raises(transport.OfficialTransportError) as caught:
        fetch(handler)
    assert len(seen) == 1
    assert not stream.iterated
    assert stream.closed
    assert "SECRET" not in str(caught.value)
    assert "SECRET" not in repr(caught.value.diagnostics)


def test_page_identity_is_rechecked_after_an_accepted_first_redirect():
    seen = []

    def handler(request):
        seen.append(request)
        target = FIRST + "&PAGEN_1=1" if len(seen) == 1 else SECOND
        return response(status=307, headers={"Location": target})

    with pytest.raises(transport.OfficialTransportError):
        fetch(handler, url=FIRST)
    assert [str(request.url) for request in seen] == [FIRST, FIRST + "&PAGEN_1=1"]


def test_explicit_and_implicit_first_page_cycle_is_bounded_by_loop_detection():
    seen = []

    def handler(request):
        seen.append(request)
        target = FIRST + "&PAGEN_1=1" if len(seen) == 1 else FIRST
        return response(status=308, headers={"Location": target})

    with pytest.raises(transport.OfficialTransportError, match="redirect loop"):
        fetch(handler, url=FIRST)
    assert len(seen) == 2


def test_page_entry_point_uses_shared_redirect_limit(monkeypatch):
    monkeypatch.setattr(transport, "MAX_REDIRECTS", 0)
    seen = []

    def handler(request):
        seen.append(request)
        return response(status=302, headers={"Location": FIRST + "&PAGEN_1=1"})

    with pytest.raises(transport.OfficialTransportError, match="redirect limit"):
        fetch(handler, url=FIRST)
    assert len(seen) == 1


def test_page_entry_point_uses_shared_raw_stream_limit(monkeypatch):
    assert transport.MAX_HTML_BYTES == 4 * 1024 * 1024
    monkeypatch.setattr(transport, "MAX_HTML_BYTES", 8)
    yielded = []

    def chunks():
        for chunk in [b"1234", b"5678", b"9", b"never read"]:
            yielded.append(chunk)
            yield chunk

    stream = ObservedStream(chunks())
    with pytest.raises(transport.OfficialTransportError):
        fetch(lambda request: httpx.Response(200, headers={"Content-Type": "text/html"}, stream=stream))
    assert len(yielded) == 3
    assert stream.closed


def test_page_entry_point_uses_shared_elapsed_budget(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(transport.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(transport, "TOTAL_BUDGET_SECONDS", 2.0)
    yielded = []

    def chunks():
        for chunk in [b"<html>", b"body", b"</html>"]:
            now[0] += 1.1
            yielded.append(chunk)
            yield chunk

    stream = ObservedStream(chunks())
    with pytest.raises(transport.OfficialTransportError, match="elapsed time budget"):
        fetch(lambda request: httpx.Response(200, headers={"Content-Type": "text/html"}, stream=stream))
    assert len(yielded) == 2
    assert stream.closed


def test_page_failure_is_not_retried_or_replaced_with_first_page():
    seen = []
    stream = ObservedStream([b"SECRET unavailable page"])

    def handler(request):
        seen.append(request)
        return httpx.Response(403, stream=stream)

    with pytest.raises(transport.OfficialTransportError) as caught:
        fetch(handler)
    assert [str(request.url) for request in seen] == [SECOND]
    assert not stream.iterated
    assert stream.closed
    assert "SECRET" not in str(caught.value)


def test_page_entry_point_does_not_trust_ambient_proxy_or_auth(monkeypatch):
    seen = {}
    real_client = httpx.Client

    def client(**kwargs):
        seen.update(kwargs)
        return real_client(**kwargs)

    monkeypatch.setattr(transport.httpx, "Client", client)
    monkeypatch.setenv("HTTPS_PROXY", "https://SECRET:password@untrusted.example")
    monkeypatch.setenv("NETRC", "/must-not-read-ambient-credentials")
    result = fetch(lambda request: response())
    assert result.url == SECOND
    assert seen["trust_env"] is False
    assert seen["verify"] is True
    assert seen["follow_redirects"] is False
    assert seen["timeout"] == httpx.Timeout(5.0)


def test_old_search_and_ordinary_source_entry_points_still_reject_pagination_redirect():
    for entrypoint in (
        lambda mock: search.fetch_portal_search(QUERY, _transport=mock),
        lambda mock: transport.fetch_official("https://docs.eaeunion.org/documents/399/6620/", _transport=mock),
    ):
        seen = []

        def handler(request):
            seen.append(request)
            return response(status=302, headers={"Location": SECOND})

        with pytest.raises(transport.OfficialTransportError):
            entrypoint(httpx.MockTransport(handler))
        assert len(seen) == 1
    with pytest.raises(transport.OfficialTransportError):
        transport.validate_official_url(SECOND)
