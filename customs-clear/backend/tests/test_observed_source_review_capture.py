"""Explicit observed capture cannot activate a registered monitor or baseline."""

from copy import deepcopy
from contextlib import contextmanager
import ast
import hashlib
import json
from pathlib import Path
import shlex
from unittest.mock import patch

import httpx
import pytest
import yaml

from app.services.ett_artifacts import LocalArtifactStore
from app.services.regulatory_source_capture import verify_original_capture
from scripts import monitor_official_ntm_sources as monitor

ROOT = Path(__file__).resolve().parents[3]
PLAN_PATH = ROOT / "docs/ai-workflow/evidence/eec-ad30-acquisition-plan-20260912.json"
PDF = b"%PDF-1.7\n" + b"isolated observed fixture\n" * 12
HTML = b'<html><body><a href="/review.pdf">Source reference</a>' + b"template " * 30 + b"</body></html>"
REVIEW_ID = "review_ad30_decision4_2026_pdf"
REGISTERED_URL = "https://eec.eaeunion.org/upload/registered-fixture.pdf"


@contextmanager
def _responses(*, rejected=False):
    requests = []

    def respond(request):
        requests.append(request)
        is_pdf = request.url.path.endswith(".pdf")
        body = PDF if is_pdf else HTML
        if rejected:
            body = b"<html><body>Access denied</body></html>" + b" " * 150
        return httpx.Response(
            200, content=body,
            headers={"content-type": "application/pdf" if is_pdf else "text/html"},
        )

    client = httpx.Client(transport=httpx.MockTransport(respond))
    with patch.object(monitor.httpx, "Client", return_value=client):
        yield requests


def test_exact_observations_remain_outside_default_registry_and_policies():
    from app.services.regulatory_source_updates import UPDATE_POLICIES
    from app.services.regulatory_source_registry import REGULATORY_SOURCE_REGISTRY

    plan = json.loads(PLAN_PATH.read_text())
    expected = {item["source_id"]: item["url"] for item in plan["sources"]}
    assert len(expected) == 9
    assert monitor.REVIEW_ONLY_SOURCES == expected
    assert len(monitor.SOURCES) == 72
    assert monitor._selected_sources(None) == monitor.SOURCES
    assert not set(expected).intersection(monitor.SOURCES)
    assert not set(expected).intersection(monitor.SOURCE_MODES)
    assert not set(expected).intersection(entry.source_id for entry in REGULATORY_SOURCE_REGISTRY)
    assert not set(expected).intersection(policy.source_id for policy in UPDATE_POLICIES)
    retained_pdf = "https://docs.eaeunion.org/upload/iblock/072/gnl5h50x3mzkg7zd1b0d593t4mtizhg1/Reshenie-Kollegii-_-121-ot-8-sentbrya-2026-g.pdf"
    assert retained_pdf not in expected.values()
    for item in plan["sources"]:
        if item["source_id"].startswith("review_remedy_index_page_"):
            assert item["parent_body_sha256"] == "f818b7025a7b14d93083938f77629c84f80e9e90ee90cbaef9e98658db9b5148"
            assert item["parent_capture_status"] == "quarantined_content_rejected"
            assert item["resolved_href_observed"] == item["url"]


@pytest.mark.parametrize("mixed", [False, True])
def test_programmatic_acceptance_rejected_before_network_or_store_write(mixed):
    ids = [REVIEW_ID]
    if mixed:
        ids.append("trade_remedies_official")
    with patch.object(monitor.httpx, "Client") as client, patch.object(LocalArtifactStore, "put") as put:
        with pytest.raises(ValueError, match="cannot accept"):
            monitor.monitor_sources(
                source_ids=ids, original_store=object(),
                accept_changes=True, approval_ref="review/claimed-approval",
            )
    client.assert_not_called()
    put.assert_not_called()


def test_programmatic_review_selection_requires_capture_before_network():
    with patch.object(monitor.httpx, "Client") as client:
        with pytest.raises(ValueError, match="require --capture-originals"):
            monitor.monitor_sources(source_ids=[REVIEW_ID])
    client.assert_not_called()


@pytest.mark.parametrize("accept,mixed,capture", [
    (True, False, True), (True, True, True), (True, False, False),
    (False, False, False), (False, True, False),
])
def test_cli_preflight_rejects_before_store_initialization_and_state_read(tmp_path, accept, mixed, capture):
    arguments = ["monitor", "--source-id", REVIEW_ID, "--state", str(tmp_path / "state.json")]
    if mixed:
        arguments += ["--source-id", "trade_remedies_official"]
    if accept:
        arguments += ["--accept-changes", "--approval-ref", "review/claimed-approval"]
    if capture:
        arguments += ["--capture-originals", "--store-root", str(tmp_path / "objects")]
    with (
        patch("sys.argv", arguments),
        patch.object(monitor, "LocalArtifactStore") as store,
        patch.object(monitor, "_load_state") as read_state,
        patch.object(monitor, "monitor_sources") as run,
        patch.object(monitor.httpx, "Client") as client,
    ):
        with pytest.raises(SystemExit) as exc:
            monitor.main()
    assert exc.value.code == 2
    store.assert_not_called()
    read_state.assert_not_called()
    run.assert_not_called()
    client.assert_not_called()
    assert not (tmp_path / "objects").exists()


@pytest.mark.parametrize("existing_baselines", [False, True])
def test_all_nine_targets_retain_receipts_but_no_accepted_or_pending_state(tmp_path, existing_baselines):
    ids = list(monitor.REVIEW_ONLY_SOURCES)
    previous = {"sources": {}}
    if existing_baselines:
        previous["sources"] = {
            source_id: {
                "sha256": "a" * 64, "pending_sha256": hashlib.sha256(PDF).hexdigest(),
                "url": url, "etag": "prior-value", "approval_ref": "old/review",
            }
            for source_id, url in monitor.REVIEW_ONLY_SOURCES.items()
        }
    before = deepcopy(previous)
    store = LocalArtifactStore(tmp_path / "objects")
    with _responses() as requests:
        report = monitor.monitor_sources(
            source_ids=ids, original_store=store, previous_state=previous,
            capture_rejected_originals=True,
        )
    assert len(requests) == 9
    assert {str(request.url) for request in requests} == set(monitor.REVIEW_ONLY_SOURCES.values())
    assert all("if-none-match" not in request.headers for request in requests)
    assert report["selected_review_only_source_ids"] == ids
    assert report["selected_review_only_source_count"] == 9
    assert report["selected_registered_source_ids"] == []
    assert report["selected_registered_source_count"] == 0
    assert report["registered_monitor_source_count"] == 72
    assert report["full_registry_checked"] is report["revision_coverage_complete"] is False
    assert report["original_capture_count"] == 9
    assert report["original_capture_complete"] is True
    assert report["rejected_original_capture_count"] == 0
    assert report["accepted_source_ids"] == []
    assert report["next_state"]["sources"] == before["sources"] == previous["sources"]
    for claim in ("legal_review_verified", "active_rates_written", "can_promote", "durable_legal_retention_attested"):
        assert report[claim] is False
    for row in report["sources"]:
        assert row["source_scope"] == "review_only_observed"
        assert row["ok"] is True
        assert row["approval_allowed"] is row["baseline_advanced"] is False
        receipt = verify_original_capture(store, row["original_capture"]["receipt_sha256"])
        exact = monitor.REVIEW_ONLY_SOURCES[row["source_id"]]
        assert receipt["requested"]["url_sha256"] == hashlib.sha256(exact.encode()).hexdigest()
        if row["source_id"].startswith("review_remedy_index_page_"):
            assert receipt["requested"]["query_redacted"] is True
            assert receipt["requested"]["url"] == "https://docs.eaeunion.org/documents/"
            assert row["url"] == "https://docs.eaeunion.org/documents/"


def test_review_only_content_rejection_stays_quarantined_and_incomplete(tmp_path):
    store = LocalArtifactStore(tmp_path / "objects")
    with _responses(rejected=True):
        report = monitor.monitor_sources(
            source_ids=[REVIEW_ID], original_store=store, capture_rejected_originals=True,
        )
    row = report["sources"][0]
    assert row["source_scope"] == "review_only_observed"
    assert row["ok"] is row["approval_allowed"] is row["baseline_advanced"] is False
    assert row["original_capture"] is None
    assert row["rejected_original_capture"]["capture_kind"] == "official_monitor_rejected_original"
    assert report["original_capture_count"] == 0
    assert report["rejected_original_capture_count"] == 1
    assert report["original_capture_complete"] is False
    assert report["next_state"]["sources"] == {}


def test_mixed_capture_preserves_registered_pending_behavior_and_review_only_isolation(tmp_path):
    store = LocalArtifactStore(tmp_path / "objects")
    with (
        patch.object(monitor, "SOURCES", {"registered": REGISTERED_URL}),
        patch.object(monitor, "SOURCE_MODES", {"registered": "legal_drift"}),
        _responses(),
    ):
        report = monitor.monitor_sources(source_ids=["registered", REVIEW_ID], original_store=store)
    assert report["selected_registered_source_ids"] == ["registered"]
    assert report["selected_review_only_source_ids"] == [REVIEW_ID]
    assert set(report["next_state"]["sources"]) == {"registered"}
    assert report["next_state"]["sources"]["registered"]["pending_sha256"] == hashlib.sha256(PDF).hexdigest()
    assert "sha256" not in report["next_state"]["sources"]["registered"]
    assert report["accepted_source_ids"] == []


def test_default_monitor_does_not_fetch_review_only_sources():
    with (
        patch.object(monitor, "SOURCES", {"registered": REGISTERED_URL}),
        patch.object(monitor, "SOURCE_MODES", {"registered": "legal_drift"}),
        _responses() as requests,
    ):
        report = monitor.monitor_sources()
    assert [str(request.url) for request in requests] == [REGISTERED_URL]
    assert report["selected_review_only_source_ids"] == []
    assert report["selected_review_only_source_count"] == 0


def test_workflow_exact_nine_target_cli_and_packaged_scope(tmp_path, capsys):
    workflow_path = ROOT / ".github/workflows/official-rate-source-capture.yml"
    workflow = yaml.load(workflow_path.read_text(), Loader=yaml.BaseLoader)
    assert workflow["on"] == {"push": {"branches": ["ops/official-rate-source-capture"]}}
    assert workflow["permissions"] == {"contents": "read"}
    steps = workflow["jobs"]["capture"]["steps"]
    acquire = next(step for step in steps if step.get("id") == "acquire")
    tokens = shlex.split(acquire["run"].replace("\\\n", " "))
    arguments = tokens[tokens.index("scripts/monitor_official_ntm_sources.py"):tokens.index(">")]
    selected = [arguments[i + 1] for i, value in enumerate(arguments) if value == "--source-id"]
    assert selected == list(monitor.REVIEW_ONLY_SOURCES)
    assert "--capture-originals" in arguments and "--capture-rejected-originals" in arguments
    assert "--accept-changes" not in arguments and "--approval-ref" not in arguments
    package = next(step for step in steps if "Record execution boundary" in step.get("name", ""))
    embedded = package["run"].split("python - <<'PY'\n", 1)[1].split("\nPY", 1)[0]
    declared = None
    for node in ast.walk(ast.parse(embedded)):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "selected_monitor_ids":
                    declared = ast.literal_eval(value)
    assert declared == selected
    arguments = [value.replace("$RATE_CAPTURE_ROOT", str(tmp_path)) for value in arguments]
    with _responses() as requests, patch("sys.argv", arguments):
        assert monitor.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert len(requests) == report["original_capture_count"] == 9
    assert report["selected_review_only_source_ids"] == selected
    assert report["accepted_source_ids"] == []
    assert json.loads((tmp_path / "observed-state.json").read_text())["sources"] == {}


def _capture_for_inspection(tmp_path, *, page_body=None):
    store = LocalArtifactStore(tmp_path / "objects")

    def respond(request):
        is_pdf = request.url.path.endswith(".pdf")
        body = PDF if is_pdf else HTML
        if page_body is not None and "PAGEN_1" in request.url.params:
            body = page_body
        return httpx.Response(
            200, content=body,
            headers={"content-type": "application/pdf" if is_pdf else "text/html"},
        )

    client = httpx.Client(transport=httpx.MockTransport(respond))
    with patch.object(monitor.httpx, "Client", return_value=client):
        report = monitor.monitor_sources(
            source_ids=list(monitor.REVIEW_ONLY_SOURCES), original_store=store,
            capture_rejected_originals=True,
        )
    return report


def _pagination_fixture():
    return (
        '<html><head><title>Fixture official index</title></head><body>captcha'
        '<a href="/documents/463/fixture-12/">Fixture Решение № 12 от 9 февраля 2021 года</a>'
        '<a href="/upload/report.pdf?signature=private-fixture-secret">Fixture PDF</a>'
        '<a href="https://untrusted.example/documents/12/">Untrusted fixture</a>'
        '<a href="javascript:alert(1)">Ignored fixture</a>'
        + " filler " * 25 + "</body></html>"
    ).encode("utf-8")


def test_read_only_inspection_verifies_all_receipts_without_network_or_store_writes(tmp_path, capsys):
    from scripts import inspect_observed_source_capture as inspector

    report = _capture_for_inspection(tmp_path)
    source = tmp_path / "report.json"
    source.write_text(json.dumps(report))
    output = tmp_path / "inspection.json"
    before = {path.name: path.read_bytes() for path in (tmp_path / "objects").iterdir()}
    with patch.object(monitor.httpx, "Client") as client, patch.object(LocalArtifactStore, "put") as put:
        assert inspector.main([
            "--store-root", str(tmp_path / "objects"),
            "--report", str(source), "--output", str(output),
        ]) == 0
    client.assert_not_called()
    put.assert_not_called()
    after = {path.name: path.read_bytes() for path in (tmp_path / "objects").iterdir()}
    assert before == after
    assert json.loads(source.read_text()) == report
    result = json.loads(output.read_text())
    assert result["original_count"] == 9
    assert result["quarantined_count"] == result["unretained_count"] == 0
    assert result["all_selected_bodies_retained"] is result["original_capture_complete"] is True
    assert result["input_report_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert result["legal_review_verified"] is result["can_promote"] is False
    assert "verified_retained_evidence" in capsys.readouterr().out


def test_quarantined_pagination_links_are_discovery_only_with_exact_parent_hashes(tmp_path, capsys):
    from scripts import inspect_observed_source_capture as inspector

    report = _capture_for_inspection(tmp_path, page_body=_pagination_fixture())
    source = tmp_path / "report.json"
    source.write_text(json.dumps(report))
    output = tmp_path / "inspection.json"
    assert inspector.main([
        "--store-root", str(tmp_path / "objects"),
        "--report", str(source), "--output", str(output),
    ]) == 0
    result = json.loads(output.read_text())
    assert result["original_count"] == 5 and result["quarantined_count"] == 4
    assert result["original_capture_complete"] is False
    assert result["all_selected_bodies_retained"] is True
    for item in result["sources"]:
        if not item["source_id"].startswith("review_remedy_index_page_"):
            continue
        assert item["capture_status"] == "quarantined_content_rejected"
        assert item["monitor_ok"] is False
        assert item["body_sha256"] == hashlib.sha256(_pagination_fixture()).hexdigest()
        discovery = item["pagination_discovery"]
        assert discovery["discovery_only"] is True and discovery["links_truncated"] is False
        candidates = discovery["links"]
        assert len(candidates) == 2
        assert candidates[0]["href_observed"] == "/documents/463/fixture-12/"
        assert candidates[0]["decision12_date_candidate"] is True
        assert candidates[0]["discovery_only"] is True
        assert candidates[0]["legal_review_verified"] is False
        assert candidates[1]["href_observed"] is None
        assert candidates[1]["resolved"]["query_redacted"] is True
        assert candidates[1]["resolved"]["url"] == "https://docs.eaeunion.org/upload/report.pdf"
    rendered = output.read_text() + capsys.readouterr().out
    assert "private-fixture-secret" not in rendered
    assert "untrusted.example" not in rendered


@pytest.mark.parametrize("mutation", [
    "duplicate_id", "wrong_receipt", "body_sha", "legal_claim",
    "claimed_complete", "quarantine_as_original", "report_count",
])
def test_inspection_rejects_unbound_or_relabelled_evidence(tmp_path, mutation):
    from app.services.ett_artifacts import ArtifactIntegrityError
    from scripts import inspect_observed_source_capture as inspector

    report = _capture_for_inspection(tmp_path, page_body=_pagination_fixture())
    if mutation == "duplicate_id":
        report["sources"][-1]["source_id"] = report["sources"][0]["source_id"]
    elif mutation == "wrong_receipt":
        report["sources"][0]["original_capture"] = report["sources"][1]["original_capture"]
    elif mutation == "body_sha":
        report["sources"][0]["original_capture"]["original_body_sha256"] = "0" * 64
    elif mutation == "legal_claim":
        report["legal_review_verified"] = True
    elif mutation == "claimed_complete":
        report["original_capture_complete"] = True
    elif mutation == "quarantine_as_original":
        row = report["sources"][-1]
        row["original_capture"] = row.pop("rejected_original_capture")
    else:
        report["original_capture_count"] = True
    with pytest.raises(ArtifactIntegrityError):
        inspector.inspect_capture(LocalArtifactStore(tmp_path / "objects", create=False), report)


def test_inspection_reports_unretained_transport_failure_without_claiming_completeness(tmp_path):
    from scripts import inspect_observed_source_capture as inspector

    report = _capture_for_inspection(tmp_path)
    row = report["sources"][-1]
    row["original_capture"] = None
    row["ok"] = False
    report["original_capture_count"] -= 1
    report["original_capture_complete"] = False
    result = inspector.inspect_capture(LocalArtifactStore(tmp_path / "objects", create=False), report)
    assert result["original_count"] == 8 and result["unretained_count"] == 1
    assert result["all_selected_bodies_retained"] is result["original_capture_complete"] is False
    assert result["sources"][-1]["capture_status"] == "not_retained"


def test_corrupt_cas_inspection_fails_closed_and_emits_only_sanitized_error(tmp_path, capsys):
    from scripts import inspect_observed_source_capture as inspector

    report = _capture_for_inspection(tmp_path)
    body_sha = report["sources"][0]["original_capture"]["original_body_sha256"]
    blob = tmp_path / "objects" / (body_sha + ".blob")
    blob.chmod(0o600)
    blob.write_bytes(b"damaged bytes; signature=private-fixture-secret")
    blob.chmod(0o400)
    source = tmp_path / "report.json"
    source.write_text(json.dumps(report))
    output = tmp_path / "inspection.json"
    assert inspector.main([
        "--store-root", str(tmp_path / "objects"),
        "--report", str(source), "--output", str(output),
    ]) == 1
    result = json.loads(output.read_text())
    assert result["inspection_status"] == "unavailable"
    assert "original_count" not in result and "sources" not in result
    assert result["legal_review_verified"] is result["can_promote"] is False
    assert "private-fixture-secret" not in output.read_text() + capsys.readouterr().out


@pytest.mark.parametrize("target", ["input_report", "store"])
def test_inspector_cannot_overwrite_input_or_store(tmp_path, target):
    from scripts import inspect_observed_source_capture as inspector

    report = _capture_for_inspection(tmp_path)
    source = tmp_path / "report.json"
    source.write_text(json.dumps(report))
    output = source if target == "input_report" else tmp_path / "objects" / "output.json"
    with pytest.raises(SystemExit) as exc:
        inspector.main([
            "--store-root", str(tmp_path / "objects"),
            "--report", str(source), "--output", str(output),
        ])
    assert exc.value.code == 2
    assert json.loads(source.read_text()) == report
    assert not (tmp_path / "objects" / "output.json").exists()


def test_workflow_inspects_existing_store_even_after_capture_failure_and_uploads_json():
    workflow = yaml.load(
        (ROOT / ".github/workflows/official-rate-source-capture.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    steps = workflow["jobs"]["capture"]["steps"]
    acquire_index = next(i for i, step in enumerate(steps) if step.get("id") == "acquire")
    inspect_index = next(i for i, step in enumerate(steps) if step.get("id") == "inspect")
    package_index = next(i for i, step in enumerate(steps) if "Record execution boundary" in step.get("name", ""))
    assert acquire_index < inspect_index < package_index
    step = steps[inspect_index]
    assert step["if"] == "$" + "{{ always() && steps.prepare.outcome == 'success' }}"
    assert "scripts/inspect_observed_source_capture.py" in step["run"]
    assert '--store-root "$RATE_CAPTURE_ROOT/store"' in step["run"]
    assert '--report "$RATE_CAPTURE_ROOT/report.json"' in step["run"]
    assert '--output "$RATE_CAPTURE_ROOT/inspection.json"' in step["run"]
    upload = next(step for step in steps if step.get("name") == "Upload temporary source evidence")
    assert "$" + "{{ runner.temp }}/official-rate-originals/inspection.json" in upload["with"]["path"]
