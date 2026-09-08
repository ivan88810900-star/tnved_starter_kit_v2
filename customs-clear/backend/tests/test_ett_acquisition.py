"""Download-set atomicity and provenance; fixtures are explicitly synthetic."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest

from app.services import ett_acquisition as acquisition
from app.services.ett_artifacts import LocalArtifactStore
from app.services.ett_index import INDEX_URL, parse_index
from app.services.ett_transport import OfficialResponse
from tests.ett_index_fixtures import synthetic_index_html


@pytest.fixture
def store(tmp_path):
    return LocalArtifactStore(tmp_path / "objects")


def fake_fetch(*, end_html=None, fail_at=None):
    """In-memory transport seam; never a real source attestation."""
    calls = []
    def fetch(url, *, expected_media):
        calls.append((url, expected_media))
        if len(calls) == fail_at:
            raise ValueError("simulated network failure")
        body = synthetic_index_html() if url == INDEX_URL else (b"%PDF-1.7\nSYNTHETIC " + url.encode() + b"\n%%EOF\n")
        if url == INDEX_URL and len(calls) > 1 and end_html is not None:
            body = end_html
        if url != INDEX_URL and expected_media == "text/html":
            body = b"<!doctype html><html><body>SYNTHETIC legal landing page</body></html>"
        return OfficialResponse(url=url, requested_url=url, content=body, media_type=expected_media,
                                retrieved_at=datetime(2026, 9, 8, tzinfo=timezone.utc) + timedelta(seconds=len(calls)))
    return fetch, calls


def capture(store, **kwargs):
    fetch, calls = fake_fetch(**kwargs)
    result = acquisition.acquire_official(store, _fetch=fetch)
    return result, calls


def test_complete_download_set_is_one_revalidatable_technical_receipt(store):
    result, calls = capture(store)
    receipt, discovery = acquisition.load_acquisition(store, result["receipt_sha256"])
    assert len(discovery.chapters) == 96
    assert result["downloaded_documents"] == len(discovery.documents) + len(discovery.amendment_links)
    assert calls[0] == calls[-1] == (INDEX_URL, "text/html")
    assert len(calls) == result["downloaded_documents"] + 2
    assert result["production_ready"] is result["active_rates_written"] is False
    assert receipt.legal_inventory_complete is receipt.effective_dates_verified is False
    assert receipt.mode == "technical_capture_only"
    assert not {"rates", "valid_from", "vat"}.intersection(type(receipt).model_fields)
    assert hashlib.sha256(store.read(result["receipt_sha256"])).hexdigest() == result["receipt_sha256"]


def test_index_changes_abort_receipt_publication(store):
    changed = synthetic_index_html().replace(b"published-01-opaque", b"revised-01-new")
    with pytest.raises(acquisition.AcquisitionError, match="changed during"):
        capture(store, end_html=changed)


def test_fetch_failure_never_returns_success_or_writes_application_tables(store):
    with pytest.raises(ValueError, match="simulated"):
        capture(store, fail_at=8)


def test_retrieval_does_not_sort_notes_by_file_date(store):
    result, _ = capture(store)
    _, discovery = acquisition.load_acquisition(store, result["receipt_sha256"])
    assert discovery.tariff_notes.url.endswith("_24.08.2026.pdf")
    assert any(ref.url.endswith("_08.02.2024.pdf") for ref in discovery.additional_documents)


@pytest.mark.parametrize("mutation", ["missing_download", "duplicate_download", "unrelated_url", "wrong_size", "wrong_discovery",
    "wrong_role", "future_retrieval", "final_index_url", "claim_current", "redirect_final", "redirect_cross_host", "redirect_loop"])
def test_receipt_rehash_cannot_hide_invalid_source_bindings(store, mutation):
    result, _ = capture(store)
    value = json.loads(store.read(result["receipt_sha256"]))
    first = value["downloads"][0]
    if mutation == "missing_download": value["downloads"].pop()
    elif mutation == "duplicate_download": value["downloads"][-1] = deepcopy(first)
    elif mutation == "unrelated_url": first["requested_url"] = first["url"] = INDEX_URL + "unrelated.pdf"
    elif mutation == "wrong_size": first["size_bytes"] += 1
    elif mutation == "wrong_discovery": value["discovery_sha256"] = "0" * 64
    elif mutation == "wrong_role": first["media_type"] = "text/html"
    elif mutation == "future_retrieval": first["retrieved_at"] = "2027-01-01T00:00:00Z"
    elif mutation == "final_index_url":
        value["index_start"]["url"] = INDEX_URL + "other/"
        value["index_start"]["redirect_chain"] = [value["index_start"]["url"]]
    elif mutation == "claim_current": value["legal_inventory_complete"] = True
    elif mutation == "redirect_final": first["redirect_chain"] = [INDEX_URL + "other.pdf"]
    elif mutation == "redirect_cross_host":
        first["url"] = "https://docs.eaeunion.org/documents/1/2/"
        first["redirect_chain"] = [first["url"]]
    elif mutation == "redirect_loop": first["redirect_chain"] = [first["url"]]
    changed_digest = store.put(acquisition.canonical_bytes(value))
    with pytest.raises(ValueError):
        acquisition.load_acquisition(store, changed_digest)


def test_rehashed_receipt_must_use_canonical_serialization(store):
    result, _ = capture(store)
    value = json.loads(store.read(result["receipt_sha256"]))
    digest = store.put(json.dumps(value, indent=2).encode())
    with pytest.raises(acquisition.AcquisitionError, match="canonical"):
        acquisition.load_acquisition(store, digest)


def test_index_redirect_does_not_rebase_relative_document_links(store):
    fetch, _ = fake_fetch()
    def redirect(url, **kwargs):
        response = fetch(url, **kwargs)
        return replace(response, url=INDEX_URL + "moved/", redirect_chain=(INDEX_URL + "moved/",))
    with pytest.raises(acquisition.AcquisitionError, match="discovery base"):
        acquisition.acquire_official(store, _fetch=redirect)


def test_aggregate_bound_stops_before_a_receipt_is_created(store, monkeypatch):
    monkeypatch.setattr(acquisition, "MAX_TOTAL_BYTES", len(synthetic_index_html()) + 10)
    with pytest.raises(acquisition.AcquisitionError, match="aggregate"):
        capture(store)


def test_elapsed_budget_stops_capture(store, monkeypatch):
    moments = iter([0, acquisition.MAX_RUN_SECONDS + 1])
    monkeypatch.setattr(acquisition.time, "monotonic", lambda: next(moments))
    with pytest.raises(acquisition.AcquisitionError, match="elapsed-time"):
        capture(store)


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}'])
def test_receipt_json_rejects_ambiguity(raw):
    with pytest.raises(ValueError): acquisition.read_json(raw)


def test_extraction_uses_verified_original_objects_and_preserves_the_capture(store, monkeypatch):
    from app.services import ett_pdf_evidence
    result, _ = capture(store)
    calls = []
    def fake_extract(data, *, artifact_id, chapter):
        calls.append((artifact_id, chapter))
        return {"artifact_sha256": hashlib.sha256(data).hexdigest(), "artifact_id": artifact_id,
                "chapter": chapter, "mode": "extraction_review", "can_promote": False}
    monkeypatch.setattr(ett_pdf_evidence, "extract_pdf_evidence", fake_extract)
    report = acquisition.extract_acquisition(store, result["receipt_sha256"])
    assert report["chapters"] == 96
    assert report["extracted_documents"] == len(parse_index(synthetic_index_html()).documents)
    assert len(calls) == report["extracted_documents"]
    summary = json.loads(store.read(report["report_sha256"]))
    assert summary["receipt_sha256"] == result["receipt_sha256"]
    assert summary["effective_dates_verified"] is summary["production_ready"] is False
    for item in summary["documents"]:
        extracted = json.loads(store.read(item["report_sha256"]))
        assert extracted["artifact_sha256"] == item["source_sha256"]
    acquisition.load_acquisition(store, result["receipt_sha256"])
