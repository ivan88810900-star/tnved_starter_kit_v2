#!/usr/bin/env python3
"""Capture a fixed public query set through the observed portal search form.

This is a read-only discovery probe, without a DB, authentication, guessed search
API or legal interpretation. A captured response, including an empty results page,
does not prove that a named act exists, is absent or has any particular date.
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
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ett_artifacts import ArtifactIntegrityError, LocalArtifactStore
from app.services.ett_portal_search import (
    PORTAL_SEARCH_URL, _validate_search_url, fetch_portal_search,
)
from app.services.ett_transport import (
    MAX_HTML_BYTES, MAX_REDIRECTS, OfficialResponse, OfficialTransportError,
    _validate_document, sanitize_transport_diagnostics,
)

# Literal public text/numbers observed in the ETT sources and official lists.
# "168" relates to the cited Council act of 14.12.2022; the observed Council
# list includes an act dated 09.07.2026, number 76. These remain search queries,
# not asserted identity matches or legal adoption/effective-date evidence.
PROBE_QUERIES = (
    ("ett_title", "Единого таможенного тарифа"),
    ("council_168_number", "168"),
    ("observed_council_date", "09.07.2026"),
)
# Exact numbers of index amendments not strictly identified in the retained
# ten-page title search (Run 34248830768). Number hits require separate exact
# issuer/date/number matching; neither query text nor an empty page is proof.
MISSING_ACT_QUERIES = tuple(("index_act_number_" + number, number) for number in (
    "170", "42", "77", "78", "24", "131", "35", "102", "104",
))
QUERY_SETS = {"initial": PROBE_QUERIES, "missing_index_acts": MISSING_ACT_QUERIES}
OBSERVED_FORM_SOURCE_SHA256 = (
    "d9c2c6856efd697ce8a54bda27f7673e88bd344aeaeb9aa5d06331546e1da729",
    "79c4909e92cb4a573dc2347e997dbb7bc7b186d560d1c374a209860d16af586f",
)
MAX_REPORT_BYTES = 128 * 1024
_TRANSPORT_REASONS = {
    "invalid public portal search query": "invalid_search_query",
    "invalid public portal search URL": "invalid_search_url",
    "invalid public portal search redirect": "invalid_search_redirect",
    "invalid official source URL": "invalid_source_url",
    "official source exceeded the elapsed time budget": "elapsed_time_budget",
    "official source is not an HTML document": "invalid_html_shape",
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


def _response_metadata(response: OfficialResponse, requested_url: str) -> dict:
    if not isinstance(response, OfficialResponse) or response.requested_url != requested_url or response.media_type != "text/html":
        raise ValueError("invalid response identity")
    if type(response.content) is not bytes or not 1 <= len(response.content) <= MAX_HTML_BYTES:
        raise ValueError("invalid response size")
    if type(response.redirect_chain) is not tuple or len(response.redirect_chain) > MAX_REDIRECTS:
        raise ValueError("invalid response redirects")
    _validate_search_url(response.requested_url)
    for url in (response.url, *response.redirect_chain):
        _validate_search_url(url)
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


def probe_portal_search(store: LocalArtifactStore, *, fetch=fetch_portal_search, query_set="initial") -> dict:
    """Attempt each literal query once, retain originals and continue failures."""
    if type(query_set) is not str or query_set not in QUERY_SETS:
        raise ValueError("unknown fixed query set")
    queries = QUERY_SETS[query_set]
    started_at = _instant(datetime.now(timezone.utc))
    results = []
    for query_id, query in queries:
        requested_url = PORTAL_SEARCH_URL + "?" + urlencode({"q": query})
        record = {
            "query_id": query_id, "query": query, "requested_url": requested_url,
            "expected_media_type": "text/html", "attempted_at": _instant(datetime.now(timezone.utc)),
        }
        try:
            response = fetch(query)
            metadata = _response_metadata(response, requested_url)
            if store.put(response.content) != metadata["sha256"]:
                raise ArtifactIntegrityError("source digest mismatch")
            record.update(status="captured", **metadata)
        except OfficialTransportError as exc:
            record.update(status="failed", reason=_TRANSPORT_REASONS.get(str(exc), "transport_failure"))
            diagnostics = sanitize_transport_diagnostics(exc.diagnostics)
            if diagnostics:
                record["diagnostics"] = diagnostics
        except ArtifactIntegrityError:
            record.update(status="failed", reason="source_storage_integrity_failure")
        except Exception:
            record.update(status="failed", reason="probe_operation_failed")
        results.append(record)
    captured = sum(record["status"] == "captured" for record in results)
    return {
        "schema_version": 1, "probe_kind": "observed_official_portal_search",
        "query_set": query_set,
        "started_at": started_at, "finished_at": _instant(datetime.now(timezone.utc)),
        "observed_form_source_sha256": list(OBSERVED_FORM_SOURCE_SHA256),
        "attempted_queries": len(results), "captured_queries": captured,
        "failed_queries": len(results) - captured, "all_queries_captured": captured == len(queries),
        "source_identity_verified": False, "adoption_dates_verified": False,
        "effective_dates_verified": False, "amendment_inventory_complete": False,
        "search_results_interpreted": False, "document_absence_verified": False,
        "production_ready": False, "active_rates_written": False,
        "storage_kind": "local_development", "durable_legal_retention_attested": False,
        "results": results,
    }


def _write_report(path: Path, report: dict) -> None:
    payload = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if len(payload) > MAX_REPORT_BYTES:
        raise ValueError("probe report exceeds its bound")
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".ett-search-probe-", delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
            os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def main(argv=None, *, fetch=fetch_portal_search) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--query-set", choices=tuple(QUERY_SETS), default="initial")
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink() or not args.output.parent.is_dir():
            raise ValueError("report destination unavailable")
        report = probe_portal_search(LocalArtifactStore(args.store_root), fetch=fetch, query_set=args.query_set)
        _write_report(args.output, report)
    except Exception:
        print(json.dumps({"status": "ERROR", "reason": "probe_setup_or_report_failed", "production_ready": False}))
        return 2
    print(json.dumps({
        "status": "captured" if report["all_queries_captured"] else "incomplete",
        "attempted_queries": report["attempted_queries"], "captured_queries": report["captured_queries"],
        "failed_queries": report["failed_queries"], "production_ready": False,
    }))
    return 0 if report["all_queries_captured"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
