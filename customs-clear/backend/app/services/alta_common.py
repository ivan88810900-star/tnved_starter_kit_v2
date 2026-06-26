"""MD5 signing helpers for Alta-Soft XML APIs (see docs/integration/alta_auth.md)."""
from __future__ import annotations

import hashlib


def md5_hex(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def tik_request_secret(srchstr: str, login: str, password: str) -> str:
    return md5_hex(f"{srchstr}:{login}:{md5_hex(password)}")


def apu_request_secret(payload_id: str, login: str, password: str) -> str:
    return md5_hex(f"{payload_id}:{login}:{md5_hex(password)}")
