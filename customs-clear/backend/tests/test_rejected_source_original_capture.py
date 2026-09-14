"""Rejected source bytes are diagnostic quarantine, never accepted originals."""

from copy import deepcopy
from contextlib import contextmanager
import hashlib
import json
from unittest.mock import patch

import httpx
import pytest

from app.services.ett_artifacts import ArtifactIntegrityError, LocalArtifactStore
from app.services.regulatory_source_capture import (
    verify_original_capture, verify_rejected_original_capture,
)
from scripts import monitor_official_ntm_sources as monitor


URL = "https://eec.eaeunion.org/upload/observed-source.pdf"
PDF = b"%PDF-1.7\n" + b"observed source content\n" * 10
BLOCK = b"<html><body>Access denied</body></html>" + b" " * 150


@contextmanager
def _responses(responder, *, sources=None):
    requests = []

    def respond(request):
        requests.append(request)
        return responder(request)

    source_map = sources or {"only": URL}
    client = httpx.Client(transport=httpx.MockTransport(respond))
    with (
        patch.object(monitor, "SOURCES", source_map),
        patch.object(monitor, "SOURCE_MODES", {key: "legal_drift" for key in source_map}),
        patch.object(monitor, "REGULATORY_SOURCE_REGISTRY", ()),
        patch.object(monitor.httpx, "Client", return_value=client),
    ):
        yield requests


def _response(body=BLOCK, *, content_type="text/html", status=200, extra_headers=None):
    return lambda request: httpx.Response(
        status, content=body,
        headers={"content-type": content_type, **(extra_headers or {})},
    )


@pytest.mark.parametrize("body,ctype,error", [
    (BLOCK, "text/html", "block_or_error_page_detected"),
    (PDF, "text/plain", "invalid_pdf_content"),
    (PDF, "", "invalid_pdf_content"),
    (b"small rejected response", "application/pdf", "content_too_small"),
])
def test_quarantine_replays_rejected_bytes_without_accepting_a_matching_pending_digest(tmp_path, body, ctype, error):
    store = LocalArtifactStore(tmp_path / "objects")
    previous = {"sources": {"only": {
        "sha256": "a" * 64, "pending_sha256": hashlib.sha256(body).hexdigest(),
        "etag": "previous-etag", "url": URL,
    }}}
    original = deepcopy(previous)
    with _responses(_response(body, content_type=ctype)):
        report = monitor.monitor_sources(
            original_store=store, capture_rejected_originals=True,
            previous_state=previous, accept_changes=True, approval_ref="review/fixture",
        )
    row = report["sources"][0]
    capture = row["rejected_original_capture"]
    assert row["ok"] is row["approval_allowed"] is row["baseline_advanced"] is False
    assert row["validation_error"] == error
    assert row["original_capture"] is None
    assert capture["capture_kind"] == "official_monitor_rejected_original"
    assert capture["quarantine_status"] == "content_rejected"
    assert capture["evidence_scope"] == "quarantined_response_bytes_only"
    assert capture["validation_error"] == error
    assert capture["original_body_sha256"] == hashlib.sha256(body).hexdigest()
    for claim in (
        "content_validation_passed", "approval_allowed", "legal_review_verified", "retention_verified",
        "production_ready", "legal_ready", "can_promote", "active_rates_written",
        "durable_legal_retention_attested", "source_authenticity_attested",
    ):
        assert capture[claim] is False
    assert verify_rejected_original_capture(store, capture["receipt_sha256"]) == {
        key: value for key, value in capture.items() if key != "receipt_sha256"
    }
    with pytest.raises(ArtifactIntegrityError):
        verify_original_capture(store, capture["receipt_sha256"])
    assert report["original_capture_count"] == 0
    assert report["rejected_original_capture_count"] == 1
    assert report["original_capture_complete"] is report["all_available"] is False
    assert report["selected_revision_coverage_complete"] is report["revision_coverage_complete"] is False
    assert report["accepted_source_ids"] == report["pending_review_source_ids"] == []
    assert report["next_state"]["sources"] == previous["sources"] == original["sources"]


def test_rejected_shared_url_is_retained_once_and_query_redacted(tmp_path):
    store = LocalArtifactStore(tmp_path / "objects")
    signed = URL + "?access_token=fixture-private-value"
    with _responses(_response(), sources={"second": signed, "first": signed}) as requests:
        report = monitor.monitor_sources(original_store=store, capture_rejected_originals=True)
    assert len(requests) == 1
    captures = [row["rejected_original_capture"] for row in report["sources"]]
    assert captures[0] == captures[1]
    assert captures[0]["source_ids"] == ["first", "second"]
    assert captures[0]["requested"]["url_sha256"] == hashlib.sha256(signed.encode()).hexdigest()
    assert "fixture-private-value" not in json.dumps(report)
    assert "access_token" not in json.dumps(report)
    assert report["rejected_original_capture_count"] == 1
    assert report["original_capture_count"] == 0
    assert len(list((tmp_path / "objects").glob("*.blob"))) == 2


def test_mixed_success_and_quarantine_counts_never_claim_complete(tmp_path):
    store = LocalArtifactStore(tmp_path / "objects")
    good = "https://eec.eaeunion.org/upload/good.pdf"

    def respond(request):
        return httpx.Response(200, content=PDF if str(request.url) == good else BLOCK,
                              headers={"content-type": "application/pdf"})

    with _responses(respond, sources={"good": good, "bad": URL}):
        report = monitor.monitor_sources(original_store=store, capture_rejected_originals=True)
    rows = {row["source_id"]: row for row in report["sources"]}
    assert rows["good"]["original_capture"] is not None
    assert rows["good"]["rejected_original_capture"] is None
    assert rows["bad"]["original_capture"] is None
    assert rows["bad"]["rejected_original_capture"] is not None
    assert report["original_capture_count"] == report["rejected_original_capture_count"] == 1
    assert report["original_capture_complete"] is False
    assert "bad" not in report["next_state"]["sources"]
    with pytest.raises(ArtifactIntegrityError):
        verify_rejected_original_capture(store, rows["good"]["original_capture"]["receipt_sha256"])


@pytest.mark.parametrize("kind", ["redirect", "oversize_header", "oversize_stream", "short_body", "encoding", "http_503", "http_304", "empty"])
def test_transport_failure_or_empty_body_never_enters_quarantine(tmp_path, kind):
    store = LocalArtifactStore(tmp_path / "objects")
    headers = {}
    status = 200
    body = BLOCK
    if kind == "redirect":
        status = 302
        headers["location"] = "https://untrusted.example/source.pdf?token=fixture-private-value"
    elif kind == "oversize_header":
        headers["content-length"] = str(64 * 1024**2 + 1)
    elif kind == "oversize_stream":
        body = b"x" * (64 * 1024**2 + 1)
    elif kind == "short_body":
        headers["content-length"] = str(len(body) + 1)
    elif kind == "encoding":
        headers["content-encoding"] = "gzip"
    elif kind == "http_503":
        status = 503
    elif kind == "http_304":
        status, body = 304, b""
    else:
        body = b""
    with _responses(_response(body, status=status, extra_headers=headers)) as requests:
        report = monitor.monitor_sources(original_store=store, capture_rejected_originals=True)
    assert len(requests) == 1
    assert report["sources"][0]["ok"] is False
    assert not report["sources"][0].get("rejected_original_capture")
    assert report["original_capture_count"] == report["rejected_original_capture_count"] == 0
    assert report["original_capture_complete"] is False
    assert report["next_state"]["sources"] == {}
    assert list((tmp_path / "objects").glob("*.blob")) == []
    assert "fixture-private-value" not in json.dumps(report)


@pytest.mark.parametrize("target", ["original_body_sha256", "receipt_sha256"])
def test_quarantine_verifier_detects_corruption(tmp_path, target):
    store = LocalArtifactStore(tmp_path / "objects")
    with _responses(_response()):
        report = monitor.monitor_sources(original_store=store, capture_rejected_originals=True)
    capture = report["sources"][0]["rejected_original_capture"]
    path = tmp_path / "objects" / (capture[target] + ".blob")
    raw = path.read_bytes()
    path.chmod(0o600)
    path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
    path.chmod(0o400)
    with pytest.raises(ArtifactIntegrityError):
        verify_rejected_original_capture(store, capture["receipt_sha256"])


@pytest.mark.parametrize("field,value", [
    ("content_validation_passed", True), ("approval_allowed", True),
    ("legal_review_verified", True), ("retention_verified", True),
    ("quarantine_status", "approved"), ("validation_error", "unexpected_redirect_target"),
    ("capture_kind", "official_monitor_original"), ("status_code", 201),
])
def test_quarantine_verifier_rejects_rehashed_positive_or_transport_claims(tmp_path, field, value):
    store = LocalArtifactStore(tmp_path / "objects")
    with _responses(_response()):
        report = monitor.monitor_sources(original_store=store, capture_rejected_originals=True)
    capture = report["sources"][0]["rejected_original_capture"]
    receipt = verify_rejected_original_capture(store, capture["receipt_sha256"])
    receipt[field] = value
    forged = store.put(json.dumps(receipt).encode())
    with pytest.raises(ArtifactIntegrityError):
        verify_rejected_original_capture(store, forged)
    with pytest.raises(ArtifactIntegrityError):
        verify_original_capture(store, forged)


def test_quarantine_storage_error_is_sanitized_and_does_not_advance_baseline(tmp_path):
    store = LocalArtifactStore(tmp_path / "objects")
    previous = {"sources": {"only": {"sha256": "a" * 64}}}
    with _responses(_response()), patch.object(LocalArtifactStore, "put", side_effect=OSError("fixture-private-value")):
        report = monitor.monitor_sources(
            original_store=store, capture_rejected_originals=True, previous_state=previous,
        )
    row = report["sources"][0]
    assert row["validation_error"] == "rejected_original_capture_failed"
    assert row["ok"] is row["baseline_advanced"] is row["approval_allowed"] is False
    assert report["next_state"]["sources"] == previous["sources"]
    assert "fixture-private-value" not in json.dumps(report)


@pytest.mark.parametrize("arguments", [
    ["--capture-rejected-originals"],
    ["--capture-rejected-originals", "--capture-originals"],
    ["--capture-rejected-originals", "--store-root", "unused"],
])
def test_cli_requires_explicit_normal_capture_and_store_before_quarantine(arguments):
    with patch("sys.argv", ["monitor", *arguments]), patch.object(monitor, "monitor_sources") as run:
        with pytest.raises(SystemExit) as exc:
            monitor.main()
    assert exc.value.code == 2
    run.assert_not_called()


@pytest.mark.parametrize("value", [True, "true", 1])
def test_programmatic_quarantine_requires_boolean_and_store_before_network(value):
    with patch.object(monitor.httpx, "Client") as client:
        with pytest.raises(ValueError):
            monitor.monitor_sources(capture_rejected_originals=value)
    client.assert_not_called()


def test_cli_successful_quarantine_still_exits_nonzero_and_persists_no_baseline(tmp_path, capsys):
    with _responses(_response()), patch("sys.argv", [
        "monitor", "--capture-originals", "--capture-rejected-originals",
        "--store-root", str(tmp_path / "objects"), "--state", str(tmp_path / "state.json"),
    ]):
        assert monitor.main() == 1
    report = json.loads(capsys.readouterr().out)
    assert report["rejected_original_capture_count"] == 1
    assert report["original_capture_count"] == 0
    assert report["original_capture_complete"] is False
    assert json.loads((tmp_path / "state.json").read_text())["sources"] == {}
