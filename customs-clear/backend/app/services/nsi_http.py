"""Fail-closed HTTP transport for official EAEU NSI registry snapshots."""

from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

from .source_http import read_requests_body


NSI_OFFICIAL_HOST = "nsi.eaeunion.org"
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
_MAX_REDIRECTS = 5
_MAX_JSON_BYTES = 64 * 1024 * 1024


def _validate_nsi_endpoint(url: str, *, expected_path: str | None = None) -> str:
    """Return an exact official NSI API URL or fail before any request.

    Dictionary identifiers remain configurable for explicit manual tools, but
    the transport is pinned to the official HTTPS origin and the two observed
    list endpoints.  Query strings are rejected because the API contract puts
    pagination and the requested date in the POST body.
    """

    value = str(url or "").strip()
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError(f"untrusted NSI API URL: {value!r}") from exc
    path_parts = (parsed.path or "").split("/")
    valid_path = bool(
        len(path_parts) == 7
        and path_parts[:4] == ["", "portal", "api", "dictionaries"]
        and re.fullmatch(r"[0-9]+", path_parts[4])
        and path_parts[5] in {"get-list-data", "get-list-data-total"}
        and path_parts[6] == ""
    )
    # Canonical URLs currently have no trailing slash.  Accept that exact shape
    # as well while continuing to reject extra path components.
    if len(path_parts) == 6:
        valid_path = bool(
            path_parts[:4] == ["", "portal", "api", "dictionaries"]
            and re.fullmatch(r"[0-9]+", path_parts[4])
            and path_parts[5] in {"get-list-data", "get-list-data-total"}
        )
    if (
        parsed.scheme.casefold() != "https"
        or (parsed.hostname or "").casefold() != NSI_OFFICIAL_HOST
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.params
        or parsed.fragment
        or not valid_path
        or (expected_path is not None and parsed.path != expected_path)
    ):
        raise RuntimeError(f"untrusted NSI API URL: {value!r}")
    return value


def _json_media_type(response: requests.Response) -> str:
    return str(response.headers.get("content-type") or "").split(";", 1)[0].strip().casefold()


def post_official_nsi_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str],
    proxy: str = "",
    timeout_sec: float = 45.0,
    retries: int = 4,
) -> Any:
    """POST JSON to one pinned NSI endpoint with prevalidated redirects.

    The session never consumes ambient proxy/netrc settings.  Redirect targets
    are validated before the next request and cannot change the exact dataset
    endpoint.  Only 307/308 preserve POST semantics; 301/302/303 fail closed.
    """

    canonical_url = _validate_nsi_endpoint(url)
    expected_path = urlparse(canonical_url).path
    explicit_proxy = str(proxy or "").strip()
    proxies = (
        {"http": explicit_proxy, "https": explicit_proxy}
        if explicit_proxy
        else {"http": None, "https": None}
    )
    last_error: Exception | None = None

    with requests.Session() as session:
        session.trust_env = False
        for attempt in range(1, max(1, int(retries)) + 1):
            current_url = canonical_url
            response = None
            try:
                for redirect_count in range(_MAX_REDIRECTS + 1):
                    response = session.post(
                        current_url,
                        json=payload,
                        headers={**headers, "Accept-Encoding": "identity"},
                        timeout=timeout_sec,
                        proxies=proxies,
                        allow_redirects=False,
                        verify=True,
                        stream=True,
                    )
                    response_url = str(response.url or current_url)
                    _validate_nsi_endpoint(response_url, expected_path=expected_path)
                    if response.status_code in _REDIRECT_STATUSES:
                        if response.status_code not in {307, 308}:
                            raise RuntimeError(
                                f"NSI API redirect does not preserve POST: {response.status_code}"
                            )
                        location = str(response.headers.get("location") or "").strip()
                        if not location:
                            raise RuntimeError("NSI API redirect is missing Location")
                        if redirect_count >= _MAX_REDIRECTS:
                            raise RuntimeError("NSI API redirect limit exceeded")
                        next_url = urljoin(current_url, location)
                        _validate_nsi_endpoint(next_url, expected_path=expected_path)
                        current_url = next_url
                        response.close()
                        continue
                    if response.status_code in _RETRYABLE_STATUSES and attempt < max(1, int(retries)):
                        raise requests.HTTPError(
                            f"retryable NSI HTTP status {response.status_code}",
                            response=response,
                        )
                    response.raise_for_status()
                    if response.status_code != 200:
                        raise RuntimeError("NSI requires a complete HTTP 200 snapshot")
                    media_type = _json_media_type(response)
                    if media_type != "application/json" and not media_type.endswith("+json"):
                        raise RuntimeError(
                            f"NSI API returned non-JSON Content-Type: {media_type or 'missing'}"
                        )
                    body = read_requests_body(response, max_bytes=_MAX_JSON_BYTES)
                    parsed = json.loads(body)
                    if not isinstance(parsed, (dict, list)):
                        raise RuntimeError("NSI API JSON root must be an object or array")
                    return parsed
                raise RuntimeError("NSI API redirect limit exceeded")
            except Exception as exc:
                last_error = exc
                if attempt >= max(1, int(retries)):
                    break
            finally:
                if response is not None:
                    response.close()
            time.sleep(min(1.2 * attempt, 8.0))

    raise RuntimeError(f"NSI POST failed: {canonical_url} | {last_error!r}")
