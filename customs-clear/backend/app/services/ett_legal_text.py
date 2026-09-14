"""Native text from retained, source-bound legal PDFs; no OCR or legal approval.

Only successful PDF records are eligible. Their original bytes and every declared
parent attachment are replayed before the bounded PDF worker runs. Pages without
native words are OCR candidates, not proof that a page contains a scanned image.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import re
import time

from .ett_acquisition import DownloadRecord, read_json
from .ett_artifacts import LocalArtifactStore
from .ett_discovery_audit import canonical_json_bytes
from .ett_legal_attachments import parse_legal_attachments, validate_attachment_url
from .ett_legal_capture import _page_identity, _replay_plan
from .ett_legal_metadata import parse_legal_metadata
from .ett_pdf_evidence import (
    MAX_OUTPUT_BYTES, MAX_PDF_BYTES, WORKER_TIMEOUT_SECONDS, extract_pdf_evidence,
)
from .ett_transport import _validate_document

MAX_PDFS = 256
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_REPORT_BYTES = 16 * 1024 * 1024
MAX_RUN_SECONDS = 20 * 60
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_METADATA = tuple(DownloadRecord.model_fields)
_BINDING = {"page_sha256", "page_url", "attachment_discovery_sha256", "reference_index"}


class LegalTextError(ValueError):
    """Static input or extraction failure, with no upstream text."""


class _BudgetError(LegalTextError):
    pass


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _instant() -> str:
    return datetime.now(timezone.utc).isoformat()


class _Reader:
    def __init__(self, store, started):
        self.store, self.started = store, started
        self.seen, self.total, self.stop_reason = set(), 0, None

    def check_time(self, reserve=0):
        if time.monotonic() - self.started + reserve >= MAX_RUN_SECONDS:
            self.stop_reason = "elapsed_time_budget"
            raise _BudgetError(self.stop_reason)

    def charge(self, digest, size):
        if digest not in self.seen:
            if self.total + size > MAX_TOTAL_BYTES:
                self.stop_reason = "artifact_byte_budget"
                raise _BudgetError(self.stop_reason)
            self.total += size
            self.seen.add(digest)

    def read(self, digest):
        self.check_time()
        if type(digest) is not str or not _SHA.fullmatch(digest):
            raise LegalTextError("artifact_integrity_failed")
        raw = self.store.read(digest)
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_PDF_BYTES or _sha(raw) != digest:
            raise LegalTextError("artifact_integrity_failed")
        self.charge(digest, len(raw))
        return raw

    def put(self, raw):
        digest = _sha(raw)
        self.charge(digest, len(raw))
        if self.store.put(raw) != digest:
            raise LegalTextError("extraction_evidence_storage_failed")
        return digest


def _metadata(row, media):
    if type(row) is not dict or row.get("status") != "captured":
        raise LegalTextError("successful_capture_record_required")
    metadata = DownloadRecord.model_validate({key: row[key] for key in _METADATA})
    if metadata.media_type != media or row.get("document_validation_passed") is not True:
        raise LegalTextError("capture_media_or_validation_mismatch")
    return metadata


def _original(reader, metadata):
    raw = reader.read(metadata.sha256)
    if len(raw) != metadata.size_bytes:
        raise LegalTextError("artifact_size_mismatch")
    _validate_document(raw, metadata.media_type)
    return raw


def _summary(evidence, raw, artifact_id):
    if (type(evidence) is not dict or evidence.get("artifact_sha256") != _sha(raw)
            or evidence.get("artifact_id") != artifact_id or evidence.get("size_bytes") != len(raw)
            or evidence.get("chapter") is not None or evidence.get("mode") != "extraction_review"
            or evidence.get("can_promote") is not False or evidence.get("legal_rates_resolved") != 0):
        raise LegalTextError("native_evidence_provenance_failed")
    pages = evidence.get("pages")
    if type(pages) is not list or not pages or len(pages) != evidence.get("page_count"):
        raise LegalTextError("native_evidence_counts_failed")
    words = rows = 0
    empty = []
    for index, page in enumerate(pages, 1):
        if type(page) is not dict or page.get("page") != index or type(page.get("rows")) is not list:
            raise LegalTextError("native_evidence_counts_failed")
        page_words = 0
        for row in page["rows"]:
            if type(row) is not dict or type(row.get("words")) is not list:
                raise LegalTextError("native_evidence_counts_failed")
            page_words += len(row["words"])
        rows += len(page["rows"])
        words += page_words
        if page_words == 0:
            empty.append(index)
    if words != evidence.get("word_count"):
        raise LegalTextError("native_evidence_counts_failed")
    return {"page_count": len(pages), "word_count": words, "row_count": rows,
            "no_native_text_pages": empty, "no_native_text_page_count": len(empty),
            "ocr_candidate_pages": empty, "all_pages_without_native_text": len(empty) == len(pages),
            "scan_image_presence_verified": False}


def extract_legal_documents(store: LocalArtifactStore, capture_report_raw: bytes, *, extract=extract_pdf_evidence) -> dict:
    """Extract declared successful PDFs, preserving bounded partial progress.

    Completion describes these captured records only. Capture status, legal
    completeness, missing acts, unsupported attachments and legal dates are never
    inferred from successful text extraction. No source URL is fetched here.
    """
    started, started_at = time.monotonic(), _instant()
    reader = _Reader(store, started)
    try:
        if type(capture_report_raw) is not bytes or not 0 < len(capture_report_raw) <= MAX_REPORT_BYTES:
            raise ValueError
        capture = read_json(capture_report_raw)
        if (type(capture) is not dict or capture.get("schema_version") != 1
                or capture.get("kind") != "ett_observed_legal_document_capture"
                or type(capture.get("documents")) is not list or type(capture.get("pdfs")) is not list):
            raise ValueError
        audit = _replay_plan(reader.read(capture["discovery_report_sha256"]), reader)
        if capture.get("capture_plan_sha256") != audit["capture_plan_sha256"] or capture.get("source_inputs") != audit["inputs"]:
            raise ValueError
        pages = {}
        for row in capture["documents"]:
            if type(row) is not dict or type(row.get("plan_entry_index")) is not int:
                raise ValueError
            index = row["plan_entry_index"]
            if not 0 <= index < len(audit["capture_plan"]):
                raise ValueError
            target = audit["capture_plan"][index]
            if row.get("requested_url") != target["page_url"] or row.get("expected_identity") != target["identity"]:
                raise ValueError
            if row["requested_url"] in pages:
                raise ValueError
            pages[row["requested_url"]] = (row, target)
        for row in capture["pdfs"]:
            if type(row) is not dict or row.get("status") not in ("captured", "failed"):
                raise ValueError
        requested = [row.get("requested_url") for row in capture["pdfs"]]
        if any(type(url) is not str for url in requested) or len(set(requested)) != len(requested):
            raise ValueError
    except Exception:
        raise LegalTextError(reader.stop_reason or "capture_report_replay_failed") from None

    capture_sha = reader.put(capture_report_raw)
    records, verified_parents, parent_metadata = [], {}, {}
    eligible = [(i, row) for i, row in enumerate(capture["pdfs"]) if row["status"] == "captured"]
    stop_reason, pending_index = None, None

    def parent(binding):
        key = binding["page_url"]
        if key not in verified_parents:
            row, target = pages[key]
            metadata = _metadata(row, "text/html")
            if metadata.url != target["page_url"] or row.get("attachment_parse_status") != "parsed":
                raise LegalTextError("parent_page_identity_failed")
            raw = _original(reader, metadata)
            _page_identity(raw, target["identity"])
            attachments = parse_legal_attachments(raw, metadata.url)
            actual = canonical_json_bytes(asdict(attachments))
            if reader.read(row["attachment_discovery_sha256"]) != actual:
                raise LegalTextError("attachment_discovery_replay_failed")
            verified_parents[key] = (row, attachments)
            observed_metadata = {"source_url": metadata.url, "source_sha256": metadata.sha256,
                                 "source_size_bytes": metadata.size_bytes, "status": "failed"}
            parent_metadata[key] = observed_metadata
            try:
                payload = canonical_json_bytes(parse_legal_metadata(raw, metadata.url))
                observed_metadata.update(status="extracted", metadata_report_sha256=reader.put(payload),
                                         metadata_report_size_bytes=len(payload))
            except _BudgetError:
                raise
            except Exception:
                observed_metadata["reason"] = "parent_metadata_extraction_failed"
        row, attachments = verified_parents[key]
        if (binding["page_sha256"] != row["sha256"]
                or binding["attachment_discovery_sha256"] != row["attachment_discovery_sha256"]):
            raise LegalTextError("attachment_parent_binding_failed")
        index = binding["reference_index"]
        if type(index) is not int or not 0 <= index < len(attachments.documents):
            raise LegalTextError("attachment_reference_index_failed")
        return attachments.documents[index]

    for capture_index, pdf in eligible:
        if len(records) >= MAX_PDFS:
            stop_reason, pending_index = "pdf_count_budget", capture_index
            break
        result = {"capture_pdf_index": capture_index, "status": "failed"}
        records.append(result)
        try:
            reader.check_time(WORKER_TIMEOUT_SECONDS + 1)
            metadata = _metadata(pdf, "application/pdf")
            validate_attachment_url(metadata.requested_url)
            validate_attachment_url(metadata.url)
            refs = pdf.get("source_references")
            if type(refs) is not list or not refs:
                raise LegalTextError("attachment_source_binding_missing")
            observed = set()
            for binding in refs:
                if type(binding) is not dict or binding.keys() != _BINDING:
                    raise LegalTextError("attachment_source_binding_invalid")
                encoded = canonical_json_bytes(binding)
                if encoded in observed:
                    raise LegalTextError("attachment_source_binding_duplicate")
                observed.add(encoded)
                if parent(binding).url != metadata.requested_url:
                    raise LegalTextError("attachment_source_url_mismatch")
            raw = _original(reader, metadata)
            result.update(source_sha256=metadata.sha256, source_size_bytes=metadata.size_bytes,
                          requested_url=metadata.requested_url, source_url=metadata.url,
                          source_references=refs, source_bindings_replayed=True,
                          parent_metadata_report_sha256s=sorted({
                              parent_metadata[ref["page_url"]]["metadata_report_sha256"]
                              for ref in refs if parent_metadata[ref["page_url"]]["status"] == "extracted"}))
            reader.check_time(WORKER_TIMEOUT_SECONDS + 1)
            artifact_id = "legal-pdf:" + metadata.sha256
            evidence = extract(raw, artifact_id=artifact_id, chapter=None)
            summary = _summary(evidence, raw, artifact_id)
            evidence_raw = canonical_json_bytes(evidence)
            if len(evidence_raw) > MAX_OUTPUT_BYTES:
                raise LegalTextError("native_evidence_output_budget")
            evidence_sha = reader.put(evidence_raw)
            result.update(status="extracted", extraction_report_sha256=evidence_sha,
                          extraction_report_size_bytes=len(evidence_raw), **summary)
            reader.check_time()
        except _BudgetError as exc:
            stop_reason, pending_index = str(exc), capture_index
            if result["status"] != "extracted":
                result["reason"] = stop_reason
            break
        except Exception:
            result["reason"] = "source_verification_or_native_extraction_failed"
    succeeded = [row for row in records if row["status"] == "extracted"]
    failed = len(records) - len(succeeded)
    complete = bool(eligible) and len(succeeded) == len(eligible) and stop_reason is None
    return {
        "schema_version": 1, "kind": "ett_observed_legal_native_text",
        "status": "declared_successful_pdfs_extracted" if complete else "incomplete",
        "started_at": started_at, "finished_at": _instant(), "capture_report_sha256": capture_sha,
        "discovery_report_sha256": capture["discovery_report_sha256"],
        "capture_plan_sha256": audit["capture_plan_sha256"], "discovery_plan_replayed": True,
        "declared_pdf_records": len(capture["pdfs"]), "declared_successful_pdfs": len(eligible),
        "skipped_failed_capture_pdfs": len(capture["pdfs"]) - len(eligible),
        "attempted_pdfs": len(records), "extracted_pdfs": len(succeeded), "failed_pdfs": failed,
        "all_declared_successful_pdfs_extracted": complete,
        "page_count": sum(row["page_count"] for row in succeeded),
        "word_count": sum(row["word_count"] for row in succeeded),
        "row_count": sum(row["row_count"] for row in succeeded),
        "no_native_text_page_count": sum(row["no_native_text_page_count"] for row in succeeded),
        "pdfs_with_ocr_candidates": sum(bool(row["ocr_candidate_pages"]) for row in succeeded),
        "all_pages_without_native_text_pdfs": sum(row["all_pages_without_native_text"] for row in succeeded),
        "verified_and_derived_artifact_bytes": reader.total,
        "stop_reason": stop_reason or ("pdf_verification_or_extraction_failures" if failed else "no_successful_captured_pdfs" if not eligible else None),
        "pending_capture_pdf_index": pending_index, "pdfs": records,
        "parent_metadata": list(parent_metadata.values()),
        "parent_metadata_failures": sum(row["status"] != "extracted" for row in parent_metadata.values()),
        "limits": {"pdfs": MAX_PDFS, "artifact_bytes": MAX_TOTAL_BYTES, "elapsed_seconds": MAX_RUN_SECONDS},
        "ocr_performed": False, "scan_image_presence_verified": False,
        "capture_plan_completion_verified": False, "original_ett_receipt_modified": False,
        "primary_act_bodies_verified": False, "legal_inventory_complete": False,
        "effective_dates_verified": False, "legal_approval_verified": False,
        "production_ready": False, "active_rates_written": False,
        "storage_kind": "local_development", "durable_legal_retention_attested": False,
    }
