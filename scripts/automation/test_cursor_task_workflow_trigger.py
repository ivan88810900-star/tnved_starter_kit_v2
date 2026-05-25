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


def test_workflow_trigger_includes_workflow_dispatch_issue_number() -> None:
    on_block = _workflow_on_block()
    assert "workflow_dispatch:" in on_block
    assert "issue_number:" in on_block


def test_job_if_supports_issues_and_workflow_dispatch() -> None:
    job_if = _cursor_task_job_if()
    assert "github.event_name == 'issues'" in job_if
    assert "github.event_name == 'workflow_dispatch'" in job_if


def test_job_if_checks_issue_labels_not_only_event_label() -> None:
    job_if = _cursor_task_job_if()
    assert "github.event.label.name" not in job_if
    assert "github.event.issue.labels" in job_if
    assert "cursor-task" in job_if


def test_job_if_excludes_pull_requests_for_issues_event() -> None:
    job_if = _cursor_task_job_if()
    assert "!github.event.issue.pull_request" in job_if


def test_resolve_issue_context_fetches_dispatch_issue_via_api() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    block = text.split("- name: Resolve issue context", 1)[1].split("- name: Authorize", 1)[0]
    assert "workflow_dispatch" in block
    assert "github.rest.issues.get" in block
    assert "DISPATCH_ISSUE_NUMBER" in block
    assert "/^[1-9][0-9]*$/.test(rawIssueNumber)" in block
    assert "parseInt(process.env.DISPATCH_ISSUE_NUMBER" not in block


def test_resolve_issue_context_validates_dispatch_issue_number_before_api() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    block = text.split("- name: Resolve issue context", 1)[1].split("- name: Authorize", 1)[0]
    dispatch_block = block.split("if (context.eventName === 'workflow_dispatch')", 1)[1]
    api_pos = dispatch_block.find("github.rest.issues.get")
    regex_pos = dispatch_block.find("/^[1-9][0-9]*$/.test(rawIssueNumber)")
    assert regex_pos != -1 and api_pos != -1
    assert regex_pos < api_pos


def test_resolve_issue_context_validates_label_pr_and_closed() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    block = text.split("- name: Resolve issue context", 1)[1].split("- name: Authorize", 1)[0]
    assert "issue.pull_request" in block
    assert "issue.state === 'closed'" in block
    assert "cursor-task" in block


def test_trusted_actor_gate_still_present() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Authorize trusted actor" in text
    assert "ivan88810900-star" in text
    assert "steps.authorize.outputs.authorized == 'true'" in text
