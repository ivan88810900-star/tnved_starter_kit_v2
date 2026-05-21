"""Static security checks for cursor-task workflow."""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "cursor-task-agent.yml"

DANGEROUS_STEP_NAMES = (
    "Create task branch",
    "Install Cursor CLI",
    "Run Cursor agent (headless)",
    "Commit changes",
    "Push branch",
    "Open pull request",
)


def _step_block(text: str, step_name: str) -> str:
    marker = f"- name: {step_name}"
    assert marker in text, f"missing step {step_name}"
    return text.split(marker, 1)[1].split("\n      - name:", 1)[0]


def test_checkout_disables_persist_credentials() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "uses: actions/checkout@v4" in text
    assert "persist-credentials: false" in text


def test_trusted_actor_gate_in_workflow() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    auth_block = _step_block(text, "Authorize trusted actor")
    assert "ivan88810900-star" in auth_block
    assert "CURSOR_TASK_TRUSTED_ACTORS" in auth_block
    assert 'authorized=true' in auth_block or "authorized=true" in auth_block
    assert "Comment on issue (unauthorized actor)" in text


def test_dangerous_steps_require_authorization() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for step_name in DANGEROUS_STEP_NAMES:
        block = _step_block(text, step_name)
        assert "steps.authorize.outputs.authorized == 'true'" in block, step_name


def test_cursor_agent_step_unsets_github_tokens() -> None:
    block = _step_block(WORKFLOW.read_text(encoding="utf-8"), "Run Cursor agent (headless)")
    assert "env -u GITHUB_TOKEN -u GH_TOKEN" in block


def test_commit_step_runs_staged_validation() -> None:
    block = _step_block(WORKFLOW.read_text(encoding="utf-8"), "Commit changes")
    assert "git add -A" in block
    assert "validate_cursor_task_staged_changes.py" in block
    assert block.find("git add -A") < block.find("validate_cursor_task_staged_changes.py")
    assert block.find("validate_cursor_task_staged_changes.py") < block.find(
        "git diff --cached --quiet"
    )


def test_push_step_sets_up_git_auth_explicitly() -> None:
    block = _step_block(WORKFLOW.read_text(encoding="utf-8"), "Push branch")
    assert "gh auth setup-git" in block


def test_failure_comment_includes_workflow_run_url() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    block = _step_block(text, "Comment on issue (workflow failed)")
    assert "if: failure()" in block
    assert "WORKFLOW_RUN_URL" in block
