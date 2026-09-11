"""Original monitor bytes remain distinct from revision identity and legal approval."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from app.services.ett_artifacts import ArtifactIntegrityError, LocalArtifactStore
from app.services.regulatory_source_capture import verify_original_capture
from scripts import monitor_official_ntm_sources as monitor


PDF_URL = "https://eec.eaeunion.org/upload/observed-source.pdf"
HTML_URL = "https://www.nalog.gov.ru/rn77/taxation/taxes/nds/"
PDF_BODY = b"%PDF-1.7\n" + b"retained official monitor response\n" * 8
FALSE_CLAIMS = (
    "production_ready",
    "legal_ready",
    "can_promote",
    "active_rates_written",
    "durable_legal_retention_attested",
    "source_authenticity_attested",
)


@contextmanager
def _responses(
    body: bytes,
    *,
    sources: dict[str, str] | None = None,
    content_type: str = "application/pdf",
    status_code: int = 200,
):
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            status_code,
            content=body,
            headers={"content-type": content_type, "etag": '"observed-etag"'},
        )

    source_map = sources or {"only": PDF_URL}
    client = httpx.Client(transport=httpx.MockTransport(respond))
    with (
        patch.object(monitor, "SOURCES", source_map),
        patch.object(monitor, "SOURCE_MODES", {key: "legal_drift" for key in source_map}),
        patch.object(monitor.httpx, "Client", return_value=client),
    ):
        yield requests


def _store(tmp_path: Path) -> LocalArtifactStore:
    return LocalArtifactStore(tmp_path / "objects")


def _assert_receipt(store, capture, body, source_ids):
    assert capture["original_body_sha256"] == hashlib.sha256(body).hexdigest()
    assert capture["size_bytes"] == len(body)
    assert capture["source_ids"] == source_ids
    assert capture["storage_kind"] == "local_development"
    assert capture["evidence_scope"] == "retrieved_response_bytes_only"
    for field in FALSE_CLAIMS:
        assert capture[field] is False
    verified = verify_original_capture(store, capture["receipt_sha256"])
    assert verified == {key: value for key, value in capture.items() if key != "receipt_sha256"}
    return verified


def test_pdf_capture_replays_original_without_approving_first_baseline(tmp_path):
    store = _store(tmp_path)
    with _responses(PDF_BODY) as requests:
        report = monitor.monitor_sources(original_store=store)

    assert len(requests) == 1
    row = report["sources"][0]
    receipt = _assert_receipt(store, row["original_capture"], PDF_BODY, ["only"])
    assert receipt["schema_version"] == 1
    assert receipt["capture_kind"] == "official_monitor_original"
    assert receipt["requested"]["url"] == PDF_URL
    assert receipt["response"]["url"] == PDF_URL
    assert receipt["redirect_chain"][0] == receipt["requested"]
    assert receipt["redirect_chain"][-1] == receipt["response"]
    assert receipt["status_code"] == 200
    assert row["observed_sha256"] == row["original_capture"]["original_body_sha256"]
    assert row["ok"] is True
    assert row["baseline_advanced"] is False
    assert report["accepted_source_ids"] == []
    assert "sha256" not in report["next_state"]["sources"]["only"]


def test_html_retains_different_bodies_even_when_legal_identity_is_unchanged(tmp_path):
    store = _store(tmp_path)
    template = (
        '<html><body><a href="/docs/retained-law.pdf">Official law</a>'
        '<p>{}</p></body></html>'
    )
    first_body = template.format("First template " * 15).encode()
    second_body = template.format("Changed template " * 15).encode()
    with _responses(first_body, sources={"vat": HTML_URL}, content_type="text/html"):
        first = monitor.monitor_sources(original_store=store)
    with _responses(second_body, sources={"vat": HTML_URL}, content_type="text/html"):
        second = monitor.monitor_sources(previous_state=first["next_state"], original_store=store)

    first_row, second_row = first["sources"][0], second["sources"][0]
    _assert_receipt(store, first_row["original_capture"], first_body, ["vat"])
    _assert_receipt(store, second_row["original_capture"], second_body, ["vat"])
    assert first_row["observed_sha256"] == second_row["observed_sha256"]
    assert first_row["original_capture"]["original_body_sha256"] != second_row["original_capture"]["original_body_sha256"]
    assert first_row["original_capture"]["receipt_sha256"] != second_row["original_capture"]["receipt_sha256"]
    assert second_row["artifact_identity_verified"] is True
    assert second_row["revision_covered"] is False
    assert second_row["revision_gap"] is True


def test_same_url_captures_once_with_every_source_id(tmp_path):
    store = _store(tmp_path)
    sources = {"second": PDF_URL, "first": PDF_URL}
    with _responses(PDF_BODY, sources=sources) as requests:
        report = monitor.monitor_sources(original_store=store)

    assert len(requests) == 1
    captures = [row["original_capture"] for row in report["sources"]]
    assert captures[0] == captures[1]
    _assert_receipt(store, captures[0], PDF_BODY, ["first", "second"])
    assert len(list((tmp_path / "objects").glob("*.blob"))) == 2


def test_capture_report_redacts_query_but_receipt_binds_exact_requested_url(tmp_path):
    store = _store(tmp_path)
    signed_url = PDF_URL + "?access_token=fixture-private-value"
    with _responses(PDF_BODY, sources={"only": signed_url}):
        report = monitor.monitor_sources(original_store=store)

    capture = report["sources"][0]["original_capture"]
    receipt = _assert_receipt(store, capture, PDF_BODY, ["only"])
    assert receipt["requested"] == {
        "url": PDF_URL,
        "url_sha256": hashlib.sha256(signed_url.encode()).hexdigest(),
        "query_redacted": True,
        "fragment_redacted": False,
    }
    assert "fixture-private-value" not in json.dumps(report)
    assert "access_token" not in json.dumps(receipt)


@pytest.mark.parametrize("status_code", [200, 304])
def test_capture_forces_full_body_and_rejects_unsolicited_304(tmp_path, status_code):
    store = _store(tmp_path)
    digest = hashlib.sha256(PDF_BODY).hexdigest()
    previous = {"sources": {"only": {
        "url": PDF_URL,
        "sha256": digest,
        "etag": '"accepted-etag"',
        "last_modified": "Mon, 31 Aug 2026 00:00:00 GMT",
    }}}
    with _responses(PDF_BODY if status_code == 200 else b"", status_code=status_code) as requests:
        report = monitor.monitor_sources(previous_state=previous, original_store=store)

    assert len(requests) == 1
    assert "if-none-match" not in requests[0].headers
    assert "if-modified-since" not in requests[0].headers
    assert requests[0].headers["accept-encoding"] == "identity"
    row = report["sources"][0]
    assert row["ok"] is (status_code == 200)
    if status_code == 200:
        _assert_receipt(store, row["original_capture"], PDF_BODY, ["only"])
    else:
        assert not row.get("original_capture")
        assert report["all_available"] is False
        assert report["next_state"]["sources"]["only"] == previous["sources"]["only"]
        assert list((tmp_path / "objects").glob("*.blob")) == []


@pytest.mark.parametrize("failing_put", [1, 2])
def test_failed_body_or_receipt_storage_cannot_accept_pending_baseline(tmp_path, failing_put):
    store = _store(tmp_path)
    previous = {"sources": {"only": {
        "url": PDF_URL,
        "sha256": "a" * 64,
        "pending_sha256": hashlib.sha256(PDF_BODY).hexdigest(),
    }}}
    original_put = LocalArtifactStore.put
    calls = 0

    def failing_write(self, body):
        nonlocal calls
        calls += 1
        if calls == failing_put:
            raise ArtifactIntegrityError("storage unavailable")
        return original_put(self, body)

    with _responses(PDF_BODY), patch.object(LocalArtifactStore, "put", failing_write):
        report = monitor.monitor_sources(
            previous_state=previous,
            original_store=store,
            accept_changes=True,
            approval_ref="review/exact-pending-digest",
        )

    row = report["sources"][0]
    assert row["ok"] is False
    assert row["validation_error"] == "original_capture_failed"
    assert row.get("baseline_advanced") is not True
    assert not row.get("original_capture")
    assert report["accepted_source_ids"] == []
    assert report["next_state"]["sources"]["only"] == previous["sources"]["only"]


def test_invalid_source_body_is_never_retained_as_successful_capture(tmp_path):
    store = _store(tmp_path)
    body = b"<html><body>Access denied</body></html>" + b" " * 150
    with _responses(body, content_type="text/html"):
        report = monitor.monitor_sources(original_store=store)
    assert report["sources"][0]["ok"] is False
    assert not report["sources"][0].get("original_capture")
    assert list((tmp_path / "objects").glob("*.blob")) == []


@pytest.mark.parametrize("url", [
    "http://eec.eaeunion.org/source.pdf?token=fixture-private-value",
    "https://user:fixture-private-value@eec.eaeunion.org/source.pdf",
])
def test_capture_rejects_insecure_url_without_fetching_or_exposing_credentials(tmp_path, url):
    store = _store(tmp_path)
    with _responses(PDF_BODY, sources={"only": url}) as requests:
        report = monitor.monitor_sources(original_store=store)
    assert requests == []
    assert report["sources"][0]["ok"] is False
    assert not report["sources"][0].get("original_capture")
    assert "fixture-private-value" not in json.dumps(report)
    assert list((tmp_path / "objects").glob("*.blob")) == []


@pytest.mark.parametrize("target", ["original_body_sha256", "receipt_sha256"])
def test_verifier_rejects_tampered_receipt_or_original_blob(tmp_path, target):
    store = _store(tmp_path)
    with _responses(PDF_BODY):
        report = monitor.monitor_sources(original_store=store)
    capture = report["sources"][0]["original_capture"]
    path = tmp_path / "objects" / (capture[target] + ".blob")
    original = path.read_bytes()
    path.chmod(0o600)
    path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    path.chmod(0o400)

    with pytest.raises(ArtifactIntegrityError):
        verify_original_capture(store, capture["receipt_sha256"])


@pytest.mark.parametrize("claim", FALSE_CLAIMS)
def test_validly_hashed_receipt_cannot_claim_legal_approval_or_retention(tmp_path, claim):
    store = _store(tmp_path)
    with _responses(PDF_BODY):
        report = monitor.monitor_sources(original_store=store)
    capture = report["sources"][0]["original_capture"]
    receipt = verify_original_capture(store, capture["receipt_sha256"])
    receipt[claim] = True
    forged_sha = store.put(json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode())

    with pytest.raises(ArtifactIntegrityError):
        verify_original_capture(store, forged_sha)


def test_default_monitor_does_not_write_original_objects():
    with _responses(PDF_BODY), patch.object(LocalArtifactStore, "put", side_effect=AssertionError("capture was not requested")):
        report = monitor.monitor_sources()
    assert report["sources"][0]["ok"] is True
    assert not report["sources"][0].get("original_capture")


@pytest.mark.parametrize("arguments", [["--capture-originals"], ["--store-root", "unused-objects"]])
def test_cli_requires_capture_flag_and_store_root_together(arguments):
    with patch("sys.argv", ["monitor_official_ntm_sources.py", *arguments]), patch.object(monitor, "monitor_sources") as run:
        with pytest.raises(SystemExit) as exc:
            monitor.main()
    assert exc.value.code == 2
    run.assert_not_called()


def test_cli_capture_failure_is_nonzero_without_strict(tmp_path, capsys):
    with _responses(b"upstream unavailable", status_code=503), patch("sys.argv", [
        "monitor_official_ntm_sources.py", "--capture-originals", "--store-root", str(tmp_path / "objects"),
    ]):
        result = monitor.main()
    assert result == 1
    output = json.loads(capsys.readouterr().out)
    assert output["original_capture_complete"] is False
    assert output["sources"][0]["ok"] is False


@pytest.mark.parametrize("selection", [["unknown"], [], [""], [" "], ""])
def test_source_selection_rejects_invalid_input_before_http_client_creation(selection):
    with (
        patch.object(monitor, "SOURCES", {"only": PDF_URL}),
        patch.object(monitor, "SOURCE_MODES", {"only": "legal_drift"}),
        patch.object(monitor.httpx, "Client") as client,
    ):
        with pytest.raises(ValueError):
            monitor.monitor_sources(source_ids=selection)
    client.assert_not_called()


def test_selected_source_capture_preserves_other_baselines_and_discloses_partial_scope(tmp_path):
    store = _store(tmp_path)
    untouched = {
        "url": HTML_URL,
        "sha256": "a" * 64,
        "pending_sha256": "b" * 64,
        "etag": '"unselected-etag"',
        "last_modified": "Mon, 31 Aug 2026 00:00:00 GMT",
        "revision_covered": False,
        "original_capture": {"retained_prior_metadata": ["unchanged", {"revision": 7}]},
    }
    previous = {"sources": {"unselected": deepcopy(untouched)}}
    previous_copy = deepcopy(previous)
    with _responses(PDF_BODY, sources={"only": PDF_URL, "unselected": HTML_URL}) as requests:
        report = monitor.monitor_sources(
            source_ids=["only"], previous_state=previous, original_store=store,
        )

    assert [str(request.url) for request in requests] == [PDF_URL]
    assert [row["source_id"] for row in report["sources"]] == ["only"]
    assert report["monitor_scope"] == "selected_sources"
    assert report["selected_source_ids"] == ["only"]
    assert report["selected_source_count"] == 1
    assert report["registered_monitor_source_count"] == 2
    assert report["full_registry_checked"] is False
    assert report["revision_coverage_complete"] is False
    assert report["selected_revision_coverage_complete"] is True
    assert report["next_state"]["sources"]["unselected"] == untouched
    assert previous == previous_copy
    _assert_receipt(store, report["sources"][0]["original_capture"], PDF_BODY, ["only"])


def test_cli_unknown_source_id_is_rejected_before_monitor_fetch():
    with (
        patch("sys.argv", ["monitor_official_ntm_sources.py", "--source-id", "unknown"]),
        patch.object(monitor, "SOURCES", {"only": PDF_URL}),
        patch.object(monitor, "monitor_sources") as run,
        patch.object(monitor.httpx, "Client") as client,
    ):
        with pytest.raises(SystemExit) as exc:
            monitor.main()
    assert exc.value.code == 2
    run.assert_not_called()
    client.assert_not_called()


def test_cli_forwards_repeatable_source_selection(capsys):
    result = {
        "next_state": {"sources": {}},
        "sources": [],
        "all_available": True,
        "revision_monitor_gate_ok": True,
        "review_required": False,
    }
    with (
        patch("sys.argv", [
            "monitor_official_ntm_sources.py",
            "--source-id", "first", "--source-id", "second",
        ]),
        patch.object(monitor, "SOURCES", {"first": PDF_URL, "second": HTML_URL}),
        patch.object(monitor, "monitor_sources", return_value=result) as run,
    ):
        assert monitor.main() == 0
    assert run.call_args.kwargs["source_ids"] == ["first", "second"]
    json.loads(capsys.readouterr().out)
