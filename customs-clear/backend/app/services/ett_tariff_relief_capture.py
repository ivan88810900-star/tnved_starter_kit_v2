"""Bounded acquisition of observed tariff-relief/GSP originals for review.

The two observed landing pages are captured once. Only their directly linked
PDFs and PDFs on explicitly selected official detail pages are followed. This
is not a crawler, a legal inventory, an eligibility check or a rate importer.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
import re
import time
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

from app.services.ett_artifacts import ArtifactIntegrityError, LocalArtifactStore
from app.services.ett_transport import (
    MAX_HTML_BYTES, MAX_PDF_BYTES, MAX_REDIRECTS, OfficialResponse,
    OfficialTransportError, _validate_document, fetch_official,
    sanitize_transport_diagnostics, validate_official_url,
)

LANDING_SOURCES = (
    ("tariff_relief", "https://eec.eaeunion.org/comission/department/catr/ttr/preferences.php"),
    ("gsp_preferences", "https://eec.eaeunion.org/comission/department/dotp/tariff_preferences.php"),
)
MAX_DETAILS = 8
MAX_ANCHORS = 2000
MAX_PDFS = 48
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_SECONDS = 900
MAX_OBSERVED_BASELINE_BYTES = 1024 * 1024


class ReliefCaptureError(ValueError):
    """A bounded capture cannot be completed or reproduced as requested."""


def selected_details(urls: tuple[str, ...]) -> tuple[str, ...]:
    if type(urls) is not tuple or len(urls) > MAX_DETAILS or len(set(urls)) != len(urls):
        raise ReliefCaptureError("invalid_detail_selection")
    for url in urls:
        validate_official_url(url)
        if not re.fullmatch(r"https://docs\.eaeunion\.org/documents/[0-9]+/[0-9]+/", url):
            raise ReliefCaptureError("invalid_detail_selection")
    return urls


class _Anchors(HTMLParser):
    """Retain positional href evidence; ambiguous attributes cannot choose a URL."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchors: list[dict] = []
        self.current: dict | None = None
        self.has_base = False

    def handle_starttag(self, tag, attrs):
        if tag == "base":
            self.has_base = True
        if tag != "a":
            return
        if len(self.anchors) >= MAX_ANCHORS:
            raise ReliefCaptureError("anchor_count_limit")
        hrefs = [value for name, value in attrs if name == "href"]
        if any(value is not None and len(value) > 4096 for value in hrefs):
            raise ReliefCaptureError("href_size_limit")
        raw_tag = self.get_starttag_text()
        if len(raw_tag) > 8192:
            raise ReliefCaptureError("anchor_tag_size_limit")
        self.current = {"anchor_index": len(self.anchors), "href_attributes": hrefs,
                        "raw_start_tag": raw_tag, "label": ""}
        self.anchors.append(self.current)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag == "a":
            self.current = None

    def handle_endtag(self, tag):
        if tag == "a":
            self.current = None

    def handle_data(self, data):
        if self.current is not None:
            self.current["label"] += data
            if len(self.current["label"]) > 8192:
                raise ReliefCaptureError("anchor_label_size_limit")


def extract_pdf_links(content: bytes, *, parent_url: str) -> list[dict]:
    """Extract exact observed anchors without fetching or inventing locators.

    Relative URLs resolve against the actual response URL. HTML base tags are
    rejected: silently ignoring or accepting one could change evidence identity.
    Query strings, foreign hosts and ambiguous PDF hrefs remain rejected records.
    """
    validate_official_url(parent_url)
    if type(content) is not bytes or not 0 < len(content) <= MAX_HTML_BYTES:
        raise ReliefCaptureError("invalid_html_size")
    _validate_document(content, "text/html")
    parser = _Anchors()
    parser.feed(content.decode("utf-8-sig", errors="strict"))
    parser.close()
    if parser.has_base:
        raise ReliefCaptureError("unsupported_html_base")
    source_sha256 = hashlib.sha256(content).hexdigest()
    links = []
    for anchor in parser.anchors:
        hrefs = anchor["href_attributes"]
        # Retain potentially relevant malformed hrefs; normal navigation links
        # are not capture targets and never initiate further HTML requests.
        if not any(type(href) is str and re.search(r"\.pdf(?:$|[?#\s])", unquote(href), re.I) for href in hrefs):
            continue
        link = {**anchor, "parent_url": parent_url, "parent_sha256": source_sha256,
                "label": " ".join(anchor["label"].split()), "status": "rejected"}
        if len(hrefs) != 1 or type(hrefs[0]) is not str:
            link["reason"] = "ambiguous_href"
        else:
            link["href"] = hrefs[0]
            try:
                # urljoin strips leading controls; reject them before resolution.
                if (hrefs[0] != hrefs[0].strip() or any(ord(char) < 32 or ord(char) == 127 for char in hrefs[0])
                        or any(char in hrefs[0] for char in "\\?#")):
                    raise ReliefCaptureError("invalid_href")
                resolved = urljoin(parent_url, hrefs[0])
                parsed = urlsplit(resolved)
                # URL serialization of the observed path, not a new locator.
                # Preserve existing escapes and exact href evidence, including
                # literal internal spaces and Cyrillic in official filenames.
                resolved = urlunsplit((parsed.scheme, parsed.netloc,
                                       quote(parsed.path, safe="/%:@-._~!$&'()*+,;="), "", ""))
                validate_official_url(resolved)
                if not unquote(urlsplit(resolved).path).lower().endswith(".pdf"):
                    raise ReliefCaptureError("invalid_pdf_path")
                link.update(status="eligible", resolved_url=resolved,
                            url_serialization="relative_resolution_and_utf8_path_encoding")
            except (OfficialTransportError, ReliefCaptureError, ValueError):
                link["reason"] = "unsupported_pdf_locator"
        links.append(link)
    return links


def _instant(value: datetime) -> str:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ReliefCaptureError("invalid_response_time")
    return value.isoformat()


def _metadata(response: OfficialResponse, url: str, media: str) -> dict:
    if not isinstance(response, OfficialResponse) or response.requested_url != url or response.media_type != media:
        raise ReliefCaptureError("invalid_response_identity")
    if type(response.content) is not bytes or not 0 < len(response.content) <= (MAX_PDF_BYTES if media == "application/pdf" else MAX_HTML_BYTES):
        raise ReliefCaptureError("invalid_response_size")
    if type(response.redirect_chain) is not tuple or len(response.redirect_chain) > MAX_REDIRECTS:
        raise ReliefCaptureError("invalid_response_redirects")
    chain = response.redirect_chain
    if (chain and chain[-1] != response.url) or (not chain and response.url != url):
        raise ReliefCaptureError("invalid_response_final_url")
    for destination in (response.url, *chain):
        validate_official_url(destination)
        if urlsplit(destination).netloc != urlsplit(url).netloc:
            raise ReliefCaptureError("invalid_response_origin")
    _validate_document(response.content, media)
    return {"requested_url": url, "response_url": response.url, "redirect_chain": list(chain),
            "sha256": hashlib.sha256(response.content).hexdigest(), "size_bytes": len(response.content),
            "media_type": media, "retrieved_at": _instant(response.retrieved_at)}


def capture_tariff_relief(store: LocalArtifactStore, *, detail_urls=(), fetch=fetch_official) -> dict:
    details = selected_details(detail_urls)
    started_at = _instant(datetime.now(timezone.utc))
    deadline = time.monotonic() + MAX_SECONDS
    total_bytes = 0
    records, links, gaps = [], [], []
    pages = [(*item, "observed_fixed_landing") for item in LANDING_SOURCES]
    pages += [(f"selected_detail_{index + 1}", url, "explicit_detail_selection") for index, url in enumerate(details)]

    def capture(url, media, **provenance):
        nonlocal total_bytes
        record = {"requested_url": url, "expected_media_type": media, **provenance}
        records.append(record)
        try:
            if time.monotonic() >= deadline:
                raise ReliefCaptureError("capture_time_limit")
            if total_bytes >= MAX_TOTAL_BYTES:
                raise ReliefCaptureError("capture_byte_limit")
            response = fetch(url, expected_media=media)
            if time.monotonic() >= deadline:
                raise ReliefCaptureError("capture_time_limit")
            metadata = _metadata(response, url, media)
            if total_bytes + len(response.content) > MAX_TOTAL_BYTES:
                raise ReliefCaptureError("capture_byte_limit")
            digest = store.put(response.content)
            if digest != metadata["sha256"]:
                raise ArtifactIntegrityError("capture_digest_mismatch")
            total_bytes += len(response.content)
            record.update(status="captured", **metadata)
            return response
        except OfficialTransportError as exc:
            record.update(status="failed", reason="official_transport_failure")
            diagnostics = sanitize_transport_diagnostics(exc.diagnostics)
            if diagnostics:
                record["diagnostics"] = diagnostics
        except ReliefCaptureError:
            record.update(status="failed", reason="capture_bounds_or_response_identity_failure")
        except ArtifactIntegrityError:
            record.update(status="failed", reason="source_storage_integrity_failure")
        except Exception:
            record.update(status="failed", reason="capture_operation_failed")
        return None

    for source_id, url, selection in pages:
        response = capture(url, "text/html", source_id=source_id, selection=selection)
        if response is None:
            continue
        try:
            observed = extract_pdf_links(response.content, parent_url=response.url)
            if not any(link["status"] == "eligible" for link in observed):
                gaps.append({"source_id": source_id, "reason": "no_eligible_pdf_links"})
            for link in observed:
                link.update(parent_requested_url=url, source_id=source_id)
            links.extend(observed)
        except Exception:
            gaps.append({"source_id": source_id, "reason": "landing_link_extraction_failed"})

    targets: dict[str, list[int]] = {}
    for index, link in enumerate(links):
        if link["status"] == "eligible":
            targets.setdefault(link["resolved_url"], []).append(index)
    if len(targets) > MAX_PDFS:
        gaps.append({"reason": "pdf_target_count_limit"})
    for index, (url, link_indices) in enumerate(targets.items()):
        if index >= MAX_PDFS:
            break
        capture(url, "application/pdf", selection="direct_observed_pdf", parent_link_indices=link_indices)
    failed = sum(record["status"] == "failed" for record in records)
    rejected = sum(link["status"] == "rejected" for link in links)
    complete = not failed and not rejected and not gaps and len(targets) <= MAX_PDFS
    return {
        "schema_version": 1, "capture_kind": "observed_tariff_relief_and_gsp_originals",
        "started_at": started_at, "finished_at": _instant(datetime.now(timezone.utc)),
        "selected_detail_urls": list(details), "capture_complete": complete,
        "attempted_sources": len(records), "captured_sources": len(records) - failed,
        "failed_sources": failed, "captured_bytes": total_bytes,
        "unique_eligible_pdf_targets": len(targets), "rejected_pdf_links": rejected,
        "source_inventory_complete": False, "source_identity_verified": False,
        "effective_dates_verified": False, "legal_ready": False, "can_promote": False,
        "production_ready": False, "active_rates_written": False,
        "storage_kind": "local_development", "durable_legal_retention_attested": False,
        "records": records, "links": links, "gaps": gaps,
    }


def _check(condition: bool) -> None:
    if not condition:
        raise ReliefCaptureError("invalid_capture_or_observation_evidence")


def _digest(value) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        _check(key not in result)
        result[key] = value
    return result


def _invalid_json_constant(value):
    raise ReliefCaptureError("invalid_json_constant")


def load_observed_baseline(raw: bytes) -> dict:
    """Read unapproved observation pins; never turn them into accepted baselines."""
    _check(type(raw) is bytes and 0 < len(raw) <= MAX_OBSERVED_BASELINE_BYTES)
    baseline = json.loads(raw.decode("utf-8"), object_pairs_hook=_json_object,
                          parse_constant=_invalid_json_constant)
    _check(type(baseline) is dict and type(baseline.get("schema_version")) is int and baseline["schema_version"] == 1)
    _check(baseline.get("observation_kind") == "retrieved_tariff_relief_gsp_artifacts")
    for flag in ("is_accepted_monitor_baseline", "is_legal_approval", "can_promote", "active_rates_written"):
        _check(baseline.get(flag) is False)
    _check(baseline.get("capture_complete") is True and _digest(baseline.get("capture_report_sha256")))
    sources = baseline.get("sources")
    _check(type(sources) is list and 0 < len(sources) <= MAX_PDFS)
    _check(type(baseline.get("source_count")) is int and baseline["source_count"] == len(sources))
    seen_urls, seen_ids = set(), set()
    for source in sources:
        _check(type(source) is dict)
        source_id = source.get("source_id")
        _check(type(source_id) is str and re.fullmatch(r"[a-z][a-z0-9_]{0,99}", source_id) is not None)
        _check(source_id not in seen_ids)
        seen_ids.add(source_id)
        for field in ("requested_url", "response_url", "parent_requested_url"):
            validate_official_url(source.get(field))
        _check(source["requested_url"] not in seen_urls)
        seen_urls.add(source["requested_url"])
        _check(urlsplit(source["response_url"]).netloc == urlsplit(source["requested_url"]).netloc)
        _check(source.get("media_type") == "application/pdf")
        _check(unquote(urlsplit(source["requested_url"]).path).lower().endswith(".pdf"))
        _check(_digest(source.get("sha256")) and _digest(source.get("parent_sha256")))
        for field, maximum in (("size_bytes", MAX_PDF_BYTES), ("parent_size_bytes", MAX_HTML_BYTES)):
            _check(type(source.get(field)) is int and 0 < source[field] <= maximum)
        for field in ("retrieved_at", "parent_retrieved_at"):
            _check(type(source.get(field)) is str)
            _instant(datetime.fromisoformat(source[field]))
        if source["parent_requested_url"] not in {url for _, url in LANDING_SOURCES}:
            selected_details((source["parent_requested_url"],))
    return baseline


def _replay_current_capture(report: dict, store: LocalArtifactStore) -> dict[str, dict]:
    """Recompute the complete current HTML→PDF graph from original objects.

    Historical pins identify an observation only; this replay does not assert
    possession or verification of the historical originals in that other run.
    """
    _check(type(report) is dict and type(report.get("schema_version")) is int and report["schema_version"] == 1)
    _check(report.get("capture_kind") == "observed_tariff_relief_and_gsp_originals")
    _check(report.get("capture_complete") is True)
    for field in ("source_inventory_complete", "source_identity_verified", "effective_dates_verified",
                  "legal_ready", "can_promote", "production_ready", "active_rates_written", "durable_legal_retention_attested"):
        _check(report.get(field) is False)
    details = report.get("selected_detail_urls")
    _check(type(details) is list)
    selected_details(tuple(details))
    pages = [(*item, "observed_fixed_landing") for item in LANDING_SOURCES]
    pages += [(f"selected_detail_{index + 1}", url, "explicit_detail_selection") for index, url in enumerate(details)]
    records = report.get("records")
    _check(type(records) is list and len(pages) < len(records) <= len(pages) + MAX_PDFS)
    _check(all(type(row) is dict and row.get("status") == "captured" for row in records))
    _check(all(type(row.get("size_bytes")) is int and row["size_bytes"] > 0 for row in records))
    _check(sum(row["size_bytes"] for row in records) <= MAX_TOTAL_BYTES)

    def original(row, url, media):
        _check(row.get("requested_url") == url and row.get("expected_media_type") == media)
        _check(_digest(row.get("sha256")) and type(row.get("redirect_chain")) is list)
        raw = store.read(row["sha256"])
        response = OfficialResponse(url=row.get("response_url"), requested_url=url,
                                    content=raw, media_type=media, retrieved_at=datetime.fromisoformat(row["retrieved_at"]),
                                    redirect_chain=tuple(row["redirect_chain"]))
        metadata = _metadata(response, url, media)
        _check(all(row.get(key) == value for key, value in metadata.items()))
        return raw

    replayed = []
    for row, (source_id, url, selection) in zip(records[:len(pages)], pages, strict=True):
        _check(row.get("source_id") == source_id and row.get("selection") == selection)
        raw = original(row, url, "text/html")
        links = extract_pdf_links(raw, parent_url=row["response_url"])
        _check(bool(links) and all(link["status"] == "eligible" for link in links))
        for link in links:
            link.update(parent_requested_url=url, source_id=source_id)
        replayed.extend(links)
    _check(type(report.get("links")) is list)
    # JSON equality must remain type-sensitive: False/0 and 0.0/0 cannot
    # substitute for the exact anchor indexes produced by the extractor.
    _check(json.dumps(report["links"], sort_keys=True, ensure_ascii=False)
           == json.dumps(replayed, sort_keys=True, ensure_ascii=False))
    targets: dict[str, list[int]] = {}
    for index, link in enumerate(replayed):
        targets.setdefault(link["resolved_url"], []).append(index)
    _check(len(records) == len(pages) + len(targets))
    result = {}
    for row, (url, indices) in zip(records[len(pages):], targets.items(), strict=True):
        _check(type(row.get("parent_link_indices")) is list
               and all(type(index) is int for index in row["parent_link_indices"]))
        _check(row.get("selection") == "direct_observed_pdf" and row.get("parent_link_indices") == indices)
        original(row, url, "application/pdf")
        result[url] = {**row, "parent_requested_urls": sorted({replayed[index]["parent_requested_url"] for index in indices})}
    for field in ("failed_sources", "captured_sources", "attempted_sources", "unique_eligible_pdf_targets", "captured_bytes", "rejected_pdf_links"):
        _check(type(report.get(field)) is int)
    _check(report.get("gaps") == [] and report.get("rejected_pdf_links") == 0)
    _check(report.get("failed_sources") == 0 and report.get("captured_sources") == len(records)
           and report.get("attempted_sources") == len(records) and report.get("unique_eligible_pdf_targets") == len(result)
           and report.get("captured_bytes") == sum(row["size_bytes"] for row in records))
    return result


def reconcile_tariff_relief(report: dict, store: LocalArtifactStore, *, observed_baseline: bytes | None = None) -> dict:
    """Detect live link replacement and same-URL byte changes without approval.

    Unchanged observation pins still require the separate review process. This
    function neither fetches historical PDFs nor accepts/replaces any baseline.
    HTML byte changes are not revision changes: every current anchor is replayed,
    while PDF URL/digest/final-URL and its observed parent determine the diff.
    """
    result = {"schema_version": 1, "comparison_kind": "unapproved_observation_pins",
              "review_required": True, "baseline_accepted": False, "baseline_updated": False,
              "operational_ok": False,
              "source_graph_verified": False, "historical_originals_replayed": False,
              "legal_ready": False, "can_promote": False, "active_rates_written": False,
              "added_pdf_urls": [], "missing_pdf_urls": [], "changed_pdfs": [],
              "observed_baseline_sha256": hashlib.sha256(observed_baseline).hexdigest() if type(observed_baseline) is bytes else None}
    try:
        baseline = load_observed_baseline(observed_baseline) if observed_baseline is not None else None
        if type(report) is not dict or report.get("capture_complete") is not True:
            result.update(status="capture_incomplete", reason="complete_current_capture_required")
            return result
        current = _replay_current_capture(report, store)
        result["source_graph_verified"] = True
        if baseline is None:
            result.update(status="baseline_missing", reason="first_observation_requires_review")
            return result
        previous = {row["requested_url"]: row for row in baseline["sources"]}
        result["added_pdf_urls"] = sorted(current.keys() - previous.keys())
        result["missing_pdf_urls"] = sorted(previous.keys() - current.keys())
        for url in sorted(current.keys() & previous.keys()):
            old, new = previous[url], current[url]
            fields = [field for field in ("sha256", "size_bytes", "response_url") if old[field] != new[field]]
            if old["parent_requested_url"] not in new["parent_requested_urls"]:
                fields.append("parent_requested_url")
            if fields:
                result["changed_pdfs"].append({"source_id": old["source_id"], "requested_url": url,
                                                "changed_fields": fields, "previous_sha256": old["sha256"],
                                                "observed_sha256": new["sha256"],
                                                "observed_response_url": new["response_url"],
                                                "observed_parent_requested_urls": new["parent_requested_urls"]})
        changed = bool(result["added_pdf_urls"] or result["missing_pdf_urls"] or result["changed_pdfs"])
        result.update(status="changes_detected" if changed else "observed_baseline_unreviewed",
                      operational_ok=not changed,
                      reason="source_link_or_content_change" if changed else "unchanged_observations_are_not_approval")
    except Exception:
        result.update(status="evidence_invalid", reason="observation_or_original_graph_validation_failed")
    return result
