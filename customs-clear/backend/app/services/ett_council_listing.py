"""Retain observed 2026 Council list pages for amendment-source discovery.

The list locator is an actual return-to-list anchor in Council 72 detail HTML
SHA256 46ab3de6485fd97371ea0bda002e579b9d6e2b220b0a58b91b8ed5afcf83d442
(2026-09-10, line 220). Replay that link from newly retained detail bytes before
fetching it. Later pages must have literal links in their retained parent page.
No JavaScript, search guesses, generated detail IDs, PDF downloads or DB writes.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from urllib.parse import parse_qsl, urljoin, urlsplit

from app.services.ett_artifacts import ArtifactIntegrityError, LocalArtifactStore
from app.services.ett_legal_list import ETTLegalListError, parse_legal_list, validate_list_url
from app.services.ett_tariff_relief_capture import _Anchors
from app.services.ett_transport import (
    IO_TIMEOUT_SECONDS, MAX_HTML_BYTES, OfficialResponse, OfficialTransportError,
    TOTAL_BUDGET_SECONDS, _fetch_bounded, _validate_document, fetch_official,
    sanitize_transport_diagnostics,
)

DETAIL_URL = "https://docs.eaeunion.org/documents/461/10843/"
LIST_URL = "https://docs.eaeunion.org/documents/461/"
TARGET_NUMBERS = ("75", "77", "80")
MAX_PAGES = 16
MAX_ROWS = 1000
MAX_TOTAL_BYTES = (MAX_PAGES + 1) * MAX_HTML_BYTES
MAX_ELAPSED_SECONDS = 1200
MAX_REPORT_BYTES = 8 * 1024 * 1024


class CouncilListingError(ValueError):
    """An observed listing cannot be captured within its evidence boundaries."""


def _instant(value: datetime) -> str:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise CouncilListingError("invalid_response_time")
    return value.isoformat()


def observed_parent_link(raw: bytes) -> dict:
    """Return the exact, unambiguous retained anchor; ignore its onclick code."""
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_HTML_BYTES:
        raise CouncilListingError("invalid_bootstrap_size")
    _validate_document(raw, "text/html")
    parser = _Anchors()
    parser.feed(raw.decode("utf-8-sig", errors="strict"))
    parser.close()
    if parser.has_base:
        raise CouncilListingError("unsupported_html_base")
    candidates = [a for a in parser.anchors if any(
        h in ("/documents/461/", LIST_URL) for h in a["href_attributes"]
    )]
    if len(candidates) != 1 or len(candidates[0]["href_attributes"]) != 1:
        raise CouncilListingError("parent_link_missing_or_ambiguous")
    anchor = candidates[0]
    href = anchor["href_attributes"][0]
    if urljoin(DETAIL_URL, href) != LIST_URL:
        raise CouncilListingError("parent_link_mismatch")
    return {**anchor, "href": href, "url": LIST_URL, "page_url": DETAIL_URL,
            "page_sha256": hashlib.sha256(raw).hexdigest()}


def _page_number(url: str) -> int:
    validate_list_url(url)
    if urlsplit(url).path != urlsplit(LIST_URL).path:
        raise CouncilListingError("list_path_changed")
    return int(dict(parse_qsl(urlsplit(url).query)).get("PAGEN_1", "1"))


def fetch_council_list_page(url: str, *, _transport=None) -> OfficialResponse:
    """Bounded transport only for a caller's observed, exact list/page URL."""
    _page_number(url)

    def validate(target):
        _page_number(target)
        if target != url:
            raise OfficialTransportError("council listing redirect changed URL")
        return target

    def redirect(current, location):
        # Check before urljoin can normalize traversal or control characters.
        if type(location) is not str or location != location.strip() or any(
            ord(char) < 33 or ord(char) == 127 for char in location
        ) or "\\" in location or "#" in location:
            raise OfficialTransportError("invalid council listing redirect")
        absolute = "https://docs.eaeunion.org" + location if location.startswith("/") else location
        return validate(absolute)

    return _fetch_bounded(url, expected_media="text/html", _transport=_transport,
                          url_validator=validate, redirect_target=redirect)


def _metadata(response, requested_url):
    if not isinstance(response, OfficialResponse) or response.requested_url != requested_url:
        raise CouncilListingError("response_identity_mismatch")
    if response.url != requested_url or response.redirect_chain != () or response.media_type != "text/html":
        raise CouncilListingError("response_origin_or_media_mismatch")
    if type(response.content) is not bytes or not 0 < len(response.content) <= MAX_HTML_BYTES:
        raise CouncilListingError("response_size_invalid")
    _validate_document(response.content, "text/html")
    return {"requested_url": requested_url, "response_url": response.url,
            "redirect_chain": [], "media_type": "text/html",
            "sha256": hashlib.sha256(response.content).hexdigest(),
            "size_bytes": len(response.content), "retrieved_at": _instant(response.retrieved_at)}


def capture_council_listing(store: LocalArtifactStore, *, fetch=fetch_official,
                            fetch_page=fetch_council_list_page) -> dict:
    """Stop at three observed targets or a bounded unresolved/exhausted chain.

    A successful target selection is not proof that the year list is complete,
    its metadata is legally correct, or these are the current operative acts.
    """
    started = time.monotonic()
    started_at = _instant(datetime.now(timezone.utc))
    records, candidates = [], []
    seen_urls, seen_bodies, seen_documents = set(), set(), set()
    current_url, parent = DETAIL_URL, None
    total_bytes = accepted_rows = list_pages = 0
    reported_count = None
    highest_page = 1
    reason = "capture_operation_failed"
    try:
        while True:
            if time.monotonic() - started + TOTAL_BUDGET_SECONDS + IO_TIMEOUT_SECONDS > MAX_ELAPSED_SECONDS:
                reason = "elapsed_time_budget"
                break
            if current_url != DETAIL_URL and list_pages >= MAX_PAGES:
                reason = "page_budget_exceeded"
                break
            if total_bytes + MAX_HTML_BYTES > MAX_TOTAL_BYTES:
                reason = "byte_budget_exceeded"
                break
            if current_url in seen_urls:
                reason = "repeated_page_url"
                break
            seen_urls.add(current_url)
            record = {"requested_url": current_url, "followed_from": parent, "status": "failed"}
            records.append(record)
            response = fetch(current_url, expected_media="text/html") if current_url == DETAIL_URL else fetch_page(current_url)
            metadata = _metadata(response, current_url)
            if store.put(response.content) != metadata["sha256"]:
                raise ArtifactIntegrityError("source digest mismatch")
            total_bytes += len(response.content)
            record.update(status="captured", parse_status="unresolved", **metadata)
            if time.monotonic() - started >= MAX_ELAPSED_SECONDS:
                reason = "elapsed_time_budget"
                break
            if metadata["sha256"] in seen_bodies:
                reason = "repeated_page_body"
                break
            seen_bodies.add(metadata["sha256"])
            if current_url == DETAIL_URL:
                parent = observed_parent_link(response.content)
                record.update(parse_status="observed_parent_verified")
                current_url = parent["url"]
                continue
            parsed = parse_legal_list(response.content, current_url)
            if parsed.issuing_body != "council" or parsed.observed_year != 2026:
                reason = "list_category_changed"
                break
            if reported_count is not None and reported_count != parsed.reported_result_count:
                reason = "reported_result_count_changed"
                break
            reported_count = parsed.reported_result_count
            if accepted_rows + len(parsed.documents) > MAX_ROWS:
                reason = "row_budget_exceeded"
                break
            row_urls = {row.document_link.url for row in parsed.documents}
            if seen_documents.intersection(row_urls):
                reason = "repeated_document_rows"
                break
            seen_documents.update(row_urls)
            accepted_rows += len(parsed.documents)
            list_pages += 1
            record.update(parse_status="parsed", observed_rows=len(parsed.documents),
                          reported_result_count=reported_count)
            for row in parsed.documents:
                if row.number in TARGET_NUMBERS:
                    candidates.append({"parent_page_sha256": metadata["sha256"],
                                       "parent_page_url": current_url, **asdict(row)})
            numbers = [row["number"] for row in candidates]
            if len(numbers) != len(set(numbers)):
                reason = "target_identity_ambiguous"
                break
            if time.monotonic() - started >= MAX_ELAPSED_SECONDS:
                reason = "elapsed_time_budget"
                break
            if set(numbers) == set(TARGET_NUMBERS):
                reason = "selected_targets_observed"
                break
            current = _page_number(current_url)
            next_links = {}
            if len(parsed.pagination_links) > MAX_ROWS:
                reason = "pagination_link_budget_exceeded"
                break
            for link in parsed.pagination_links:
                page = _page_number(link.url)
                if urljoin(current_url, link.href) != link.url:
                    raise CouncilListingError("pagination_parent_mismatch")
                highest_page = max(highest_page, page)
                if page == current + 1:
                    next_links.setdefault(link.url, link)
            if len(next_links) != 1:
                reason = ("ambiguous_next_page_link" if next_links else
                          "observed_next_page_link_missing" if highest_page > current else "observed_chain_exhausted")
                break
            link = next(iter(next_links.values()))
            parent = {"page_sha256": metadata["sha256"], "page_url": current_url, "link": asdict(link)}
            current_url = link.url
    except OfficialTransportError as exc:
        reason = "official_transport_failure"
        if records:
            records[-1]["diagnostics"] = sanitize_transport_diagnostics(exc.diagnostics)
    except ArtifactIntegrityError:
        reason = "source_storage_integrity_failure"
    except ETTLegalListError:
        reason = "list_parse_failed"
    except (CouncilListingError, UnicodeError, ValueError):
        reason = "source_binding_failed"
    except Exception:
        reason = "capture_operation_failed"
    return {
        "schema_version": 1, "capture_kind": "observed_2026_council_amendment_listing",
        "started_at": started_at, "finished_at": _instant(datetime.now(timezone.utc)),
        "status": "selected_targets_observed" if reason == "selected_targets_observed" else "incomplete",
        "stop_reason": reason, "target_numbers": list(TARGET_NUMBERS),
        "selected_target_urls_observed": reason == "selected_targets_observed",
        "unobserved_target_numbers": [n for n in TARGET_NUMBERS if n not in {c["number"] for c in candidates}],
        "captured_sources": sum(r["status"] == "captured" for r in records),
        "accepted_list_pages": list_pages, "accepted_rows": accepted_rows,
        "captured_bytes": total_bytes, "reported_result_count": reported_count,
        "observed_chain_exhausted": reason == "observed_chain_exhausted",
        "limits": {"max_list_pages": MAX_PAGES, "max_rows": MAX_ROWS,
                   "max_bytes": MAX_TOTAL_BYTES, "max_elapsed_seconds": MAX_ELAPSED_SECONDS},
        "records": records, "candidates": candidates,
        "source_identity_verified": False, "adoption_dates_verified": False,
        "effective_dates_verified": False, "legal_inventory_complete": False,
        "document_absence_verified": False, "cross_page_snapshot_consistency_verified": False,
        "production_ready": False, "can_promote": False, "active_rates_written": False,
        "storage_kind": "local_development", "durable_legal_retention_attested": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink() or not args.output.parent.is_dir():
            raise CouncilListingError("report_destination_unavailable")
        report = capture_council_listing(LocalArtifactStore(args.store_root))
        def encode_date(value):
            if isinstance(value, (date, datetime)):
                return value.isoformat()
            raise TypeError("unsupported report value")
        raw = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2,
                          default=encode_date, allow_nan=False) + "\n").encode()
        if len(raw) > MAX_REPORT_BYTES:
            raise CouncilListingError("report_size_limit")
        with tempfile.NamedTemporaryFile(dir=args.output.parent, delete=False) as output:
            temporary = Path(output.name)
            try:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
                os.link(temporary, args.output)
            finally:
                temporary.unlink(missing_ok=True)
    except Exception:
        print(json.dumps({"status": "ERROR", "reason": "listing_capture_setup_or_report_failed", "production_ready": False}))
        return 2
    print(json.dumps({key: report[key] for key in (
        "status", "captured_sources", "accepted_list_pages", "accepted_rows", "stop_reason", "production_ready",
    )}))
    return 0 if report["selected_target_urls_observed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
