"""Resource limits shared by official-source transports.

Callers must open responses in streaming mode and validate origin/status/MIME
before iterating. Identity encoding makes the byte bound apply to wire bytes as
well as decoded bytes; decompression must not hide an unbounded response.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping

CHUNK_SIZE = 64 * 1024


def validate_body_headers(headers: Mapping[str, str], *, max_bytes: int) -> int | None:
    encoding = str(headers.get("content-encoding") or "").strip().casefold()
    if encoding not in {"", "identity"}:
        raise RuntimeError("official source returned unsupported Content-Encoding")
    length = str(headers.get("content-length") or "").strip()
    if not length:
        return None
    if not re.fullmatch(r"[0-9]{1,20}", length):
        raise RuntimeError("official source returned invalid Content-Length")
    declared = int(length)
    if declared > max_bytes:
        raise RuntimeError("official source response exceeds the size limit")
    return declared


def bounded_chunks(
    chunks: Iterable[bytes], *, max_bytes: int, declared: int | None = None
) -> Iterator[bytes]:
    size = 0
    for chunk in chunks:
        size += len(chunk)
        if size > max_bytes:
            raise RuntimeError("official source response exceeds the size limit")
        if chunk:
            yield chunk
    if size == 0:
        raise RuntimeError("official source returned an empty response")
    if declared is not None and size != declared:
        raise RuntimeError("official source Content-Length does not match body size")


async def read_async_body(response, *, max_bytes: int) -> bytes:
    declared = validate_body_headers(response.headers, max_bytes=max_bytes)
    result = bytearray()
    async for chunk in response.aiter_bytes(chunk_size=CHUNK_SIZE):
        if len(result) + len(chunk) > max_bytes:
            raise RuntimeError("official source response exceeds the size limit")
        result.extend(chunk)
    if not result:
        raise RuntimeError("official source returned an empty response")
    if declared is not None and len(result) != declared:
        raise RuntimeError("official source Content-Length does not match body size")
    return bytes(result)


def read_httpx_body(response, *, max_bytes: int) -> bytes:
    declared = validate_body_headers(response.headers, max_bytes=max_bytes)
    return b"".join(bounded_chunks(
        response.iter_bytes(chunk_size=CHUNK_SIZE), max_bytes=max_bytes, declared=declared,
    ))


def read_requests_body(response, *, max_bytes: int) -> bytes:
    declared = validate_body_headers(response.headers, max_bytes=max_bytes)
    return b"".join(bounded_chunks(
        response.iter_content(chunk_size=CHUNK_SIZE), max_bytes=max_bytes, declared=declared,
    ))
