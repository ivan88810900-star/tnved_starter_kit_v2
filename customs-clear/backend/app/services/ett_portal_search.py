"""Capture the observed public legal-portal search form, only for discovery.

The original list bodies SHA256 d9c2c6856efd697ce8a54bda27f7673e88bd344aeaeb9aa5d06331546e1da729
and 79c4909e92cb4a573dc2347e997dbb7bc7b186d560d1c374a209860d16af586f contain
``<form action="/documents/search/">`` with input ``name="q"``. The omitted
method has HTML's GET default. This module implements only that observed form,
not a guessed API. Returned original bytes are discovery evidence, not an
approved manifest artifact, verified act identity or proof of an effective date.

Ordinary ETT source and manifest validators continue to forbid all queries.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit

import httpx

from .ett_transport import (
    OfficialResponse,
    OfficialTransportError,
    _fetch_bounded,
    validate_official_url,
)


PORTAL_SEARCH_URL = "https://docs.eaeunion.org/documents/search/"
MAX_QUERY_CHARACTERS = 200
_DOCUMENT_PATH = re.compile(
    r"/(?:documents/[0-9]+/[0-9]+/?|docs/ru-ru/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*/?)"
)


def _query(value: str) -> str:
    if (
        type(value) is not str
        or not 1 <= len(value) <= MAX_QUERY_CHARACTERS
        or not value.strip()
        or not value.isprintable()
        or any(part in {".", ".."} for part in re.split(r"[/\\]", value))
    ):
        raise OfficialTransportError("invalid public portal search query")
    return value


def _validate_search_url(url: str) -> str:
    """Allow exactly one canonical q or a query-free canonical document URL."""
    if (
        type(url) is not str
        or not 1 <= len(url) <= 4096
        or not url.isascii()
        or any(ord(char) < 33 or ord(char) == 127 for char in url)
        or "\\" in url
        or "#" in url
    ):
        raise OfficialTransportError("invalid public portal search URL")
    try:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.netloc != "docs.eaeunion.org":
            raise ValueError
        if parts.path == "/documents/search/":
            pairs = parse_qsl(
                parts.query, keep_blank_values=True, strict_parsing=True,
                max_num_fields=1, encoding="utf-8", errors="strict",
            )
            if len(pairs) != 1 or pairs[0][0] != "q":
                raise ValueError
            query = _query(pairs[0][1])
            # This rejects alternate encodings, delimiters, duplicate keys,
            # malformed escapes and unescaped reserved characters. Query text
            # is encoded once by the ordinary HTML-form urlencode convention.
            if url != PORTAL_SEARCH_URL + "?" + urlencode({"q": query}):
                raise ValueError
        else:
            validate_official_url(url)
            if not _DOCUMENT_PATH.fullmatch(parts.path):
                raise ValueError
    except (ValueError, UnicodeError):
        raise OfficialTransportError("invalid public portal search URL") from None
    return url


def _search_redirect_target(current_url: str, location: str) -> str:
    # Only explicit absolute or root-relative destinations are accepted. Check
    # before urljoin so neither it nor HTTPX can erase traversal or controls.
    if (
        not location
        or len(location) > 4096
        or not location.isascii()
        or any(ord(char) < 33 or ord(char) == 127 for char in location)
        or any(char in location for char in "\\#")
        or not (location.startswith("https://") or location.startswith("/"))
        or location.startswith("//")
    ):
        raise OfficialTransportError("invalid public portal search redirect")
    try:
        path = urlsplit(location).path
        if any(part in {".", ".."} for part in path.split("/")):
            raise ValueError
        # Validate the pre-join spelling too: encoded separators/traversal are
        # outside both exact search and canonical document paths.
        absolute = "https://docs.eaeunion.org" + location if location.startswith("/") else location
        _validate_search_url(absolute)
        return _validate_search_url(urljoin(current_url, location))
    except (ValueError, UnicodeError):
        raise OfficialTransportError("invalid public portal search redirect") from None


def fetch_portal_search(
    query: str,
    *,
    _transport: httpx.BaseTransport | None = None,
) -> OfficialResponse:
    """Fetch public search HTML with the ordinary 4 MiB/timeout/redirect bounds.

    No authentication, ambient cookies/proxies, retries, DB writes or legal
    interpretation occur. SHA256 is computed from ``response.content`` by the
    ordinary acquisition evidence writer; the returned bytes are unmodified.
    ``_transport`` is the same explicit MockTransport test seam as fetch_official.
    """
    requested_url = PORTAL_SEARCH_URL + "?" + urlencode({"q": _query(query)})
    return _fetch_bounded(
        requested_url, expected_media="text/html", _transport=_transport,
        url_validator=_validate_search_url,
        redirect_target=_search_redirect_target,
    )


def validate_portal_search_page_url(url: str) -> str:
    """Validate a search page, including the observed final PAGEN_1 field.

    Accepting a spelling does not establish that its pagination link was
    observed. A caller that traverses results must retain and verify that link
    against the parent page's original bytes before fetching it.
    """
    if type(url) is not str or not 1 <= len(url) <= 4096:
        raise OfficialTransportError("invalid public portal search page URL")
    base, marker, number = url.rpartition("&PAGEN_1=")
    if marker:
        if not re.fullmatch(r"[1-9][0-9]*", number):
            raise OfficialTransportError("invalid public portal search page URL")
    else:
        base = url
    _validate_search_url(base)
    if not base.startswith(PORTAL_SEARCH_URL + "?q="):
        raise OfficialTransportError("invalid public portal search page URL")
    return url


def _search_page_identity(url: str) -> tuple[str, int]:
    validate_portal_search_page_url(url)
    fields = dict(parse_qsl(urlsplit(url).query, strict_parsing=True, encoding="utf-8", errors="strict"))
    return fields["q"], int(fields.get("PAGEN_1", "1"))


def fetch_portal_search_page(
    url: str,
    *,
    _transport: httpx.BaseTransport | None = None,
) -> OfficialResponse:
    """Capture one observed page URL without changing query or page on redirect.

    Only this entry point accepts the portal's observed PAGEN_1 parameter.
    Ordinary fetch_official and fetch_portal_search policies are unchanged.
    """
    expected_identity = _search_page_identity(url)

    def validate_page(target: str) -> str:
        if _search_page_identity(target) != expected_identity:
            raise OfficialTransportError("portal search redirect changed query or page")
        return target

    def redirect_page(current: str, location: str) -> str:
        # As with the q-only form, reject before joining so dot segments and
        # control characters cannot be normalized into an acceptable URL.
        if (
            not location or len(location) > 4096 or not location.isascii()
            or any(ord(char) < 33 or ord(char) == 127 for char in location)
            or any(char in location for char in "\\#")
            or not (location.startswith("https://") or location.startswith("/"))
            or location.startswith("//")
        ):
            raise OfficialTransportError("invalid public portal search page redirect")
        absolute = "https://docs.eaeunion.org" + location if location.startswith("/") else location
        validate_page(absolute)
        return validate_page(urljoin(current, location))

    return _fetch_bounded(
        url, expected_media="text/html", _transport=_transport,
        url_validator=validate_page, redirect_target=redirect_page,
    )
