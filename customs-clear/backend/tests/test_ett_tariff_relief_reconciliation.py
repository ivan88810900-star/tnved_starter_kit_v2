"""Changed landing links cannot hide behind a still-available older PDF."""
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

import pytest

from app.services.ett_artifacts import LocalArtifactStore
from app.services.ett_tariff_relief_capture import (
    LANDING_SOURCES, ReliefCaptureError, capture_tariff_relief, load_observed_baseline,
    load_observed_baselines, reconcile_tariff_relief,
)
from app.services.ett_transport import OfficialResponse
from scripts.capture_ett_tariff_relief import main

OLD_URL = "https://eec.eaeunion.org/upload/old.pdf"
NEW_URL = "https://eec.eaeunion.org/upload/current.pdf"
PDF = b"%PDF-1.7\nSYNTHETIC\n%%EOF\n"
INSTANT = datetime(2026, 9, 10, tzinfo=timezone.utc)
DETAIL_URLS = (
    "https://docs.eaeunion.org/documents/461/10843/",
    "https://docs.eaeunion.org/documents/461/10846/",
    "https://docs.eaeunion.org/documents/461/10848/",
    "https://docs.eaeunion.org/documents/461/10854/",
)


def fetcher(urls=(OLD_URL,), pdf=PDF, page_note="", calls=None):
    def fetch(url, *, expected_media):
        if calls is not None:
            calls.append(url)
        anchors = "".join(f'<a href="{target}">Observed PDF</a>' for target in urls)
        content = f"<html><body>{page_note}{anchors}</body></html>".encode() if expected_media == "text/html" else pdf
        return OfficialResponse(url=url, requested_url=url, media_type=expected_media,
                                retrieved_at=INSTANT, content=content)
    return fetch


def baseline_for(report):
    rows = []
    by_url = {row["requested_url"]: row for row in report["records"]}
    for row in report["records"]:
        if row["media_type"] != "application/pdf":
            continue
        link = report["links"][row["parent_link_indices"][0]]
        parent = by_url[link["parent_requested_url"]]
        rows.append({**{key: row[key] for key in ("requested_url", "response_url", "sha256", "size_bytes", "media_type", "retrieved_at")},
                     "source_id": f"observed_source_{len(rows)}", "parent_requested_url": parent["requested_url"],
                     "parent_sha256": parent["sha256"], "parent_size_bytes": parent["size_bytes"],
                     "parent_retrieved_at": parent["retrieved_at"]})
    return json.dumps({"schema_version": 1, "observation_kind": "retrieved_tariff_relief_gsp_artifacts",
                       "capture_report_sha256": hashlib.sha256(json.dumps(report).encode()).hexdigest(),
                       "capture_complete": True, "source_count": len(rows), "sources": rows,
                       "is_accepted_monitor_baseline": False, "is_legal_approval": False,
                       "can_promote": False, "active_rates_written": False}).encode()


def split_baseline(raw):
    baseline = json.loads(raw)
    return tuple(
        json.dumps({**baseline, "source_count": 1, "sources": [source]}).encode()
        for source in baseline["sources"]
    )


def capture(tmp_path, name="store", **kwargs):
    store = LocalArtifactStore(tmp_path / name)
    return store, capture_tariff_relief(store, fetch=fetcher(**kwargs))


def test_replaced_href_detected_even_when_old_pdf_bytes_would_still_be_available(tmp_path):
    _, old = capture(tmp_path, "old")
    calls = []
    store, current = capture(tmp_path, "current", urls=(NEW_URL,), calls=calls)
    result = reconcile_tariff_relief(current, store, observed_baseline=baseline_for(old))
    assert OLD_URL not in calls  # following only a fixed old URL would miss this change
    assert result["source_graph_verified"] is True
    assert result["status"] == "changes_detected"
    assert result["operational_ok"] is False
    assert result["added_pdf_urls"] == [NEW_URL]
    assert result["missing_pdf_urls"] == [OLD_URL]
    assert result["changed_pdfs"] == []
    assert result["review_required"] is True


def test_same_url_changed_bytes_require_review(tmp_path):
    _, old = capture(tmp_path, "old")
    store, current = capture(tmp_path, "current", pdf=b"%PDF-1.7\nREVISED\n%%EOF\n")
    result = reconcile_tariff_relief(current, store, observed_baseline=baseline_for(old))
    assert result["status"] == "changes_detected"
    assert result["changed_pdfs"][0]["changed_fields"] == ["sha256", "size_bytes"]
    assert result["changed_pdfs"][0]["previous_sha256"] != result["changed_pdfs"][0]["observed_sha256"]


def test_changed_final_pdf_url_detected_even_when_bytes_unchanged(tmp_path):
    _, old = capture(tmp_path, "old")
    store = LocalArtifactStore(tmp_path / "current")
    original_fetch = fetcher()
    def redirected(url, *, expected_media):
        response = original_fetch(url, expected_media=expected_media)
        return replace(response, url=NEW_URL, redirect_chain=(NEW_URL,)) if expected_media == "application/pdf" else response
    current = capture_tariff_relief(store, fetch=redirected)
    result = reconcile_tariff_relief(current, store, observed_baseline=baseline_for(old))
    assert result["status"] == "changes_detected"
    assert result["changed_pdfs"][0]["changed_fields"] == ["response_url"]


def test_missing_link_is_reported_without_new_document_or_assumed_replacement(tmp_path):
    _, old = capture(tmp_path, "old", urls=(OLD_URL, NEW_URL))
    store, current = capture(tmp_path, "current")
    result = reconcile_tariff_relief(current, store, observed_baseline=baseline_for(old))
    assert result["missing_pdf_urls"] == [NEW_URL]
    assert result["added_pdf_urls"] == []


def test_first_capture_and_unchanged_observation_are_both_unapproved(tmp_path):
    store, current = capture(tmp_path)
    first = reconcile_tariff_relief(current, store)
    assert first["status"] == "baseline_missing"
    assert first["operational_ok"] is False
    unchanged = reconcile_tariff_relief(current, store, observed_baseline=baseline_for(current))
    assert unchanged["status"] == "observed_baseline_unreviewed"
    assert unchanged["operational_ok"] is True
    assert unchanged["observed_baseline_count"] == 1
    assert unchanged["observed_baseline_sha256"] == hashlib.sha256(baseline_for(current)).hexdigest()
    assert unchanged["observed_baseline_sha256s"] == [unchanged["observed_baseline_sha256"]]
    for result in (first, unchanged):
        assert result["source_graph_verified"] is True
        assert result["review_required"] is True
        for flag in ("baseline_accepted", "baseline_updated", "historical_originals_replayed", "legal_ready", "can_promote", "active_rates_written"):
            assert result[flag] is False


def test_volatile_html_text_changes_do_not_masquerade_as_pdf_revision(tmp_path):
    _, old = capture(tmp_path, "old", page_note="Thursday morning")
    store, current = capture(tmp_path, "current", page_note="Friday afternoon")
    assert current["records"][0]["sha256"] != old["records"][0]["sha256"]
    result = reconcile_tariff_relief(current, store, observed_baseline=baseline_for(old))
    assert result["source_graph_verified"] is True
    assert result["status"] == "observed_baseline_unreviewed"
    assert result["changed_pdfs"] == []


@pytest.mark.parametrize("field,value", [
    ("href", "/invented.pdf"), ("label", "Invented label"), ("parent_sha256", "a" * 64),
    ("parent_url", "https://eec.eaeunion.org/other"), ("parent_requested_url", LANDING_SOURCES[1][1]),
    ("anchor_index", 42), ("raw_start_tag", '<a href="invented.pdf">'),
    ("resolved_url", NEW_URL),
    ("anchor_index", False), ("anchor_index", 0.0),
])
def test_tampered_current_link_record_fails_original_byte_replay(tmp_path, field, value):
    store, current = capture(tmp_path)
    baseline = baseline_for(current)
    current["links"][0][field] = value
    result = reconcile_tariff_relief(current, store, observed_baseline=baseline)
    assert result["status"] == "evidence_invalid"
    assert result["source_graph_verified"] is False
    assert result["review_required"] is True


def test_tampered_pdf_parent_indices_fail_graph_replay(tmp_path):
    store, current = capture(tmp_path)
    baseline = baseline_for(current)
    current["records"][-1]["parent_link_indices"] = [1]
    result = reconcile_tariff_relief(current, store, observed_baseline=baseline)
    assert result["status"] == "evidence_invalid"


def test_missing_original_cannot_be_verified_by_report_hash_alone(tmp_path):
    store, current = capture(tmp_path)
    (tmp_path / "store" / (current["records"][0]["sha256"] + ".blob")).unlink()
    result = reconcile_tariff_relief(current, store, observed_baseline=baseline_for(current))
    assert result["status"] == "evidence_invalid"
    assert result["source_graph_verified"] is False


@pytest.mark.parametrize("flag", ["is_accepted_monitor_baseline", "is_legal_approval", "can_promote", "active_rates_written"])
def test_observation_file_cannot_grant_approval(tmp_path, flag):
    store, current = capture(tmp_path)
    baseline = json.loads(baseline_for(current))
    baseline[flag] = True
    result = reconcile_tariff_relief(current, store, observed_baseline=json.dumps(baseline).encode())
    assert result["status"] == "evidence_invalid"
    assert result["baseline_accepted"] is False


def test_duplicate_json_keys_are_not_accepted_as_observation_pins():
    with pytest.raises(ValueError):
        load_observed_baseline(b'{"schema_version":1,"schema_version":1}')


def test_multiple_observation_manifests_are_combined_without_synthetic_baseline_identity(tmp_path):
    store, current = capture(tmp_path, urls=(OLD_URL, NEW_URL))
    baselines = split_baseline(baseline_for(current))
    assert len(load_observed_baselines(baselines)) == 2
    result = reconcile_tariff_relief(current, store, observed_baseline=baselines)
    assert result["status"] == "observed_baseline_unreviewed"
    assert result["operational_ok"] is True
    assert result["observed_baseline_count"] == 2
    assert result["observed_baseline_sha256"] is None
    assert result["observed_baseline_sha256s"] == [hashlib.sha256(raw).hexdigest() for raw in baselines]


def test_duplicate_sources_across_observation_manifests_are_rejected(tmp_path):
    store, current = capture(tmp_path)
    baseline = baseline_for(current)
    with pytest.raises(ReliefCaptureError):
        load_observed_baselines((baseline, baseline))
    result = reconcile_tariff_relief(current, store, observed_baseline=(baseline, baseline))
    assert result["status"] == "evidence_invalid"
    assert result["source_graph_verified"] is False


def test_failed_current_acquisition_is_not_a_false_missing_link_finding(tmp_path):
    store, current = capture(tmp_path)
    baseline = baseline_for(current)
    current["capture_complete"] = False
    result = reconcile_tariff_relief(current, store, observed_baseline=baseline)
    assert result["status"] == "capture_incomplete"
    assert result["missing_pdf_urls"] == []
    assert result["source_graph_verified"] is False


def test_cli_reconciliation_returns_review_exit_without_modifying_observation_pins(tmp_path):
    _, old = capture(tmp_path, "old")
    observed = tmp_path / "observed.json"
    pinned = baseline_for(old)
    observed.write_bytes(pinned)
    output = tmp_path / "report.json"
    result = main(["--store-root", str(tmp_path / "current"), "--output", str(output),
                   "--observed-baseline", str(observed)], fetch=fetcher(urls=(NEW_URL,)))
    assert result == 3
    assert observed.read_bytes() == pinned
    assert json.loads(output.read_text())["reconciliation"]["added_pdf_urls"] == [NEW_URL]


def test_cli_stable_unapproved_observations_are_operationally_healthy_without_activation(tmp_path):
    _, old = capture(tmp_path, "old")
    observed = tmp_path / "observed.json"
    pinned = baseline_for(old)
    observed.write_bytes(pinned)
    output = tmp_path / "report.json"
    result = main(["--store-root", str(tmp_path / "current"), "--output", str(output),
                   "--observed-baseline", str(observed)], fetch=fetcher(page_note="changed clock text"))
    assert result == 0
    assert observed.read_bytes() == pinned
    reconciliation = json.loads(output.read_text())["reconciliation"]
    assert reconciliation["operational_ok"] is True
    assert reconciliation["review_required"] is True
    assert reconciliation["baseline_accepted"] is False
    assert reconciliation["baseline_updated"] is False
    assert reconciliation["legal_ready"] is False
    assert reconciliation["can_promote"] is False
    assert reconciliation["active_rates_written"] is False


def test_cli_combines_repeatable_observation_files_without_modifying_them(tmp_path):
    _, old = capture(tmp_path, "old", urls=(OLD_URL, NEW_URL))
    pins = split_baseline(baseline_for(old))
    paths = []
    for index, pinned in enumerate(pins):
        path = tmp_path / f"observed-{index}.json"
        path.write_bytes(pinned)
        paths.append(path)
    output = tmp_path / "report.json"
    result = main([
        "--store-root", str(tmp_path / "current"), "--output", str(output),
        "--observed-baseline", str(paths[0]), "--observed-baseline", str(paths[1]),
    ], fetch=fetcher(urls=(OLD_URL, NEW_URL)))
    assert result == 0
    assert tuple(path.read_bytes() for path in paths) == pins
    reconciliation = json.loads(output.read_text())["reconciliation"]
    assert reconciliation["operational_ok"] is True
    assert reconciliation["observed_baseline_count"] == 2
    assert reconciliation["observed_baseline_sha256"] is None
    assert reconciliation["observed_baseline_sha256s"] == [hashlib.sha256(raw).hexdigest() for raw in pins]


def test_cli_rejects_overlapping_observation_files_before_network(tmp_path):
    _, old = capture(tmp_path, "old")
    observed = tmp_path / "observed.json"
    observed.write_bytes(baseline_for(old))
    assert main([
        "--store-root", str(tmp_path / "current"),
        "--output", str(tmp_path / "report.json"),
        "--observed-baseline", str(observed),
        "--observed-baseline", str(observed),
    ], fetch=lambda *args, **kwargs: pytest.fail("must not fetch")) == 2


@pytest.mark.parametrize("kind", ["fifo", "symlink", "directory", "invalid", "missing"])
def test_cli_rejects_unsafe_baseline_before_network_or_blocking_open(tmp_path, kind):
    path = tmp_path / "observed"
    if kind == "fifo":
        os.mkfifo(path)
    elif kind == "symlink":
        path.symlink_to(tmp_path / "missing")
    elif kind == "directory":
        path.mkdir()
    elif kind == "invalid":
        path.write_text("{}")
    assert main(["--store-root", str(tmp_path / "store"), "--output", str(tmp_path / "report.json"),
                 "--observed-baseline", str(path)], fetch=lambda *args, **kwargs: pytest.fail("must not fetch")) == 2


def test_daily_workflow_reconciles_dynamic_links_retains_originals_and_cannot_accept_baseline():
    import yaml
    root = Path(__file__).resolve().parents[3]
    raw = (root / ".github/workflows/scheduled-data-refresh.yml").read_text()
    workflow = yaml.safe_load(raw)
    triggers = workflow.get("on", workflow.get(True))
    assert triggers["schedule"] == [{"cron": "17 3 * * *"}]
    monitor = workflow["jobs"]["monitor"]
    assert monitor["permissions"] == {"contents": "read", "issues": "read"}
    by_id = {step.get("id"): step for step in monitor["steps"]}
    capture_step = by_id["tariff_relief_capture"]
    assert capture_step["run"].count("--observed-baseline ") == 2
    assert capture_step["run"].count("--detail-url ") == len(DETAIL_URLS)
    assert "--observed-baseline data/ett_tariff_relief_source_observations.json" in capture_step["run"]
    assert "--observed-baseline data/ett_tariff_relief_council_source_observations.json" in capture_step["run"]
    for detail_url in DETAIL_URLS:
        assert f"--detail-url {detail_url}" in capture_step["run"]
    assert "--accept" not in capture_step["run"]
    assert "secrets." not in json.dumps(capture_step)
    assert capture_step["env"]["CUSTOMSCLEAR_READ_ONLY"] == "1"
    upload = by_id["upload_evidence"]
    assert upload["with"]["retention-days"] == 90
    assert "ett-tariff-relief-report.json" in upload["with"]["path"]
    assert "ett-tariff-relief-objects.tar.gz" in upload["with"]["path"]
    assert len(upload["uses"].split("@")[-1]) == 40
    notifier = workflow["jobs"]["notify"]["steps"][-1]["with"]["script"]
    assert "if (needsAttention || tariffReliefNeedsAttention)" in notifier
    assert "tariffReliefReport?.reconciliation?.review_required !== false" in notifier
    assert "TARIFF_RELIEF_REVIEW=pending_or_invalid" in raw
    assert ".reconciliation.operational_ok == true" in raw
    assert ".reconciliation.review_required == false" not in raw


@pytest.mark.parametrize("gate_name", [
    "Validate state persistence after evidence upload",
    "Enforce monitor gate after evidence and state persistence",
])
@pytest.mark.parametrize("failed_step", ["TARIFF_RELIEF_OBJECTS", "TARIFF_RELIEF_CAPTURE"])
def test_daily_gates_reject_failed_capture_or_archive_even_with_nonempty_evidence(tmp_path, gate_name, failed_step):
    import subprocess
    import yaml

    root = Path(__file__).resolve().parents[3]
    workflow = yaml.safe_load((root / ".github/workflows/scheduled-data-refresh.yml").read_text())
    gate = next(step for step in workflow["jobs"]["monitor"]["steps"] if step["name"] == gate_name)
    assert gate["env"]["TARIFF_RELIEF_OBJECTS_OUTCOME"] == "${{ steps.tariff_relief_objects.outcome }}"
    assert gate["env"]["TARIFF_RELIEF_CAPTURE_OUTCOME"] == "${{ steps.tariff_relief_capture.outcome }}"

    evidence = tmp_path / "customs-clear/backend"
    evidence.mkdir(parents=True)
    partial_archive = evidence / "ett-tariff-relief-objects.tar.gz"
    partial_archive.write_bytes(b"partial nonempty archive from failed tar")
    (evidence / "ett-tariff-relief-report.json").write_text(json.dumps({
        "capture_complete": True, "reconciliation": {"source_graph_verified": True, "operational_ok": True},
    }))
    # All independent JSON gates pass. Execute the actual workflow Bash to
    # isolate the archive/capture outcome: nonempty partial output is inadequate.
    commands = tmp_path / "commands"
    commands.mkdir()
    jq = commands / "jq"
    jq.write_text("#!/bin/sh\nexit 0\n")
    jq.chmod(0o700)
    environment = {**os.environ, "PATH": str(commands) + os.pathsep + os.environ.get("PATH", "")}
    environment.update({name: "success" for name in gate["env"] if name.endswith("_OUTCOME")})
    environment[failed_step + "_OUTCOME"] = "failure"
    completed = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", gate["run"]],
                               cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=10)
    assert partial_archive.stat().st_size > 0
    assert completed.returncode == 1
    assert failed_step + "=failure" in completed.stderr
    if gate_name.startswith("Validate"):
        assert "State persistence blocked" in completed.stderr
        assert "Traceback" not in completed.stderr  # stops before the state-reading Python block
