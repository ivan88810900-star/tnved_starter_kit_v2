from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import timezone
import hashlib
import json

import httpx
import pytest

from app.services import ett_transport as transport

URL = "https://eec.eaeunion.org/comission/department/catr/ett/"
HTML = b"<!DOCTYPE html><html><body>synthetic source</body></html>"
PDF = b"%PDF-1.7\nsynthetic fixture, not a legal document\n%%EOF\n"


def response(content=HTML, *, status=200, headers=None):
    return httpx.Response(
        status,
        headers={"Content-Type": "text/html", **(headers or {})},
        stream=httpx.ByteStream(content),
    )


def fetch(handler, **kwargs):
    return transport.fetch_official(URL, _transport=httpx.MockTransport(handler), **kwargs)


def test_fetch_retains_exact_original_bytes_and_immutable_metadata():
    value = fetch(lambda request: response(HTML, headers={"Content-Length": str(len(HTML))}))
    assert value.url == value.requested_url == URL
    assert value.content == HTML
    assert value.media_type == "text/html"
    assert value.retrieved_at.tzinfo == timezone.utc
    assert value.redirect_chain == ()
    with pytest.raises(FrozenInstanceError):
        value.url = "other"


def test_pdf_shape_and_original_hash_input_are_retained():
    value = fetch(lambda request: response(PDF, headers={"Content-Type": "application/pdf"}), expected_media="application/pdf")
    assert value.content == PDF
    assert value.media_type == "application/pdf"


@pytest.mark.parametrize("content,magic,offset,ending", [
    (b" \n%PDF-1.7\nSECRET\n%%EOF\n", "pdf", 2, "lf"),
    (b"%PDF-1.7 SECRET\n%%EOF\n", "pdf", 0, "other"),
    (b"<!doctype html><html>SECRET</html>", "html", None, "absent"),
    (b"PK\x03\x04SECRET", "zip", None, "absent"),
    (b"\x1f\x8bSECRET", "gzip", None, "absent"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1SECRET", "ole", None, "absent"),
    (b"SECRET", "unknown", None, "absent"),
    (b"x" * 1020 + b"%PDF-1.7\n%%EOF", "unknown", None, "absent"),
])
def test_rejected_pdf_diagnostics_are_bounded_and_do_not_relax_shape(content, magic, offset, ending):
    with pytest.raises(transport.OfficialTransportError, match="not a PDF") as caught:
        fetch(lambda request: response(content, headers={"Content-Type": "application/pdf"}), expected_media="application/pdf")
    details = caught.value.diagnostics
    assert details["kind"] == "rejected_document"
    assert details["magic"] == magic
    assert details["pdf_header_offset"] == offset
    assert details["pdf_header_ending"] == ending
    assert details["sha256"] == hashlib.sha256(content).hexdigest()
    assert details["size_bytes"] == len(content)
    assert "SECRET" not in json.dumps(details)
    assert "SECRET" not in str(caught.value)
    details["magic"] = "changed external copy"
    assert caught.value.diagnostics["magic"] == magic


@pytest.mark.parametrize("location,reason", [
    ("/documents/399/6620/?token=SECRET", "query"),
    ("/documents/399/6620/#SECRET", "fragment"),
    ("https://eec.eaeunion.org:443/SECRET", "port"),
    ("http://eec.eaeunion.org/SECRET", "scheme"),
    ("https://docs.eaeunion.org/SECRET", "cross_host"),
    ("https://user:SECRET@eec.eaeunion.org/a", "credentials"),
    ("/a/%2e%2e/SECRET", "traversal"),
])
def test_redirect_rejection_exposes_only_static_reason_without_following(location, reason):
    calls = []
    def handler(request):
        calls.append(request)
        return response(status=302, headers={"Location": location})
    with pytest.raises(transport.OfficialTransportError) as caught:
        fetch(handler)
    assert len(calls) == 1
    expected = {"kind": "rejected_redirect", "url_reason": reason}
    if reason == "port":
        expected["url_port_class"] = "default_https"
    assert caught.value.diagnostics == expected
    assert "SECRET" not in json.dumps(caught.value.diagnostics)
    assert "SECRET" not in str(caught.value)


def test_diagnostic_sanitizer_rejects_unknown_keys_values_and_unbounded_numbers():
    assert transport.sanitize_transport_diagnostics({
        "kind": "SECRET", "magic": "SECRET", "sha256": "SECRET", "size_bytes": True,
        "pdf_header_offset": 1024, "pdf_header_ending": "SECRET", "body": "SECRET",
        "url_reason": "https://example.com/?token=SECRET",
        "url_port_class": "443 SECRET", "trailing_header_whitespace_count": 1017,
    }) == {}


@pytest.mark.parametrize("gap", [b"", b" ", b"\t", b" \t" * 8])
@pytest.mark.parametrize("ending", [b"\n", b"\r", b"\r\n"])
def test_bounded_horizontal_pdf_header_gap_preserves_original_bytes(gap, ending):
    content = b"%PDF-1.7" + gap + ending + b"synthetic body\n%%EOF\n"
    value = fetch(lambda request: response(content, headers={"Content-Type": "application/pdf"}), expected_media="application/pdf")
    assert value.content == content
    assert transport._document_diagnostics(content)["trailing_header_whitespace_count"] == len(gap)


@pytest.mark.parametrize("header", [
    b" %PDF-1.7 \n", b"\xef\xbb\xbf%PDF-1.7 \n", b"\n%PDF-1.7 \n",
    b"%PDF-1.7" + b" " * 17 + b"\n", b"%PDF-1.7" + b"\t" * 17 + b"\r\n",
    b"%PDF-1.7 x\n", b"%PDF-1.7\x00\n", b"%PDF-1.7\v\n", b"%PDF-1.7\f\n",
    b"%PDF-1.70\n", b"%PDF-3.0 \n", b"%PDF-1.7" + b" " * 16,
])
def test_pdf_header_gap_does_not_admit_shifted_long_or_arbitrary_headers(header):
    content = header + b"synthetic body\n%%EOF\n"
    with pytest.raises(transport.OfficialTransportError, match="not a PDF") as caught:
        fetch(lambda request: response(content, headers={"Content-Type": "application/pdf"}), expected_media="application/pdf")
    assert 0 <= caught.value.diagnostics["trailing_header_whitespace_count"] <= 1016


def test_pdf_header_gap_still_requires_terminal_eof():
    with pytest.raises(transport.OfficialTransportError, match="EOF") as caught:
        fetch(lambda request: response(b"%PDF-1.7 \t\r\ntruncated body", headers={"Content-Type": "application/pdf"}), expected_media="application/pdf")
    assert caught.value.diagnostics["trailing_header_whitespace_count"] == 2


@pytest.mark.parametrize("port,port_class", [("443", "default_https"), ("8443", "nondefault")])
def test_explicit_port_is_classified_but_never_normalized_or_followed(port, port_class):
    calls = []
    def handler(request):
        calls.append(request)
        return response(status=302, headers={"Location": f"https://eec.eaeunion.org:{port}/SECRET"})
    with pytest.raises(transport.OfficialTransportError) as caught:
        fetch(handler)
    assert len(calls) == 1
    assert caught.value.diagnostics == {"kind": "rejected_redirect", "url_reason": "port", "url_port_class": port_class}
    assert "SECRET" not in str(caught.value)


def test_malformed_explicit_port_remains_invalid_and_has_no_arbitrary_text():
    with pytest.raises(transport.OfficialTransportError) as caught:
        transport.validate_official_url("https://eec.eaeunion.org:SECRET/path")
    assert caught.value.diagnostics == {"kind": "rejected_url", "url_reason": "port", "url_port_class": "nondefault"}
    assert "SECRET" not in str(caught.value)


@pytest.mark.parametrize("url", [
    "http://eec.eaeunion.org/path", "https://eec.eaeunion.org.evil.example/path",
    "https://evil.example/path", "https://user:secret@eec.eaeunion.org/path",
    "https://eec.eaeunion.org:443/path", "https://eec.eaeunion.org:8080/path",
    "https://EEC.EAEUNION.ORG/path", "https://eec.eaeunion.org./path",
    "https://eec.eaeunion.org", "https://eec.eaeunion.org/path?",
    "https://eec.eaeunion.org/path#", "https://eec.eaeunion.org/path?token=secret",
    " https://eec.eaeunion.org/path", "https://eec.eaeunion.org/a\nb",
    "https://eec.eaeunion.org/a\\b", "https://eec.eaeunion.org/%2fsecret",
    "https://eec.eaeunion.org/%5Csecret", "https://eec.eaeunion.org/%0asecret",
    "https://eec.eaeunion.org/%1fsecret", "https://eec.eaeunion.org/%7fsecret",
    "https://eec.eaeunion.org/%252fsecret", "https://eec.eaeunion.org/a%3Fb",
    "https://eec.eaeunion.org/a%23b", "https://eec.eaeunion.org/a/../b",
    "https://eec.eaeunion.org/a/./b", "https://eec.eaeunion.org/%2e%2e/b",
    "https://eec.eaeunion.org/%GG", "https://eec.eaeunion.org/%FF", "",
])
def test_invalid_url_rejected_before_request(url):
    calls = []
    with pytest.raises(transport.OfficialTransportError):
        transport.fetch_official(url, _transport=httpx.MockTransport(lambda request: calls.append(request)))
    assert calls == []


def test_encoded_cyrillic_and_space_and_document_portal_path_are_allowed():
    url = "https://docs.eaeunion.org/documents/399/6620/"
    assert transport.validate_official_url(url) == url
    url = "https://eec.eaeunion.org/upload/%D0%95%D0%A2%D0%A2%20notes.pdf"
    assert transport.validate_official_url(url) == url


def test_every_redirect_has_same_host_and_cookies_are_never_forwarded():
    seen = []

    def handler(request):
        seen.append(request)
        assert request.headers["Accept-Encoding"] == "identity"
        assert request.headers["Accept"] == "text/html"
        assert not any(name in request.headers for name in ("Cookie", "Authorization", "Proxy-Authorization"))
        assert request.extensions["timeout"] == {"connect": 5.0, "read": 5.0, "write": 5.0, "pool": 5.0}
        if len(seen) < 4:
            return response(b"not read", status=302, headers={"Location": f"/redirect-{len(seen)}", "Set-Cookie": "server-secret=do-not-send; Path=/"})
        return response()

    value = fetch(handler)
    assert len(seen) == 4
    assert value.url == "https://eec.eaeunion.org/redirect-3"
    assert value.redirect_chain == tuple(f"https://eec.eaeunion.org/redirect-{n}" for n in (1, 2, 3))


@pytest.mark.parametrize("location", [
    "https://docs.eaeunion.org/documents/399/6620/", "https://evil.example/file.pdf",
    "http://eec.eaeunion.org/file.pdf", "https://secret@eec.eaeunion.org/file.pdf",
    "/file.pdf?token=secret", "/file.pdf#page=1", " /file.pdf", "\n/file.pdf",
    "/a/../file.pdf", "/a/%2E%2E/file.pdf", "/file%253Ftoken", "/file%2fsecret", "",
])
def test_unsafe_redirect_rejected_without_following(location):
    calls = []

    def handler(request):
        calls.append(request)
        return response(status=302, headers={"Location": location})

    with pytest.raises(transport.OfficialTransportError):
        fetch(handler)
    assert len(calls) == 1


def test_redirect_limit_and_loop_are_bounded():
    calls = []

    def handler(request):
        calls.append(request)
        return response(status=307, headers={"Location": f"/redirect-{len(calls)}"})

    with pytest.raises(transport.OfficialTransportError, match="redirect limit"):
        fetch(handler)
    assert len(calls) == 4
    calls.clear()
    with pytest.raises(transport.OfficialTransportError, match="redirect loop"):
        fetch(lambda request: response(status=308, headers={"Location": URL}))


def test_percent_encoded_redirect_chain_matches_final_request_url():
    def handler(request):
        if str(request.url) == URL:
            return response(status=302, headers={"Location": "/%D0%95%D0%A2%D0%A2.pdf"})
        return response()

    value = fetch(handler)
    assert value.redirect_chain == (value.url,)
    assert value.url == "https://eec.eaeunion.org/%D0%95%D0%A2%D0%A2.pdf"


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


@pytest.mark.parametrize("status", [204, 206, 304, 400, 401, 403, 404, 429, 500])
def test_non200_error_bodies_are_not_read_or_logged(status):
    stream = ObservedStream([b"remote confidential secret"])
    with pytest.raises(transport.OfficialTransportError) as error:
        fetch(lambda request: httpx.Response(status, stream=stream))
    assert "secret" not in str(error.value)
    assert not stream.iterated
    assert stream.closed


@pytest.mark.parametrize("headers", [
    {"Content-Type": "application/json"}, {"Content-Type": "application/pdf"},
    {"Content-Encoding": "gzip"}, {"Content-Encoding": "br"},
    {"Content-Length": "-1"}, {"Content-Length": "bad"},
    {"Content-Length": "99999999999999"},
    {"Content-Length": "10", "Transfer-Encoding": "chunked"},
])
def test_invalid_headers_fail_before_body_read(headers):
    stream = ObservedStream([HTML])
    with pytest.raises(transport.OfficialTransportError):
        fetch(lambda request: httpx.Response(200, headers={"Content-Type": "text/html", **headers}, stream=stream))
    assert not stream.iterated
    assert stream.closed


@pytest.mark.parametrize("length", [1, len(HTML) - 1, len(HTML) + 1])
def test_content_length_mismatch_rejected(length):
    with pytest.raises(transport.OfficialTransportError):
        fetch(lambda request: response(headers={"Content-Length": str(length)}))


def test_unadvertised_stream_limit_stops_before_later_chunks(monkeypatch):
    monkeypatch.setattr(transport, "MAX_HTML_BYTES", 8)
    yielded = []

    def chunks():
        for chunk in [b"1234", b"5678", b"9", b"should never be read"]:
            yielded.append(chunk)
            yield chunk

    stream = ObservedStream(chunks())
    with pytest.raises(transport.OfficialTransportError):
        fetch(lambda request: httpx.Response(200, headers={"Content-Type": "text/html"}, stream=stream))
    assert len(yielded) == 3
    assert stream.closed


@pytest.mark.parametrize("content,media", [
    (b"", "text/html"), (b"temporary outage", "text/html"),
    (b"{\"looks_like_json\":true}", "text/html"),
    (b"<!doctype html><body>no html root", "text/html"),
    (HTML, "application/pdf"), (b" %PDF-1.7\n%%EOF", "application/pdf"),
    (b"%PDF-1.7\ntruncated", "application/pdf"),
    (b"%PDF-1.7\n%%EOF\n<script>trailing payload</script>", "application/pdf"),
])
def test_non_documents_or_truncated_pdf_rejected(content, media):
    with pytest.raises(transport.OfficialTransportError):
        fetch(lambda request: response(content, headers={"Content-Type": media}), expected_media=media)


def test_html_bom_and_charset_parameter_preserve_bytes():
    content = b"\xef\xbb\xbf\n<HTML lang='ru'><body>fixture</body></HTML>"
    value = fetch(lambda request: response(content, headers={"Content-Type": "Text/HTML; charset=utf-8"}))
    assert value.content == content


def test_slow_drip_exceeding_elapsed_budget_cannot_be_accepted(monkeypatch):
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


def test_late_headers_are_rejected_before_reading_body(monkeypatch):
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


def test_client_does_not_trust_environment_and_network_errors_are_sanitized(monkeypatch):
    seen = {}
    real_client = httpx.Client

    def client(**kwargs):
        seen.update(kwargs)
        return real_client(**kwargs)

    def handler(request):
        raise httpx.ConnectError("remote confidential token=secret", request=request)

    monkeypatch.setattr(transport.httpx, "Client", client)
    monkeypatch.setenv("HTTPS_PROXY", "https://secret:password@untrusted.example")
    with pytest.raises(transport.OfficialTransportError) as error:
        fetch(handler)
    assert seen["trust_env"] is False
    assert seen["verify"] is True
    assert seen["follow_redirects"] is False
    assert "secret" not in str(error.value)
    assert error.value.__suppress_context__


def test_duplicate_type_or_location_headers_are_rejected():
    with pytest.raises(transport.OfficialTransportError):
        fetch(lambda request: httpx.Response(200, headers=[("Content-Type", "text/html"), ("Content-Type", "text/html")], stream=httpx.ByteStream(HTML)))
    with pytest.raises(transport.OfficialTransportError):
        fetch(lambda request: httpx.Response(302, headers=[("Location", "/first"), ("Location", "/second")], stream=httpx.ByteStream(b"")))


def test_unsupported_expected_media_does_not_open_network():
    with pytest.raises(transport.OfficialTransportError, match="unsupported"):
        fetch(lambda request: pytest.fail("network must not be used"), expected_media="application/json")
