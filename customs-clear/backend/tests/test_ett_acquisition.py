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
    assert error.value.progress_report_sha256 is not None
    progress, discovery = acquisition.load_incomplete_capture(store, error.value.progress_report_sha256)
    assert progress.failed_stage == "initial_index"
    assert progress.index_start is discovery is None
    assert progress.downloads == progress.attachment_downloads == ()
    assert progress.failed_media_type == "text/html"
    assert progress.reason_code == "official_transport_failure"
    assert "sensitive" not in store.read(error.value.progress_report_sha256).decode()


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


def _failed_transport_capture(store, *, fail_request_number=None, fail_url=None):
    fetch, calls = fake_fetch()
    count = 0
    def failing(url, **kwargs):
        nonlocal count
        count += 1
        if count == fail_request_number or url == fail_url:
            raise OfficialTransportError("private transport diagnostics must not be retained")
        return fetch(url, **kwargs)
    with pytest.raises(acquisition.AcquisitionDownloadError) as caught:
        acquisition.acquire_official(store, _fetch=failing)
    return caught.value, calls


def test_mid_chapter_transport_failure_retains_exact_completed_source_prefix(store):
    error, calls = _failed_transport_capture(store, fail_request_number=8)
    progress, discovery = acquisition.load_incomplete_capture(store, error.progress_report_sha256)
    assert progress.kind == "ett_incomplete_capture"
    assert progress.status == "incomplete"
    assert progress.failed_stage == "index_documents"
    assert len(progress.downloads) == 6
    assert len(calls) == 7  # Initial index plus six completely stored documents.
    assert progress.index_start.requested_url == INDEX_URL
    expected = acquisition._plan(discovery)
    assert tuple((r.requested_url, r.media_type) for r in progress.downloads) == expected[:6]
    assert (progress.failed_requested_url, progress.failed_media_type) == expected[6]
    assert error.requested_url == expected[6][0]
    for record in (progress.index_start, *progress.downloads):
        assert hashlib.sha256(store.read(record.sha256)).hexdigest() == record.sha256
        assert record.retrieved_at.tzinfo is not None
    assert progress.production_ready is progress.active_rates_written is progress.legal_inventory_complete is False
    assert progress.index_stable_during_capture is False
    assert not {"receipt_sha256", "index_end", "rates"}.intersection(type(progress).model_fields)


def test_first_amendment_failure_preserves_every_completed_chapter_download(store):
    discovery = parse_index(synthetic_index_html())
    plan = acquisition._plan(discovery)
    failing_url = next(url for url, media in plan if media == "text/html")
    error, _ = _failed_transport_capture(store, fail_url=failing_url)
    progress, replayed = acquisition.load_incomplete_capture(store, error.progress_report_sha256)
    captured = {record.requested_url for record in progress.downloads}
    assert len(replayed.chapters) == 96
    assert all(chapter.url in captured for chapter in replayed.chapters)
    assert progress.failed_requested_url == failing_url
    assert progress.failed_media_type == "text/html"
    assert progress.failed_stage == "index_documents"
    assert progress.attachment_downloads == ()


def test_attachment_failure_retains_initial_plan_and_binds_failed_attachment(store):
    url = "https://docs.eaeunion.org/upload/iblock/synthetic/test-act.pdf"
    error, _ = _failed_transport_capture(store, fail_url=url)
    progress, discovery = acquisition.load_incomplete_capture(store, error.progress_report_sha256)
    assert len(progress.downloads) == len(acquisition._plan(discovery))
    assert progress.failed_stage == "legal_attachments"
    assert progress.failed_requested_url == url
    assert progress.failed_media_type == "application/pdf"
    assert progress.attachment_downloads == ()


def test_final_index_failure_keeps_all_completed_sources_but_never_stability(store):
    fetch, calls = fake_fetch()
    def final_fails(url, **kwargs):
        if url == INDEX_URL and calls:
            raise OfficialTransportError("failed final index")
        return fetch(url, **kwargs)
    with pytest.raises(acquisition.AcquisitionDownloadError) as caught:
        acquisition.acquire_official(store, _fetch=final_fails)
    progress, discovery = acquisition.load_incomplete_capture(store, caught.value.progress_report_sha256)
    assert progress.failed_stage == "final_index"
    assert len(progress.downloads) == len(acquisition._plan(discovery))
    assert len(progress.attachment_downloads) == 1
    assert progress.index_stable_during_capture is False


@pytest.mark.parametrize("mutation", ["missing_middle", "missing_last", "reordered", "duplicate", "unrelated_url", "missing_blob", "wrong_size", "wrong_discovery", "wrong_failed_request", "wrong_stage", "claimed_ready", "missing_index"])
def test_rehashing_incomplete_report_cannot_hide_invalid_prefix_or_source_associations(store, mutation):
    error, _ = _failed_transport_capture(store, fail_request_number=8)
    value = json.loads(store.read(error.progress_report_sha256))
    if mutation == "missing_middle": value["downloads"].pop(1)
    elif mutation == "missing_last": value["downloads"].pop()
    elif mutation == "reordered": value["downloads"][0], value["downloads"][1] = value["downloads"][1], value["downloads"][0]
    elif mutation == "duplicate": value["downloads"][1] = deepcopy(value["downloads"][0])
    elif mutation == "unrelated_url": value["downloads"][0]["requested_url"] = value["downloads"][0]["url"] = INDEX_URL + "unrelated.pdf"
    elif mutation == "missing_blob": value["downloads"][0]["sha256"] = "0" * 64
    elif mutation == "wrong_size": value["downloads"][0]["size_bytes"] += 1
    elif mutation == "wrong_discovery": value["discovery_sha256"] = "0" * 64
    elif mutation == "wrong_failed_request": value["failed_requested_url"] = INDEX_URL + "unrelated.pdf"
    elif mutation == "wrong_stage": value["failed_stage"] = "final_index"
    elif mutation == "claimed_ready": value["production_ready"] = True
    elif mutation == "missing_index": value["index_start"] = None
    digest = store.put(acquisition.canonical_bytes(value))
    with pytest.raises(ValueError):
        acquisition.load_incomplete_capture(store, digest)


def test_incomplete_capture_is_never_accepted_by_complete_receipt_loader(store):
    error, _ = _failed_transport_capture(store, fail_request_number=8)
    with pytest.raises(ValueError):
        acquisition.load_acquisition(store, error.progress_report_sha256)


def test_incomplete_json_must_be_canonical_and_cannot_add_exception_payload(store):
    error, _ = _failed_transport_capture(store, fail_request_number=8)
    value = json.loads(store.read(error.progress_report_sha256))
    noncanonical = store.put(json.dumps(value, indent=2).encode())
    with pytest.raises(acquisition.AcquisitionError, match="canonical"):
        acquisition.load_incomplete_capture(store, noncanonical)
    value["exception_message"] = "arbitrary upstream response"
    extra = store.put(acquisition.canonical_bytes(value))
    with pytest.raises(ValueError):
        acquisition.load_incomplete_capture(store, extra)


def test_incomplete_report_size_bound_is_enforced_before_publication(store, monkeypatch):
    monkeypatch.setattr(acquisition, "MAX_PROGRESS_REPORT_BYTES", 10)
    with pytest.raises(acquisition.AcquisitionError, match="byte bound"):
        acquisition.acquire_official(store, _fetch=lambda *a, **k: (_ for _ in ()).throw(OfficialTransportError("failure")))


def test_first_index_failure_cannot_claim_downloads_from_an_unknown_index(store):
    result, _ = capture(store)
    receipt, _ = acquisition.load_acquisition(store, result["receipt_sha256"])
    error, _ = _failed_transport_capture(store, fail_request_number=1)
    value = json.loads(store.read(error.progress_report_sha256))
    value["downloads"] = [receipt.downloads[0].model_dump(mode="json")]
    digest = store.put(acquisition.canonical_bytes(value))
    with pytest.raises(acquisition.AcquisitionError, match="Initial-index"):
        acquisition.load_incomplete_capture(store, digest)
