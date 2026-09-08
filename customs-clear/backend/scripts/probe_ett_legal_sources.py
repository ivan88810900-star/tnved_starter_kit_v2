#!/usr/bin/env python3
"""Capture observed official URLs; no database or legal approval.

This explicit diagnostic compares the legacy portal locator, its observed canonical
pages, observed Russian PDF attachments and observed public discovery pages. It
does not discover or synthesize URLs. Successful HTTP acquisition does not verify
the act identity, adoption/effective dates or completeness of any inventory.
Shape-rejected original bodies may be retained as rejected-document evidence.
Their records remain failed; object-store presence never establishes validation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ett_artifacts import ArtifactIntegrityError, LocalArtifactStore
from app.services.ett_transport import (
    MAX_HTML_BYTES, MAX_PDF_BYTES, MAX_REDIRECTS, OfficialResponse,
    OfficialTransportError, fetch_official, sanitize_transport_diagnostics, validate_official_url,
    _get_rejected_document_bytes,
)

# Literal locators observed on official EEC/document pages, never filename guesses.
PROBE_SOURCES = (
    ("legacy_collegium_66", "https://docs.eaeunion.org/docs/ru-ru/01232481/err_28042022_66", "text/html"),
    ("canonical_collegium_66", "https://docs.eaeunion.org/documents/399/6620/", "text/html"),
    ("observed_collegium_66_pdf", "https://docs.eaeunion.org/upload/iblock/393/f3ak35ptlhz2u9paqn79dontu4r2kj8h/err_28042022_66_doc.pdf", "application/pdf"),
    ("canonical_council_76", "https://docs.eaeunion.org/documents/401/6619/", "text/html"),
    ("observed_council_76_pdf", "https://docs.eaeunion.org/upload/iblock/82b/1h7ofr72qrt3q86uvgi7kwy36d0l66m6/err_28042022_76_doc.pdf", "application/pdf"),
    ("observed_public_api_landing", "https://docs.eaeunion.org/api/", "text/html"),
    ("observed_collegium_document_list", "https://docs.eaeunion.org/documents/399/", "text/html"),
    ("observed_council_document_list", "https://docs.eaeunion.org/documents/401/", "text/html"),
)
MAX_REPORT_BYTES = 128 * 1024
_TRANSPORT_REASONS = {
    "invalid official source URL": "invalid_source_url",
    "official source exceeded the elapsed time budget": "elapsed_time_budget",
    "official source is not a PDF document": "invalid_pdf_shape",
    "official PDF has no terminal EOF marker": "missing_pdf_eof",
    "official source is not an HTML document": "invalid_html_shape",
    "unsupported official source media type": "unsupported_media_type",
    "official source redirect loop": "redirect_loop",
    "official source exceeded the redirect limit": "redirect_limit",
    "official source returned an invalid redirect": "invalid_redirect",
    "official source redirected to a different host": "cross_host_redirect",
    "official source did not return HTTP 200": "http_non_200",
    "official source returned an unexpected media type": "unexpected_media_type",
    "official source returned ambiguous body framing": "ambiguous_body_framing",
    "official source acquisition failed": "transport_failure",
}


def _instant(value: datetime) -> str:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError("invalid response instant")
    return value.isoformat()


def _response_metadata(response: OfficialResponse, requested_url: str, media: str) -> dict:
    if not isinstance(response, OfficialResponse) or response.requested_url != requested_url or response.media_type != media:
        raise ValueError("invalid response identity")
    if type(response.content) is not bytes or not 1 <= len(response.content) <= (MAX_PDF_BYTES if media == "application/pdf" else MAX_HTML_BYTES):
        raise ValueError("invalid response size")
    if type(response.redirect_chain) is not tuple or len(response.redirect_chain) > MAX_REDIRECTS:
        raise ValueError("invalid response redirects")
    for url in (response.url, *response.redirect_chain):
        validate_official_url(url)
        if urlsplit(url).netloc != urlsplit(requested_url).netloc:
            raise ValueError("invalid response origin")
    if (response.redirect_chain and response.redirect_chain[-1] != response.url) or (not response.redirect_chain and response.url != requested_url):
        raise ValueError("invalid response final URL")
    return {
        "response_url": response.url, "requested_url": response.requested_url,
        "redirect_chain": list(response.redirect_chain), "sha256": hashlib.sha256(response.content).hexdigest(),
        "size_bytes": len(response.content), "media_type": response.media_type,
        "retrieved_at": _instant(response.retrieved_at),
    }


def probe_legal_sources(store: LocalArtifactStore, *, fetch=fetch_official) -> dict:
    """Attempt each literal source once through the bounded official transport.

    ``fetch`` is the testing seam; production CLI uses ``fetch_official``. The eight
    top-level attempts may follow that transport's existing same-host redirect
    limit. No retry, fallback hostname, API mutation or activation is performed.
    """
    started_at = _instant(datetime.now(timezone.utc))
    results = []
    for source_id, url, media in PROBE_SOURCES:
        record = {"source_id": source_id, "requested_url": url, "expected_media_type": media,
                  "attempted_at": _instant(datetime.now(timezone.utc))}
        try:
            response = fetch(url, expected_media=media)
            metadata = _response_metadata(response, url, media)
            digest = store.put(response.content)
            if digest != metadata["sha256"]:
                raise ArtifactIntegrityError("source digest mismatch")
            record.update(status="captured", **metadata)
        except OfficialTransportError as exc:
            # Only exact messages owned by our transport are mapped. Never emit
            # arbitrary exceptions, response bodies, headers or credentials.
            record.update(status="failed", reason=_TRANSPORT_REASONS.get(str(exc), "transport_failure"))
            diagnostics = sanitize_transport_diagnostics(exc.diagnostics)
            if diagnostics:
                record["diagnostics"] = diagnostics
            rejected = _get_rejected_document_bytes(exc)
            if rejected is not None:
                record["document_validation_passed"] = False
                try:
                    rejected_digest = store.put(rejected)
                    if rejected_digest != diagnostics.get("sha256"):
                        raise ArtifactIntegrityError("rejected evidence digest mismatch")
                    record["rejected_document_sha256"] = rejected_digest
                except Exception:
                    # Preserve the original transport rejection and continue
                    # the probe even if retaining its evidence also fails.
                    record["rejected_document_retention_reason"] = "rejected_evidence_retention_failed"
        except ArtifactIntegrityError:
            record.update(status="failed", reason="source_storage_integrity_failure")
        except Exception:
            record.update(status="failed", reason="probe_operation_failed")
        results.append(record)
    succeeded = sum(item["status"] == "captured" for item in results)
    return {
        "schema_version": 1, "probe_kind": "observed_official_source_access",
        "started_at": started_at, "finished_at": _instant(datetime.now(timezone.utc)),
        "attempted_sources": len(results), "captured_sources": succeeded,
        "failed_sources": len(results) - succeeded, "all_sources_captured": succeeded == len(PROBE_SOURCES),
        "retained_rejected_documents": sum("rejected_document_sha256" in item for item in results),
        "source_identity_verified": False, "adoption_dates_verified": False,
        "effective_dates_verified": False, "amendment_inventory_complete": False,
        "production_ready": False, "active_rates_written": False,
        "storage_kind": "local_development", "durable_legal_retention_attested": False,
        "results": results,
    }


def _write_report(path: Path, report: dict) -> None:
    payload = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if len(payload) > MAX_REPORT_BYTES:
        raise ValueError("probe report exceeds its bound")
    # Publish a complete private report without replacing an existing path.
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".ett-legal-probe-", delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
            os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def main(argv=None, *, fetch=fetch_official) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink() or not args.output.parent.is_dir():
            raise ValueError("report destination unavailable")
        report = probe_legal_sources(LocalArtifactStore(args.store_root), fetch=fetch)
        _write_report(args.output, report)
    except Exception:
        print(json.dumps({"status": "ERROR", "reason": "probe_setup_or_report_failed", "production_ready": False}))
        return 2
    print(json.dumps({"status": "captured" if report["all_sources_captured"] else "incomplete",
                      "attempted_sources": report["attempted_sources"], "captured_sources": report["captured_sources"],
                      "failed_sources": report["failed_sources"], "production_ready": False}))
    return 0 if report["all_sources_captured"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
