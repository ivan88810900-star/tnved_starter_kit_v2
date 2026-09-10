"""Bounded acquisition of observed tariff-relief/GSP originals for review.

The two observed landing pages are captured once. Only their directly linked
PDFs and PDFs on explicitly selected official detail pages are followed. This
is not a crawler, a legal inventory, an eligibility check or a rate importer.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
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
