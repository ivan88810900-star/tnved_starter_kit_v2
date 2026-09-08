"""Bounded access diagnostics retain originals without establishing legal effect."""
from datetime import datetime, timezone
import hashlib
import json

import pytest

from app.services.ett_artifacts import LocalArtifactStore
from app.services.ett_transport import OfficialResponse, OfficialTransportError
from scripts.probe_ett_legal_sources import PROBE_SOURCES, main, probe_legal_sources


def captured(url, *, expected_media):
    content = b"%PDF-1.7\nSYNTHETIC\n%%EOF\n" if expected_media == "application/pdf" else b"<!doctype html><html><body>SYNTHETIC</body></html>"
    return OfficialResponse(url=url, requested_url=url, content=content, media_type=expected_media,
                            retrieved_at=datetime(2026, 9, 8, tzinfo=timezone.utc))


def test_exact_four_observed_sources_and_success_does_not_verify_law(tmp_path):
    store = LocalArtifactStore(tmp_path / "objects")
    calls = []
    def fetch(url, **kwargs):
        calls.append((url, kwargs["expected_media"]))
        return captured(url, **kwargs)
    report = probe_legal_sources(store, fetch=fetch)
    assert calls == [(url, media) for _, url, media in PROBE_SOURCES]
    assert report["attempted_sources"] == report["captured_sources"] == 4
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
    assert len(calls) == report["attempted_sources"] == 4
    assert report["captured_sources"] == 3
    assert report["failed_sources"] == 1
    assert report["results"][0]["reason"] == reason
    assert "SECRET" not in json.dumps(report)
    assert "PRIVATE" not in json.dumps(report)


def test_mismatched_response_identity_is_rejected_without_stopping(tmp_path):
    def fetch(url, **kwargs):
        return captured(PROBE_SOURCES[0][1], **kwargs)
    report = probe_legal_sources(LocalArtifactStore(tmp_path / "objects"), fetch=fetch)
    assert report["captured_sources"] == 1
    assert report["failed_sources"] == 3
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
    assert len(report["results"]) == 4
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
