"""Replay captured parents before extracting native text from retained PDFs."""
from copy import deepcopy
import hashlib
import json

import pymupdf
import pytest

from app.services import ett_legal_text as text
from app.services.ett_discovery_audit import canonical_json_bytes
from app.services.ett_pdf_evidence import PDFEvidenceError, extract_pdf_evidence
from app.services.ett_transport import OfficialTransportError
from tests.test_ett_legal_capture import (
    PAGE1, PDF, PDF_PATH, SECOND_PDF, SECOND_PDF_PATH, execute, originals, portal,
)


@pytest.fixture(scope="module")
def pdf_bodies():
    with pymupdf.open() as document:
        document.new_page().insert_text((72, 90), "Synthetic legal text. No effective date verified.")
        native = document.tobytes()
    with pymupdf.open() as document:
        document.new_page()
        blank = document.tobytes()
    return native, blank


def captured(tmp_path, pdf_bodies, *, two=False, fail_first=False):
    audit, store = originals(tmp_path)
    links = f'<a href="{PDF_PATH}">Рус</a><a href="{PDF_PATH}">Скачать</a>'
    responses = {PDF: pdf_bodies[0]}
    if fail_first:
        responses[PDF] = OfficialTransportError("official source did not return HTTP 200")
    if two:
        links += f'<a href="{SECOND_PDF_PATH}">Приложение</a>'
        responses[SECOND_PDF] = pdf_bodies[1]
    responses[PAGE1] = portal(links=links)
    report, _ = execute(audit, store, responses)
    return report, store


def verify_false_flags(report):
    for flag in (
        "ocr_performed", "scan_image_presence_verified", "capture_plan_completion_verified",
        "original_ett_receipt_modified", "primary_act_bodies_verified", "legal_inventory_complete",
        "effective_dates_verified", "legal_approval_verified", "production_ready",
        "active_rates_written", "durable_legal_retention_attested",
    ):
        assert report[flag] is False


def test_actual_worker_retains_native_evidence_and_blank_page_ocr_candidate_without_scan_claim(tmp_path, pdf_bodies):
    capture, store = captured(tmp_path, pdf_bodies, two=True)
    raw = canonical_json_bytes(capture)
    report = text.extract_legal_documents(store, raw)
    assert report["extracted_pdfs"] == report["attempted_pdfs"] == 2
    assert report["failed_pdfs"] == 0
    assert report["all_declared_successful_pdfs_extracted"] is True
    assert report["capture_report_sha256"] == hashlib.sha256(raw).hexdigest()
    assert store.read(report["capture_report_sha256"]) == raw
    assert report["no_native_text_page_count"] == 1
    assert report["pdfs_with_ocr_candidates"] == report["all_pages_without_native_text_pdfs"] == 1
    native, blank = report["pdfs"]
    assert native["word_count"] > 0 and native["row_count"] > 0
    assert native["no_native_text_pages"] == native["ocr_candidate_pages"] == []
    assert native["all_pages_without_native_text"] is False
    assert blank["word_count"] == blank["row_count"] == 0
    assert blank["no_native_text_pages"] == blank["ocr_candidate_pages"] == [1]
    assert blank["all_pages_without_native_text"] is True
    with pymupdf.open(stream=pdf_bodies[1], filetype="pdf") as document:
        assert document[0].get_images() == []  # A blank page is not a scanned-image assertion.
    for result, body in zip(report["pdfs"], pdf_bodies):
        assert result["source_bindings_replayed"] is True
        assert result["source_sha256"] == hashlib.sha256(body).hexdigest()
        assert result["source_size_bytes"] == len(body)
        evidence_raw = store.read(result["extraction_report_sha256"])
        assert hashlib.sha256(evidence_raw).hexdigest() == result["extraction_report_sha256"]
        assert len(evidence_raw) == result["extraction_report_size_bytes"]
        evidence = json.loads(evidence_raw)
        assert evidence["artifact_sha256"] == result["source_sha256"]
        assert evidence["parser"]["engine_version"] == pymupdf.VersionBind
        assert evidence["can_promote"] is False
        assert result["scan_image_presence_verified"] is False
    verify_false_flags(report)


@pytest.mark.parametrize("mutation", ["bytes", "size", "parent", "reference_index", "url"])
def test_tampered_pdf_or_parent_reference_never_reaches_extractor(tmp_path, pdf_bodies, mutation):
    capture, store = captured(tmp_path, pdf_bodies)
    changed = deepcopy(capture)
    pdf = changed["pdfs"][0]
    if mutation == "bytes":
        path = tmp_path / "objects" / (pdf["sha256"] + ".blob")
        path.chmod(0o600)
        path.write_bytes(b"altered original PDF")
        path.chmod(0o400)
    elif mutation == "size":
        pdf["size_bytes"] += 1
    elif mutation == "parent":
        pdf["source_references"][0]["page_sha256"] = "f" * 64
    elif mutation == "reference_index":
        pdf["source_references"][0]["reference_index"] = 999
    else:
        pdf["requested_url"] = pdf["url"] = SECOND_PDF
    report = text.extract_legal_documents(
        store, canonical_json_bytes(changed),
        extract=lambda *a, **k: pytest.fail("unbound source reached PDF extraction"),
    )
    assert report["extracted_pdfs"] == 0
    assert report["failed_pdfs"] == 1
    assert report["all_declared_successful_pdfs_extracted"] is False
    assert "extraction_report_sha256" not in report["pdfs"][0]
    verify_false_flags(report)


def test_failed_capture_is_skipped_while_next_successful_pdf_is_extracted(tmp_path, pdf_bodies):
    capture, store = captured(tmp_path, pdf_bodies, two=True, fail_first=True)
    calls = []

    def extract(raw, **kwargs):
        calls.append(hashlib.sha256(raw).hexdigest())
        return extract_pdf_evidence(raw, **kwargs)

    report = text.extract_legal_documents(store, canonical_json_bytes(capture), extract=extract)
    assert calls == [hashlib.sha256(pdf_bodies[1]).hexdigest()]
    assert report["skipped_failed_capture_pdfs"] == 1
    assert report["declared_successful_pdfs"] == report["extracted_pdfs"] == 1
    assert report["all_declared_successful_pdfs_extracted"] is True
    assert report["pdfs"][0]["capture_pdf_index"] == 1
    assert report["capture_plan_completion_verified"] is False
    verify_false_flags(report)


def test_one_extraction_failure_keeps_next_pdf_progress_and_sanitizes_payload(tmp_path, pdf_bodies):
    capture, store = captured(tmp_path, pdf_bodies, two=True)
    calls = []

    def extract(raw, **kwargs):
        calls.append(raw)
        if len(calls) == 1:
            raise PDFEvidenceError("SECRET worker details")
        return extract_pdf_evidence(raw, **kwargs)

    report = text.extract_legal_documents(store, canonical_json_bytes(capture), extract=extract)
    assert calls == list(pdf_bodies)
    assert report["attempted_pdfs"] == 2
    assert report["failed_pdfs"] == report["extracted_pdfs"] == 1
    assert [row["status"] for row in report["pdfs"]] == ["failed", "extracted"]
    assert report["all_declared_successful_pdfs_extracted"] is False
    assert "SECRET" not in json.dumps(report)


@pytest.mark.parametrize("budget", ["count", "bytes", "time"])
def test_count_source_byte_and_elapsed_bounds_prevent_unbounded_extraction(tmp_path, pdf_bodies, monkeypatch, budget):
    capture, store = captured(tmp_path, pdf_bodies, two=True)
    calls = []

    def extract(raw, **kwargs):
        calls.append(raw)
        return extract_pdf_evidence(raw, **kwargs)

    if budget == "count":
        monkeypatch.setattr(text, "MAX_PDFS", 1)
    elif budget == "bytes":
        monkeypatch.setattr(text, "MAX_TOTAL_BYTES", 1)
    else:
        monkeypatch.setattr(text.time, "monotonic", lambda: 0.0)
        monkeypatch.setattr(text, "MAX_RUN_SECONDS", 1)
    if budget == "bytes":
        with pytest.raises(text.LegalTextError, match="artifact_byte_budget"):
            text.extract_legal_documents(store, canonical_json_bytes(capture), extract=extract)
        assert calls == []
        return
    report = text.extract_legal_documents(store, canonical_json_bytes(capture), extract=extract)
    assert report["all_declared_successful_pdfs_extracted"] is False
    if budget == "count":
        assert calls == [pdf_bodies[0]]
        assert report["extracted_pdfs"] == 1
        assert report["pending_capture_pdf_index"] == 1
        assert report["stop_reason"] == "pdf_count_budget"
    else:
        assert calls == []
        assert report["extracted_pdfs"] == 0
        assert report["stop_reason"] == "elapsed_time_budget"


def test_extractor_report_bound_to_another_source_cannot_be_published(tmp_path, pdf_bodies):
    capture, store = captured(tmp_path, pdf_bodies)

    def extract(raw, **kwargs):
        result = extract_pdf_evidence(raw, **kwargs)
        result["artifact_sha256"] = "f" * 64
        return result

    report = text.extract_legal_documents(store, canonical_json_bytes(capture), extract=extract)
    assert report["extracted_pdfs"] == 0
    assert report["failed_pdfs"] == 1
    assert report["pdfs"][0]["source_bindings_replayed"] is True
    assert "extraction_report_sha256" not in report["pdfs"][0]
    verify_false_flags(report)
