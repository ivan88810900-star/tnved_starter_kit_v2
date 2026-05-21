"""Static and unit checks for cursor-task duplicate-PR guard in workflow."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from count_cursor_task_duplicate_prs import (
    count_same_repo_duplicates,
    is_same_repo_cursor_task_duplicate,
)

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "cursor-task-agent.yml"
COUNT_SCRIPT = Path(__file__).resolve().parent / "count_cursor_task_duplicate_prs.py"


def _duplicate_guard_block() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    return text.split("Detect existing open PR for this issue", 1)[1].split(
        "- name: Comment on issue (run started)", 1
    )[0]


def test_duplicate_pr_guard_uses_explicit_pr_list_limit() -> None:
    guard_block = _duplicate_guard_block()
    assert "gh pr list --state open --limit 1000" in guard_block


def test_duplicate_pr_guard_requests_head_repo_fields() -> None:
    guard_block = _duplicate_guard_block()
    assert "headRefName,headRepositoryOwner,headRepository" in guard_block
    assert "count_cursor_task_duplicate_prs.py" in guard_block


def test_duplicate_pr_guard_scopes_to_repository_owner() -> None:
    guard_block = _duplicate_guard_block()
    assert "REPOSITORY_OWNER" in guard_block
    assert 'REPO_NAME="${GITHUB_REPOSITORY#*/}"' in guard_block
    assert "--owner" in guard_block
    assert "--repo" in guard_block


def test_duplicate_pr_guard_uses_explicit_gh_repo_before_checkout() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    job_env = text.split("jobs:", 1)[1].split("\n    steps:", 1)[0]
    assert "GH_REPO: ${{ github.repository }}" in job_env

    guard_block = _duplicate_guard_block()
    assert "gh pr list --state open --limit 1000" in guard_block
    checkout_pos = text.find("uses: actions/checkout@v4")
    duplicate_pos = text.find("Detect existing open PR for this issue")
    assert duplicate_pos != -1 and checkout_pos != -1
    assert duplicate_pos < checkout_pos, "duplicate guard must run before checkout"

    pre_checkout = text[:checkout_pos]
    assert "gh pr list" in pre_checkout
    assert "GH_REPO: ${{ github.repository }}" in pre_checkout.split("steps:", 1)[0]


def test_fork_pr_with_colliding_branch_is_not_duplicate() -> None:
    prs = [
        {
            "headRefName": "cursor/issue-7-malicious-slug",
            "headRepositoryOwner": {"login": "evil-fork-user"},
            "headRepository": {"name": "tnved_starter_kit_v2"},
        },
        {
            "headRefName": "cursor/issue-7-real-task",
            "headRepositoryOwner": {"login": "ivan88810900-star"},
            "headRepository": {"name": "tnved_starter_kit_v2"},
        },
    ]
    assert (
        count_same_repo_duplicates(
            prs,
            branch_prefix="cursor/issue-7-",
            repository_owner="ivan88810900-star",
            repository_name="tnved_starter_kit_v2",
        )
        == 1
    )
    assert not is_same_repo_cursor_task_duplicate(
        prs[0],
        branch_prefix="cursor/issue-7-",
        repository_owner="ivan88810900-star",
        repository_name="tnved_starter_kit_v2",
    )


def test_same_repo_matching_branch_is_duplicate() -> None:
    pr = {
        "headRefName": "cursor/issue-42-official-sgr",
        "headRepositoryOwner": {"login": "ivan88810900-star"},
        "headRepository": {"name": "tnved_starter_kit_v2"},
    }
    assert is_same_repo_cursor_task_duplicate(
        pr,
        branch_prefix="cursor/issue-42-",
        repository_owner="ivan88810900-star",
        repository_name="tnved_starter_kit_v2",
    )


def test_count_script_reads_json_file(tmp_path: Path) -> None:
    prs = [
        {
            "headRefName": "cursor/issue-9-task",
            "headRepositoryOwner": {"login": "owner-a"},
            "headRepository": {"name": "repo-a"},
        }
    ]
    path = tmp_path / "prs.json"
    path.write_text(json.dumps(prs), encoding="utf-8")
    import subprocess
    import sys

    out = subprocess.check_output(
        [
            sys.executable,
            str(COUNT_SCRIPT),
            "--branch-prefix",
            "cursor/issue-9-",
            "--owner",
            "owner-a",
            "--repo",
            "repo-a",
            str(path),
        ],
        text=True,
    ).strip()
    assert out == "1"
