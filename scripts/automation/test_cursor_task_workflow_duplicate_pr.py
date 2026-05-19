"""Static checks for cursor-task duplicate-PR guard in workflow."""

from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "cursor-task-agent.yml"


def test_duplicate_pr_guard_uses_explicit_pr_list_limit() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Detect existing open PR for this issue" in text
    guard_block = text.split("Detect existing open PR for this issue", 1)[1].split(
        "- name: Comment on issue (run started)", 1
    )[0]
    assert "gh pr list --state open --limit 1000" in guard_block
    assert "gh pr list --state open --json" not in guard_block.replace(
        "gh pr list --state open --limit 1000 --json", ""
    )
