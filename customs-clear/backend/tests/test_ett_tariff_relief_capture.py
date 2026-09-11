"""Original acquisition remains bounded and distinct from legal completeness."""
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json

import pytest

from app.services.ett_artifacts import LocalArtifactStore
from app.services import ett_tariff_relief_capture as capture_module
from app.services.ett_tariff_relief_capture import (
    LANDING_SOURCES, ReliefCaptureError, capture_tariff_relief, extract_pdf_links, selected_details,
)
from app.services.ett_transport import OfficialResponse, OfficialTransportError
from scripts.capture_ett_tariff_relief import main

PDF_URL = "https://eec.eaeunion.org/upload/medialibrary/example.pdf"
DETAIL = "https://docs.eaeunion.org/documents/461/10843/"
CAPTURE_DETAIL_URLS = (
    DETAIL,
    "https://docs.eaeunion.org/documents/461/10846/",
    "https://docs.eaeunion.org/documents/461/10848/",
    "https://docs.eaeunion.org/documents/461/10854/",
)
PDF = b"%PDF-1.7\nSYNTHETIC TEST ORIGINAL\n%%EOF\n"


def html(anchors):
    return f"<!doctype html><html><body>{anchors}</body></html>".encode()


def response(url, media, content=None):
    return OfficialResponse(url=url, requested_url=url, media_type=media,
                            content=content if content is not None else PDF if media == "application/pdf" else html(f'<a href="{PDF_URL}">Original</a>'),
                            retrieved_at=datetime(2026, 9, 10, tzinfo=timezone.utc))


def fetch(url, *, expected_media):
    return response(url, expected_media)


def test_shared_pdf_is_fetched_once_with_both_original_parents(tmp_path):
    calls = []
    def counting(url, **kwargs):
        calls.append(url)
        return fetch(url, **kwargs)
    store = LocalArtifactStore(tmp_path / "objects")
    report = capture_tariff_relief(store, fetch=counting)
    assert calls == [url for _, url in LANDING_SOURCES] + [PDF_URL]
    assert report["capture_complete"] is True
    assert report["captured_sources"] == 3
    assert report["unique_eligible_pdf_targets"] == 1
    pdf_record = report["records"][-1]
    assert pdf_record["parent_link_indices"] == [0, 1]
    for record in report["records"]:
        raw = store.read(record["sha256"])
        assert len(raw) == record["size_bytes"]
        assert hashlib.sha256(raw).hexdigest() == record["sha256"]
    for link in report["links"]:
        assert link["raw_start_tag"] == f'<a href="{PDF_URL}">'
        assert link["label"] == "Original"
        assert link["parent_sha256"] == report["records"][0]["sha256"]
        assert link["parent_requested_url"] in calls[:2]
    for field in ("source_inventory_complete", "source_identity_verified", "effective_dates_verified",
                  "legal_ready", "can_promote", "production_ready", "active_rates_written", "durable_legal_retention_attested"):
        assert report[field] is False


def test_relative_pdf_is_resolved_against_final_response_url(tmp_path):
    final = "https://eec.eaeunion.org/changed/landing.html"
    def redirected(url, *, expected_media):
        if expected_media == "text/html":
            return replace(response(url, expected_media, html('<a href="files/original.pdf">Exact</a>')),
                           url=final, redirect_chain=(final,))
        assert url == "https://eec.eaeunion.org/changed/files/original.pdf"
        return fetch(url, expected_media=expected_media)
    report = capture_tariff_relief(LocalArtifactStore(tmp_path / "objects"), fetch=redirected)
    assert report["capture_complete"] is True
    assert report["links"][0]["parent_url"] == final
    assert report["links"][0]["parent_requested_url"] == LANDING_SOURCES[0][1]


def test_observed_cyrillic_and_internal_spaces_are_serialized_with_raw_href_retained():
    raw_href = "/sources/Льготы 130.pdf"
    links = extract_pdf_links(html(f'<a href="{raw_href}">Акт <b>130</b></a>'), parent_url=LANDING_SOURCES[0][1])
    assert links[0]["href"] == raw_href
    assert links[0]["label"] == "Акт 130"
    assert links[0]["resolved_url"] == "https://eec.eaeunion.org/sources/%D0%9B%D1%8C%D0%B3%D0%BE%D1%82%D1%8B%20130.pdf"


def test_percent_encoded_extension_cannot_silently_skip_a_direct_pdf():
    links = extract_pdf_links(html('<a href="/sources/original%2Epdf">Original</a>'), parent_url=LANDING_SOURCES[0][1])
    assert links[0]["resolved_url"] == "https://eec.eaeunion.org/sources/original%2Epdf"
    assert links[0]["href"] == "/sources/original%2Epdf"


@pytest.mark.parametrize("anchor", [
    '<a href="https://foreign.example/x.pdf">Foreign</a>',
    '<a href="http://eec.eaeunion.org/x.pdf">HTTP</a>',
    '<a href="/x.pdf?download=1">Query</a>',
    '<a href="/x.pdf#">Fragment</a>',
    '<a href="/x.pdf" href="/other.pdf">Ambiguous</a>',
    '<a href="&#9;https://eec.eaeunion.org/x.pdf">Control</a>',
    '<a href=" /x.pdf">Leading space</a>',
    '<a href="https://eec.eaeunion.org@foreign.example/x.pdf">Userinfo</a>',
    '<a href="/x%2fother.pdf">Encoded separator</a>',
])
def test_rejected_pdf_links_never_fetch_or_report_complete(tmp_path, anchor):
    calls = []
    def invalid(url, *, expected_media):
        calls.append(url)
        assert expected_media == "text/html"
        return response(url, expected_media, html(anchor))
    report = capture_tariff_relief(LocalArtifactStore(tmp_path / "objects"), fetch=invalid)
    assert len(calls) == 2
    assert report["capture_complete"] is False
    assert report["rejected_pdf_links"] == 2
    assert len(report["gaps"]) == 2


def test_detail_selection_is_explicit_and_html_links_are_not_crawled(tmp_path):
    calls = []
    def observed(url, *, expected_media):
        calls.append(url)
        if expected_media == "text/html":
            return response(url, expected_media, html(f'<a href="{DETAIL}">Selected page</a><a href="{PDF_URL}">PDF</a>'))
        return fetch(url, expected_media=expected_media)
    report = capture_tariff_relief(LocalArtifactStore(tmp_path / "default"), fetch=observed)
    assert report["capture_complete"] is True and DETAIL not in calls
    calls.clear()
    report = capture_tariff_relief(LocalArtifactStore(tmp_path / "selected"), detail_urls=(DETAIL,), fetch=observed)
    assert calls.count(DETAIL) == 1
    assert report["selected_detail_urls"] == [DETAIL]
    assert report["records"][2]["selection"] == "explicit_detail_selection"
    assert report["records"][-1]["parent_link_indices"] == [0, 1, 2]


@pytest.mark.parametrize("urls", [
    [DETAIL], (DETAIL, DETAIL), ("https://docs.eaeunion.org/documents/461/",),
    ("https://foreign.example/documents/461/10843/",),
    ("https://docs.eaeunion.org/documents/461/10843/?q=x",), tuple(DETAIL + str(index) for index in range(9)),
])
def test_detail_selection_is_bounded_and_cannot_be_a_search_or_arbitrary_host(urls):
    with pytest.raises((ReliefCaptureError, OfficialTransportError)):
        selected_details(urls)


@pytest.mark.parametrize("content", [html("No documents"), html('<base href="https://foreign.example/"><a href="x.pdf">PDF</a>'),
                                      b"<html><a href='/x.pdf'>\xff</a></html>"])
def test_empty_or_ambiguous_page_cannot_fake_capture_completeness(tmp_path, content):
    report = capture_tariff_relief(LocalArtifactStore(tmp_path / "objects"),
                                  fetch=lambda url, expected_media: response(url, expected_media, content))
    assert report["capture_complete"] is False
    assert report["captured_sources"] == 2  # originals retained even if extraction fails
    assert report["unique_eligible_pdf_targets"] == 0
    assert len(report["gaps"]) == 2


@pytest.mark.parametrize("error", [OfficialTransportError("Authorization SECRET"), RuntimeError("COOKIE PRIVATE"),
                                   ReliefCaptureError("TOKEN PRIVATE")])
def test_transport_or_callback_failure_is_sanitized_and_not_complete(tmp_path, error):
    def fail_pdf(url, *, expected_media):
        if expected_media == "application/pdf":
            raise error
        return fetch(url, expected_media=expected_media)
    report = capture_tariff_relief(LocalArtifactStore(tmp_path / "objects"), fetch=fail_pdf)
    assert report["capture_complete"] is False
    assert report["captured_sources"] == 2
    assert report["failed_sources"] == 1
    assert not any(secret in json.dumps(report) for secret in ("SECRET", "PRIVATE", "COOKIE", "TOKEN"))


@pytest.mark.parametrize("change", [
    {"requested_url": "https://eec.eaeunion.org/wrong"},
    {"url": "https://eec.eaeunion.org/wrong"},
    {"media_type": "application/pdf"},
    {"content": b"not html"},
    {"retrieved_at": datetime(2026, 9, 10)},
    {"redirect_chain": ["https://eec.eaeunion.org/wrong"]},
    {"url": "https://docs.eaeunion.org/wrong", "redirect_chain": ("https://docs.eaeunion.org/wrong",)},
])
def test_untrusted_response_identity_or_shape_is_not_stored(tmp_path, change):
    report = capture_tariff_relief(LocalArtifactStore(tmp_path / "objects"),
                                  fetch=lambda url, expected_media: replace(response(url, expected_media), **change))
    assert report["capture_complete"] is False
    assert report["captured_sources"] == 0
    assert report["failed_sources"] == 2
    assert not any("sha256" in record for record in report["records"])


def test_pdf_shape_is_rechecked_at_capture_boundary(tmp_path):
    def bad_pdf(url, *, expected_media):
        return response(url, expected_media, b"%PDF-1.7\nmissing EOF" if expected_media == "application/pdf" else None)
    report = capture_tariff_relief(LocalArtifactStore(tmp_path / "objects"), fetch=bad_pdf)
    assert report["failed_sources"] == 1
    assert report["records"][-1]["status"] == "failed"


def test_document_count_is_bounded_without_fake_complete(tmp_path, monkeypatch):
    monkeypatch.setattr(capture_module, "MAX_PDFS", 1)
    calls = []
    def many(url, *, expected_media):
        calls.append(url)
        if expected_media == "text/html":
            return response(url, expected_media, html('<a href="/a.pdf">A</a><a href="/b.pdf">B</a>'))
        return fetch(url, expected_media=expected_media)
    report = capture_tariff_relief(LocalArtifactStore(tmp_path / "objects"), fetch=many)
    assert len(calls) == 3
    assert report["capture_complete"] is False
    assert report["unique_eligible_pdf_targets"] == 2
    assert {"reason": "pdf_target_count_limit"} in report["gaps"]


def test_byte_budget_prevents_further_requests(tmp_path, monkeypatch):
    content = html(f'<a href="{PDF_URL}">PDF</a>')
    monkeypatch.setattr(capture_module, "MAX_TOTAL_BYTES", len(content))
    calls = []
    # Use exact content length for the single allowed first page.
    def exact(url, *, expected_media):
        calls.append(url)
        return response(url, expected_media, content)
    report = capture_tariff_relief(LocalArtifactStore(tmp_path / "objects"), fetch=exact)
    assert len(calls) == 1
    assert report["captured_bytes"] == len(content)
    assert report["capture_complete"] is False


def test_late_fetch_cannot_be_accepted_and_prevents_further_requests(tmp_path, monkeypatch):
    clock = [0.0]
    calls = []
    monkeypatch.setattr(capture_module.time, "monotonic", lambda: clock[0])
    def late(url, *, expected_media):
        calls.append(url)
        clock[0] = capture_module.MAX_SECONDS
        return fetch(url, expected_media=expected_media)
    report = capture_tariff_relief(LocalArtifactStore(tmp_path / "objects"), fetch=late)
    assert calls == [LANDING_SOURCES[0][1]]
    assert report["captured_sources"] == 0
    assert report["captured_bytes"] == 0
    assert report["failed_sources"] == 2
    assert report["capture_complete"] is False


def test_anchor_limit_is_enforced_before_document_fetch(tmp_path, monkeypatch):
    monkeypatch.setattr(capture_module, "MAX_ANCHORS", 1)
    report = capture_tariff_relief(LocalArtifactStore(tmp_path / "objects"),
                                  fetch=lambda url, expected_media: response(url, expected_media, html('<a href="/a.pdf">A</a><a href="/b.pdf">B</a>')))
    assert report["capture_complete"] is False
    assert len(report["records"]) == 2
    assert len(report["gaps"]) == 2


def test_cli_publishes_originals_and_new_complete_report_exclusively(tmp_path, capsys):
    destination = tmp_path / "report.json"
    args = ["--store-root", str(tmp_path / "store"), "--output", str(destination)]
    assert main(args, fetch=fetch) == 0
    original = destination.read_bytes()
    assert json.loads(original)["capture_complete"] is True
    assert main(args, fetch=lambda *args, **kwargs: pytest.fail("must not fetch with existing output")) == 2
    assert destination.read_bytes() == original
    assert "traceback" not in capsys.readouterr().out.lower()


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_cli_existing_special_output_cannot_fetch_or_overwrite(tmp_path, kind):
    import os
    destination = tmp_path / "report"
    if kind == "fifo":
        os.mkfifo(destination)
    else:
        destination.symlink_to(tmp_path / "missing")
    assert main(["--store-root", str(tmp_path / "store"), "--output", str(destination)],
                fetch=lambda *args, **kwargs: pytest.fail("must not fetch")) == 2


def test_cli_incomplete_capture_still_publishes_inspectable_report(tmp_path):
    destination = tmp_path / "report.json"
    assert main(["--store-root", str(tmp_path / "store"), "--output", str(destination)],
                fetch=lambda url, expected_media: response(url, expected_media, html("empty"))) == 2
    assert json.loads(destination.read_text())["capture_complete"] is False


def test_workflow_is_read_only_branch_limited_and_pinned():
    from pathlib import Path
    import yaml
    root = Path(__file__).resolve().parents[3]
    workflow = yaml.safe_load((root / ".github/workflows/ett-tariff-relief-capture.yml").read_text())
    triggers = workflow.get("on", workflow.get(True))
    assert set(triggers) == {"push", "workflow_dispatch"}
    assert triggers["push"]["branches"] == ["ops/ett-tariff-relief-capture"]
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["relief-capture"]
    assert job["if"] == "github.ref == 'refs/heads/ops/ett-tariff-relief-capture'"
    capture_step = next(step for step in job["steps"] if step["name"].startswith("Capture observed"))
    assert capture_step["run"].count("--detail-url ") == len(CAPTURE_DETAIL_URLS)
    for detail_url in CAPTURE_DETAIL_URLS:
        assert f"--detail-url {detail_url}" in capture_step["run"]
    for step in job["steps"]:
        if "uses" in step:
            assert len(step["uses"].split("@")[-1]) == 40
    assert job["steps"][-1]["with"]["retention-days"] == 90
