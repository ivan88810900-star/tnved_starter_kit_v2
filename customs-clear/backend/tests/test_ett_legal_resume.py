"""Resume from verified original responses while replaying the source plan."""
from copy import deepcopy
import hashlib
import json

import pytest

from app.services import ett_legal_capture as capture
from app.services import ett_legal_resume as resume
from app.services.ett_discovery_audit import canonical_json_bytes
from app.services.ett_transport import OfficialResponse, OfficialTransportError
from tests.test_ett_legal_capture import (
    INSTANT, PAGE1, PAGE2, PDF, PDF_BYTES, PDF_PATH, SECOND_PDF, SECOND_PDF_PATH,
    assert_unverified, execute, mocked_fetch, originals, portal,
)


def rerun(audit, old, store, responses=None):
    seen = []
    report = resume.resume_legal_documents(
        store, canonical_json_bytes(old), canonical_json_bytes(audit),
        fetch=mocked_fetch(responses or {}, seen),
    )
    return report, seen


def test_complete_cache_uses_no_network_and_preserves_retrieval_and_redirect_provenance(tmp_path):
    audit, store = originals(tmp_path)
    redirected = OfficialResponse(
        requested_url=PDF, url=SECOND_PDF, content=PDF_BYTES, media_type="application/pdf",
        retrieved_at=INSTANT, redirect_chain=(SECOND_PDF,),
    )
    old, _ = execute(audit, store, {PAGE1: portal(), PDF: redirected})
    source_raw = canonical_json_bytes(old)
    before = {path.name: path.read_bytes() for path in (tmp_path / "objects").iterdir()}
    report, seen = rerun(audit, old, store)
    assert seen == []
    assert report["kind"] == old["kind"]
    assert report["supported_capture_plan_completed"] is True
    evidence = report["resume_evidence"]
    assert evidence["source_capture_report_sha256"] == hashlib.sha256(source_raw).hexdigest()
    assert store.read(evidence["source_capture_report_sha256"]) == source_raw
    assert evidence["reused_html_responses"] == evidence["reused_pdf_responses"] == 1
    assert evidence["new_request_count"] == 0 and evidence["new_requests"] == []
    assert evidence["original_retrieval_timestamps_preserved"] is True
    assert evidence["reused_sources_refetched"] is False
    assert evidence["source_capture_report_modified"] is False
    assert evidence["new_capture_of_reused_sources_claimed"] is False
    for category in ("documents", "pdfs"):
        assert report[category][0]["retrieval_origin"] == "reused_original_capture"
        assert report[category][0]["source_capture_report_sha256"] == evidence["source_capture_report_sha256"]
        for field in ("requested_url", "url", "retrieved_at", "redirect_chain", "sha256", "size_bytes"):
            assert report[category][0][field] == old[category][0][field]
    assert report["pdfs"][0]["redirect_chain"] == [SECOND_PDF]
    assert canonical_json_bytes(old) == source_raw
    assert all((tmp_path / "objects" / name).read_bytes() == raw for name, raw in before.items())
    assert_unverified(report)


def test_saved_html_from_prior_parser_failure_is_reparsed_then_only_missing_pdf_is_fetched(tmp_path, monkeypatch):
    audit, store = originals(tmp_path)
    with monkeypatch.context() as old_parser:
        def failed_identity(*args, **kwargs):
            raise capture.LegalCaptureError("document_metadata_missing_or_ambiguous")
        old_parser.setattr(capture, "_page_identity", failed_identity)
        old, seen = execute(audit, store, {PAGE1: portal()})
    assert seen == [(PAGE1, "text/html")]
    assert old["documents"][0]["status"] == "captured"
    assert old["documents"][0]["attachment_parse_status"] == "unresolved"
    assert old["pdfs"] == []
    report, seen = rerun(audit, old, store, {PDF: PDF_BYTES})
    assert seen == [(PDF, "application/pdf")]
    assert report["documents"][0]["attachment_parse_status"] == "parsed"
    assert report["documents"][0]["sha256"] == old["documents"][0]["sha256"]
    assert report["supported_capture_plan_completed"] is True
    assert report["resume_evidence"]["reused_html_responses"] == 1
    assert report["resume_evidence"]["reused_pdf_responses"] == 0
    assert report["resume_evidence"]["new_request_count"] == 1


@pytest.mark.parametrize("mutation", ["bytes", "size", "foreign_page"])
def test_invalid_cached_successful_record_fails_before_any_network(tmp_path, mutation):
    audit, store = originals(tmp_path)
    old, _ = execute(audit, store, {PAGE1: portal(), PDF: PDF_BYTES})
    changed = deepcopy(old)
    if mutation == "bytes":
        path = tmp_path / "objects" / (changed["pdfs"][0]["sha256"] + ".blob")
        path.chmod(0o600)
        path.write_bytes(b"corrupted cached PDF")
        path.chmod(0o400)
    elif mutation == "size":
        changed["pdfs"][0]["size_bytes"] += 1
    else:
        changed["documents"][0]["requested_url"] = PAGE2
        changed["documents"][0]["url"] = PAGE2
    with pytest.raises(ValueError):
        resume.resume_legal_documents(
            store, canonical_json_bytes(changed), canonical_json_bytes(audit),
            fetch=lambda *a, **k: pytest.fail("bad cached provenance reached network"),
        )


def test_modified_discovery_plan_cannot_be_authorized_by_existing_cached_sources(tmp_path):
    audit, store = originals(tmp_path)
    old, _ = execute(audit, store, {PAGE1: portal(), PDF: PDF_BYTES})
    changed = deepcopy(audit)
    changed["capture_plan"][0]["page_url"] = PAGE2
    changed["capture_plan_sha256"] = hashlib.sha256(canonical_json_bytes(changed["capture_plan"])).hexdigest()
    with pytest.raises(ValueError):
        resume.resume_legal_documents(
            store, canonical_json_bytes(old), canonical_json_bytes(changed),
            fetch=lambda *a, **k: pytest.fail("edited discovery reached network"),
        )


def test_same_discovery_object_with_different_bytes_does_not_replace_original_report_identity(tmp_path):
    audit, store = originals(tmp_path)
    old, _ = execute(audit, store, {PAGE1: portal(), PDF: PDF_BYTES})
    other_bytes = json.dumps(audit, ensure_ascii=False, indent=2).encode()
    assert other_bytes != canonical_json_bytes(audit)
    with pytest.raises(ValueError):
        resume.resume_legal_documents(
            store, canonical_json_bytes(old), other_bytes,
            fetch=lambda *a, **k: pytest.fail("different discovery bytes reached network"),
        )


def test_failed_pdf_with_retained_original_bytes_is_requested_again_instead_of_reused(tmp_path):
    audit, store = originals(tmp_path)
    failed_pdf = OfficialResponse(
        requested_url=PDF, url=PAGE2, content=PDF_BYTES, media_type="application/pdf",
        retrieved_at=INSTANT, redirect_chain=(PAGE2,),
    )
    old, _ = execute(audit, store, {PAGE1: portal(), PDF: failed_pdf})
    assert old["pdfs"][0]["status"] == "failed"
    assert old["pdfs"][0]["source_bytes_retained"] is True
    assert store.read(old["pdfs"][0]["sha256"]) == PDF_BYTES
    report, seen = rerun(audit, old, store, {PDF: PDF_BYTES})
    assert seen == [(PDF, "application/pdf")]
    assert report["resume_evidence"]["reused_pdf_responses"] == 0
    assert report["resume_evidence"]["new_request_count"] == 1
    assert report["pdfs"][0]["url"] == PDF
    assert report["supported_capture_plan_completed"] is True


def test_partial_capture_reuses_first_pdf_and_requests_only_missing_second_pdf(tmp_path):
    audit, store = originals(tmp_path)
    links = f'<a href="{PDF_PATH}">Рус</a><a href="{SECOND_PDF_PATH}">Приложение</a>'
    old, _ = execute(audit, store, {
        PAGE1: portal(links=links), PDF: PDF_BYTES,
        SECOND_PDF: OfficialTransportError("official source did not return HTTP 200"),
    })
    report, seen = rerun(audit, old, store, {SECOND_PDF: PDF_BYTES})
    assert seen == [(SECOND_PDF, "application/pdf")]
    assert report["captured_unique_pdfs"] == 2
    assert report["resume_evidence"]["reused_html_responses"] == 1
    assert report["resume_evidence"]["reused_pdf_responses"] == 1
    assert report["resume_evidence"]["new_request_count"] == 1
    assert report["supported_capture_plan_completed"] is True


def test_resumed_network_failure_preserves_cache_progress_and_sanitizes_request_failure(tmp_path):
    audit, store = originals(tmp_path)
    old, _ = execute(audit, store, {PAGE1: portal(), PDF: OfficialTransportError("official source did not return HTTP 200")})
    report, seen = rerun(audit, old, store, {PDF: OfficialTransportError("SECRET upstream diagnostic")})
    assert seen == [(PDF, "application/pdf")]
    assert report["captured_document_pages"] == 1
    assert report["captured_unique_pdfs"] == 0
    assert report["supported_capture_plan_completed"] is False
    assert report["resume_evidence"]["reused_html_responses"] == 1
    assert report["resume_evidence"]["new_request_count"] == 1
    assert len(report["resume_evidence"]["new_requests"]) == 1
    request = report["resume_evidence"]["new_requests"][0]
    assert request["requested_url"] == PDF
    assert request["expected_media_type"] == "application/pdf"
    assert report["documents"][0]["retrieval_origin"] == "reused_original_capture"
    assert report["pdfs"][0]["retrieval_origin"] == "new_request"
    assert "SECRET" not in json.dumps(report)
    assert_unverified(report)
