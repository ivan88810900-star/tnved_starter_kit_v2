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


DATA_ROOT = Path(__file__).resolve().parents[1] / "data"
LEGACY_OBSERVATION_PATH = DATA_ROOT / "ett_tariff_relief_source_observations.json"
COUNCIL_OBSERVATION_PATH = DATA_ROOT / "ett_tariff_relief_council_source_observations.json"
OBSERVATION_PATHS = (LEGACY_OBSERVATION_PATH, COUNCIL_OBSERVATION_PATH)
OBSERVATION_MANIFESTS = tuple(json.loads(path.read_text(encoding="utf-8")) for path in OBSERVATION_PATHS)
OBSERVED_SOURCES = tuple(row for manifest in OBSERVATION_MANIFESTS for row in manifest["sources"])
OBSERVED_ON_BY_SOURCE = {
    row["source_id"]: manifest["observed_on"]
    for manifest in OBSERVATION_MANIFESTS
    for row in manifest["sources"]
}


def test_captured_pdf_observations_match_registered_monitor_targets_without_approval():
    entries = {entry.source_id: entry for entry in TARIFF_RELIEF_SOURCE_REGISTRY}
    observations = {row["source_id"]: row for row in OBSERVED_SOURCES}
    assert set(entries) == set(observations)
    assert len(OBSERVATION_MANIFESTS) == 2
    assert sum(manifest["source_count"] for manifest in OBSERVATION_MANIFESTS) == len(entries) == 12
    assert all(manifest["source_count"] == len(manifest["sources"]) for manifest in OBSERVATION_MANIFESTS)
    for manifest in OBSERVATION_MANIFESTS:
        assert manifest["is_accepted_monitor_baseline"] is False
        assert manifest["is_legal_approval"] is False
        assert manifest["can_promote"] is False
        assert manifest["active_rates_written"] is False
    for source_id, entry in entries.items():
        observed = observations[source_id]
        assert entry.monitor_urls == (observed["requested_url"],)
        assert entry.official_url == observed["parent_requested_url"]
        assert observed["media_type"] == "application/pdf"
        assert len(observed["sha256"]) == len(observed["parent_sha256"]) == 64
        assert len(bytes.fromhex(observed["sha256"])) == 32
        assert observed["size_bytes"] > 0
        assert observed["retrieved_at"].startswith(OBSERVED_ON_BY_SOURCE[source_id])
        assert entry.manual_review_default is True
        assert entry.refresh_cadence == "daily"
        assert entry.max_age_hours == 48
        # An observation manifest is not counted as a locally loaded legal act.
        assert entry.local_paths == ()
        assert entry.db_probe is None
        assert entry.source_status_code is None
        assert monitor.SOURCES[source_id] == observed["requested_url"]
        assert monitor.SOURCE_MODES[source_id] == "legal_drift"


def test_observation_manifests_keep_distinct_capture_provenance():
    legacy, supplement = OBSERVATION_MANIFESTS
    assert hashlib.sha256(LEGACY_OBSERVATION_PATH.read_bytes()).hexdigest() == (
        "6972606d59d94aedec7e4b22d8cd39c11ad5b3da80a0e63bba9335faeb003b1d"
    )
    assert legacy["source_count"] == 9
    assert legacy["capture_report_sha256"] == "afc55fd41c2bea027e2cb8c39d9c26ca90b7ad8731dfb8876a995d36232db396"
    assert supplement["source_count"] == 3
    assert supplement["capture_report_sha256"] == "5100837b60cf40857ab88da2fcf94f150cb5232c531365ea435f1d8c034746d3"
    assert supplement["capture_report_attempted_sources"] == 16
    assert supplement["capture_report_unique_eligible_pdf_targets"] == 11
    assert "does not represent Decision 72 as part of that capture" in supplement["scope"]
    assert "eec_tariff_relief_council72_2026" not in {
        row["source_id"] for row in supplement["sources"]
    }
    for row in supplement["sources"]:
        assert monitor.SOURCES[f'{row["source_id"]}__landing'] == row["parent_requested_url"]
        assert monitor.SOURCE_MODES[f'{row["source_id"]}__landing'] == "legal_drift"


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


@pytest.mark.parametrize("observed", OBSERVED_SOURCES, ids=lambda row: row["source_id"])
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
