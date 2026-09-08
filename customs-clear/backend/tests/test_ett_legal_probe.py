"""Bounded access diagnostics retain originals without establishing legal effect."""
from datetime import datetime, timezone
import hashlib
import json

import pytest

from app.services.ett_artifacts import LocalArtifactStore
from app.services.ett_transport import OfficialResponse, OfficialTransportError, _validate_document
from scripts.probe_ett_legal_sources import PROBE_SOURCES, main, probe_legal_sources


@pytest.mark.parametrize("source_id,url", [
    ("observed_collegium_42_review_page", "https://docs.eaeunion.org/documents/399/6485/"),
    ("observed_collegium_42_review_pdf", "https://docs.eaeunion.org/upload/iblock/f50/46fwofvvh6dw34qku7vyou54j81p9zml/err_17032022_42_doc.pdf"),
])
def test_unresolved_label_detail_page_requires_explicit_selection(tmp_path, source_id, url):
    calls = []
    def fetch(url, **kwargs):
        calls.append(url)
        return captured(url, **kwargs)
    report = probe_legal_sources(LocalArtifactStore(tmp_path / "objects"), fetch=fetch,
                                 source_ids=[source_id])
    assert calls == [url]
    assert report["captured_sources"] == 1
    assert report["source_identity_verified"] is False
    assert all(configured_id != source_id for configured_id, _, _ in PROBE_SOURCES)


def captured(url, *, expected_media):
    content = b"%PDF-1.7\nSYNTHETIC\n%%EOF\n" if expected_media == "application/pdf" else b"<!doctype html><html><body>SYNTHETIC</body></html>"
    return OfficialResponse(url=url, requested_url=url, content=content, media_type=expected_media,
                            retrieved_at=datetime(2026, 9, 8, tzinfo=timezone.utc))


def test_exact_eight_observed_sources_and_success_does_not_verify_law(tmp_path):
    store = LocalArtifactStore(tmp_path / "objects")
    calls = []
    def fetch(url, **kwargs):
        calls.append((url, kwargs["expected_media"]))
        return captured(url, **kwargs)
    report = probe_legal_sources(store, fetch=fetch)
    assert calls == [(url, media) for _, url, media in PROBE_SOURCES]
    assert report["selected_source_ids"] == [item[0] for item in PROBE_SOURCES]
    assert report["attempted_sources"] == report["captured_sources"] == 8
    assert report["failed_sources"] == 0
    assert report["all_sources_captured"] is True
    for key in ("source_identity_verified", "adoption_dates_verified", "effective_dates_verified", "amendment_inventory_complete", "production_ready", "active_rates_written", "durable_legal_retention_attested"):
        assert report[key] is False
    for result in report["results"]:
        raw = store.read(result["sha256"])
        assert hashlib.sha256(raw).hexdigest() == result["sha256"]
        assert len(raw) == result["size_bytes"]
        assert result["response_url"] == result["requested_url"]
        assert result["retrieved_at"] == "2026-09-08T00:00:00+00:00"


def test_redirect_metadata_and_original_body_are_retained(tmp_path):
    store = LocalArtifactStore(tmp_path / "objects")
    def fetch(url, **kwargs):
        result = captured(url, **kwargs)
        if url == PROBE_SOURCES[0][1]:
            return OfficialResponse(url=PROBE_SOURCES[1][1], requested_url=url, content=b"<html>Original\r\nbytes</html>",
                                    media_type=result.media_type, retrieved_at=result.retrieved_at,
                                    redirect_chain=(PROBE_SOURCES[1][1],))
        return result
    first = probe_legal_sources(store, fetch=fetch)["results"][0]
    assert first["redirect_chain"] == [PROBE_SOURCES[1][1]]
    assert first["response_url"] == PROBE_SOURCES[1][1]
    assert store.read(first["sha256"]) == b"<html>Original\r\nbytes</html>"


@pytest.mark.parametrize("exception,reason", [
    (OfficialTransportError("official source did not return HTTP 200"), "http_non_200"),
    (OfficialTransportError("official source returned an unexpected media type"), "unexpected_media_type"),
    (OfficialTransportError("Authorization: SECRET cookie=PRIVATE"), "transport_failure"),
    (RuntimeError("Authorization: SECRET cookie=PRIVATE"), "probe_operation_failed"),
])
def test_first_failure_does_not_stop_remaining_attempts_or_leak_text(tmp_path, exception, reason):
    calls = []
    def fetch(url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            raise exception
        return captured(url, **kwargs)
    report = probe_legal_sources(LocalArtifactStore(tmp_path / "objects"), fetch=fetch)
    assert len(calls) == report["attempted_sources"] == 8
    assert report["captured_sources"] == 7
    assert report["failed_sources"] == 1
    assert report["results"][0]["reason"] == reason
    assert "SECRET" not in json.dumps(report)
    assert "PRIVATE" not in json.dumps(report)


def test_mismatched_response_identity_is_rejected_without_stopping(tmp_path):
    def fetch(url, **kwargs):
        return captured(PROBE_SOURCES[0][1], **kwargs)
    report = probe_legal_sources(LocalArtifactStore(tmp_path / "objects"), fetch=fetch)
    assert report["captured_sources"] == 1
    assert report["failed_sources"] == 7
    assert all(item["reason"] == "probe_operation_failed" for item in report["results"][1:])


@pytest.mark.parametrize("fail", [False, True])
def test_cli_explicit_paths_complete_report_and_exit_code(tmp_path, capsys, fail):
    calls = []
    def fetch(url, **kwargs):
        calls.append(url)
        if fail and len(calls) == 1:
            raise OfficialTransportError("official source acquisition failed")
        return captured(url, **kwargs)
    output = tmp_path / "probe.json"
    code = main(["--store-root", str(tmp_path / "objects"), "--output", str(output)], fetch=fetch)
    assert code == (2 if fail else 0)
    report = json.loads(output.read_text())
    assert len(report["results"]) == 8
    assert report["all_sources_captured"] is (not fail)
    assert json.loads(capsys.readouterr().out)["production_ready"] is False
    assert output.stat().st_mode & 0o777 == 0o600


def test_cli_does_not_overwrite_existing_report_or_fetch(tmp_path, capsys):
    output = tmp_path / "probe.json"
    output.write_text("existing report")
    def forbidden(*args, **kwargs):
        pytest.fail("fetch must not run")
    assert main(["--store-root", str(tmp_path / "objects"), "--output", str(output)], fetch=forbidden) == 2
    assert output.read_text() == "existing report"
    assert json.loads(capsys.readouterr().out)["reason"] == "probe_setup_or_report_failed"


def test_probe_exposes_only_sanctioned_diagnostic_fields(tmp_path):
    def fetch(url, **kwargs):
        raise OfficialTransportError("official source is not a PDF document", diagnostics={
            "kind": "rejected_document", "magic": "html", "size_bytes": 123,
            "sha256": "a" * 64, "pdf_header_offset": None,
            "pdf_header_ending": "absent", "returned_url": "https://example.com/?token=SECRET",
            "body": "SECRET", "arbitrary_field": "PRIVATE", "url_reason": "SECRET",
        })
    report = probe_legal_sources(LocalArtifactStore(tmp_path / "objects"), fetch=fetch)
    assert report["failed_sources"] == report["attempted_sources"] == 8
    assert report["captured_sources"] == 0
    assert report["all_sources_captured"] is False
    assert report["results"][0]["diagnostics"] == {
        "kind": "rejected_document", "magic": "html", "size_bytes": 123,
        "sha256": "a" * 64, "pdf_header_offset": None, "pdf_header_ending": "absent",
    }
    assert "SECRET" not in json.dumps(report)
    assert "PRIVATE" not in json.dumps(report)


def test_probe_retains_rejected_originals_only_as_failed_evidence(tmp_path):
    rejected = b"%PDF-1.7 PRIVATE_HEADER_CONTENT\n%%EOF\n"
    def fetch(url, **kwargs):
        if kwargs["expected_media"] == "application/pdf":
            _validate_document(rejected, "application/pdf")
            pytest.fail("invalid document must stay rejected")
        return captured(url, **kwargs)
    store = LocalArtifactStore(tmp_path / "objects")
    report = probe_legal_sources(store, fetch=fetch)
    assert report["attempted_sources"] == 8
    assert report["failed_sources"] == report["retained_rejected_documents"] == 2
    assert report["captured_sources"] == 6
    assert report["all_sources_captured"] is False
    for result in report["results"]:
        if result["expected_media_type"] == "application/pdf":
            assert result["status"] == "failed"
            assert result["document_validation_passed"] is False
            assert result["reason"] == "invalid_pdf_shape"
            assert "sha256" not in result
            digest = result["rejected_document_sha256"]
            assert digest == result["diagnostics"]["sha256"] == hashlib.sha256(rejected).hexdigest()
            assert store.read(digest) == rejected
    assert "PRIVATE_HEADER_CONTENT" not in json.dumps(report)
    assert report["production_ready"] is report["active_rates_written"] is False


def test_probe_other_transport_errors_cannot_smuggle_payloads_into_store(tmp_path):
    def fetch(url, **kwargs):
        error = OfficialTransportError("official source acquisition failed")
        error._rejected_document = b"PRIVATE unrelated payload"
        raise error
    store = LocalArtifactStore(tmp_path / "objects")
    report = probe_legal_sources(store, fetch=fetch)
    assert report["retained_rejected_documents"] == 0
    assert report["failed_sources"] == 8
    assert all("rejected_document_sha256" not in item for item in report["results"])
    assert "PRIVATE" not in json.dumps(report)


def test_rejected_retention_failure_preserves_rejection_and_continues(tmp_path, monkeypatch):
    def fetch(url, **kwargs):
        _validate_document(b"invalid rejected body", "application/pdf")
    def fail_store(*args):
        raise OSError("PRIVATE filesystem error")
    monkeypatch.setattr(LocalArtifactStore, "put", fail_store)
    report = probe_legal_sources(LocalArtifactStore(tmp_path / "objects"), fetch=fetch)
    assert report["failed_sources"] == report["attempted_sources"] == 8
    assert report["retained_rejected_documents"] == 0
    assert all(item["reason"] == "invalid_pdf_shape" for item in report["results"])
    assert all(item["rejected_document_retention_reason"] == "rejected_evidence_retention_failed" for item in report["results"])
    assert "PRIVATE" not in json.dumps(report)


def test_explicit_pdf_selection_fetches_only_selected_sources_in_requested_order(tmp_path):
    selected = ["observed_council_76_pdf", "observed_collegium_66_pdf"]
    calls = []
    def fetch(url, **kwargs):
        calls.append((url, kwargs["expected_media"]))
        return captured(url, **kwargs)
    report = probe_legal_sources(LocalArtifactStore(tmp_path / "objects"), fetch=fetch, source_ids=selected)
    by_id = {source_id: (url, media) for source_id, url, media in PROBE_SOURCES}
    assert calls == [by_id[source_id] for source_id in selected]
    assert report["selected_source_ids"] == selected
    assert [item["source_id"] for item in report["results"]] == selected
    assert report["attempted_sources"] == report["captured_sources"] == 2
    assert report["all_sources_captured"] is True
    assert report["amendment_inventory_complete"] is report["source_identity_verified"] is False
    assert report["production_ready"] is report["active_rates_written"] is False


@pytest.mark.parametrize("selected", [[], (), "observed_collegium_66_pdf", ["unknown"],
                                      ["observed_collegium_66_pdf"] * 2, [None],
                                      ["observed_collegium_66_pdf"] * 9])
def test_invalid_selection_is_rejected_before_any_fetch(tmp_path, selected):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid selection must not fetch any source")
    with pytest.raises(ValueError, match="source identifiers"):
        probe_legal_sources(LocalArtifactStore(tmp_path / "objects"), fetch=forbidden, source_ids=selected)


@pytest.mark.parametrize("fail", [False, True])
def test_cli_pdf_selection_reports_only_selected_denominator(tmp_path, capsys, fail):
    selected = ["observed_collegium_66_pdf", "observed_council_76_pdf"]
    calls = []
    def fetch(url, **kwargs):
        calls.append(url)
        if fail and len(calls) == 1:
            raise OfficialTransportError("official source acquisition failed")
        return captured(url, **kwargs)
    output = tmp_path / "probe.json"
    argv = ["--store-root", str(tmp_path / "objects"), "--output", str(output)]
    for source_id in selected:
        argv.extend(["--source-id", source_id])
    assert main(argv, fetch=fetch) == (2 if fail else 0)
    report = json.loads(output.read_text())
    assert report["selected_source_ids"] == selected
    assert len(calls) == report["attempted_sources"] == 2
    assert report["captured_sources"] == (1 if fail else 2)
    assert report["all_sources_captured"] is (not fail)
    assert json.loads(capsys.readouterr().out)["attempted_sources"] == 2


@pytest.mark.parametrize("selected", [["unknown"], ["observed_collegium_66_pdf"] * 2])
def test_cli_unknown_or_duplicate_source_ids_reject_before_setup(tmp_path, selected):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid selection must not fetch")
    argv = ["--store-root", str(tmp_path / "objects"), "--output", str(tmp_path / "probe.json")]
    for source_id in selected:
        argv.extend(["--source-id", source_id])
    with pytest.raises(SystemExit) as caught:
        main(argv, fetch=forbidden)
    assert caught.value.code == 2
    assert not (tmp_path / "objects").exists()
    assert not (tmp_path / "probe.json").exists()
