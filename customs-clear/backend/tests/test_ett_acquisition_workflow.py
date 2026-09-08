"""Protect the explicitly requested, non-promoting ETT acquisition CI path."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest
import yaml

from scripts.validate_scheduled_workflow_contract import _check_python


WORKFLOW_PATH = Path(__file__).resolve().parents[3] / ".github/workflows/ci.yml"


def acquisition_job():
    document = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    return document, document["jobs"]["ett-acquisition"]


def test_official_acquisition_requires_explicit_capture_request_and_has_no_write_authority():
    document, job = acquisition_job()
    configured = document["on"]["workflow_dispatch"]["inputs"]["ett_acquire"]
    assert configured["type"] == "boolean"
    assert configured["default"] == "false"
    assert configured["required"] == "false"
    assert job["if"] == "${{ (github.event_name == 'workflow_dispatch' && inputs.ett_acquire == true) || (github.event_name == 'push' && github.ref == 'refs/heads/ops/ett-source-capture') }}"
    assert job["permissions"] == {"contents": "read"}
    # Three 20-minute stage budgets plus dependency/packaging reserve.
    assert 60 < int(job["timeout-minutes"]) <= 90
    assert "DATABASE_URL" not in job["env"]
    assert job["env"]["CUSTOMSCLEAR_READ_ONLY"] == "1"
    assert job["env"]["SCHEDULER_ENABLED"] == "0"
    assert job["env"]["REGULATORY_SYNC_SCHEDULER_ENABLED"] == "0"
    for step in job["steps"]:
        assert "secrets." not in json.dumps(step)
        if "uses" in step:
            assert re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", step["uses"])
        if step.get("uses", "").startswith("actions/checkout@"):
            assert step["with"]["persist-credentials"] == "false"
    uploads = [step for step in job["steps"] if step.get("uses", "").startswith("actions/upload-artifact@")]
    assert len(uploads) == 1
    assert int(uploads[0]["with"]["retention-days"]) <= 90
    assert "ett-acquisition-store.tar.gz" in uploads[0]["with"]["path"]
    assert "workflow-status.json" in uploads[0]["with"]["path"]


def test_job_environment_uses_only_contexts_available_before_runner_allocation(tmp_path):
    document, job = acquisition_job()
    for configured_job in document["jobs"].values():
        for value in configured_job.get("env", {}).values():
            for expression in re.findall(r"\$\{\{(.*?)\}\}", value):
                assert not re.search(r"\b(?:runner|steps|job|env)\.", expression)
    script = next(step["run"] for step in job["steps"] if step["name"] == "Prepare private temporary evidence directory")
    output = tmp_path / "environment"
    result = subprocess.run(["bash", "-euo", "pipefail", "-c", script],
                            env={**os.environ, "RUNNER_TEMP": str(tmp_path), "GITHUB_ENV": str(output)},
                            text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert output.read_text() == f"ETT_EVIDENCE_ROOT={tmp_path}/ett-acquisition\nETT_STORE_ROOT={tmp_path}/ett-acquisition/store\n"
    assert (tmp_path / "ett-acquisition/store").stat().st_mode & 0o777 == 0o700


def test_acquisition_workflow_shell_and_embedded_python_compile():
    _, job = acquisition_job()
    for step in job["steps"]:
        if "run" not in step:
            continue
        result = subprocess.run(["bash", "-n"], input=step["run"], text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        _check_python(step["run"], label=step["name"])


@pytest.mark.parametrize(
    "receipt,allowed",
    [
        ({"receipt_sha256": "a" * 64, "production_ready": False}, True),
        ({"receipt_sha256": "a" * 64, "production_ready": True}, False),
        ({"receipt_sha256": "a" * 64}, False),
        ({"receipt_sha256": "a" * 63, "production_ready": False}, False),
        ({"receipt_sha256": "A" * 64, "production_ready": False}, False),
        ({"receipt_sha256": "$(touch unexpected-write)", "production_ready": False}, False),
        ({"receipt_sha256": None, "production_ready": False}, False),
    ],
)
def test_workflow_extracts_only_the_explicit_validated_receipt(tmp_path, receipt, allowed):
    _, job = acquisition_job()
    script = next(step["run"] for step in job["steps"] if step.get("id") == "extract")
    evidence = tmp_path / "evidence"
    evidence.mkdir(mode=0o700)
    store = evidence / "store"
    store.mkdir(mode=0o700)
    (evidence / "acquisition.json").write_text(json.dumps(receipt), encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/ett_candidates.py").write_text(
        "import json, pathlib, sys\n"
        "pathlib.Path('invocation.json').write_text(json.dumps(sys.argv[1:]))\n"
        "print(json.dumps({'production_ready': False}))\n",
        encoding="utf-8",
    )
    # Use the test interpreter without changing the workflow's real Python command.
    binaries = tmp_path / "bin"
    binaries.mkdir()
    (binaries / "python").symlink_to(sys.executable)
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": str(binaries) + os.pathsep + os.environ.get("PATH", ""),
            "ETT_EVIDENCE_ROOT": str(evidence),
            "ETT_STORE_ROOT": str(store),
            "GITHUB_OUTPUT": str(tmp_path / "step-output"),
        },
        text=True,
        capture_output=True,
    )
    assert (result.returncode == 0) is allowed, result.stderr
    invocation = tmp_path / "invocation.json"
    assert invocation.exists() is allowed
    assert not (tmp_path / "unexpected-write").exists()
    if allowed:
        assert json.loads(invocation.read_text()) == ["extract", "a" * 64, "--store-root", str(store)]
        assert json.loads((evidence / "extraction.json").read_text())["production_ready"] is False
        assert (tmp_path / "step-output").read_text() == "receipt_sha256=" + "a" * 64 + "\n"


def test_analysis_receives_only_the_successfully_verified_receipt_output():
    _, job = acquisition_job()
    steps = job["steps"]
    analysis = next(step for step in steps if step.get("id") == "analyze")
    extract = next(step for step in steps if step.get("id") == "extract")
    assert steps.index(analysis) > steps.index(extract)
    assert analysis["env"] == {"ETT_RECEIPT_SHA256": "${{ steps.extract.outputs.receipt_sha256 }}"}
    assert 'analyze "$ETT_RECEIPT_SHA256"' in analysis["run"]
    assert "${{" not in analysis["run"]
    upload = next(step for step in steps if step.get("uses", "").startswith("actions/upload-artifact@"))
    assert "analysis.json" in upload["with"]["path"]


def test_legal_source_check_is_explicit_readonly_and_uses_valid_runner_contexts():
    path = WORKFLOW_PATH.with_name("ett-legal-source-check.yml")
    document = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    assert document["on"] == {"push": {"branches": ["ops/ett-legal-source-check"]}}
    assert document["permissions"] == {"contents": "read"}
    job = document["jobs"]["legal-source-check"]
    # Allow the separately bounded 20-minute observed-page capture, the source
    # probes, dependency setup and evidence packaging to finish within the job.
    assert 20 < int(job["timeout-minutes"]) <= 60
    assert job["env"]["CUSTOMSCLEAR_READ_ONLY"] == "1"
    assert "secrets." not in json.dumps(document)
    assert "DATABASE_URL" not in json.dumps(document)
    assert "runner." not in json.dumps(job["env"])
    for step in job["steps"]:
        if "uses" in step:
            assert re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", step["uses"])
        if "run" in step:
            assert "${{" not in step["run"]
            result = subprocess.run(["bash", "-n"], input=step["run"], text=True, capture_output=True)
            assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("filename,branch", [
    ("ett-legal-archive-capture.yml", "ops/ett-legal-archive-capture"),
    ("ett-legal-document-capture.yml", "ops/ett-legal-document-capture"),
])
def test_additional_legal_captures_have_isolated_readonly_branch_and_runnable_shell(filename, branch):
    document = yaml.load(WORKFLOW_PATH.with_name(filename).read_text(), Loader=yaml.BaseLoader)
    assert document["on"] == {"push": {"branches": [branch]}}
    assert document["permissions"] == {"contents": "read"}
    assert "secrets." not in json.dumps(document)
    assert "DATABASE_URL" not in json.dumps(document)
    for job in document["jobs"].values():
        assert int(job["timeout-minutes"]) <= 90
        assert job["env"]["CUSTOMSCLEAR_READ_ONLY"] == "1"
        assert "runner." not in json.dumps(job["env"])
        for step in job["steps"]:
            if "uses" in step:
                assert re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", step["uses"])
            if "run" in step:
                assert "${{" not in step["run"]
                result = subprocess.run(["bash", "-n"], input=step["run"], text=True, capture_output=True)
                assert result.returncode == 0, result.stderr
                for script in re.findall(r"\bpython (scripts/[a-z_]+\.py)\b", step["run"]):
                    assert (Path(__file__).resolve().parents[1] / script).is_file(), script
