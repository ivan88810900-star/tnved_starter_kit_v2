"""The network trust boundary is checked before consuming unbounded bytes."""

from __future__ import annotations

import asyncio
import hashlib
import io
import zipfile

import httpx
import pytest

from app.services import exchange_rates, nsi_http, opendata_client
from app.services.source_document import SourceDocument, original_source_bytes, parse_source_xml
from app.services.source_http import bounded_chunks, read_httpx_body, validate_body_headers
from scripts import sync_eu_sanctions


@pytest.mark.parametrize("encoding", ["gzip", "br", "deflate", "gzip, identity", "zstd"])
def test_transport_rejects_compression_before_body_read(encoding):
    with pytest.raises(RuntimeError, match="Content-Encoding"):
        validate_body_headers({"content-encoding": encoding}, max_bytes=100)


@pytest.mark.parametrize("length", ["-1", "1, 1", "١", "+1", "1e4", "9" * 40])
def test_malformed_lengths_fail_closed(length):
    with pytest.raises(RuntimeError, match="Content-Length"):
        validate_body_headers({"content-length": length}, max_bytes=100)


def test_chunk_limit_stops_iterator_before_unbounded_tail():
    observed = []
    def chunks():
        for i in range(100):
            observed.append(i)
            yield b"x" * 4
    with pytest.raises(RuntimeError, match="size limit"):
        b"".join(bounded_chunks(chunks(), max_bytes=5))
    assert observed == [0, 1]
    with pytest.raises(RuntimeError, match="does not match"):
        b"".join(bounded_chunks([b"abc"], max_bytes=20, declared=4))


class _CountingStream(httpx.SyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.reads = 0
        self.closed = False
    def __iter__(self):
        for chunk in self.chunks:
            self.reads += 1
            yield chunk
    def close(self):
        self.closed = True


def test_fsa_archive_streams_to_file_and_hashes_exact_bytes(monkeypatch, tmp_path):
    payload = b"7z\xbc\xaf'\x1c" + b"x" * 100_000
    body = _CountingStream([payload[:65_536], payload[65_536:]])
    url = "https://fsa.gov.ru/opendata/7736638268-rss/data-20260901.7z"
    def handler(request):
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(200, stream=body, headers={"content-type": "application/x-7z-compressed"})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(opendata_client, "_http_client", lambda **kw: client)
    target = tmp_path / "snapshot.7z"
    result = opendata_client.download_file(url, dest=target, dataset_id="7736638268-rss")
    assert result.sha256 == hashlib.sha256(payload).hexdigest()
    assert result.size_bytes == len(payload)
    assert target.read_bytes() == payload
    assert body.closed
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("headers", [
    {"content-length": str(4 * 1024**3 + 1)},
    {"content-encoding": "gzip"},
    {"content-type": "text/html"},
])
def test_fsa_invalid_headers_never_consume_body_or_write(monkeypatch, tmp_path, headers):
    body = _CountingStream([b"7z\xbc\xaf'\x1c"])
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, stream=body, headers={"content-type": "application/x-7z-compressed", **headers})))
    monkeypatch.setattr(opendata_client, "_http_client", lambda **kw: client)
    with pytest.raises(RuntimeError):
        opendata_client.download_file(
            "https://fsa.gov.ru/opendata/7736638268-rss/data-20260901.7z",
            dest=tmp_path / "snapshot.7z", dataset_id="7736638268-rss")
    assert body.reads == 0 and body.closed
    assert not list(tmp_path.iterdir())


def test_failed_archive_body_preserves_destination_and_cleans_partial(monkeypatch, tmp_path):
    target = tmp_path / "snapshot.7z"
    target.write_bytes(b"last good")
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, stream=_CountingStream([b"7z\xbc\xaf'\x1c", b"too long"]),
        headers={"content-type": "application/octet-stream"})))
    monkeypatch.setattr(opendata_client, "_http_client", lambda **kw: client)
    with pytest.raises(RuntimeError, match="size limit"):
        opendata_client.download_file(
            "https://fsa.gov.ru/opendata/7736638268-rss/data-20260901.7z",
            dest=target, max_bytes=7, dataset_id="7736638268-rss")
    assert target.read_bytes() == b"last good"
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("path", ["../get-list-data", "./get-list-data", "1995/get-list-data;evil", "１９９５/get-list-data"])
def test_nsi_ambiguous_dictionary_paths_rejected_before_network(path):
    with pytest.raises(RuntimeError, match="untrusted NSI"):
        nsi_http._validate_nsi_endpoint("https://nsi.eaeunion.org/portal/api/dictionaries/" + path)


def test_evidence_hash_is_over_original_encoding_not_reencoded_text():
    raw = '<?xml version="1.0" encoding="windows-1251"?><doc>Товар</doc>'.encode("cp1251")
    doc = SourceDocument(raw, "application/xml")
    assert original_source_bytes(doc) == raw
    assert hashlib.sha256(raw).digest() != hashlib.sha256(doc.encode()).digest()
    assert parse_source_xml(doc).text == "Товар"
    with pytest.raises(ValueError, match="original downloaded bytes"):
        original_source_bytes(str(doc))


@pytest.mark.parametrize("raw", [b'<!DOCTYPE doc [<!ENTITY x "a">]><doc>&x;</doc>', '<doc/>'.encode("utf-16")])
def test_xml_dtd_and_wide_encodings_rejected(raw):
    with pytest.raises(ValueError):
        parse_source_xml(raw)


def test_eu_xlsx_rejects_arbitrary_zip_and_expansion_bomb(monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", "<not-ooxml/>")
    with pytest.raises(ValueError, match="OOXML"):
        sync_eu_sanctions._rows_from_eu_correlation_xlsx(buf.getvalue())
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("huge.xml", b"0" * (16 * 1024**2 + 1))
    with pytest.raises(ValueError, match="unsafe ZIP"):
        sync_eu_sanctions._rows_from_eu_correlation_xlsx(buf.getvalue())


def test_real_eu_workbook_requires_code_and_semantic_columns():
    from openpyxl import Workbook
    workbook = Workbook()
    workbook.active.append(["CN code", "Category", "Control text"])
    workbook.active.append(["85176200", "Radio", "Equipment"])
    out = io.BytesIO()
    workbook.save(out)
    rows = sync_eu_sanctions._rows_from_eu_correlation_xlsx(out.getvalue())
    assert len(rows) == 1 and rows[0]["hs_code"] == "85176200"
