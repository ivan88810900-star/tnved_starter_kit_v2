#!/usr/bin/env python3
"""Inspect retained observations without fetching, accepting or interpreting them."""
from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.parse import urljoin, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.ett_artifacts import ArtifactIntegrityError, LocalArtifactStore
from app.services.regulatory_source_capture import (
    url_identity, verify_original_capture, verify_rejected_original_capture,
)
from scripts.monitor_official_ntm_sources import REVIEW_ONLY_CAPTURE_PLANS, REVIEW_ONLY_SOURCES

DEFAULT_CAPTURE_PLAN = "ad30-discovery-20260912"

_MAX_REPORT_BYTES = 4 * 1024 * 1024
_MAX_LINKS = 300
_HOSTS = {"docs.eaeunion.org", "eec.eaeunion.org", "remedies.eaeunion.org"}
_FALSE_CLAIMS = (
    "legal_review_verified", "active_rates_written", "can_promote",
    "durable_legal_retention_attested", "production_ready",
)


def _require(condition):
    if not condition:
        raise ArtifactIntegrityError("Observed capture inspection failed")


def _object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _text(value, limit=600):
    value = re.sub(r"https?://\S+", "[URL omitted]", value)
    return " ".join(value.split())[:limit]


class _Links(HTMLParser):
    """Literal anchor observations only; no applicability or source approval."""

    def __init__(self, base_url):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.anchor = None
        self.title = []
        self.in_title = False
        self.links = {}
        self.truncated = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.in_title = True
        if tag != "a":
            return
        self._finish()
        attrs = dict(attrs)
        href = attrs.get("href")
        if isinstance(href, str) and 0 < len(href) <= 16384:
            self.anchor = {
                "href": href, "line": self.getpos()[0],
                "title": attrs.get("title") or "", "text": [],
            }

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)
        if self.anchor is not None:
            self.anchor["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag == "a":
            self._finish()

    def _finish(self):
        anchor, self.anchor = self.anchor, None
        if anchor is None:
            return
        raw = anchor["href"]
        if any(ord(char) < 32 or ord(char) == 127 for char in raw):
            return
        try:
            absolute = urljoin(self.base_url, raw)
            identity = url_identity(absolute)
            parts = urlsplit(absolute)
        except ValueError:
            return
        if parts.hostname not in _HOSTS:
            return
        if not (
            parts.path.lower().endswith(".pdf")
            or parts.path.startswith("/documents/") and parts.path != "/documents/"
        ):
            return
        key = identity["url_sha256"]
        text = _text(" ".join(anchor["text"]) or anchor["title"])
        candidate = {
            "href_observed": raw if not identity["query_redacted"] and not identity["fragment_redacted"] else None,
            "href_observation": "HTMLParser-decoded attribute; not raw byte spelling",
            "href_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "resolved": identity,
            "anchor_line": anchor["line"],
            "anchor_text_normalized": text,
            "decision12_date_candidate": bool(re.search(
                r"(?:09[./-]02[./-]2021|9\s+февраля\s+2021)", text, re.I,
            )),
            "discovery_only": True,
            "legal_review_verified": False,
        }
        if key in self.links:
            if len(text) > len(self.links[key]["anchor_text_normalized"]):
                self.links[key] = candidate
        elif len(self.links) < _MAX_LINKS:
            self.links[key] = candidate
        else:
            self.truncated = True

    def result(self):
        self._finish()
        return {
            "document_title_normalized": _text(" ".join(self.title)),
            "links": list(self.links.values()),
            "links_truncated": self.truncated,
            "discovery_only": True,
        }


def _native_pdf_text(body, source_id):
    """Expose existing native rows only; an empty text layer remains empty."""
    from app.services.ett_pdf_evidence import extract_pdf_evidence

    try:
        evidence = extract_pdf_evidence(body, artifact_id=source_id)
        _require(evidence["artifact_sha256"] == hashlib.sha256(body).hexdigest())
        _require(evidence["size_bytes"] == len(body) and 1 <= evidence["page_count"] <= 30)
        pages = []
        for page in evidence["pages"]:
            rows = [
                {key: row[key] for key in ("row", "raw_text", "raw_text_sha256", "bbox")}
                for row in page["rows"]
            ]
            text = "\n".join(row["raw_text"] for row in rows)
            pages.append({
                "page": page["page"], "rows": rows,
                "page_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "has_native_text": bool(text.strip()),
            })
        _require(len(pages) == evidence["page_count"])
        _require(len(json.dumps(pages, ensure_ascii=False).encode("utf-8")) <= 2 * 1024 * 1024)
        complete = all(page["has_native_text"] for page in pages)
        return {
            "status": "native_text_extracted" if complete else "native_text_incomplete",
            "artifact_sha256": evidence["artifact_sha256"],
            "parser": evidence["parser"], "text_serialization": evidence["text_serialization"],
            "page_count": len(pages), "pages": pages, "all_pages_have_native_text": complete,
            "ocr_used": False, "legal_review_verified": False, "can_promote": False,
        }
    except Exception:
        return {
            "status": "unavailable", "reason": "native_pdf_text_could_not_be_extracted",
            "ocr_used": False, "legal_review_verified": False, "can_promote": False,
        }


def inspect_capture(store, report, *, capture_plan=DEFAULT_CAPTURE_PLAN, extract_native_pdf_text=False):
    """Replay receipts against one named, fixed observation scope."""
    _require(isinstance(capture_plan, str) and capture_plan in REVIEW_ONLY_CAPTURE_PLANS)
    _require(type(extract_native_pdf_text) is bool)
    ids = list(REVIEW_ONLY_CAPTURE_PLANS[capture_plan])
    _require(type(report) is dict and report.get("selected_source_ids") == ids)
    _require(report.get("accepted_source_ids") == [])
    _require(report.get("full_registry_checked") is False)
    _require(report.get("selected_registered_source_ids") == [])
    _require(report.get("selected_review_only_source_ids") == ids)
    _require(all(report.get(key) is False for key in _FALSE_CLAIMS if key != "production_ready"))
    rows = report.get("sources")
    _require(type(rows) is list and len(rows) == len(ids))
    _require(all(type(row) is dict for row in rows))
    _require([row.get("source_id") for row in rows] == ids)
    result = {
        "schema_version": 1, "kind": "read_only_observed_capture_inspection",
        "capture_plan": capture_plan,
        "native_pdf_text_requested": extract_native_pdf_text,
        "inspection_status": "verified_retained_evidence",
        "selected_source_count": len(ids), "original_count": 0, "quarantined_count": 0,
        "unretained_count": 0, "sources": [], **dict.fromkeys(_FALSE_CLAIMS, False),
    }
    for row in rows:
        source_id = row["source_id"]
        _require(type(row.get("ok")) is bool)
        original = row.get("original_capture")
        rejected = row.get("rejected_original_capture")
        _require(not (original is not None and rejected is not None))
        item = {"source_id": source_id, "monitor_ok": row["ok"], "discovery_only": True}
        capture = rejected if rejected is not None else original
        if capture is None:
            _require(row["ok"] is False)
            item["capture_status"] = "not_retained"
            status = row.get("status_code")
            item["reported_status_code"] = status if type(status) is int and 100 <= status <= 599 else None
            result["unretained_count"] += 1
            result["sources"].append(item)
            continue
        _require(type(capture) is dict and isinstance(capture.get("receipt_sha256"), str))
        receipt_sha = capture["receipt_sha256"]
        verify = verify_rejected_original_capture if rejected is not None else verify_original_capture
        receipt = verify(store, receipt_sha)
        _require({key: value for key, value in capture.items() if key != "receipt_sha256"} == receipt)
        _require(source_id in receipt["source_ids"])
        _require(receipt["requested"] == url_identity(REVIEW_ONLY_SOURCES[source_id]))
        _require(row.get("status_code") == receipt["status_code"])
        if rejected is not None:
            _require(row["ok"] is False)
            _require(row.get("validation_error") == receipt["validation_error"])
        status = "quarantined_content_rejected" if rejected is not None else "original_retained"
        result["quarantined_count" if rejected is not None else "original_count"] += 1
        item.update({
            "capture_status": status, "receipt_sha256": receipt_sha,
            "body_sha256": receipt["original_body_sha256"],
            "size_bytes": receipt["size_bytes"], "status_code": receipt["status_code"],
            "content_type": receipt["content_type"], "retrieved_at": receipt["retrieved_at"],
            "requested": receipt["requested"], "response": receipt["response"],
            "validation_error": receipt.get("validation_error"),
        })
        if extract_native_pdf_text and rejected is None and receipt["content_type"].split(";", 1)[0].strip().lower() == "application/pdf":
            item["native_pdf_text"] = _native_pdf_text(store.read(receipt["original_body_sha256"]), source_id)
        if source_id.startswith("review_remedy_index_page_"):
            body = store.read(receipt["original_body_sha256"])
            parser = _Links(REVIEW_ONLY_SOURCES[source_id])
            parser.feed(body.decode("utf-8", errors="replace"))
            parser.close()
            item["pagination_discovery"] = parser.result()
        result["sources"].append(item)
    complete = result["original_count"] == len(ids) and all(row["ok"] for row in rows)
    _require(type(report.get("original_capture_count")) is int)
    _require(type(report.get("rejected_original_capture_count")) is int)
    _require(report.get("original_capture_count") == result["original_count"])
    _require(report.get("rejected_original_capture_count") == result["quarantined_count"])
    _require(report.get("original_capture_complete") is complete)
    result["original_capture_complete"] = complete
    result["all_selected_bodies_retained"] = result["unretained_count"] == 0
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capture-plan", choices=tuple(REVIEW_ONLY_CAPTURE_PLANS), default=DEFAULT_CAPTURE_PLAN)
    parser.add_argument("--extract-native-pdf-text", action="store_true", help="Extract verified original PDF rows for review; never OCR or approve")
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output == args.report.resolve() or output.is_relative_to(args.store_root.resolve()):
        parser.error("--output must be outside the store and distinct from the input report")
    try:
        with args.report.open("rb") as source:
            raw = source.read(_MAX_REPORT_BYTES + 1)
        _require(0 < len(raw) <= _MAX_REPORT_BYTES)
        report = json.loads(raw, object_pairs_hook=_object)
        result = inspect_capture(
            LocalArtifactStore(args.store_root, create=False), report,
            capture_plan=args.capture_plan, extract_native_pdf_text=args.extract_native_pdf_text,
        )
        result["input_report_sha256"] = hashlib.sha256(raw).hexdigest()
        exit_code = 0
    except Exception:
        result = {
            "schema_version": 1, "kind": "read_only_observed_capture_inspection",
            "inspection_status": "unavailable",
            "error": "retained_evidence_or_report_could_not_be_verified",
            **dict.fromkeys(_FALSE_CLAIMS, False),
        }
        exit_code = 1
    # Only the explicit result path is written. CAS and input report stay read-only.
    with args.output.open("x", encoding="utf-8") as destination:
        destination.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    summary = {key: value for key, value in result.items() if key != "sources"}
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    for source in result.get("sources", []):
        print(json.dumps({key: value for key, value in source.items() if key not in {"pagination_discovery", "native_pdf_text"}}, ensure_ascii=False, sort_keys=True))
        native = source.get("native_pdf_text")
        if native is not None:
            print(json.dumps({
                "source_id": source["source_id"], "body_sha256": source["body_sha256"],
                "receipt_sha256": source["receipt_sha256"],
                "native_pdf_text": {key: value for key, value in native.items() if key != "pages"},
            }, ensure_ascii=False, sort_keys=True))
            for page in native.get("pages", []):
                print(json.dumps({
                    "source_id": source["source_id"], "body_sha256": source["body_sha256"],
                    "receipt_sha256": source["receipt_sha256"], "native_pdf_page": page,
                    "discovery_only": True, "legal_review_verified": False,
                }, ensure_ascii=False, sort_keys=True))
        discovery = source.get("pagination_discovery")
        if discovery is not None:
            print(json.dumps({
                "source_id": source["source_id"], "body_sha256": source["body_sha256"],
                "receipt_sha256": source["receipt_sha256"], "pagination_discovery": discovery,
            }, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
