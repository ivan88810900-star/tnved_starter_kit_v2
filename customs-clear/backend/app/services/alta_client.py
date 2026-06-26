"""HTTP clients for Alta-Soft XML APIs (async httpx)."""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx

from .alta_common import apu_request_secret, tik_request_secret
from .alta_xml import parse_apu_codes, parse_apu_suggest, parse_tik_list


def _tik_base_url() -> str:
    u = os.getenv("ALTA_TIK_BASE_URL", "https://www.alta.ru/tik/xml/").strip()
    return u if u.endswith("/") else u + "/"


def _apu_base_url() -> str:
    u = os.getenv("ALTA_APU_BASE_URL", "https://www.alta.ru/tnved/xml_apu/").strip()
    return u if u.endswith("/") else u + "/"


def _timeout() -> float:
    try:
        return float(os.getenv("ALTA_HTTP_TIMEOUT", "45"))
    except ValueError:
        return 45.0


async def fetch_tik_search(
    *,
    srchstr: str,
    login: str,
    password: str,
    tncode: Optional[str] = None,
    tnfiltr: Optional[str] = None,
    page: Optional[int] = None,
) -> Dict[str, Any]:
    secret = tik_request_secret(srchstr, login, password)
    params: Dict[str, Any] = {"srchstr": srchstr, "login": login, "secret": secret}
    if tncode:
        params["tncode"] = tncode
    if tnfiltr:
        params["tnfiltr"] = tnfiltr
    if page is not None:
        params["page"] = page

    async with httpx.AsyncClient(timeout=_timeout()) as client:
        r = await client.get(_tik_base_url(), params=params)
        r.raise_for_status()
        return parse_tik_list(r.text)


async def fetch_apu_suggest(*, q: str, limit: Optional[int] = None) -> Dict[str, Any]:
    params: Dict[str, Any] = {"q": q}
    if limit is not None:
        params["limit"] = limit

    async with httpx.AsyncClient(timeout=_timeout()) as client:
        r = await client.get(_apu_base_url(), params=params)
        r.raise_for_status()
        return parse_apu_suggest(r.text)


async def fetch_apu_codes(
    *,
    payload_id: str,
    login: str,
    password: str,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    secret = apu_request_secret(payload_id, login, password)
    params: Dict[str, Any] = {"code": payload_id, "login": login, "secret": secret}
    if limit is not None:
        params["limit"] = limit

    async with httpx.AsyncClient(timeout=_timeout()) as client:
        r = await client.get(_apu_base_url(), params=params)
        r.raise_for_status()
        return parse_apu_codes(r.text)
