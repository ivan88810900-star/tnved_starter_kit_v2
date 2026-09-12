"""A5 independent checks: rejected bytes cannot replace accepted observations."""

import hashlib
import json
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import patch

import httpx
import pytest

from app.services.ett_artifacts import ArtifactIntegrityError, LocalArtifactStore
from app.services.regulatory_source_capture import (
    capture_original, verify_original_capture, verify_rejected_original_capture,
)
from scripts import monitor_official_ntm_sources as monitor


def run_monitor(store, state, respond):
    with ExitStack() as stack:
        stack.enter_context(patch.object(monitor, "SOURCES", {
            "qa": "https://eec.eaeunion.org/upload/fixture.pdf?ticket=qa-sensitive"}))
        stack.enter_context(patch.object(monitor, "SOURCE_MODES", {"qa": "legal_drift"}))
        stack.enter_context(patch.object(monitor, "REGULATORY_SOURCE_REGISTRY", ()))
        client = httpx.Client(transport=httpx.MockTransport(respond))
        stack.enter_context(patch.object(monitor.httpx, "Client", return_value=client))
        return monitor.monitor_sources(previous_state=state, original_store=store,
                                       capture_rejected_originals=True,
                                       accept_changes=True, approval_ref="qa-asserted-review")


def test_rejected_redirect_body_preserves_last_accepted_receipt_and_pending_review(tmp_path):
    store = LocalArtifactStore(tmp_path / "objects")
    original_url = "https://eec.eaeunion.org/upload/fixture.pdf?ticket=qa-sensitive"
    old_body = b"%PDF-1.7\n" + b"retained prior observation\n" * 12
    old = capture_original(store, body=old_body, source_ids=["qa"], requested_url=original_url,
                           final_url=original_url, redirect_chain=[original_url], retrieved_at=datetime.now(timezone.utc),
                           status_code=200, content_type="application/pdf")
    body = b"<html><body>Access denied</body></html>" + b" " * 160
    state = {"sources": {"qa": {
        "sha256": hashlib.sha256(old_body).hexdigest(), "etag": "old-approved-etag",
        "pending_sha256": hashlib.sha256(body).hexdigest(), "original_capture": old,
        "revision_covered": True, "artifact_identity_verified": True,
    }}}
    before = deepcopy(state)
    requests = []

    def respond(request):
        requests.append(request)
        assert "if-none-match" not in request.headers
        if len(requests) == 1:
            return httpx.Response(302, headers={"location": original_url})
        return httpx.Response(200, content=body, headers={"content-type": "text/html"})

    report = run_monitor(store, state, respond)
    row = report["sources"][0]
    assert len(requests) == 2
    assert row["ok"] is row["approval_allowed"] is row["baseline_advanced"] is False
    assert report["next_state"]["sources"] == state["sources"] == before["sources"]
    assert report["original_capture_count"] == 0
    assert report["rejected_original_capture_count"] == 1
    assert report["accepted_source_ids"] == []
    assert report["original_capture_complete"] is False
    rejected = row["rejected_original_capture"]
    receipt = verify_rejected_original_capture(store, rejected["receipt_sha256"])
    assert store.read(receipt["original_body_sha256"]) == body
    assert receipt["requested"]["url_sha256"] == hashlib.sha256(original_url.encode()).hexdigest()
    assert receipt["response"]["url_sha256"] == hashlib.sha256(str(requests[-1].url).encode()).hexdigest()
    assert "qa-sensitive" not in json.dumps(report)
    with pytest.raises(ArtifactIntegrityError):
        verify_original_capture(store, rejected["receipt_sha256"])
    assert verify_original_capture(store, old["receipt_sha256"])["original_body_sha256"] == hashlib.sha256(old_body).hexdigest()


@pytest.mark.parametrize("mutation", ["duplicate_kind", "extra_approval", "numeric_false"])
def test_rehashed_quarantine_receipt_cannot_add_or_retype_authority(tmp_path, mutation):
    store = LocalArtifactStore(tmp_path / "objects")
    body = b"<html><body>Access denied</body></html>" + b" " * 160
    report = run_monitor(store, {}, lambda _: httpx.Response(200, content=body,
                                                           headers={"content-type": "text/html"}))
    captured = report["sources"][0]["rejected_original_capture"]
    receipt = verify_rejected_original_capture(store, captured["receipt_sha256"])
    if mutation == "duplicate_kind":
        raw = json.dumps(receipt)[:-1] + ',"capture_kind":"official_monitor_original"}'
    elif mutation == "extra_approval":
        receipt["approved_by"] = "admin"
        raw = json.dumps(receipt)
    else:
        receipt["legal_review_verified"] = 0
        raw = json.dumps(receipt)
    forged = store.put(raw.encode())
    with pytest.raises(ArtifactIntegrityError):
        verify_rejected_original_capture(store, forged)
    with pytest.raises(ArtifactIntegrityError):
        verify_original_capture(store, forged)
