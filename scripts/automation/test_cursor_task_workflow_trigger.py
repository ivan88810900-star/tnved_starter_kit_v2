"""Static checks for cursor-task workflow trigger and job conditions."""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "cursor-task-agent.yml"


def _workflow_on_block() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"^on:\n(.*?)^permissions:", text, re.MULTILINE | re.DOTALL)
    assert match, "workflow on: block not found"
    return match.group(1)


def _cursor_task_job_if() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(
        r"^\s+cursor-task:\s*\n\s+if:\s*(.+?)\n\s+runs-on:",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match, "cursor-task job if: condition not found"
    return re.sub(r"\s+", " ", match.group(1).strip())


def test_workflow_trigger_includes_opened_and_labeled() -> None:
    on_block = _workflow_on_block()
    assert "issues:" in on_block
    assert "opened" in on_block
    assert "labeled" in on_block


def test_workflow_trigger_excludes_edited() -> None:
    on_block = _workflow_on_block()
    assert "edited" not in on_block


def test_job_if_checks_issue_labels_not_only_event_label() -> None:
    job_if = _cursor_task_job_if()
    assert "github.event.label.name" not in job_if
    assert "github.event.issue.labels" in job_if
    assert "cursor-task" in job_if


def test_job_if_excludes_pull_requests() -> None:
    job_if = _cursor_task_job_if()
    assert "!github.event.issue.pull_request" in job_if


def test_trusted_actor_gate_still_present() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Authorize trusted actor" in text
    assert "ivan88810900-star" in text
    assert "steps.authorize.outputs.authorized == 'true'" in text
