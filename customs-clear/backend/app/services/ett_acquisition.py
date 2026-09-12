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
MAX_PROGRESS_REPORT_BYTES = 8 * 1024 * 1024


class AcquisitionError(ValueError):
    """Incomplete, inconsistent or unsupported official download set."""


class AcquisitionDownloadError(AcquisitionError):
    """Safe identity of a failed public-source request, without response content."""
    def __init__(self, requested_url: str, progress_report_sha256: str | None = None):
        super().__init__("Official source download failed")
        self.requested_url = requested_url
        self.progress_report_sha256 = progress_report_sha256


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


class ExpandedAcquisitionReceipt(AcquisitionReceipt):
    """V2 also retains PDF bodies linked from the captured legal portal pages."""
    schema_version: Literal[2] = 2
    legal_attachment_inventory_sha256: SHA256
    attachment_downloads: tuple[DownloadRecord, ...] = Field(max_length=MAX_DOWNLOADS)


class IncompleteCaptureReport(_Frozen):
    """Diagnostic source associations only; never accepted as a capture receipt."""
    schema_version: Literal[1] = 1
    kind: Literal["ett_incomplete_capture"] = "ett_incomplete_capture"
    status: Literal["incomplete"] = "incomplete"
    mode: Literal["technical_progress_only"] = "technical_progress_only"
    storage_kind: Literal["local_development"] = "local_development"
    production_ready: Literal[False] = False
    active_rates_written: Literal[False] = False
    legal_inventory_complete: Literal[False] = False
    effective_dates_verified: Literal[False] = False
    index_stable_during_capture: Literal[False] = False
    index_start: DownloadRecord | None = None
    discovery_sha256: SHA256 | None = None
    downloads: tuple[DownloadRecord, ...] = Field(max_length=MAX_DOWNLOADS)
    attachment_downloads: tuple[DownloadRecord, ...] = Field(max_length=MAX_DOWNLOADS)
    failed_stage: Literal["initial_index", "index_documents", "legal_attachments", "final_index"]
    failed_requested_url: Annotated[StrictStr, Field(max_length=4096)]
    failed_media_type: Literal["text/html", "application/pdf"]
    reason_code: Literal["official_transport_failure"] = "official_transport_failure"

    @field_validator("failed_requested_url")
    @classmethod
    def official_failed_url(cls, value):
        return validate_official_url(value)

    @model_validator(mode="after")
    def bounded_completed_records(self):
        if len(self.downloads) + len(self.attachment_downloads) > MAX_DOWNLOADS:
            raise ValueError("Incomplete capture exceeds its download bound")
        return self


def _attachment_plan(store, records):
    from app.services.ett_legal_attachments import parse_legal_attachments

    inventory = []
    documents = {}
    unsupported = 0
    for record in records:
        if record.media_type != "text/html" or urlsplit(record.url).netloc != "docs.eaeunion.org":
            continue
        page = parse_legal_attachments(store.read(record.sha256), record.url)
        inventory.append(asdict(page))
        unsupported += len(page.unsupported_references)
        for reference in page.documents:
            documents[reference.url] = "application/pdf"
    existing = {record.requested_url for record in records}
    plan = tuple((url, media) for url, media in documents.items() if url not in existing)
    if len(records) + len(plan) > MAX_DOWNLOADS:
        raise AcquisitionError("Legal attachments exceed the download count bound")
    raw_inventory = canonical_bytes(inventory)
    return plan, hashlib.sha256(raw_inventory).hexdigest(), unsupported, raw_inventory


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


def _verify_capture_interval(index_start, records, index_end):
    if index_end.retrieved_at < index_start.retrieved_at or any(
        record.retrieved_at < index_start.retrieved_at or record.retrieved_at > index_end.retrieved_at
        for record in records
    ):
        raise AcquisitionError("Receipt timestamps fall outside acquisition interval")


def acquire_official(store: LocalArtifactStore, *, _fetch=fetch_official) -> dict:
    start = time.monotonic()
    total = 0
    index_start = None
    discovered = None
    completed_documents = []
    completed_attachments = []
    stage = "initial_index"

    def retain_failure(url, media):
        report = IncompleteCaptureReport(
            index_start=index_start,
            discovery_sha256=hashlib.sha256(discovered).hexdigest() if discovered is not None else None,
            downloads=tuple(completed_documents), attachment_downloads=tuple(completed_attachments),
            failed_stage=stage, failed_requested_url=url, failed_media_type=media,
        )
        # Bounded metadata only: no exception message, traceback, response body,
        # credentials or arbitrary transport details are copied into the report.
        raw = canonical_bytes(report.model_dump(mode="json"))
        if len(raw) > MAX_PROGRESS_REPORT_BYTES:
            raise AcquisitionError("Incomplete capture report exceeds its byte bound")
        for record in ((index_start,) if index_start is not None else ()) + tuple(completed_documents) + tuple(completed_attachments):
            store.verify(record.sha256, record.size_bytes)
        return store.put(raw)

    def download(url, media):
        nonlocal total
        if time.monotonic() - start > MAX_RUN_SECONDS:
            raise AcquisitionError("Acquisition exceeded the elapsed-time budget")
        from app.services.ett_transport import OfficialTransportError
        try:
            response = _fetch(url, expected_media=media)
        except OfficialTransportError:
            progress_digest = retain_failure(url, media)
            raise AcquisitionDownloadError(url, progress_digest) from None
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
    discovered = canonical_bytes(discovery_payload(discovery))
    plan = _plan(discovery)
    stage = "index_documents"
    for url, media in plan:
        completed_documents.append(download(url, media)[0])
    records = tuple(completed_documents)
    attachment_plan, attachment_inventory_sha, unsupported_count, raw_inventory = _attachment_plan(store, records)
    stage = "legal_attachments"
    for url, media in attachment_plan:
        completed_attachments.append(download(url, media)[0])
    attachments = tuple(completed_attachments)
    store.put(raw_inventory)
    stage = "final_index"
    index_end, end_raw = download(INDEX_URL, "text/html")
    if discovered != canonical_bytes(discovery_payload(parse_index(end_raw))):
        raise AcquisitionError("Official index changed during acquisition; repeat as a new capture")
    _verify_capture_interval(index_start, (*records, *attachments), index_end)
    # Recheck every retained object before publishing the single receipt object.
    for record in (index_start, *records, *attachments, index_end):
        store.verify(record.sha256, record.size_bytes)
    receipt = ExpandedAcquisitionReceipt(
        index_start=index_start, index_end=index_end,
        discovery_sha256=hashlib.sha256(discovered).hexdigest(), downloads=records,
        legal_attachment_inventory_sha256=attachment_inventory_sha,
        attachment_downloads=attachments,
    )
    digest = store.put(canonical_bytes(receipt.model_dump(mode="json")))
    return {
        "status": "acquired_for_review", "receipt_sha256": digest,
        "chapters": len(discovery.chapters), "downloaded_documents": len(records) + len(attachments),
        "linked_legal_pdfs": len(attachments), "unsupported_legal_references": unsupported_count,
        "legal_attachment_inventory_sha256": attachment_inventory_sha,
        "source_bytes": total, "index_stable_during_capture": True,
        "legal_inventory_complete": False, "effective_dates_verified": False,
        "production_ready": False, "active_rates_written": False,
    }


def load_incomplete_capture(store: LocalArtifactStore, digest: str) -> tuple[IncompleteCaptureReport, object | None]:
    """Verify retained source associations without granting complete-capture status.

    The completed sequence must be the exact prefix of the discovered plan and
    the failed request must be its next element. A missing middle document,
    reordered prefix or unrelated URL cannot be hidden by rehashing JSON.
    """
    raw = store.read(digest)
    if len(raw) > MAX_PROGRESS_REPORT_BYTES:
        raise AcquisitionError("Incomplete capture report exceeds its byte bound")
    report = IncompleteCaptureReport.model_validate(read_json(raw))
    if canonical_bytes(report.model_dump(mode="json")) != raw:
        raise AcquisitionError("Incomplete capture report must use canonical serialization")
    failed = (report.failed_requested_url, report.failed_media_type)
    if report.failed_stage == "initial_index":
        if report.index_start is not None or report.discovery_sha256 is not None or report.downloads or report.attachment_downloads or failed != (INDEX_URL, "text/html"):
            raise AcquisitionError("Initial-index failure has inconsistent progress")
        return report, None
    index = report.index_start
    if index is None or index.requested_url != INDEX_URL or index.url != INDEX_URL or index.media_type != "text/html":
        raise AcquisitionError("Incomplete capture index identity mismatch")
    completed = (index, *report.downloads, *report.attachment_downloads)
    if sum(record.size_bytes for record in completed) > MAX_TOTAL_BYTES:
        raise AcquisitionError("Incomplete capture exceeds its aggregate byte bound")
    if any(record.retrieved_at < index.retrieved_at for record in completed):
        raise AcquisitionError("Incomplete capture timestamps predate its index")
    for record in completed:
        store.verify(record.sha256, record.size_bytes)
    discovery = parse_index(store.read(index.sha256))
    if hashlib.sha256(canonical_bytes(discovery_payload(discovery))).hexdigest() != report.discovery_sha256:
        raise AcquisitionError("Incomplete capture discovery identity mismatch")
    expected = _plan(discovery)
    actual = tuple((record.requested_url, record.media_type) for record in report.downloads)
    if actual != expected[:len(actual)]:
        raise AcquisitionError("Completed downloads are not the exact index-plan prefix")
    if report.failed_stage == "index_documents":
        if len(actual) >= len(expected) or report.attachment_downloads or failed != expected[len(actual)]:
            raise AcquisitionError("Failure does not identify the next index-plan request")
        return report, discovery
    if actual != expected:
        raise AcquisitionError("Attachment stage requires the entire initial download plan")
    attachment_plan, _, _, _ = _attachment_plan(store, report.downloads)
    actual_attachments = tuple((record.requested_url, record.media_type) for record in report.attachment_downloads)
    if actual_attachments != attachment_plan[:len(actual_attachments)]:
        raise AcquisitionError("Completed attachments are not the exact attachment-plan prefix")
    if report.failed_stage == "legal_attachments":
        if len(actual_attachments) >= len(attachment_plan) or failed != attachment_plan[len(actual_attachments)]:
            raise AcquisitionError("Failure does not identify the next attachment request")
    elif actual_attachments != attachment_plan or failed != (INDEX_URL, "text/html"):
        raise AcquisitionError("Final-index failure has an incomplete download plan")
    return report, discovery


def load_acquisition(store: LocalArtifactStore, digest: str) -> tuple[AcquisitionReceipt, object]:
    raw = store.read(digest)
    value = read_json(raw)
    receipt_type = ExpandedAcquisitionReceipt if isinstance(value, dict) and value.get("schema_version") == 2 else AcquisitionReceipt
    receipt = receipt_type.model_validate(value)
    if canonical_bytes(receipt.model_dump(mode="json")) != raw:
        raise AcquisitionError("Receipt must use its canonical serialization")
    if receipt.index_start.requested_url != INDEX_URL or receipt.index_end.requested_url != INDEX_URL:
        raise AcquisitionError("Receipt index identity mismatch")
    if receipt.index_start.url != INDEX_URL or receipt.index_end.url != INDEX_URL:
        raise AcquisitionError("Receipt index final URL changed the discovery base")
    if receipt.index_start.media_type != "text/html" or receipt.index_end.media_type != "text/html":
        raise AcquisitionError("Index response must be HTML")
    attachments = receipt.attachment_downloads if isinstance(receipt, ExpandedAcquisitionReceipt) else ()
    records = (receipt.index_start, *receipt.downloads, *attachments, receipt.index_end)
    if sum(record.size_bytes for record in records) > MAX_TOTAL_BYTES:
        raise AcquisitionError("Receipt exceeds aggregate byte bound")
    _verify_capture_interval(receipt.index_start, records, receipt.index_end)
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
    if isinstance(receipt, ExpandedAcquisitionReceipt):
        plan, inventory_sha, _, raw_inventory = _attachment_plan(store, receipt.downloads)
        actual_attachments = tuple((record.requested_url, record.media_type) for record in attachments)
        if plan != actual_attachments or inventory_sha != receipt.legal_attachment_inventory_sha256:
            raise AcquisitionError("Receipt does not bind the discovered legal attachments")
        if store.read(inventory_sha) != raw_inventory:
            raise AcquisitionError("Retained legal attachment inventory mismatch")
    return receipt, discovery


def extract_acquisition(store: LocalArtifactStore, digest: str) -> dict:
    # Delayed import: acquiring original bytes must not run the PDF engine.
    from app.services.ett_pdf_evidence import extract_pdf_evidence

    receipt, discovery = load_acquisition(store, digest)
    references = {}
    for ref in discovery.documents:
        if ref.url not in references or ref.chapter is not None:
            references[ref.url] = ref
    extracted = []
    started = time.monotonic()
    total = 0
    records = receipt.downloads + (receipt.attachment_downloads if isinstance(receipt, ExpandedAcquisitionReceipt) else ())
    for index, record in enumerate(records):
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
