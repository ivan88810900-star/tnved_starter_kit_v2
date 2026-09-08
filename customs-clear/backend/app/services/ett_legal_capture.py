"""Capture source-bound legal pages and their observed PDFs for later review.

A caller-supplied plan is never trusted: the complete discovery audit is replayed
against retained original inputs before any request. HTML metadata matching and
PDF transport validation do not verify a primary act's legal identity, contents
or effective dates. This report is separate from the original ETT receipt.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone
import hashlib
import json
import re
import time
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .ett_acquisition import DownloadRecord, read_json
from .ett_artifacts import ArtifactIntegrityError, LocalArtifactStore
from .ett_discovery_audit import audit_legal_discovery, canonical_json_bytes
from .ett_index import _text, _visible
from .ett_legal_attachments import _EEC_DECISION_CATEGORY, parse_legal_attachments, validate_attachment_url
from .ett_transport import (
    IO_TIMEOUT_SECONDS, MAX_HTML_BYTES, MAX_PDF_BYTES, TOTAL_BUDGET_SECONDS,
    OfficialResponse, OfficialTransportError, _get_rejected_document_bytes,
    _validate_document, fetch_official, sanitize_transport_diagnostics,
    validate_official_url,
)

MAX_DOCUMENTS = 110
MAX_PDFS = 256
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_INPUT_BYTES = 256 * 1024 * 1024
MAX_REPORT_BYTES = 16 * 1024 * 1024
MAX_RUN_SECONDS = 20 * 60
MAX_REQUEST_SECONDS = TOTAL_BUDGET_SECONDS + IO_TIMEOUT_SECONDS
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_PAGE = re.compile(r"/documents/[1-9][0-9]*/[1-9][0-9]*/\Z")
_LABEL = re.compile(r"Решение (Коллегии|Совета) (?:ЕЭК|Евразийской экономической комиссии) №\s*([1-9][0-9]{0,5})\Z")
_SHORT_LABEL = re.compile(r"Решение (Коллегии|Совета) №\s*([1-9][0-9]{0,5})\Z")
_TRANSPORT_REASONS = {
    "official source exceeded the elapsed time budget": "request_time_budget",
    "official source did not return HTTP 200": "http_non_200",
    "official source returned an unexpected media type": "unexpected_media_type",
    "official source redirect loop": "redirect_loop",
    "official source exceeded the redirect limit": "redirect_limit",
    "official source is not a PDF document": "invalid_pdf_shape",
    "official PDF has no terminal EOF marker": "missing_pdf_eof",
    "official source is not an HTML document": "invalid_html_shape",
}
_CAPTURE_REASONS = frozenset({
    "invalid_observed_document_url", "response_identity_mismatch", "response_body_bound_failed",
    "document_metadata_missing_or_ambiguous", "document_metadata_identity_mismatch",
    "document_page_redirect_changed",
})


class LegalCaptureError(ValueError):
    """Static capture/input failure; never includes an upstream payload."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _instant() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_page(url: str) -> str:
    validate_official_url(url)
    parts = urlsplit(url)
    if parts.netloc != "docs.eaeunion.org" or not _PAGE.fullmatch(parts.path):
        raise LegalCaptureError("invalid_observed_document_url")
    return url


def _replay_plan(raw: bytes, store: LocalArtifactStore) -> dict:
    """Rehash all supplied input objects and compare the regenerated full audit."""
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_REPORT_BYTES:
            raise ValueError
        supplied = read_json(raw)
        if type(supplied) is not dict or type(supplied.get("inputs")) is not dict:
            raise ValueError
        inputs = supplied["inputs"]
        cache = {}
        total = 0

        def read_object(digest):
            nonlocal total
            if type(digest) is not str or not _SHA.fullmatch(digest):
                raise ValueError
            if digest not in cache:
                data = store.read(digest)
                if type(data) is not bytes or not 0 < len(data) <= MAX_PDF_BYTES or _sha(data) != digest:
                    raise ValueError
                total += len(data)
                if total > MAX_INPUT_BYTES:
                    raise ValueError
                cache[digest] = data
            return cache[digest]

        supplementary = inputs.get("supplementary_probe_report_sha256s", [])
        if type(supplementary) is not list or len(supplementary) > 20:
            raise ValueError
        # The auditor replays original notes PDFs for fresh note evidence; legacy
        # census reports cannot authorize notes-only capture targets.
        rebuilt = audit_legal_discovery(
            read_object(inputs["index_source_sha256"]),
            read_object(inputs["index_inventory_report_sha256"]),
            read_object(inputs["notes_report_sha256"]),
            read_object(inputs["pagination_report_sha256"]),
            read_object,
            supplementary_report_raws=tuple(read_object(digest) for digest in supplementary),
        )
        if canonical_json_bytes(rebuilt) != canonical_json_bytes(supplied):
            raise ValueError
        plan = rebuilt["capture_plan"]
        if type(plan) is not list or _sha(canonical_json_bytes(plan)) != rebuilt["capture_plan_sha256"]:
            raise ValueError
        if len({row["page_url"] for row in plan}) != len(plan):
            raise ValueError
        for row in plan:
            _canonical_page(row["page_url"])
        return rebuilt
    except Exception:
        raise LegalCaptureError("discovery_plan_replay_failed") from None


def _page_identity(raw: bytes, expected: dict) -> dict:
    """Match the observed metadata fields, never interpret PDF contents or effect."""
    soup = BeautifulSoup(raw.decode("utf-8-sig", errors="strict"), "html.parser")
    infos = [node for node in soup.select(".DocDetail_Info") if _visible(node)]
    if len(infos) != 1:
        raise LegalCaptureError("document_metadata_missing_or_ambiguous")
    wanted = {"Номер документа", "Короткий заголовок документа", "Дата принятия документа"}
    values = {}
    for row in infos[0].select(".DocDetail_Row"):
        if not _visible(row):
            continue
        labels = [node for node in row.select(".DocDetail_Col._title") if _visible(node)]
        contents = [node for node in row.select(".DocDetail_Col._value") if _visible(node)]
        if len(labels) != 1 or len(contents) != 1:
            raise LegalCaptureError("document_metadata_missing_or_ambiguous")
        label = _text(labels[0])
        if label in wanted or label == "Вид документа":
            if label in values:
                raise LegalCaptureError("document_metadata_missing_or_ambiguous")
            values[label] = _text(contents[0])
    if not wanted <= values.keys():
        raise LegalCaptureError("document_metadata_missing_or_ambiguous")
    match = _LABEL.fullmatch(values["Короткий заголовок документа"])
    short = match is None
    if short:
        match = _SHORT_LABEL.fullmatch(values["Короткий заголовок документа"])
    literal = values["Дата принятия документа"]
    if match is None or not re.fullmatch(r"[0-9]{2}\.[0-9]{2}\.[0-9]{4}", literal):
        raise LegalCaptureError("document_metadata_identity_mismatch")
    try:
        adopted = date(int(literal[6:10]), int(literal[3:5]), int(literal[:2])).isoformat()
    except ValueError:
        raise LegalCaptureError("document_metadata_identity_mismatch") from None
    identity = {"issuing_body": "collegium" if match[1] == "Коллегии" else "council",
                "adoption_date": adopted, "number": match[2]}
    category = _EEC_DECISION_CATEGORY.fullmatch(values.get("Вид документа", ""))
    if (short and category is None) or (category is not None and (
            category[1] != ("Коллегия" if match[1] == "Коллегии" else "Совет")
            or int(category[2]) != int(adopted[:4]))):
        raise LegalCaptureError("document_metadata_identity_mismatch")
    if identity != expected or values["Номер документа"] != expected["number"]:
        raise LegalCaptureError("document_metadata_identity_mismatch")
    return {"observed_identity": identity, "short_title": values["Короткий заголовок документа"],
            "metadata_matches_discovery_identity": True, "primary_body_identity_verified": False}


def capture_legal_documents(
    store: LocalArtifactStore,
    discovery_report_raw: bytes,
    *,
    fetch=fetch_official,
) -> dict:
    """Capture an audited plan with bounded progress, no retries or extraction.

    Originals are retained before attachment/identity checks. Shape-rejected
    bodies may also be retained explicitly as failed evidence; they are never
    counted as successfully captured PDFs. Every PDF is attributable to a stored
    page and its replayable attachment-discovery object, including repeated links.
    """
    started_at, started = _instant(), time.monotonic()
    audit = _replay_plan(discovery_report_raw, store)
    plan = audit["capture_plan"]
    audit_sha = store.put(discovery_report_raw)
    if audit_sha != _sha(discovery_report_raw):
        raise LegalCaptureError("discovery_report_storage_failed")
    pages, pdfs = [], []
    pdf_by_url = {}
    retained_bytes = 0
    stop_reason = None
    pending_url = None

    def budget(media):
        if time.monotonic() - started + MAX_REQUEST_SECONDS > MAX_RUN_SECONDS:
            return "elapsed_time_budget"
        if retained_bytes + (MAX_PDF_BYTES if media == "application/pdf" else MAX_HTML_BYTES) > MAX_TOTAL_BYTES:
            return "source_byte_budget"
        return None

    def download(url, media):
        nonlocal retained_bytes
        result = {"requested_url": url, "expected_media_type": media,
                  "attempted_at": _instant(), "status": "failed"}
        try:
            response = fetch(url, expected_media=media)
            if not isinstance(response, OfficialResponse) or response.requested_url != url or response.media_type != media:
                raise LegalCaptureError("response_identity_mismatch")
            if (type(response.retrieved_at) is not datetime or response.retrieved_at.tzinfo is None
                    or response.retrieved_at.utcoffset() != timezone.utc.utcoffset(response.retrieved_at)
                    or type(response.redirect_chain) is not tuple):
                raise LegalCaptureError("response_identity_mismatch")
            body = response.content
            if type(body) is not bytes or not 0 < len(body) <= (MAX_PDF_BYTES if media == "application/pdf" else MAX_HTML_BYTES):
                raise LegalCaptureError("response_body_bound_failed")
            metadata = DownloadRecord(
                requested_url=url, url=response.url, sha256=_sha(body), size_bytes=len(body),
                media_type=media, retrieved_at=response.retrieved_at, redirect_chain=response.redirect_chain,
            ).model_dump(mode="json")
            _validate_document(body, media)
            if store.put(body) != metadata["sha256"]:
                raise ArtifactIntegrityError("source digest mismatch")
            retained_bytes += len(body)
            result.update(metadata, status="captured", document_validation_passed=True)
            if time.monotonic() - started >= MAX_RUN_SECONDS:
                result.update(status="failed", reason="elapsed_time_budget", source_bytes_retained=True)
                return result, None
            return result, body
        except OfficialTransportError as exc:
            result["reason"] = _TRANSPORT_REASONS.get(str(exc), "transport_failure")
            diagnostics = sanitize_transport_diagnostics(exc.diagnostics)
            if diagnostics:
                result["diagnostics"] = diagnostics
            rejected = _get_rejected_document_bytes(exc)
            if rejected is not None:
                result["document_validation_passed"] = False
                try:
                    if retained_bytes + len(rejected) > MAX_TOTAL_BYTES:
                        raise ValueError
                    digest = store.put(rejected)
                    if digest != _sha(rejected):
                        raise ValueError
                    retained_bytes += len(rejected)
                    result.update(rejected_document_sha256=digest, rejected_size_bytes=len(rejected))
                except Exception:
                    result["rejected_document_retention_reason"] = "rejected_evidence_retention_failed"
        except LegalCaptureError as exc:
            result["reason"] = str(exc) if str(exc) in _CAPTURE_REASONS else "capture_operation_failed"
        except ArtifactIntegrityError:
            result["reason"] = "source_storage_integrity_failure"
        except Exception:
            result["reason"] = "capture_operation_failed"
        return result, None

    for plan_index, target in enumerate(plan):
        if len(pages) >= MAX_DOCUMENTS:
            stop_reason, pending_url = "document_count_budget", target["page_url"]
            break
        stop_reason = budget("text/html")
        if stop_reason:
            pending_url = target["page_url"]
            break
        record, raw = download(target["page_url"], "text/html")
        record.update(plan_entry_index=plan_index, expected_identity=target["identity"],
                      attachment_parse_status="unresolved",
                      reference_counts={key: len(target.get(key, [])) for key in (
                          "amendment_references", "note_references", "founding_references")},
                      founding_references=target.get("founding_references", []))
        pages.append(record)
        if raw is None:
            continue
        try:
            if record["url"] != target["page_url"]:
                raise LegalCaptureError("document_page_redirect_changed")
            attachments = parse_legal_attachments(raw, record["url"])
            record.update(_page_identity(raw, target["identity"]))
            payload = canonical_json_bytes(asdict(attachments))
            discovery_sha = store.put(payload)
            if discovery_sha != _sha(payload):
                raise ArtifactIntegrityError("attachment discovery digest mismatch")
            record.update(attachment_parse_status="parsed", attachment_discovery_sha256=discovery_sha,
                          pdf_reference_count=len(attachments.documents),
                          unsupported_reference_count=len(attachments.unsupported_references))
            for reference_index, ref in enumerate(attachments.documents):
                binding = {"page_sha256": record["sha256"], "page_url": record["url"],
                           "attachment_discovery_sha256": discovery_sha, "reference_index": reference_index}
                if ref.url in pdf_by_url:
                    pdf_by_url[ref.url]["source_references"].append(binding)
                    continue
                if len(pdfs) >= MAX_PDFS:
                    stop_reason, pending_url = "pdf_count_budget", ref.url
                    break
                stop_reason = budget("application/pdf")
                if stop_reason:
                    pending_url = ref.url
                    break
                pdf, pdf_raw = download(ref.url, "application/pdf")
                pdf["source_references"] = [binding]
                pdf_by_url[ref.url] = pdf
                pdfs.append(pdf)
                if pdf_raw is not None:
                    try:
                        validate_attachment_url(pdf["url"])
                    except ValueError:
                        pdf.update(status="failed", reason="pdf_redirect_left_attachment_paths", source_bytes_retained=True)
            if stop_reason:
                break
        except LegalCaptureError as exc:
            record["reason"] = str(exc) if str(exc) in _CAPTURE_REASONS else "capture_operation_failed"
        except ArtifactIntegrityError:
            record["reason"] = "attachment_evidence_storage_failed"
        except Exception:
            record["reason"] = "attachment_or_metadata_parse_failed"
    failures = sum(row["status"] != "captured" or row["attachment_parse_status"] != "parsed" for row in pages)
    failures += sum(row["status"] != "captured" for row in pdfs)
    completed = bool(plan) and stop_reason is None and len(pages) == len(plan) and failures == 0
    return {
        "schema_version": 1, "kind": "ett_observed_legal_document_capture",
        "status": "supported_discovery_plan_captured" if completed else "incomplete",
        "started_at": started_at, "finished_at": _instant(),
        "discovery_report_sha256": audit_sha, "capture_plan_sha256": audit["capture_plan_sha256"],
        "source_inputs": audit["inputs"], "discovery_plan_replayed": True,
        "planned_document_pages": len(plan), "attempted_document_pages": len(pages),
        "captured_document_pages": sum(row["status"] == "captured" for row in pages),
        "identity_matched_document_pages": sum(row.get("metadata_matches_discovery_identity") is True for row in pages),
        "attempted_unique_pdfs": len(pdfs), "captured_unique_pdfs": sum(row["status"] == "captured" for row in pdfs),
        "failed_operations": failures, "retained_source_bytes": retained_bytes,
        "unsupported_attachment_references": sum(row.get("unsupported_reference_count", 0) for row in pages),
        "pages_without_pdf_links": sum(row.get("pdf_reference_count") == 0 for row in pages),
        "supported_capture_plan_completed": completed,
        "stop_reason": stop_reason or ("capture_failures" if failures else "no_unambiguous_observed_targets" if not plan else None),
        "pending_url": pending_url,
        "limits": {"document_pages": MAX_DOCUMENTS, "unique_pdfs": MAX_PDFS,
                   "source_bytes": MAX_TOTAL_BYTES, "elapsed_seconds": MAX_RUN_SECONDS},
        "documents": pages, "pdfs": pdfs,
        "original_ett_receipt_modified": False, "primary_act_bodies_verified": False,
        "legal_inventory_complete": False, "effective_dates_verified": False,
        "legal_approval_verified": False, "production_ready": False, "active_rates_written": False,
        "storage_kind": "local_development", "durable_legal_retention_attested": False,
    }
