"""Capture only plans replayed from original discovery inputs; no live requests."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from html import escape
import json

import pytest

from app.services import ett_legal_capture as capture
from app.services.ett_discovery_audit import canonical_json_bytes
from app.services.ett_transport import OfficialResponse, OfficialTransportError
from tests.test_ett_discovery_audit import audit_fixture, matched_row
from tests.test_ett_portal_search_capture import body, url


PAGE1 = "https://docs.eaeunion.org/documents/463/1/"
PAGE2 = "https://docs.eaeunion.org/documents/463/2/"
PDF_PATH = "/upload/iblock/abc/synthetic/body.pdf"
PDF = "https://docs.eaeunion.org" + PDF_PATH
SECOND_PDF_PATH = "/upload/iblock/abc/synthetic/appendix.pdf"
SECOND_PDF = "https://docs.eaeunion.org" + SECOND_PDF_PATH
PDF_BYTES = b"%PDF-1.7\nSynthetic transport shape only; not a parseable legal PDF.\n%%EOF\n"
INSTANT = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
FALSE_FLAGS = (
    "original_ett_receipt_modified", "primary_act_bodies_verified", "legal_inventory_complete",
    "effective_dates_verified", "legal_approval_verified", "production_ready", "active_rates_written",
    "durable_legal_retention_attested",
)


def portal(*, number="66", adopted="19.04.2022", authority="Коллегии", number_field=None, links=None, extra=""):
    if links is None:
        links = f'<a href="{PDF_PATH}">Рус</a><a href="{PDF_PATH}">Скачать</a>'
    metadata = (
        ("Полный заголовок документа", "Синтетический пример"),
        ("Номер документа", number if number_field is None else number_field),
        ("Короткий заголовок документа", f"Решение {authority} ЕЭК № {number}"),
        ("Вид документа", "Решения"), ("Дата принятия документа", adopted),
    )
    rows = "".join(
        f'<div class="DocDetail_Row"><div class="DocDetail_Col _title">{escape(label)}</div>'
        f'<div class="DocDetail_Col _value">{escape(value)}</div></div>'
        for label, value in metadata
    )
    return (
        '<!doctype html><html><head><title>Правовой портал</title></head><body>'
        '<div>Правовой портал</div><div>Информация о документе</div>'
        f'<div class="DocDetail_Info">{rows}</div><div>{links}</div>{extra}</body></html>'
    ).encode()


def originals(tmp_path, *, two=False):
    pages = None
    if two:
        rows = matched_row() + matched_row(document="2", number="102", adopted="11.08.2026", category="Акты Евразийской экономической комиссии – Коллегия Евразийской экономической комиссии – Решения – 2026")
        pages = {url(1): body(rows=rows)}
    audit, store = audit_fixture(tmp_path, pages=pages)
    assert audit["capture_target_count"] == (2 if two else 1)
    return audit, store


def mocked_fetch(responses, seen, *, on_fetch=None):
    def fetch(requested, *, expected_media):
        seen.append((requested, expected_media))
        if on_fetch:
            on_fetch(requested)
        raw = responses[requested]
        if isinstance(raw, Exception):
            raise raw
        if isinstance(raw, OfficialResponse):
            return raw
        return OfficialResponse(
            url=requested, requested_url=requested, content=raw, media_type=expected_media,
            retrieved_at=INSTANT, redirect_chain=(),
        )
    return fetch


def execute(audit, store, responses, *, on_fetch=None):
    seen = []
    report = capture.capture_legal_documents(
        store, canonical_json_bytes(audit), fetch=mocked_fetch(responses, seen, on_fetch=on_fetch),
    )
    return report, seen


def assert_unverified(report):
    assert all(report[flag] is False for flag in FALSE_FLAGS)
    assert report["storage_kind"] == "local_development"


def test_valid_replayed_plan_retains_original_html_and_pdf_without_legal_extraction(tmp_path):
    audit, store = originals(tmp_path)
    html = portal()
    before = {path.name: path.read_bytes() for path in (tmp_path / "objects").iterdir()}
    report, seen = execute(audit, store, {PAGE1: html, PDF: PDF_BYTES})
    assert seen == [(PAGE1, "text/html"), (PDF, "application/pdf")]
    assert report["status"] == "supported_discovery_plan_captured"
    assert report["supported_capture_plan_completed"] is True
    assert report["discovery_plan_replayed"] is True
    assert report["captured_document_pages"] == report["identity_matched_document_pages"] == 1
    assert report["captured_unique_pdfs"] == 1
    assert report["failed_operations"] == 0
    assert report["retained_source_bytes"] == len(html) + len(PDF_BYTES)
    assert report["capture_plan_sha256"] == audit["capture_plan_sha256"]
    assert store.read(report["discovery_report_sha256"]) == canonical_json_bytes(audit)
    for record, raw in ((report["documents"][0], html), (report["pdfs"][0], PDF_BYTES)):
        assert record["sha256"] == hashlib.sha256(raw).hexdigest()
        assert record["size_bytes"] == len(raw)
        assert store.read(record["sha256"]) == raw
        assert datetime.fromisoformat(record["retrieved_at"].replace("Z", "+00:00")) == INSTANT
    assert all((tmp_path / "objects" / name).read_bytes() == raw for name, raw in before.items())
    assert_unverified(report)


@pytest.mark.parametrize("mutation", ["url", "identity", "observation", "input", "counter", "legal_claim"])
def test_rehashed_caller_plan_mutation_is_rejected_before_network_or_storage(tmp_path, mutation):
    audit, store = originals(tmp_path)
    changed = deepcopy(audit)
    target = changed["capture_plan"][0]
    if mutation == "url":
        target["page_url"] = "https://docs.eaeunion.org/documents/463/999/"
    elif mutation == "identity":
        target["identity"]["number"] = "67"
    elif mutation == "observation":
        target["observations"][0]["document_link"]["locator"] = "invented-location"
    elif mutation == "input":
        changed["inputs"]["pagination_report_sha256"] = "f" * 64
    elif mutation == "counter":
        changed["capture_target_count"] += 1
    else:
        changed["effective_dates_verified"] = True
    changed["capture_plan_sha256"] = hashlib.sha256(canonical_json_bytes(changed["capture_plan"])).hexdigest()
    before = {path.name for path in (tmp_path / "objects").iterdir()}
    with pytest.raises(capture.LegalCaptureError, match="discovery_plan_replay_failed"):
        capture.capture_legal_documents(store, canonical_json_bytes(changed), fetch=lambda *a, **k: pytest.fail("edited plan reached network"))
    assert {path.name for path in (tmp_path / "objects").iterdir()} == before


def test_tampered_original_search_html_cannot_be_hidden_by_unchanged_audit(tmp_path):
    audit, store = originals(tmp_path)
    source = tmp_path / "objects" / (audit["pages"][0]["source_sha256"] + ".blob")
    source.chmod(0o600)
    source.write_bytes(b"<html>tampered original</html>")
    source.chmod(0o400)
    with pytest.raises(capture.LegalCaptureError, match="discovery_plan_replay_failed"):
        capture.capture_legal_documents(store, canonical_json_bytes(audit), fetch=lambda *a, **k: pytest.fail("corrupt source reached network"))


def test_input_aggregate_bound_is_enforced_during_replay_before_network(tmp_path, monkeypatch):
    audit, store = originals(tmp_path)
    monkeypatch.setattr(capture, "MAX_INPUT_BYTES", 1)
    with pytest.raises(capture.LegalCaptureError, match="discovery_plan_replay_failed"):
        capture.capture_legal_documents(store, canonical_json_bytes(audit), fetch=lambda *a, **k: pytest.fail("oversized replay reached network"))


@pytest.mark.parametrize("changes", [
    {"authority": "Совета"}, {"adopted": "20.04.2022"}, {"number_field": "67"},
])
def test_wrong_metadata_identity_retains_original_html_without_following_pdf(tmp_path, changes):
    audit, store = originals(tmp_path)
    raw = portal(**changes)
    report, seen = execute(audit, store, {PAGE1: raw})
    assert seen == [(PAGE1, "text/html")]
    record = report["documents"][0]
    assert store.read(record["sha256"]) == raw
    assert record["attachment_parse_status"] == "unresolved"
    assert report["identity_matched_document_pages"] == report["attempted_unique_pdfs"] == 0
    assert report["failed_operations"] == 1
    assert report["supported_capture_plan_completed"] is False


def test_unsafe_attachment_failure_retains_html_without_pdf_request(tmp_path):
    audit, store = originals(tmp_path)
    raw = portal(links='<a href="https://evil.example/SECRET.pdf">PDF</a>')
    report, seen = execute(audit, store, {PAGE1: raw})
    assert seen == [(PAGE1, "text/html")]
    record = report["documents"][0]
    assert record["reason"] == "attachment_or_metadata_parse_failed"
    assert store.read(record["sha256"]) == raw
    assert report["supported_capture_plan_completed"] is False
    assert "SECRET" not in json.dumps(report)


def test_pdf_deduplication_preserves_every_original_parent_reference(tmp_path):
    audit, store = originals(tmp_path, two=True)
    report, seen = execute(audit, store, {PAGE1: portal(), PAGE2: portal(number="102", adopted="11.08.2026"), PDF: PDF_BYTES})
    assert seen == [(PAGE1, "text/html"), (PDF, "application/pdf"), (PAGE2, "text/html")]
    assert report["attempted_unique_pdfs"] == report["captured_unique_pdfs"] == 1
    refs = report["pdfs"][0]["source_references"]
    assert len(refs) == 4
    for document in report["documents"]:
        matching = [ref for ref in refs if ref["page_url"] == document["url"]]
        assert [ref["reference_index"] for ref in matching] == [0, 1]
        discovery = json.loads(store.read(document["attachment_discovery_sha256"]))
        for ref in matching:
            assert ref["page_sha256"] == document["sha256"]
            assert ref["attachment_discovery_sha256"] == document["attachment_discovery_sha256"]
            assert discovery["documents"][ref["reference_index"]]["url"] == PDF
    assert report["supported_capture_plan_completed"] is True
    assert_unverified(report)


def test_shape_rejected_pdf_bytes_are_retained_as_failed_evidence(tmp_path):
    audit, store = originals(tmp_path)
    rejected = b"<html><body>SECRET PDF error page</body></html>"
    report, seen = execute(audit, store, {PAGE1: portal(), PDF: rejected})
    assert seen == [(PAGE1, "text/html"), (PDF, "application/pdf")]
    record = report["pdfs"][0]
    assert record["status"] == "failed"
    assert record["document_validation_passed"] is False
    assert record["rejected_document_sha256"] == hashlib.sha256(rejected).hexdigest()
    assert store.read(record["rejected_document_sha256"]) == rejected
    assert report["captured_unique_pdfs"] == 0
    assert report["supported_capture_plan_completed"] is False
    assert "SECRET" not in json.dumps(report)


@pytest.mark.parametrize("failed_kind", ["html", "pdf"])
def test_http_or_pdf_failure_does_not_prevent_later_document_capture_or_trigger_retry(tmp_path, failed_kind):
    audit, store = originals(tmp_path, two=True)
    responses = {
        PAGE1: portal(), PAGE2: portal(number="102", adopted="11.08.2026", links=f'<a href="{SECOND_PDF_PATH}">PDF</a>'),
        PDF: PDF_BYTES, SECOND_PDF: PDF_BYTES,
    }
    failed_url = PAGE1 if failed_kind == "html" else PDF
    responses[failed_url] = OfficialTransportError("official source did not return HTTP 200")
    report, seen = execute(audit, store, responses)
    assert sum(requested == failed_url for requested, _ in seen) == 1
    assert (PAGE2, "text/html") in seen and (SECOND_PDF, "application/pdf") in seen
    assert report["documents"][1]["attachment_parse_status"] == "parsed"
    assert report["captured_unique_pdfs"] == 1
    assert report["failed_operations"] == 1
    assert report["stop_reason"] == "capture_failures"


def test_document_count_limit_keeps_completed_progress_and_pending_original_url(tmp_path, monkeypatch):
    audit, store = originals(tmp_path, two=True)
    assert capture.MAX_DOCUMENTS == 110
    monkeypatch.setattr(capture, "MAX_DOCUMENTS", 1)
    report, seen = execute(audit, store, {PAGE1: portal(), PDF: PDF_BYTES})
    assert seen == [(PAGE1, "text/html"), (PDF, "application/pdf")]
    assert report["stop_reason"] == "document_count_budget"
    assert report["pending_url"] == PAGE2
    assert report["captured_document_pages"] == report["captured_unique_pdfs"] == 1
    assert report["supported_capture_plan_completed"] is False


def test_unique_pdf_count_limit_does_not_count_duplicate_links_twice(tmp_path, monkeypatch):
    audit, store = originals(tmp_path)
    assert capture.MAX_PDFS == 256
    monkeypatch.setattr(capture, "MAX_PDFS", 1)
    raw = portal(links=f'<a href="{PDF_PATH}">Рус</a><a href="{PDF_PATH}">Скачать</a><a href="{SECOND_PDF_PATH}">Приложение</a>')
    report, seen = execute(audit, store, {PAGE1: raw, PDF: PDF_BYTES})
    assert seen == [(PAGE1, "text/html"), (PDF, "application/pdf")]
    assert report["stop_reason"] == "pdf_count_budget"
    assert report["pending_url"] == SECOND_PDF
    assert len(report["pdfs"][0]["source_references"]) == 2


def test_byte_limit_reserves_maximum_pdf_before_request(tmp_path, monkeypatch):
    audit, store = originals(tmp_path)
    assert capture.MAX_TOTAL_BYTES == 512 * 1024 * 1024
    monkeypatch.setattr(capture, "MAX_TOTAL_BYTES", capture.MAX_HTML_BYTES)
    report, seen = execute(audit, store, {PAGE1: portal()})
    assert seen == [(PAGE1, "text/html")]
    assert report["stop_reason"] == "source_byte_budget"
    assert report["pending_url"] == PDF
    assert report["captured_document_pages"] == 1
    assert report["attempted_unique_pdfs"] == 0


def test_elapsed_limit_reserves_bounded_request_before_network(tmp_path, monkeypatch):
    audit, store = originals(tmp_path)
    assert capture.MAX_RUN_SECONDS == 20 * 60
    monkeypatch.setattr(capture.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(capture, "MAX_RUN_SECONDS", 2)
    monkeypatch.setattr(capture, "MAX_REQUEST_SECONDS", 3)
    report, seen = execute(audit, store, {})
    assert seen == []
    assert report["stop_reason"] == "elapsed_time_budget"
    assert report["pending_url"] == PAGE1


def test_late_returned_html_is_retained_failed_and_cannot_trigger_attachment_fetch(tmp_path, monkeypatch):
    audit, store = originals(tmp_path)
    now = [0.0]
    monkeypatch.setattr(capture.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(capture, "MAX_RUN_SECONDS", 2)
    monkeypatch.setattr(capture, "MAX_REQUEST_SECONDS", 1)
    raw = portal()
    report, seen = execute(audit, store, {PAGE1: raw}, on_fetch=lambda _: now.__setitem__(0, 3.0))
    assert seen == [(PAGE1, "text/html")]
    record = report["documents"][0]
    assert record["status"] == "failed" and record["reason"] == "elapsed_time_budget"
    assert record["source_bytes_retained"] is True
    assert store.read(record["sha256"]) == raw
    assert report["attempted_unique_pdfs"] == report["captured_document_pages"] == 0


def test_redirected_document_page_is_retained_but_cannot_rebase_attachment_identity(tmp_path):
    audit, store = originals(tmp_path)
    response = OfficialResponse(url=PAGE2, requested_url=PAGE1, content=portal(), media_type="text/html", retrieved_at=INSTANT, redirect_chain=(PAGE2,))
    report, seen = execute(audit, store, {PAGE1: response})
    assert seen == [(PAGE1, "text/html")]
    assert report["documents"][0]["reason"] == "document_page_redirect_changed"
    assert store.read(report["documents"][0]["sha256"]) == response.content
    assert report["attempted_unique_pdfs"] == 0
