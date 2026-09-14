from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx
import pytest

from app.services import ett_portal_search as search
from app.services import ett_transport as transport


QUERY = "Решение Совета ЕЭК № 76 от 15.04.2022"
URL = search.PORTAL_SEARCH_URL + "?" + urlencode({"q": QUERY})
HTML = b"\xef\xbb\xbf<!DOCTYPE html><html><body>synthetic search only</body></html>\r\n"


def response(content=HTML, *, status=200, headers=None):
    return httpx.Response(
        status,
        headers={"Content-Type": "text/html; charset=utf-8", **(headers or {})},
        stream=httpx.ByteStream(content),
    )


def fetch(handler, *, query=QUERY):
    return search.fetch_portal_search(query, _transport=httpx.MockTransport(handler))


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


def test_observed_get_form_preserves_original_bytes_and_immutable_provenance():
    seen = []

    def handler(request):
        seen.append(request)
        assert request.method == "GET"
        assert request.content == b""
        assert str(request.url) == URL
        return response(headers={"Content-Length": str(len(HTML))})

    before = datetime.now(timezone.utc)
    result = fetch(handler)
    after = datetime.now(timezone.utc)
    assert len(seen) == 1
    assert result.requested_url == result.url == URL
    assert result.content == HTML
    assert result.media_type == "text/html"
    assert result.redirect_chain == ()
    assert result.retrieved_at.tzinfo == timezone.utc
    assert before <= result.retrieved_at <= after
    with pytest.raises(FrozenInstanceError):
        result.content = b"altered"


@pytest.mark.parametrize("query", [
    "а", "я" * 200, "№ 76 (Совет ЕЭК)", "税則", "é e\u0301", "  № 76  ",
    "76&q=SECRET", "76?token=SECRET#fragment", "https://example.org/a", "a+b%20c",
])
def test_printable_query_is_encoded_once_as_one_literal_form_field(query):
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return response()

    result = fetch(handler, query=query)
    assert seen == [search.PORTAL_SEARCH_URL + "?" + urlencode({"q": query})]
    assert parse_qsl(urlsplit(result.url).query, strict_parsing=True) == [("q", query)]


@pytest.mark.parametrize("query", [
    None, 76, True, [], {}, b"76", "", " ", "а" * 201,
    "a\nb", "a\rb", "a\tb", "a\x00b", "a\x1fb", "a\x7fb", "a\u200bb",
    "a\u202eb", "a\ud800b", ".", "..", "../76", "76/../77", "76/./77", "76\\..\\77",
])
def test_invalid_query_is_rejected_before_any_request(query):
    with pytest.raises(transport.OfficialTransportError):
        fetch(lambda request: pytest.fail("invalid query reached the network"), query=query)


@pytest.mark.parametrize("location", [
    "/documents/399/6620/", "https://docs.eaeunion.org/documents/399/6620",
    "/docs/ru-ru/01232479/err_28042022_76", "/documents/search/?q=76",
])
def test_only_canonical_same_host_document_or_exact_search_redirects_are_followed(location):
    seen = []
    redirect_stream = ObservedStream([b"redirect body must not be read"])

    def handler(request):
        seen.append(request)
        assert request.method == "GET"
        assert request.headers["Accept"] == "text/html"
        assert request.headers["Accept-Encoding"] == "identity"
        assert request.extensions["timeout"] == {"connect": 5.0, "read": 5.0, "write": 5.0, "pool": 5.0}
        assert not any(name in request.headers for name in ("Cookie", "Authorization", "Proxy-Authorization"))
        if len(seen) == 1:
            return httpx.Response(302, headers={"Location": location, "Set-Cookie": "SECRET=value; Path=/"}, stream=redirect_stream)
        return response()

    result = fetch(handler)
    expected = "https://docs.eaeunion.org" + location if location.startswith("/") else location
    assert len(seen) == 2
    assert result.requested_url == URL
    assert result.url == expected
    assert result.redirect_chain == (expected,)
    assert result.content == HTML
    assert not redirect_stream.iterated
    assert redirect_stream.closed


@pytest.mark.parametrize("location", [
    "", " /documents/399/6620/", "\n/documents/399/6620/", "documents/399/6620/",
    "//docs.eaeunion.org/documents/399/6620/", "http://docs.eaeunion.org/documents/399/6620/",
    "https://eec.eaeunion.org/documents/399/6620/", "https://evil.example/documents/399/6620/",
    "https://DOCS.EAEUNION.ORG/documents/399/6620/", "https://docs.eaeunion.org./documents/399/6620/",
    "https://user:SECRET@docs.eaeunion.org/documents/399/6620/",
    "https://docs.eaeunion.org:443/documents/399/6620/", "https://docs.eaeunion.org:8443/documents/399/6620/",
    "/documents/399/../6620/", "/documents/399/./6620/", "/documents/%2e%2e/6620/",
    "/documents/399%2f6620/", "/documents/399%252f6620/", "/documents/399\\6620/",
    "/documents/399/6620/?", "/documents/399/6620/?token=SECRET", "/documents/399/6620/#SECRET",
    "/api/documents/search/?q=76", "/documents/search?q=76", "/documents/search/",
    "/documents/search/?q=", "/documents/search/?q=++", "/documents/search/?Q=76",
    "/documents/search/?q=76&q=77", "/documents/search/?q=76&page=1", "/documents/search/?q=76&",
    "/documents/search/?q=76;page=1", "/documents/search/?q=76%2077", "/documents/search/?q=%37%36",
    "/documents/search/?q=%D0%BF%d0%be", "/documents/search/?q=%FF", "/documents/search/?q=%GG",
    "/documents/search/?q=%0A76", "/documents/search/?q=..%2F76", "/documents/search/?q=" + "a" * 201,
    "/", "/documents/", "/upload/source.pdf", "/docs/en-us/01232479/act",
])
def test_malformed_redirect_or_unobserved_route_is_closed_before_following(location):
    seen = []
    stream = ObservedStream([b"SECRET response body"])

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


def test_duplicate_location_headers_are_rejected_without_following():
    seen = []
    stream = ObservedStream()

    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers=[("Location", "/documents/search/?q=76"), ("Location", "/documents/search/?q=77")], stream=stream)

    with pytest.raises(transport.OfficialTransportError):
        fetch(handler)
    assert len(seen) == 1
    assert stream.closed


def test_search_exception_does_not_relax_ordinary_official_url_policy():
    with pytest.raises(transport.OfficialTransportError):
        transport.validate_official_url(URL)
    with pytest.raises(transport.OfficialTransportError):
        transport.fetch_official(URL, _transport=httpx.MockTransport(lambda request: pytest.fail("ordinary query reached the network")))
    assert transport.validate_official_url("https://docs.eaeunion.org/documents/399/6620/") == "https://docs.eaeunion.org/documents/399/6620/"


def test_ordinary_source_redirect_still_rejects_search_query():
    seen = []

    def handler(request):
        seen.append(request)
        return response(status=302, headers={"Location": "/documents/search/?q=76"})

    with pytest.raises(transport.OfficialTransportError):
        transport.fetch_official("https://docs.eaeunion.org/documents/399/6620/", _transport=httpx.MockTransport(handler))
    assert len(seen) == 1


def test_search_keeps_shared_redirect_limit_and_detects_loops(monkeypatch):
    monkeypatch.setattr(transport, "MAX_REDIRECTS", 1)
    seen = []

    def handler(request):
        seen.append(request)
        return response(status=307, headers={"Location": f"/documents/search/?q={len(seen)}"})

    with pytest.raises(transport.OfficialTransportError, match="redirect limit"):
        fetch(handler)
    assert len(seen) == 2
    seen.clear()

    def loop(request):
        seen.append(request)
        return response(status=308, headers={"Location": URL})

    with pytest.raises(transport.OfficialTransportError, match="redirect loop"):
        fetch(loop)
    assert len(seen) == 1


@pytest.mark.parametrize("headers", [
    {"Content-Type": "application/pdf"}, {"Content-Type": "application/json"},
    {"Content-Encoding": "gzip"}, {"Content-Length": "99999999"},
    {"Content-Length": "-1"}, {"Content-Length": "1", "Transfer-Encoding": "chunked"},
])
def test_search_invalid_body_headers_are_rejected_before_reading(headers):
    stream = ObservedStream([HTML])
    with pytest.raises(transport.OfficialTransportError):
        fetch(lambda request: httpx.Response(200, headers={"Content-Type": "text/html", **headers}, stream=stream))
    assert not stream.iterated
    assert stream.closed


def test_search_rejects_non_html_body_even_with_html_media_type():
    with pytest.raises(transport.OfficialTransportError):
        fetch(lambda request: response(b'{"error":"not a search page"}'))


@pytest.mark.parametrize("status", [204, 206, 304, 401, 403, 404, 429, 500])
def test_search_http_failure_does_not_read_error_body_or_retry(status):
    seen = []
    stream = ObservedStream([b"SECRET"])

    def handler(request):
        seen.append(request)
        return httpx.Response(status, stream=stream)

    with pytest.raises(transport.OfficialTransportError) as caught:
        fetch(handler)
    assert len(seen) == 1
    assert not stream.iterated
    assert stream.closed
    assert "SECRET" not in str(caught.value)


def test_search_obeys_shared_stream_size_limit(monkeypatch):
    assert transport.MAX_HTML_BYTES == 4 * 1024 * 1024
    monkeypatch.setattr(transport, "MAX_HTML_BYTES", 8)
    yielded = []

    def chunks():
        for chunk in [b"1234", b"5678", b"9", b"must not be read"]:
            yielded.append(chunk)
            yield chunk

    stream = ObservedStream(chunks())
    with pytest.raises(transport.OfficialTransportError):
        fetch(lambda request: httpx.Response(200, headers={"Content-Type": "text/html"}, stream=stream))
    assert len(yielded) == 3
    assert stream.closed


def test_search_slow_body_cannot_exceed_shared_elapsed_budget(monkeypatch):
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


def test_search_late_headers_are_rejected_before_body(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(transport.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(transport, "TOTAL_BUDGET_SECONDS", 2.0)
    stream = ObservedStream([HTML])

    def handler(request):
        now[0] = 3.0
        return httpx.Response(200, headers={"Content-Type": "text/html"}, stream=stream)

    with pytest.raises(transport.OfficialTransportError, match="elapsed time budget"):
        fetch(handler)
    assert not stream.iterated
    assert stream.closed


def test_search_owns_client_policy_and_sanitizes_network_errors(monkeypatch):
    seen = {}
    real_client = httpx.Client

    def client(**kwargs):
        seen.update(kwargs)
        return real_client(**kwargs)

    def handler(request):
        assert not any(name in request.headers for name in ("Cookie", "Authorization", "Proxy-Authorization"))
        raise httpx.ConnectError("SECRET user password", request=request)

    monkeypatch.setattr(transport.httpx, "Client", client)
    monkeypatch.setenv("HTTPS_PROXY", "https://SECRET:password@untrusted.example")
    monkeypatch.setenv("NETRC", "/must-not-read-ambient-credentials")
    with pytest.raises(transport.OfficialTransportError) as caught:
        fetch(handler)
    assert seen["trust_env"] is False
    assert seen["verify"] is True
    assert seen["follow_redirects"] is False
    assert seen["timeout"] == httpx.Timeout(5.0)
    assert "SECRET" not in str(caught.value)
    assert caught.value.__suppress_context__
