"""Ensure cursor-task workflow runs only for GitHub Issues, not Pull Requests."""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "cursor-task-agent.yml"


def _cursor_task_job_if() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(
        r"^\s+cursor-task:\s*\n\s+if:\s*(.+?)\n\s+runs-on:",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match, "cursor-task job if: condition not found"
    return re.sub(r"\s+", " ", match.group(1).strip())


def test_cursor_task_workflow_restricts_to_issues_only() -> None:
    job_if = _cursor_task_job_if()
    assert "!github.event.issue.pull_request" in job_if
    assert "github.event.issue.labels" in job_if
    assert "cursor-task" in job_if
    assert "workflow_dispatch" in job_if
