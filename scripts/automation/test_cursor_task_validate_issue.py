"""Unit tests for cursor-task issue validation."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from validate_cursor_task_issue import (  # noqa: E402
    branch_name_from_context,
    issue_context_from_payload,
    validate_cursor_task_issue,
)


def _valid_issue() -> dict:
    return {
        "number": 6,
        "title": "E2E smoke test",
        "body": "Goal: noop",
        "html_url": "https://github.com/o/r/issues/6",
        "state": "open",
        "labels": [{"name": "cursor-task"}],
    }


def test_valid_open_issue_with_cursor_task_label() -> None:
    assert not validate_cursor_task_issue(_valid_issue())


def test_rejects_pull_request_issue() -> None:
    issue = _valid_issue()
    issue["pull_request"] = {"url": "https://github.com/o/r/pull/6"}
    errors = validate_cursor_task_issue(issue)
    assert any("pull request" in err for err in errors)


def test_rejects_closed_issue() -> None:
    issue = _valid_issue()
    issue["state"] = "closed"
    errors = validate_cursor_task_issue(issue)
    assert any("closed" in err for err in errors)


def test_rejects_missing_cursor_task_label() -> None:
    issue = _valid_issue()
    issue["labels"] = []
    errors = validate_cursor_task_issue(issue)
    assert any("cursor-task" in err for err in errors)


def test_issue_context_and_branch_name() -> None:
    ctx = issue_context_from_payload(_valid_issue())
    assert ctx["number"] == 6
    assert ctx["title"] == "E2E smoke test"
    assert branch_name_from_context(ctx).startswith("cursor/issue-6-")
