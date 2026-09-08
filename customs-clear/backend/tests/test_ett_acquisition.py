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
from app.services.ett_transport import OfficialTransportError
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
            body = '''<!doctype html><html><body>Правовой портал Информация о документе
            Номер документа 66 Короткий заголовок документа Решение Коллегии ЕЭК № 66
            Вид документа Решение SYNTHETIC
            <a href="/upload/iblock/synthetic/test-act.pdf">PDF</a>
            <a href="/upload/iblock/synthetic/clarification.docx">Разъяснение</a>
            </body></html>'''.encode()
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
    assert result["downloaded_documents"] == len(discovery.documents) + len(discovery.amendment_links) + 1
    assert result["linked_legal_pdfs"] == result["unsupported_legal_references"] == 1
    assert receipt.schema_version == 2
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


@pytest.mark.parametrize("case", ["backwards_end", "future_document", "old_document"])
def test_incoherent_capture_timestamps_never_publish_success(store, case):
    fetch, calls = fake_fetch()
    def incoherent(url, **kwargs):
        result = fetch(url, **kwargs)
        if case == "backwards_end" and url == INDEX_URL and len(calls) > 1:
            return replace(result, retrieved_at=datetime(2026, 9, 7, tzinfo=timezone.utc))
        if case != "backwards_end" and len(calls) == 2:
            return replace(result, retrieved_at=datetime(2027 if case == "future_document" else 2025, 1, 1, tzinfo=timezone.utc))
        return result
    with pytest.raises(acquisition.AcquisitionError, match="timestamps"):
        acquisition.acquire_official(store, _fetch=incoherent)


def test_fetch_failure_never_returns_success_or_writes_application_tables(store):
    with pytest.raises(ValueError, match="simulated"):
        capture(store, fail_at=8)


def test_transport_failure_keeps_public_request_identity_without_exception_payload(store):
    def fail(url, **kwargs):
        raise OfficialTransportError("sensitive upstream debug detail")
    with pytest.raises(acquisition.AcquisitionDownloadError) as error:
        acquisition.acquire_official(store, _fetch=fail)
    assert error.value.requested_url == INDEX_URL
    assert "sensitive" not in str(error.value)


def test_cli_acquisition_failure_exposes_only_public_request_identity(tmp_path, monkeypatch, capsys):
    from scripts import ett_candidates
    def fail(store):
        raise acquisition.AcquisitionDownloadError(INDEX_URL)
    monkeypatch.setattr(acquisition, "acquire_official", fail)
    assert ett_candidates.main(["acquire", "--store-root", str(tmp_path/'objects')]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["failed_public_source_url"] == INDEX_URL
    assert result["production_ready"] is False


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
    assert report["extracted_documents"] == len(parse_index(synthetic_index_html()).documents) + 1
    assert len(calls) == report["extracted_documents"]
    summary = json.loads(store.read(report["report_sha256"]))
    assert summary["receipt_sha256"] == result["receipt_sha256"]
    assert summary["effective_dates_verified"] is summary["production_ready"] is False
    for item in summary["documents"]:
        extracted = json.loads(store.read(item["report_sha256"]))
        assert extracted["artifact_sha256"] == item["source_sha256"]
    acquisition.load_acquisition(store, result["receipt_sha256"])


def test_blank_same_document_alias_does_not_erase_the_chapter_role(store, monkeypatch):
    from app.services import ett_pdf_evidence
    original = synthetic_index_html()
    visible = b'<a href="ru.2022/published-24-opaque.pdf">'
    altered = original.replace(visible, b'<a href="ru.2022/published-24-opaque.pdf"><br></a>' + visible)
    fetch, _ = fake_fetch()
    def with_alias(url, **kwargs):
        response = fetch(url, **kwargs)
        return replace(response, content=altered) if url == INDEX_URL else response
    capture_result = acquisition.acquire_official(store, _fetch=with_alias)
    calls = []
    def extract(data, *, artifact_id, chapter):
        calls.append((artifact_id, chapter))
        return {"chapter": chapter, "artifact_id": artifact_id}
    monkeypatch.setattr(ett_pdf_evidence, "extract_pdf_evidence", extract)
    result = acquisition.extract_acquisition(store, capture_result["receipt_sha256"])
    assert result["chapters"] == 96
    assert calls.count(("chapter-24", "24")) == 1


@pytest.mark.parametrize("mutation", ["missing_pdf", "inventory_hash", "unrelated_pdf", "extra_pdf"])
def test_linked_act_attachments_cannot_be_removed_or_substituted(store, mutation):
    result, _ = capture(store)
    value = json.loads(store.read(result["receipt_sha256"]))
    if mutation == "missing_pdf": value["attachment_downloads"] = []
    elif mutation == "inventory_hash": value["legal_attachment_inventory_sha256"] = "0" * 64
    elif mutation == "unrelated_pdf":
        value["attachment_downloads"][0]["requested_url"] = value["attachment_downloads"][0]["url"] = "https://docs.eaeunion.org/upload/iblock/synthetic/unrelated.pdf"
    else: value["attachment_downloads"].append(deepcopy(value["attachment_downloads"][0]))
    digest = store.put(acquisition.canonical_bytes(value))
    with pytest.raises(ValueError): acquisition.load_acquisition(store, digest)


def test_v1_receipts_remain_replayable_without_claiming_attachment_capture(store):
    result, _ = capture(store)
    value = json.loads(store.read(result["receipt_sha256"]))
    value["schema_version"] = 1
    value.pop("attachment_downloads")
    value.pop("legal_attachment_inventory_sha256")
    digest = store.put(acquisition.canonical_bytes(value))
    receipt, _ = acquisition.load_acquisition(store, digest)
    assert type(receipt) is acquisition.AcquisitionReceipt
    assert receipt.legal_inventory_complete is False


def test_failure_downloading_linked_act_cannot_publish_success(store):
    fetch, calls = fake_fetch()
    def failing(url, **kwargs):
        if "/upload/iblock/" in url: raise ValueError("act download failed")
        return fetch(url, **kwargs)
    with pytest.raises(ValueError, match="act download failed"):
        acquisition.acquire_official(store, _fetch=failing)
    assert calls[-1][0] != INDEX_URL
