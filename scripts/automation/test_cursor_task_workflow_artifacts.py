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


def test_job_env_does_not_use_runner_temp_expression() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    job_env = text.split("jobs:", 1)[1].split("\n    steps:", 1)[0]
    assert "runner.temp" not in job_env


def test_initialize_runtime_paths_step_uses_runner_temp_shell_env() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    block = text.split("- name: Initialize runtime paths", 1)[1].split("- name: Resolve issue context", 1)[0]
    assert '${RUNNER_TEMP}/cursor-task' in block
    assert "GITHUB_ENV" in block
    assert "ISSUE_CONTEXT_PATH=" in block
    assert "OPEN_PRS_PATH=" in block
    assert "PR_BODY_PATH=" in block
    resolve_pos = text.find("- name: Resolve issue context")
    init_pos = text.find("- name: Initialize runtime paths")
    assert init_pos != -1 and resolve_pos != -1
    assert init_pos < resolve_pos


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
    block = text.split("- name: Resolve issue context", 1)[1].split("- name: Authorize", 1)[0]
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
