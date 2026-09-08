"""Retain an official-index download set before legal candidate construction.

This is a separate technical receipt, deliberately not an ETTManifest. Discovery,
HTTPS acquisition and reproducible text extraction do not establish effective
dates, legal inventory completeness or approval. No application database is used.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import time
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator, model_validator

from app.services.ett_artifacts import LocalArtifactStore
from app.services.ett_index import INDEX_URL, parse_index
from app.services.ett_manifest import SHA256
from app.services.ett_transport import fetch_official, validate_official_url

MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_DOWNLOADS = 256
MAX_RUN_SECONDS = 20 * 60
MAX_EXTRACTION_BYTES = 512 * 1024 * 1024


class AcquisitionError(ValueError):
    """Incomplete, inconsistent or unsupported official download set."""


def canonical_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def read_json(raw: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise AcquisitionError("Duplicate receipt key")
            result[key] = value
        return result
    def invalid(_):
        raise AcquisitionError("Nonfinite receipt number")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class DownloadRecord(_Frozen):
    requested_url: Annotated[StrictStr, Field(max_length=4096)]
    url: Annotated[StrictStr, Field(max_length=4096)]
    sha256: SHA256
    size_bytes: Annotated[StrictInt, Field(gt=0, le=64 * 1024 * 1024)]
    media_type: Literal["text/html", "application/pdf"]
    retrieved_at: datetime
    redirect_chain: tuple[Annotated[StrictStr, Field(max_length=4096)], ...] = Field(max_length=3)

    @field_validator("url", "requested_url")
    @classmethod
    def official_url(cls, value):
        return validate_official_url(value)

    @field_validator("retrieved_at")
    @classmethod
    def utc_timestamp(cls, value):
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("UTC acquisition timestamp required")
        return value

    @field_validator("redirect_chain")
    @classmethod
    def official_redirects(cls, values):
        return tuple(validate_official_url(value) for value in values)

    @model_validator(mode="after")
    def coherent_redirects(self):
        chain = (self.requested_url, *self.redirect_chain)
        if len(chain) != len(set(chain)) or chain[-1] != self.url:
            raise ValueError("Redirect chain does not identify the response URL")
        if any(urlsplit(url).netloc != urlsplit(self.requested_url).netloc for url in chain):
            raise ValueError("Redirect chain must remain on the requested official host")
        if self.media_type == "text/html" and self.size_bytes > 4 * 1024 * 1024:
            raise ValueError("HTML receipt exceeds its byte bound")
        return self


class AcquisitionReceipt(_Frozen):
    schema_version: Literal[1] = 1
    kind: Literal["ett_index_acquisition"] = "ett_index_acquisition"
    mode: Literal["technical_capture_only"] = "technical_capture_only"
    storage_kind: Literal["local_development"] = "local_development"
    production_ready: Literal[False] = False
    legal_inventory_complete: Literal[False] = False
    effective_dates_verified: Literal[False] = False
    index_start: DownloadRecord
    index_end: DownloadRecord
    discovery_sha256: SHA256
    downloads: tuple[DownloadRecord, ...] = Field(min_length=98, max_length=MAX_DOWNLOADS)


def discovery_payload(discovery) -> dict:
    """Semantic index identity excludes markup noise and retrieval time."""
    result = asdict(discovery)
    for key in ("source_sha256", "size_bytes"):
        result.pop(key, None)
    return result


def _plan(discovery) -> tuple[tuple[str, str], ...]:
    documents = tuple((ref.url, "application/pdf") for ref in discovery.documents)
    links = tuple((ref.url, "application/pdf" if ref.url.lower().endswith(".pdf") else "text/html") for ref in discovery.amendment_links)
    # One original response per URL, including repeated references in the index.
    result = dict(documents)
    for url, media in links:
        if url in result and result[url] != media:
            raise AcquisitionError("Conflicting index media roles")
        result[url] = media
    if len(result) > MAX_DOWNLOADS:
        raise AcquisitionError("Official inventory exceeds the download bound")
    return tuple(result.items())


def acquire_official(store: LocalArtifactStore, *, _fetch=fetch_official) -> dict:
    start = time.monotonic()
    total = 0

    def download(url, media):
        nonlocal total
        if time.monotonic() - start > MAX_RUN_SECONDS:
            raise AcquisitionError("Acquisition exceeded the elapsed-time budget")
        response = _fetch(url, expected_media=media)
        if response.requested_url != url or response.media_type != media:
            raise AcquisitionError("Response does not match the discovered request")
        if url == INDEX_URL and response.url != INDEX_URL:
            raise AcquisitionError("Index redirect would change the fixed discovery base")
        if time.monotonic() - start > MAX_RUN_SECONDS:
            raise AcquisitionError("Acquisition exceeded the elapsed-time budget")
        total += len(response.content)
        if total > MAX_TOTAL_BYTES:
            raise AcquisitionError("Acquisition exceeds the aggregate byte bound")
        record = DownloadRecord(
            requested_url=response.requested_url, url=response.url,
            sha256=hashlib.sha256(response.content).hexdigest(), size_bytes=len(response.content),
            media_type=response.media_type, retrieved_at=response.retrieved_at,
            redirect_chain=response.redirect_chain,
        )
        store.put(response.content)
        return record, response.content

    index_start, raw = download(INDEX_URL, "text/html")
    discovery = parse_index(raw)
    plan = _plan(discovery)
    records = tuple(download(url, media)[0] for url, media in plan)
    index_end, end_raw = download(INDEX_URL, "text/html")
    discovered = canonical_bytes(discovery_payload(discovery))
    if discovered != canonical_bytes(discovery_payload(parse_index(end_raw))):
        raise AcquisitionError("Official index changed during acquisition; repeat as a new capture")
    # Recheck every retained object before publishing the single receipt object.
    for record in (index_start, *records, index_end):
        store.verify(record.sha256, record.size_bytes)
    receipt = AcquisitionReceipt(
        index_start=index_start, index_end=index_end,
        discovery_sha256=hashlib.sha256(discovered).hexdigest(), downloads=records,
    )
    digest = store.put(canonical_bytes(receipt.model_dump(mode="json")))
    return {
        "status": "acquired_for_review", "receipt_sha256": digest,
        "chapters": len(discovery.chapters), "downloaded_documents": len(records),
        "source_bytes": total, "index_stable_during_capture": True,
        "legal_inventory_complete": False, "effective_dates_verified": False,
        "production_ready": False, "active_rates_written": False,
    }


def load_acquisition(store: LocalArtifactStore, digest: str) -> tuple[AcquisitionReceipt, object]:
    raw = store.read(digest)
    receipt = AcquisitionReceipt.model_validate(read_json(raw))
    if canonical_bytes(receipt.model_dump(mode="json")) != raw:
        raise AcquisitionError("Receipt must use its canonical serialization")
    if receipt.index_start.requested_url != INDEX_URL or receipt.index_end.requested_url != INDEX_URL:
        raise AcquisitionError("Receipt index identity mismatch")
    if receipt.index_start.url != INDEX_URL or receipt.index_end.url != INDEX_URL:
        raise AcquisitionError("Receipt index final URL changed the discovery base")
    if receipt.index_start.media_type != "text/html" or receipt.index_end.media_type != "text/html":
        raise AcquisitionError("Index response must be HTML")
    records = (receipt.index_start, *receipt.downloads, receipt.index_end)
    if sum(record.size_bytes for record in records) > MAX_TOTAL_BYTES:
        raise AcquisitionError("Receipt exceeds aggregate byte bound")
    if any(record.retrieved_at < receipt.index_start.retrieved_at or record.retrieved_at > receipt.index_end.retrieved_at for record in records):
        raise AcquisitionError("Receipt timestamps fall outside acquisition interval")
    for record in records:
        store.verify(record.sha256, record.size_bytes)
    discovery = parse_index(store.read(receipt.index_start.sha256))
    payload = canonical_bytes(discovery_payload(discovery))
    end = canonical_bytes(discovery_payload(parse_index(store.read(receipt.index_end.sha256))))
    if payload != end or hashlib.sha256(payload).hexdigest() != receipt.discovery_sha256:
        raise AcquisitionError("Receipt discovery identity mismatch")
    expected = _plan(discovery)
    actual = tuple((record.requested_url, record.media_type) for record in receipt.downloads)
    if expected != actual:
        raise AcquisitionError("Receipt does not contain the complete discovered download plan")
    return receipt, discovery


def extract_acquisition(store: LocalArtifactStore, digest: str) -> dict:
    # Delayed import: acquiring original bytes must not run the PDF engine.
    from app.services.ett_pdf_evidence import extract_pdf_evidence

    receipt, discovery = load_acquisition(store, digest)
    references = {ref.url: ref for ref in discovery.documents}
    extracted = []
    started = time.monotonic()
    total = 0
    for index, record in enumerate(receipt.downloads):
        if record.media_type != "application/pdf":
            continue
        ref = references.get(record.requested_url)
        chapter = ref.chapter if ref else None
        artifact_id = f"chapter-{chapter}" if chapter else f"document-{index:03d}"
        if time.monotonic() - started > MAX_RUN_SECONDS:
            raise AcquisitionError("Extraction set exceeded the elapsed-time budget")
        report = extract_pdf_evidence(store.read(record.sha256), artifact_id=artifact_id, chapter=chapter)
        raw_report = canonical_bytes(report)
        total += len(raw_report)
        if total > MAX_EXTRACTION_BYTES or time.monotonic() - started > MAX_RUN_SECONDS:
            raise AcquisitionError("Extraction set exceeded its aggregate resource bound")
        report_digest = store.put(raw_report)
        extracted.append({"artifact_id": artifact_id, "chapter": chapter, "source_sha256": record.sha256, "report_sha256": report_digest})
    summary = {
        "kind": "ett_pdf_extraction_set", "schema_version": 1,
        "receipt_sha256": digest, "documents": extracted,
        "legal_inventory_complete": False, "effective_dates_verified": False,
        "production_ready": False, "active_rates_written": False,
    }
    summary_digest = store.put(canonical_bytes(summary))
    return {"status": "extracted_for_review", "receipt_sha256": digest, "report_sha256": summary_digest,
            "extracted_documents": len(extracted), "chapters": sum(item["chapter"] is not None for item in extracted),
            "production_ready": False, "active_rates_written": False}
