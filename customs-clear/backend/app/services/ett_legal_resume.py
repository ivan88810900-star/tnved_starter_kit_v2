"""Reuse verified captured originals while replaying the same legal discovery plan.

This is a technical continuation, not a fresh capture of reused HTTP responses.
Each reused response retains its original retrieval time and redirect chain. The
existing capture runner still decides every requested URL from replayed original
index/search evidence and freshly parsed parent HTML; the cache adds no targets.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib

from .ett_acquisition import DownloadRecord, read_json
from .ett_artifacts import LocalArtifactStore
from .ett_discovery_audit import canonical_json_bytes
from . import ett_legal_capture as capture
from .ett_legal_attachments import parse_legal_attachments, validate_attachment_url
from .ett_transport import OfficialResponse, _validate_document, fetch_official

MAX_CACHE_BYTES = 512 * 1024 * 1024
MAX_REPORT_BYTES = capture.MAX_REPORT_BYTES
_METADATA = tuple(DownloadRecord.model_fields)
_BINDING = {"page_sha256", "page_url", "attachment_discovery_sha256", "reference_index"}


class LegalResumeError(ValueError):
    """Static continuation failure before a new source request."""


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def resume_legal_documents(
    store: LocalArtifactStore, source_capture_report_raw: bytes, discovery_report_raw: bytes,
    *, fetch=fetch_official,
) -> dict:
    """Return a new capture report, never replace or relabel its source report.

    All cached successful originals are verified before the first new request.
    Failed PDF records are not reusable. Successfully saved HTML is reusable even
    when its prior attachment/metadata parser failed: the current capture runner
    must parse it again before following any attachments.
    """
    try:
        if (type(source_capture_report_raw) is not bytes or not 0 < len(source_capture_report_raw) <= MAX_REPORT_BYTES
                or type(discovery_report_raw) is not bytes or not 0 < len(discovery_report_raw) <= MAX_REPORT_BYTES):
            raise ValueError
        source = read_json(source_capture_report_raw)
        if (type(source) is not dict or source.get("schema_version") != 1
                or source.get("kind") != "ett_observed_legal_document_capture"
                or type(source.get("documents")) is not list or len(source["documents"]) > capture.MAX_DOCUMENTS
                or type(source.get("pdfs")) is not list or len(source["pdfs"]) > capture.MAX_PDFS):
            raise ValueError
        if source.get("discovery_report_sha256") != _sha(discovery_report_raw):
            raise ValueError
        if store.read(source["discovery_report_sha256"]) != discovery_report_raw:
            raise ValueError
        audit = capture._replay_plan(discovery_report_raw, store)
        if source.get("capture_plan_sha256") != audit["capture_plan_sha256"] or source.get("source_inputs") != audit["inputs"]:
            raise ValueError
        cache, originals, pages, parsed_parents = {}, {}, {}, {}
        seen_bytes = 0

        def original(row, media):
            nonlocal seen_bytes
            metadata = DownloadRecord.model_validate({key: row[key] for key in _METADATA})
            if (metadata.media_type != media or row.get("document_validation_passed") is not True
                    or row.get("expected_media_type") != media):
                raise ValueError
            if metadata.sha256 not in originals:
                raw = store.read(metadata.sha256)
                if type(raw) is not bytes or _sha(raw) != metadata.sha256:
                    raise ValueError
                seen_bytes += len(raw)
                if seen_bytes > MAX_CACHE_BYTES:
                    raise ValueError
                originals[metadata.sha256] = raw
            raw = originals[metadata.sha256]
            if len(raw) != metadata.size_bytes:
                raise ValueError
            _validate_document(raw, media)
            response = OfficialResponse(
                requested_url=metadata.requested_url, url=metadata.url, content=raw,
                media_type=metadata.media_type, retrieved_at=metadata.retrieved_at,
                redirect_chain=metadata.redirect_chain,
            )
            key = (metadata.requested_url, media)
            if key in cache:
                raise ValueError
            cache[key] = response
            return metadata, raw

        for row in source["documents"]:
            if (type(row) is not dict or row.get("status") not in ("captured", "failed")
                    or type(row.get("plan_entry_index")) is not int):
                raise ValueError
            index = row["plan_entry_index"]
            if not 0 <= index < len(audit["capture_plan"]):
                raise ValueError
            target = audit["capture_plan"][index]
            if row.get("requested_url") != target["page_url"] or row.get("expected_identity") != target["identity"]:
                raise ValueError
            if target["page_url"] in pages:
                raise ValueError
            pages[target["page_url"]] = (row, target)
            if row["status"] == "captured":
                metadata, raw = original(row, "text/html")
                if metadata.url != target["page_url"]:
                    raise ValueError

        def parent(binding):
            key = binding["page_url"]
            if key not in parsed_parents:
                row, target = pages[key]
                response = cache[(key, "text/html")]
                if row.get("attachment_parse_status") != "parsed":
                    raise ValueError
                capture._page_identity(response.content, target["identity"])
                attachments = parse_legal_attachments(response.content, key)
                expected = canonical_json_bytes(asdict(attachments))
                if store.read(row["attachment_discovery_sha256"]) != expected:
                    raise ValueError
                parsed_parents[key] = attachments
            row, _ = pages[key]
            attachments = parsed_parents[key]
            if (binding["page_sha256"] != row["sha256"]
                    or binding["attachment_discovery_sha256"] != row["attachment_discovery_sha256"]):
                raise ValueError
            index = binding["reference_index"]
            if type(index) is not int or not 0 <= index < len(attachments.documents):
                raise ValueError
            return attachments.documents[index]

        seen_pdf_urls = set()
        for row in source["pdfs"]:
            if type(row) is not dict or row.get("status") not in ("captured", "failed"):
                raise ValueError
            url = row.get("requested_url")
            validate_attachment_url(url)
            if url in seen_pdf_urls:
                raise ValueError
            seen_pdf_urls.add(url)
            if row["status"] != "captured":
                continue
            metadata, raw = original(row, "application/pdf")
            validate_attachment_url(metadata.url)
            refs = row.get("source_references")
            if type(refs) is not list or not refs:
                raise ValueError
            seen = set()
            for binding in refs:
                if type(binding) is not dict or binding.keys() != _BINDING:
                    raise ValueError
                encoded = canonical_json_bytes(binding)
                if encoded in seen:
                    raise ValueError
                seen.add(encoded)
                if parent(binding).url != metadata.requested_url:
                    raise ValueError
    except Exception:
        raise LegalResumeError("source_capture_reuse_verification_failed") from None

    source_sha = _sha(source_capture_report_raw)
    if store.put(source_capture_report_raw) != source_sha:
        raise LegalResumeError("source_capture_report_storage_failed")
    reused = {"text/html": 0, "application/pdf": 0}
    reused_keys, new_requests = set(), []

    def resume_fetch(url, *, expected_media):
        key = (url, expected_media)
        if key in cache:
            reused[expected_media] += 1
            reused_keys.add(key)
            return cache[key]
        new_requests.append({"requested_url": url, "expected_media_type": expected_media,
                             "attempted_at": datetime.now(timezone.utc).isoformat()})
        return fetch(url, expected_media=expected_media)

    result = capture.capture_legal_documents(store, discovery_report_raw, fetch=resume_fetch)
    for row in [*result["documents"], *result["pdfs"]]:
        key = (row["requested_url"], row["expected_media_type"])
        if key in reused_keys:
            row.update(retrieval_origin="reused_original_capture", source_capture_report_sha256=source_sha)
        else:
            row["retrieval_origin"] = "new_request"
    result["resume_evidence"] = {
        "source_capture_report_sha256": source_sha, "identical_discovery_plan_replayed": True,
        "cached_html_responses": sum(key[1] == "text/html" for key in cache),
        "cached_pdf_responses": sum(key[1] == "application/pdf" for key in cache),
        "verified_cached_original_bytes": seen_bytes,
        "reused_html_responses": reused["text/html"], "reused_pdf_responses": reused["application/pdf"],
        "new_request_count": len(new_requests), "new_requests": new_requests,
        "original_retrieval_timestamps_preserved": True, "reused_sources_refetched": False,
        "source_capture_report_modified": False, "new_capture_of_reused_sources_claimed": False,
    }
    return result
