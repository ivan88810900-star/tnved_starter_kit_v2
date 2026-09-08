"""Bounded acquisition of original EEC bytes; no rate interpretation or DB writes.

The elapsed budget is checked at every unbuffered body chunk and on completion.
Synchronous HTTPX cannot interrupt an already running I/O call at a wall-clock
deadline; every such call also has a five-second timeout. A late response is
rejected, never recorded as a successful acquisition. Document identity and
legal completeness still require the index and extraction validators.
"""

from __future__ import annotations

import re
import time
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal
from urllib.parse import unquote, urljoin, urlsplit

import httpx

from app.services.source_http import bounded_chunks, validate_body_headers

OfficialMedia = Literal["text/html", "application/pdf"]
OFFICIAL_HOSTS = frozenset({"eec.eaeunion.org", "docs.eaeunion.org"})
MAX_HTML_BYTES = 4 * 1024 * 1024
MAX_PDF_BYTES = 64 * 1024 * 1024
MAX_REDIRECTS = 3
MAX_PDF_HEADER_WHITESPACE = 16
TOTAL_BUDGET_SECONDS = 120.0
IO_TIMEOUT_SECONDS = 5.0
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_ENCODED_FORBIDDEN = re.compile(r"%(?:0[0-9a-f]|1[0-9a-f]|25|2f|3f|23|5c|7f)", re.I)


class OfficialTransportError(ValueError):
    """Sanitized failure; optional rejected bytes are private evidence only.

    ``str``/``repr`` and diagnostics never include a response body or headers.
    Only ``_validate_document`` rejections attach bounded original bytes, which
    may be retained for inspection without becoming a successful response.
    """

    def __init__(self, message: str, *, diagnostics: dict | None = None) -> None:
        super().__init__(message)
        self._diagnostics = tuple(sanitize_transport_diagnostics(diagnostics).items())
        self._rejected_document: bytes | None = None

    @property
    def diagnostics(self) -> dict:
        return dict(self._diagnostics)


_DOCUMENT_REJECTION_MESSAGES = frozenset({
    "official source is not a PDF document", "official PDF has no terminal EOF marker",
    "official source is not an HTML document",
})


def _rejected_document_error(message: str, content: bytes) -> OfficialTransportError:
    """Create a rejection, never a successful/validated source response."""
    if message not in _DOCUMENT_REJECTION_MESSAGES or type(content) is not bytes or len(content) > MAX_PDF_BYTES:
        return OfficialTransportError(message)
    error = OfficialTransportError(message, diagnostics=_document_diagnostics(content))
    error._rejected_document = content
    return error


def _get_rejected_document_bytes(error: OfficialTransportError) -> bytes | None:
    """Read only bounded hash-matching private document-validation evidence."""
    if type(error) is not OfficialTransportError or str(error) not in _DOCUMENT_REJECTION_MESSAGES:
        return None
    raw = error._rejected_document
    if type(raw) is not bytes or len(raw) > MAX_PDF_BYTES:
        return None
    diagnostics = error.diagnostics
    if (diagnostics.get("kind") != "rejected_document" or diagnostics.get("size_bytes") != len(raw)
            or diagnostics.get("sha256") != hashlib.sha256(raw).hexdigest()):
        return None
    return raw


def sanitize_transport_diagnostics(value) -> dict:
    """Return only bounded static classifications/digests, never source text."""
    if type(value) is not dict:
        return {}
    result = {}
    vocabularies = {
        "kind": {"rejected_document", "rejected_url", "rejected_redirect"},
        "magic": {"pdf", "html", "zip", "gzip", "ole", "unknown"},
        "pdf_header_signature": {"supported_version", "unsupported_version", "not_found"},
        "pdf_header_ending": {"crlf", "cr", "lf", "other", "absent"},
        "url_reason": {"missing", "oversized", "controls", "backslash", "query", "fragment", "credentials", "port", "scheme", "host", "missing_path", "encoding", "encoded_reserved", "traversal", "malformed", "cross_host"},
        "url_port_class": {"default_https", "nondefault"},
    }
    for key, vocabulary in vocabularies.items():
        item = value.get(key)
        if type(item) is str and item in vocabulary:
            result[key] = item
    size = value.get("size_bytes")
    if type(size) is int and 0 <= size <= MAX_PDF_BYTES:
        result["size_bytes"] = size
    digest = value.get("sha256")
    if type(digest) is str and re.fullmatch(r"[0-9a-f]{64}", digest):
        result["sha256"] = digest
    if "pdf_header_offset" in value:
        offset = value["pdf_header_offset"]
        if offset is None or type(offset) is int and 0 <= offset <= 1019:
            result["pdf_header_offset"] = offset
    whitespace_count = value.get("trailing_header_whitespace_count")
    if type(whitespace_count) is int and 0 <= whitespace_count <= 1016:
        result["trailing_header_whitespace_count"] = whitespace_count
    return result


def _url_diagnostics(url, *, kind: str = "rejected_url") -> dict:
    reason = "malformed"
    port_class = None
    if not isinstance(url, str) or not url:
        reason = "missing"
    elif len(url) > 4096:
        reason = "oversized"
    elif any(ord(c) < 33 or ord(c) == 127 for c in url):
        reason = "controls"
    elif "\\" in url:
        reason = "backslash"
    elif "?" in url:
        reason = "query"
    elif "#" in url:
        reason = "fragment"
    else:
        try:
            parsed = urlsplit(url)
            if "@" in parsed.netloc:
                reason = "credentials"
            elif ":" in parsed.netloc:
                reason = "port"
                try:
                    port_class = "default_https" if parsed.scheme == "https" and parsed.port == 443 else "nondefault"
                except ValueError:
                    port_class = "nondefault"
            elif parsed.scheme and parsed.scheme != "https":
                reason = "scheme"
            elif parsed.netloc and parsed.netloc not in OFFICIAL_HOSTS:
                reason = "host"
            elif not parsed.path.startswith("/"):
                reason = "missing_path"
            elif re.search(r"%(?![0-9a-fA-F]{2})", parsed.path):
                reason = "encoding"
            elif _ENCODED_FORBIDDEN.search(parsed.path):
                reason = "encoded_reserved"
            elif any(part in {".", ".."} for part in unquote(parsed.path, encoding="utf-8", errors="strict").split("/")):
                reason = "traversal"
        except (ValueError, UnicodeError):
            reason = "encoding"
    result = {"kind": kind, "url_reason": reason}
    if port_class is not None:
        result["url_port_class"] = port_class
    return result


def _document_diagnostics(content: bytes) -> dict:
    prefix = content[:1024]
    offset = prefix.find(b"%PDF-")
    stripped = prefix.removeprefix(b"\xef\xbb\xbf").lstrip()
    magic = "unknown"
    if offset >= 0:
        magic = "pdf"
    elif re.match(rb"(?:<!doctype\s+html|<html)(?:\s|>)", stripped, re.I):
        magic = "html"
    elif prefix.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        magic = "zip"
    elif prefix.startswith(b"\x1f\x8b"):
        magic = "gzip"
    elif prefix.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        magic = "ole"
    signature = "not_found"
    ending = "absent"
    whitespace_count = 0
    if offset >= 0:
        header = prefix[offset:]
        signature = "supported_version" if re.match(rb"%PDF-[12]\.[0-9]", header) else "unsupported_version"
        whitespace_count = len(header[8:]) - len(header[8:].lstrip(b" \t"))
        if len(header) > 8:
            ending = "crlf" if header[8:10] == b"\r\n" else "cr" if header[8:9] == b"\r" else "lf" if header[8:9] == b"\n" else "other"
    return {"kind": "rejected_document", "magic": magic, "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(), "pdf_header_offset": offset if offset >= 0 else None,
            "pdf_header_signature": signature, "pdf_header_ending": ending,
            "trailing_header_whitespace_count": whitespace_count}


@dataclass(frozen=True)
class OfficialResponse:
    url: str
    requested_url: str
    content: bytes
    media_type: OfficialMedia
    retrieved_at: datetime
    # Each followed destination, including the final URL after a redirect.
    redirect_chain: tuple[str, ...] = ()


def validate_official_url(url: str) -> str:
    """Require an unambiguous HTTPS origin compatible with ETT manifests.

Explicit ports (including 443) and even empty query/fragment delimiters are
forbidden. Encoded Cyrillic and spaces remain valid; encoded path separators,
controls, traversal, query delimiters and double-encoding do not.
"""
    if (
        not isinstance(url, str)
        or not 1 <= len(url) <= 4096
        or any(ord(char) < 33 or ord(char) == 127 for char in url)
        or any(char in url for char in "\\?#")
    ):
        raise OfficialTransportError("invalid official source URL", diagnostics=_url_diagnostics(url))
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc not in OFFICIAL_HOSTS
            or not parsed.path.startswith("/")
            or re.search(r"%(?![0-9a-fA-F]{2})", parsed.path)
            or _ENCODED_FORBIDDEN.search(parsed.path)
        ):
            raise ValueError
        decoded = unquote(parsed.path, encoding="utf-8", errors="strict")
        if any(part in {".", ".."} for part in decoded.split("/")):
            raise ValueError
    except (ValueError, UnicodeError):
        raise OfficialTransportError("invalid official source URL", diagnostics=_url_diagnostics(url)) from None
    return url


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise OfficialTransportError("official source exceeded the elapsed time budget")
    return min(remaining, IO_TIMEOUT_SECONDS)


def _checked_raw_chunks(response: httpx.Response, deadline: float):
    # No chunk_size argument: do not wait for HTTPX to buffer an entire fixed-size
    # chunk while a slow peer keeps sending tiny pieces below the read timeout.
    iterator = iter(response.iter_raw())
    while True:
        _remaining(deadline)
        try:
            chunk = next(iterator)
        except StopIteration:
            _remaining(deadline)
            return
        _remaining(deadline)
        yield chunk


def _validate_document(content: bytes, expected_media: OfficialMedia) -> None:
    if expected_media == "application/pdf":
        # Preserve originals while tolerating only a bounded horizontal gap
        # between the PDF version and its mandatory CR/LF. A shifted header,
        # arbitrary suffix bytes, vertical whitespace or an overlong gap fail.
        if not re.match(rb"%PDF-[12]\.[0-9][ \t]{0,16}(?:\r|\n)", content[:8 + MAX_PDF_HEADER_WHITESPACE + 2]):
            raise _rejected_document_error("official source is not a PDF document", content)
        if not re.search(rb"%%EOF[\t\n\f\r ]*\Z", content[-2048:]):
            raise _rejected_document_error("official PDF has no terminal EOF marker", content)
        return
    # This proves HTML shape, not a valid ETT index. Captcha/login/error pages
    # must additionally fail the separate exact chapter/document discovery gate.
    prefix = content[:64 * 1024].removeprefix(b"\xef\xbb\xbf").lstrip()
    if not re.match(rb"(?:<!doctype\s+html(?:\s|>)|<html(?:\s|>))", prefix, re.I):
        raise _rejected_document_error("official source is not an HTML document", content)
    if not re.search(rb"<html(?:\s|>)", prefix, re.I):
        raise _rejected_document_error("official source is not an HTML document", content)


def fetch_official(
    url: str,
    *,
    expected_media: OfficialMedia = "text/html",
    _transport: httpx.BaseTransport | None = None,
) -> OfficialResponse:
    """Acquire one source with same-host redirects and original-byte limits.

    ``_transport`` is an explicit testing seam for ``httpx.MockTransport``. A new
    client always owns TLS, timeout, redirect, proxy, auth and cookie policy;
    callers cannot inject an ambient authenticated client. There are no retries
    or fallback origins. Redirect responses close without reading their bodies.
    """
    return _fetch_bounded(
        url, expected_media=expected_media, _transport=_transport,
        url_validator=validate_official_url,
        redirect_target=_official_redirect_target,
    )


def _official_redirect_target(current_url: str, location: str) -> str:
    # Validate raw Location first: urljoin can normalize away traversal or strip
    # leading whitespace/control characters. This remains the query-free policy
    # used by every ordinary source acquisition.
    if (
        any(ord(char) < 33 or ord(char) == 127 for char in location)
        or any(char in location for char in "\\?#")
        or _ENCODED_FORBIDDEN.search(location)
        or any(part in {".", ".."} for part in location.split("/"))
    ):
        raise OfficialTransportError("official source returned an invalid redirect", diagnostics=_url_diagnostics(location, kind="rejected_redirect"))
    return validate_official_url(urljoin(current_url, location))


def _fetch_bounded(
    url: str,
    *,
    expected_media: OfficialMedia,
    url_validator: Callable[[str], str],
    redirect_target: Callable[[str, str], str],
    _transport: httpx.BaseTransport | None = None,
) -> OfficialResponse:
    """Private shared I/O; each entry point supplies its own narrow URL policy.

    URL policies never change TLS, authentication, cookies, same-origin rules,
    redirect counts, body limits, document validation or elapsed-time bounds.
    """
    requested_url = url_validator(url)
    if expected_media not in {"text/html", "application/pdf"}:
        raise OfficialTransportError("unsupported official source media type")
    limit = MAX_PDF_BYTES if expected_media == "application/pdf" else MAX_HTML_BYTES
    deadline = time.monotonic() + TOTAL_BUDGET_SECONDS
    origin = urlsplit(requested_url).netloc
    current_url = requested_url
    chain: list[str] = []
    visited: set[str] = set()
    try:
        with httpx.Client(
            verify=True,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(IO_TIMEOUT_SECONDS),
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
            transport=_transport,
        ) as client:
            while True:
                timeout = _remaining(deadline)
                client.cookies.clear()
                request = client.build_request(
                    "GET",
                    current_url,
                    headers={
                        "Accept": expected_media,
                        "Accept-Encoding": "identity",
                        "User-Agent": "CustomsClear-ETT-Acquisition/1",
                    },
                    timeout=httpx.Timeout(timeout),
                )
                actual_url = url_validator(str(request.url))
                if actual_url in visited:
                    raise OfficialTransportError("official source redirect loop")
                visited.add(actual_url)
                response = client.send(request, stream=True, auth=None, follow_redirects=False)
                try:
                    _remaining(deadline)
                    if response.status_code in _REDIRECT_STATUSES:
                        if len(chain) >= MAX_REDIRECTS:
                            raise OfficialTransportError("official source exceeded the redirect limit")
                        location = response.headers.get("location", "")
                        if not location or len(response.headers.get_list("location")) != 1:
                            raise OfficialTransportError("official source returned an invalid redirect", diagnostics=_url_diagnostics(location, kind="rejected_redirect"))
                        try:
                            target = redirect_target(actual_url, location)
                        except OfficialTransportError as exc:
                            raise OfficialTransportError("invalid official source URL", diagnostics={**exc.diagnostics, "kind": "rejected_redirect"}) from None
                        if urlsplit(target).netloc != origin:
                            raise OfficialTransportError("official source redirected to a different host", diagnostics={"kind": "rejected_redirect", "url_reason": "cross_host"})
                        # Store the exact URL spelling sent by HTTPX, including
                        # percent-encoding for Unicode relative Location values.
                        target = url_validator(str(httpx.URL(target)))
                        chain.append(target)
                        current_url = target
                        continue
                    if response.status_code != 200:
                        raise OfficialTransportError("official source did not return HTTP 200")
                    media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if len(response.headers.get_list("content-type")) != 1 or media_type != expected_media:
                        raise OfficialTransportError("official source returned an unexpected media type")
                    if response.headers.get("transfer-encoding") and response.headers.get("content-length"):
                        raise OfficialTransportError("official source returned ambiguous body framing")
                    declared = validate_body_headers(response.headers, max_bytes=limit)
                    content = b"".join(bounded_chunks(
                        _checked_raw_chunks(response, deadline), max_bytes=limit, declared=declared,
                    ))
                    _validate_document(content, expected_media)
                    _remaining(deadline)
                    return OfficialResponse(
                        url=actual_url,
                        requested_url=requested_url,
                        content=content,
                        media_type=expected_media,
                        retrieved_at=datetime.now(timezone.utc),
                        redirect_chain=tuple(chain),
                    )
                finally:
                    response.close()
    except OfficialTransportError:
        raise
    except (httpx.HTTPError, RuntimeError, OSError, ValueError):
        # Never embed upstream exception text: it can contain headers, bodies,
        # request URLs or credentials supplied by the remote endpoint.
        raise OfficialTransportError("official source acquisition failed") from None
