#!/usr/bin/env python3
"""Retain a bounded chain of actually observed official ETT search pages.

Only the first public query is constructed from the observed GET form. Every
later request uses a retained parent page's literal link to current page + 1.
An exhausted observed chain is not a complete normative inventory or a consistent
portal snapshot. Rows, including unsupported document categories, remain in the
retained original HTML and can be replayed by parse_legal_search.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ett_artifacts import ArtifactIntegrityError, LocalArtifactStore
from app.services.ett_legal_search import ETTLegalSearchError, parse_legal_search
from app.services.ett_portal_search import (
    PORTAL_SEARCH_URL, fetch_portal_search_page, validate_portal_search_page_url,
)
from app.services.ett_transport import (
    IO_TIMEOUT_SECONDS, MAX_HTML_BYTES, MAX_REDIRECTS, TOTAL_BUDGET_SECONDS,
    OfficialResponse, OfficialTransportError,
    _validate_document, sanitize_transport_diagnostics,
)
from scripts.probe_ett_portal_search import _TRANSPORT_REASONS, _instant, _write_report

QUERY = "Единого таможенного тарифа"
INITIAL_URL = PORTAL_SEARCH_URL + "?" + urlencode({"q": QUERY})
MAX_PAGES = 20
MAX_TOTAL_BYTES = 80 * 1024 * 1024
MAX_RAW_ROWS = 1000
MAX_ELAPSED_SECONDS = 20 * 60
MAX_REQUEST_SECONDS = TOTAL_BUDGET_SECONDS + IO_TIMEOUT_SECONDS
MAX_PAGINATION_LINKS = 1000
MAX_LINK_TEXT = 1024


def _identity(url: str) -> tuple[str, int]:
    validate_portal_search_page_url(url)
    fields = dict(parse_qsl(urlsplit(url).query, strict_parsing=True, encoding="utf-8", errors="strict"))
    return fields["q"], int(fields.get("PAGEN_1", "1"))


def _metadata(response: OfficialResponse, requested_url: str) -> dict:
    if not isinstance(response, OfficialResponse) or response.requested_url != requested_url or response.media_type != "text/html":
        raise ValueError("invalid response identity")
    if type(response.content) is not bytes or not 1 <= len(response.content) <= MAX_HTML_BYTES:
        raise ValueError("invalid response size")
    if type(response.redirect_chain) is not tuple or len(response.redirect_chain) > MAX_REDIRECTS:
        raise ValueError("invalid response redirects")
    expected = _identity(requested_url)
    for url in (response.url, *response.redirect_chain):
        if _identity(url) != expected:
            raise ValueError("response changed query or page")
    if len(set((requested_url, *response.redirect_chain))) != 1 + len(response.redirect_chain):
        raise ValueError("invalid response redirect loop")
    if (response.redirect_chain and response.redirect_chain[-1] != response.url) or (not response.redirect_chain and response.url != requested_url):
        raise ValueError("invalid response final URL")
    _validate_document(response.content, "text/html")
    return {
        "response_url": response.url, "requested_url": response.requested_url,
        "redirect_chain": list(response.redirect_chain), "sha256": hashlib.sha256(response.content).hexdigest(),
        "size_bytes": len(response.content), "media_type": response.media_type,
        "retrieved_at": _instant(response.retrieved_at),
    }


def _next_observed_link(parsed, current: int, highest_observed: int):
    if len(parsed.pagination_links) > MAX_PAGINATION_LINKS:
        return None, highest_observed, "pagination_link_budget_exceeded"
    candidates = {}
    for link in parsed.pagination_links:
        query, page = _identity(link.url)
        if query != QUERY or urljoin(parsed.source_url, link.href) != link.url:
            return None, highest_observed, "pagination_query_or_link_mismatch"
        highest_observed = max(highest_observed, page)
        if page == current + 1:
            candidates.setdefault(link.url, link)
    if len(candidates) > 1:
        return None, highest_observed, "ambiguous_next_page_link"
    if candidates:
        link = next(iter(candidates.values()))
        if len(link.href) > 4096 or len(link.locator) > 256 or len(link.text) > MAX_LINK_TEXT:
            return None, highest_observed, "next_link_evidence_exceeds_bound"
        return link, highest_observed, None
    if highest_observed > current:
        return None, highest_observed, "observed_next_page_link_missing"
    return None, highest_observed, "observed_chain_exhausted"


def capture_portal_search(store: LocalArtifactStore, *, fetch=fetch_portal_search_page) -> dict:
    """Capture one sequential observed chain, preserving progress on failure.

    The twenty-page/four-MiB bounds jointly enforce the eighty-MiB maximum.
    The remaining elapsed budget must fit the transport's full request budget
    plus one bounded in-flight I/O call before another request can start. Checks
    after acquisition/parsing still reject late work. There are no retries.
    A page exceeding the remaining row allowance is retained as raw evidence but
    its rows are not accepted into the bounded parsed-row count.
    """
    started_at = _instant(datetime.now(timezone.utc))
    started = time.monotonic()
    results = []
    requested_url = INITIAL_URL
    parent = None
    total_bytes = accepted_rows = accepted_pages = 0
    highest_observed = 1
    visited_urls, body_hashes, row_hashes = set(), set(), set()
    stop_reason = "capture_operation_failed"
    while True:
        if time.monotonic() - started + MAX_REQUEST_SECONDS > MAX_ELAPSED_SECONDS:
            stop_reason = "elapsed_time_budget"
            break
        if len(results) >= MAX_PAGES:
            stop_reason = "page_budget_exceeded"
            break
        # Reserve the maximum transport response before a request, so even an
        # unknown next body cannot make the total accepted byte budget overflow.
        if total_bytes + MAX_HTML_BYTES > MAX_TOTAL_BYTES:
            stop_reason = "byte_budget_exceeded"
            break
        if accepted_rows >= MAX_RAW_ROWS:
            stop_reason = "row_budget_exceeded"
            break
        if requested_url in visited_urls:
            stop_reason = "repeated_search_page_url"
            break
        visited_urls.add(requested_url)
        _, current = _identity(requested_url)
        record = {"page_number": current, "requested_url": requested_url, "status": "failed",
                  "attempted_at": _instant(datetime.now(timezone.utc)), "followed_from": parent}
        results.append(record)
        try:
            response = fetch(requested_url)
            metadata = _metadata(response, requested_url)
            if store.put(response.content) != metadata["sha256"]:
                raise ArtifactIntegrityError("source digest mismatch")
            total_bytes += metadata["size_bytes"]
            record.update(status="captured", parse_status="unresolved", **metadata)
            if time.monotonic() - started >= MAX_ELAPSED_SECONDS:
                stop_reason = "elapsed_time_budget"
                break
            if metadata["sha256"] in body_hashes:
                stop_reason = "repeated_search_page_body"
                break
            body_hashes.add(metadata["sha256"])
            parsed = parse_legal_search(response.content, response.url)
            if parsed.source_sha256 != metadata["sha256"] or parsed.observed_query != QUERY:
                raise ValueError("parsed response binding mismatch")
            row_count = len(parsed.documents)
            record.update(observed_raw_rows=row_count, empty_result_notice=parsed.empty_result_notice)
            if accepted_rows + row_count > MAX_RAW_ROWS:
                stop_reason = "row_budget_exceeded"
                break
            # This catches servers returning the same result set under different
            # pagination URLs even when incidental HTML or row ordering changes.
            row_hash = hashlib.sha256(json.dumps(
                sorted(row.document_link.url for row in parsed.documents), separators=(",", ":"),
            ).encode()).hexdigest()
            if row_count and row_hash in row_hashes:
                stop_reason = "repeated_search_result_rows"
                break
            row_hashes.add(row_hash)
            accepted_rows += row_count
            accepted_pages += 1
            statuses = Counter(row.identity_status for row in parsed.documents)
            record.update(parse_status="parsed", accepted_raw_rows=row_count,
                          row_identity_counts=dict(statuses), row_payloads_retained_in="source_html",
                          observed_pagination_link_count=len(parsed.pagination_links))
            if time.monotonic() - started >= MAX_ELAPSED_SECONDS:
                stop_reason = "elapsed_time_budget"
                break
            link, highest_observed, reason = _next_observed_link(parsed, current, highest_observed)
            if reason:
                stop_reason = reason
                break
            parent = {"page_sha256": metadata["sha256"], "page_url": response.url, "link": asdict(link)}
            requested_url = link.url
        except OfficialTransportError as exc:
            stop_reason = _TRANSPORT_REASONS.get(str(exc), "transport_failure")
            record.setdefault("status", "failed")
            diagnostics = sanitize_transport_diagnostics(exc.diagnostics)
            if diagnostics:
                record["diagnostics"] = diagnostics
            break
        except ETTLegalSearchError:
            stop_reason = "search_parse_failed"
            break
        except ArtifactIntegrityError:
            stop_reason = "source_storage_integrity_failure"
            record.setdefault("status", "failed")
            break
        except Exception:
            stop_reason = "capture_operation_failed"
            record.setdefault("status", "failed")
            break
    exhausted = stop_reason == "observed_chain_exhausted"
    if results and not exhausted:
        results[-1]["stop_reason"] = stop_reason
    return {
        "schema_version": 1, "capture_kind": "observed_official_portal_search_chain",
        "query": QUERY, "initial_url": INITIAL_URL,
        "started_at": started_at, "finished_at": _instant(datetime.now(timezone.utc)),
        "limits": {"max_pages": MAX_PAGES, "max_bytes": MAX_TOTAL_BYTES,
                   "max_raw_rows": MAX_RAW_ROWS, "max_elapsed_seconds": MAX_ELAPSED_SECONDS},
        "attempted_pages": len(results), "captured_pages": sum(r.get("status") == "captured" for r in results),
        "accepted_pages": accepted_pages, "accepted_raw_rows": accepted_rows,
        "captured_bytes": total_bytes, "highest_observed_page_number": highest_observed,
        "status": "observed_chain_captured" if exhausted else "incomplete",
        "stop_reason": stop_reason, "observed_chain_exhausted": exhausted,
        "pending_next_url": None if exhausted else requested_url,
        "pending_followed_from": None if exhausted else parent,
        "source_identity_verified": False, "adoption_dates_verified": False,
        "effective_dates_verified": False, "amendment_inventory_complete": False,
        "legal_inventory_complete": False, "reported_result_count": None,
        "document_absence_verified": False, "cross_page_snapshot_consistency_verified": False,
        "production_ready": False, "active_rates_written": False,
        "storage_kind": "local_development", "durable_legal_retention_attested": False,
        "results": results,
    }


def main(argv=None, *, fetch=fetch_portal_search_page) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink() or not args.output.parent.is_dir():
            raise ValueError("report destination unavailable")
        report = capture_portal_search(LocalArtifactStore(args.store_root), fetch=fetch)
        _write_report(args.output, report)
    except Exception:
        print(json.dumps({"status": "ERROR", "reason": "capture_setup_or_report_failed", "production_ready": False}))
        return 2
    print(json.dumps({key: report[key] for key in (
        "status", "attempted_pages", "captured_pages", "accepted_raw_rows", "stop_reason", "production_ready",
    )}))
    return 0 if report["observed_chain_exhausted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
