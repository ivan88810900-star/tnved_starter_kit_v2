"""Static checks for cursor-task workflow commit / no-change guard."""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "cursor-task-agent.yml"


def _commit_step_run_block() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(
        r"- name: Commit changes\n.*?id: git_commit\n.*?run: \|\n(.*?)(?=\n      - name:)",
        text,
        re.DOTALL,
    )
    assert match, "Commit changes step not found in workflow"
    return match.group(1)


def test_commit_step_stages_before_no_change_check() -> None:
    block = _commit_step_run_block()
    add_pos = block.find("git add -A")
    validate_pos = block.find("validate_cursor_task_staged_changes.py")
    cached_check_pos = block.find("git diff --cached --quiet")
    assert add_pos != -1 and validate_pos != -1 and cached_check_pos != -1
    assert add_pos < validate_pos < cached_check_pos


def test_commit_step_does_not_use_worktree_only_quiet_check() -> None:
    block = _commit_step_run_block()
    assert "git diff --quiet && git diff --cached --quiet" not in block


def test_commit_step_commits_staged_changes_only_after_add() -> None:
    block = _commit_step_run_block()
    assert "git commit -m" in block
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    add_idx = lines.index("git add -A")
    commit_idx = next(i for i, ln in enumerate(lines) if ln.startswith("git commit"))
    assert add_idx < commit_idx
