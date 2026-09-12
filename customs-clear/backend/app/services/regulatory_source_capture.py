"""Optional original-response evidence, independent of rates, review and DBs.

Receipts bind locally retained bytes to the transport's observation. They do
not establish the legal meaning, completeness or authenticity of those bytes.
Query strings are hashed, never copied into receipts, because redirects can
contain expiring bearer signatures. This is development storage, not retention
or legal-hold attestation.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from urllib.parse import urlsplit, urlunsplit

from app.services.ett_artifacts import ArtifactIntegrityError, LocalArtifactStore

_MAX_RECEIPT_BYTES = 64 * 1024
_MAX_BODY_BYTES = 64 * 1024 * 1024
_FALSE_CLAIMS = (
    "production_ready", "legal_ready", "can_promote", "active_rates_written",
    "durable_legal_retention_attested", "source_authenticity_attested",
)
_RECEIPT_KEYS = {
    "schema_version", "capture_kind", "source_ids", "requested", "response",
    "redirect_chain", "retrieved_at", "status_code", "content_type",
    "original_body_sha256", "size_bytes", "storage_kind", "evidence_scope",
    *_FALSE_CLAIMS,
}
QUARANTINABLE_CONTENT_ERRORS = frozenset({
    "content_too_small", "block_or_error_page_detected", "soft_not_found_page_detected",
    "invalid_pdf_content", "invalid_xml_content", "invalid_xlsx_content",
    "invalid_csv_content", "invalid_html_or_document_content",
})
_QUARANTINE_FALSE_CLAIMS = (
    "content_validation_passed", "approval_allowed", "legal_review_verified", "retention_verified",
)
_QUARANTINE_KEYS = {"quarantine_status", "validation_error", *_QUARANTINE_FALSE_CLAIMS}


def _require(value: bool) -> None:
    if not value:
        raise ArtifactIntegrityError("Invalid original-source capture evidence")


def _sha(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def url_identity(url: str) -> dict:
    """Bind the exact URL without persisting query credentials or fragments."""
    _require(isinstance(url, str) and 0 < len(url) <= 16384)
    _require(not any(ord(char) < 32 or ord(char) == 127 for char in url))
    try:
        parts = urlsplit(url)
        _require(parts.scheme == "https" and bool(parts.hostname))
        _require(parts.port in {None, 443} and parts.username is None and parts.password is None)
    except ValueError:
        raise ArtifactIntegrityError("Invalid original-source URL") from None
    return {
        "url": urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")),
        "url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
        "query_redacted": bool(parts.query),
        "fragment_redacted": bool(parts.fragment),
    }


def _check_url_identity(value: object) -> None:
    _require(type(value) is dict and set(value) == {
        "url", "url_sha256", "query_redacted", "fragment_redacted",
    })
    clean = url_identity(value["url"])
    _require(not clean["query_redacted"] and not clean["fragment_redacted"])
    _require(_sha(value["url_sha256"]))
    _require(type(value["query_redacted"]) is bool and type(value["fragment_redacted"]) is bool)
    if not value["query_redacted"] and not value["fragment_redacted"]:
        _require(value["url_sha256"] == clean["url_sha256"])


def _validate_receipt(receipt: dict, *, rejected: bool = False) -> None:
    keys = _RECEIPT_KEYS | _QUARANTINE_KEYS if rejected else _RECEIPT_KEYS
    _require(type(receipt) is dict and set(receipt) == keys)
    _require(type(receipt["schema_version"]) is int and receipt["schema_version"] == 1)
    _require(receipt["capture_kind"] == (
        "official_monitor_rejected_original" if rejected else "official_monitor_original"
    ))
    _require(receipt["storage_kind"] == "local_development")
    _require(receipt["evidence_scope"] == (
        "quarantined_response_bytes_only" if rejected else "retrieved_response_bytes_only"
    ))
    _require(all(receipt[key] is False for key in _FALSE_CLAIMS))
    if rejected:
        _require(receipt["quarantine_status"] == "content_rejected")
        _require(receipt["validation_error"] in QUARANTINABLE_CONTENT_ERRORS)
        _require(all(receipt[key] is False for key in _QUARANTINE_FALSE_CLAIMS))
        _require(type(receipt["status_code"]) is int and receipt["status_code"] == 200)
    ids = receipt["source_ids"]
    _require(type(ids) is list and 1 <= len(ids) <= 256)
    _require(all(isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9_.:-]{1,160}", value) for value in ids))
    _require(ids == sorted(set(ids)))
    _require(type(receipt["status_code"]) is int and 200 <= receipt["status_code"] < 300)
    ctype = receipt["content_type"]
    _require(isinstance(ctype, str) and (0 if rejected else 1) <= len(ctype) <= 256)
    _require(not any(ord(char) < 32 or ord(char) == 127 for char in ctype))
    _require(type(receipt["size_bytes"]) is int and 0 < receipt["size_bytes"] <= _MAX_BODY_BYTES)
    _require(_sha(receipt["original_body_sha256"]))
    _require(isinstance(receipt["retrieved_at"], str) and len(receipt["retrieved_at"]) <= 40)
    try:
        instant = datetime.fromisoformat(receipt["retrieved_at"])
        _require(instant.tzinfo is not None and instant.utcoffset() == timezone.utc.utcoffset(instant))
    except ValueError:
        raise ArtifactIntegrityError("Invalid original-source observation time") from None
    _check_url_identity(receipt["requested"])
    _check_url_identity(receipt["response"])
    chain = receipt["redirect_chain"]
    _require(type(chain) is list and 1 <= len(chain) <= 6)
    for entry in chain:
        _check_url_identity(entry)
    _require(chain[0] == receipt["requested"] and chain[-1] == receipt["response"])


def _json_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def verify_original_capture(store: LocalArtifactStore, receipt_sha256: str) -> dict:
    """Replay receipt/body integrity; this cannot independently attest a fetch."""
    return _verify_capture(store, receipt_sha256, rejected=False)


def verify_rejected_original_capture(store: LocalArtifactStore, receipt_sha256: str) -> dict:
    """Replay quarantined bytes only; the normal original verifier rejects them."""
    return _verify_capture(store, receipt_sha256, rejected=True)


def _verify_capture(store: LocalArtifactStore, receipt_sha256: str, *, rejected: bool) -> dict:
    raw = store.read(receipt_sha256)
    _require(len(raw) <= _MAX_RECEIPT_BYTES)
    try:
        receipt = json.loads(raw, object_pairs_hook=_json_object)
        _validate_receipt(receipt, rejected=rejected)
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise ArtifactIntegrityError("Invalid original-source capture receipt") from None
    body = store.read(receipt["original_body_sha256"])
    _require(len(body) == receipt["size_bytes"])
    _require(hashlib.sha256(body).hexdigest() == receipt["original_body_sha256"])
    return receipt


def capture_original(
    store: LocalArtifactStore, *, body: bytes, source_ids: list[str],
    requested_url: str, final_url: str, redirect_chain: list[str],
    retrieved_at: datetime, status_code: int, content_type: str,
) -> dict:
    """Publish original bytes and their receipt before semantic normalization."""
    return _capture_response(
        store, body=body, source_ids=source_ids, requested_url=requested_url,
        final_url=final_url, redirect_chain=redirect_chain, retrieved_at=retrieved_at,
        status_code=status_code, content_type=content_type,
    )


def capture_rejected_original(
    store: LocalArtifactStore, *, body: bytes, source_ids: list[str],
    requested_url: str, final_url: str, redirect_chain: list[str],
    retrieved_at: datetime, status_code: int, content_type: str, validation_error: str,
) -> dict:
    """Quarantine a transport-validated HTTP 200 body rejected by content checks."""
    _require(validation_error in QUARANTINABLE_CONTENT_ERRORS)
    return _capture_response(
        store, body=body, source_ids=source_ids, requested_url=requested_url,
        final_url=final_url, redirect_chain=redirect_chain, retrieved_at=retrieved_at,
        status_code=status_code, content_type=content_type, validation_error=validation_error,
    )


def _capture_response(
    store: LocalArtifactStore, *, body: bytes, source_ids: list[str],
    requested_url: str, final_url: str, redirect_chain: list[str],
    retrieved_at: datetime, status_code: int, content_type: str,
    validation_error: str | None = None,
) -> dict:
    rejected = validation_error is not None
    _require(type(body) is bytes and 0 < len(body) <= _MAX_BODY_BYTES)
    _require(isinstance(retrieved_at, datetime) and retrieved_at.tzinfo is not None)
    receipt = {
        "schema_version": 1,
        "capture_kind": "official_monitor_original",
        "source_ids": sorted(set(source_ids)),
        "requested": url_identity(requested_url),
        "response": url_identity(final_url),
        "redirect_chain": [url_identity(url) for url in redirect_chain],
        "retrieved_at": retrieved_at.astimezone(timezone.utc).isoformat(),
        "status_code": status_code,
        "content_type": content_type,
        "original_body_sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
        "storage_kind": "local_development",
        "evidence_scope": "retrieved_response_bytes_only",
        **dict.fromkeys(_FALSE_CLAIMS, False),
    }
    if rejected:
        receipt.update({
            "capture_kind": "official_monitor_rejected_original",
            "evidence_scope": "quarantined_response_bytes_only",
            "quarantine_status": "content_rejected",
            "validation_error": validation_error,
            **dict.fromkeys(_QUARANTINE_FALSE_CLAIMS, False),
        })
    _validate_receipt(receipt, rejected=rejected)
    raw = json.dumps(receipt, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    _require(len(raw) <= _MAX_RECEIPT_BYTES)
    _require(store.put(body) == receipt["original_body_sha256"])
    receipt_sha256 = store.put(raw)
    _require(receipt_sha256 == hashlib.sha256(raw).hexdigest())
    _verify_capture(store, receipt_sha256, rejected=rejected)
    return {**receipt, "receipt_sha256": receipt_sha256}
