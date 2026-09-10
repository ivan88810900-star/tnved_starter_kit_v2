"""Captured tariff relief documents join monitoring without legal activation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from app.services.regulatory_source_registry import TARIFF_RELIEF_SOURCE_REGISTRY
from app.services.regulatory_source_updates import (
    AUTOMATIC_ADAPTERS,
    UPDATE_POLICIES,
    build_update_plan,
    validate_update_coverage,
)
from scripts import monitor_official_ntm_sources as monitor


OBSERVATION_PATH = Path(__file__).resolve().parents[1] / "data" / "ett_tariff_relief_source_observations.json"
OBSERVATIONS = json.loads(OBSERVATION_PATH.read_text(encoding="utf-8"))


def test_captured_pdf_observations_match_registered_monitor_targets_without_approval():
    entries = {entry.source_id: entry for entry in TARIFF_RELIEF_SOURCE_REGISTRY}
    observations = {row["source_id"]: row for row in OBSERVATIONS["sources"]}
    assert set(entries) == set(observations)
    assert len(entries) == OBSERVATIONS["source_count"] == 9
    assert OBSERVATIONS["capture_report_sha256"] == "afc55fd41c2bea027e2cb8c39d9c26ca90b7ad8731dfb8876a995d36232db396"
    assert OBSERVATIONS["is_accepted_monitor_baseline"] is False
    assert OBSERVATIONS["is_legal_approval"] is False
    assert OBSERVATIONS["can_promote"] is False
    assert OBSERVATIONS["active_rates_written"] is False
    for source_id, entry in entries.items():
        observed = observations[source_id]
        assert entry.monitor_urls == (observed["requested_url"],)
        assert entry.official_url == observed["parent_requested_url"]
        assert observed["media_type"] == "application/pdf"
        assert len(observed["sha256"]) == len(observed["parent_sha256"]) == 64
        assert len(bytes.fromhex(observed["sha256"])) == 32
        assert observed["size_bytes"] > 0
        assert observed["retrieved_at"].startswith("2026-09-10")
        assert entry.manual_review_default is True
        assert entry.refresh_cadence == "daily"
        assert entry.max_age_hours == 48
        # An observation manifest is not counted as a locally loaded legal act.
        assert entry.local_paths == ()
        assert entry.db_probe is None
        assert entry.source_status_code is None
        assert monitor.SOURCES[source_id] == observed["requested_url"]
        assert monitor.SOURCE_MODES[source_id] == "legal_drift"


def test_every_relief_source_uses_existing_daily_monitor_without_an_apply_adapter():
    assert validate_update_coverage()["valid"] is True
    policies = {policy.source_id: policy for policy in UPDATE_POLICIES}
    plan = {row["source_id"]: row for row in build_update_plan()["sources"]}
    adapter_sources = {source_id for adapter in AUTOMATIC_ADAPTERS for source_id in adapter.source_ids}
    for entry in TARIFF_RELIEF_SOURCE_REGISTRY:
        policy = policies[entry.source_id]
        assert policy.strategy == "monitor_only"
        assert policy.cadence == "daily"
        assert policy.adapter_id is None
        assert entry.source_id not in adapter_sources
        assert plan[entry.source_id]["operational_state"] == "scheduled_source_monitor"
        assert plan[entry.source_id]["changes_enforcement_automatically"] is False


@pytest.mark.parametrize("observed", OBSERVATIONS["sources"], ids=lambda row: row["source_id"])
@pytest.mark.parametrize("existing", [False, True], ids=["first-observation", "changed-bytes"])
def test_relief_first_or_changed_pdf_stays_pending_without_advancing_baseline(monkeypatch, observed, existing):
    source_id = observed["source_id"]
    url = observed["requested_url"]
    body = b"%PDF-1.7\n" + b"A different official PDF for review.\n" * 20 + b"%%EOF\n"
    changed_digest = hashlib.sha256(body).hexdigest()
    previous = {"sources": {}}
    if existing:
        previous["sources"][source_id] = {
            "url": url,
            "sha256": observed["sha256"],
            "revision_covered": True,
            "artifact_identity_verified": True,
            "content_type": "application/pdf",
        }
    original_client = httpx.Client
    requests = []

    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(200, content=body, headers={"content-type": "application/pdf"}, request=request)

    monkeypatch.setattr(monitor, "SOURCES", {source_id: url})
    monkeypatch.setattr(monitor, "SOURCE_MODES", {source_id: "legal_drift"})
    monkeypatch.setattr(monitor.httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    report = monitor.monitor_sources(previous_state=previous)
    assert len(requests) == 1
    assert report["review_required"] is True
    assert report["pending_review_source_ids"] == [source_id]
    assert report["accepted_source_ids"] == []
    row = report["sources"][0]
    assert row["ok"] is True
    assert row["revision_covered"] is True
    assert row["baseline_advanced"] is False
    assert row["requires_approval"] is True
    state = report["next_state"]["sources"][source_id]
    assert state["pending_sha256"] == changed_digest
    if existing:
        assert state["sha256"] == observed["sha256"]
    else:
        assert not state.get("sha256")
