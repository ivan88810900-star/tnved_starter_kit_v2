"""Ensure cursor-task workflow artifacts live outside the repository workspace."""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "cursor-task-agent.yml"

REPO_ROOT_ARTIFACTS = (
    "issue-context.json",
    "open-prs.json",
    "pr-body.md",
)


def _run_blocks(text: str) -> str:
    parts = re.split(r"\n      - name:", text)
    chunks: list[str] = []
    for part in parts[1:]:
        if "run: |" in part:
            chunks.append(part.split("run: |", 1)[1])
    return "\n".join(chunks)


def test_job_env_uses_runner_temp_for_artifacts() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "CURSOR_TASK_TEMP: ${{ runner.temp }}/cursor-task" in text
    assert "ISSUE_CONTEXT_PATH: ${{ runner.temp }}/cursor-task/issue-context.json" in text
    assert "OPEN_PRS_PATH: ${{ runner.temp }}/cursor-task/open-prs.json" in text
    assert "PR_BODY_PATH: ${{ runner.temp }}/cursor-task/pr-body.md" in text


def test_workflow_does_not_write_artifacts_to_repo_root() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "writeFileSync('issue-context.json'" not in text
    assert "writeFileSync(\"issue-context.json\"" not in text
    run_text = _run_blocks(text)
    for artifact in REPO_ROOT_ARTIFACTS:
        assert f"> {artifact}" not in run_text
        assert f">{artifact}" not in run_text.replace(f"> {artifact}", "")


def test_github_script_writes_issue_context_via_env_path() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    block = text.split("- name: Write issue context", 1)[1].split("- name: Detect", 1)[0]
    assert "ISSUE_CONTEXT_PATH" in block
    assert "process.env.ISSUE_CONTEXT_PATH" in block


def test_duplicate_guard_and_open_pr_use_temp_paths() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    dup_block = text.split("Detect existing open PR", 1)[1].split("- name: Comment on issue (run started)", 1)[0]
    assert '"${OPEN_PRS_PATH}"' in dup_block
    open_block = text.split("- name: Open pull request", 1)[1].split("- name: Comment on issue (PR opened)", 1)[0]
    assert '"${ISSUE_CONTEXT_PATH}"' in open_block
    assert '"${PR_BODY_PATH}"' in open_block


def test_commit_step_still_stages_all_repo_changes_before_no_change_check() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(
        r"- name: Commit changes\n.*?run: \|\n(.*?)(?=\n      - name:)",
        text,
        re.DOTALL,
    )
    assert match
    block = match.group(1)
    assert "git add -A" in block
    assert block.find("git add -A") < block.find("git diff --cached --quiet")
