#!/usr/bin/env python3
"""Count open PRs in the same repository matching a cursor-task branch prefix."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def is_same_repo_cursor_task_duplicate(
    pr: dict[str, Any],
    *,
    branch_prefix: str,
    repository_owner: str,
    repository_name: str,
) -> bool:
    head_ref = str(pr.get("headRefName") or "")
    if not head_ref.startswith(branch_prefix):
        return False

    owner_obj = pr.get("headRepositoryOwner") or {}
    repo_obj = pr.get("headRepository") or {}
    owner = str(owner_obj.get("login") or "")
    repo = str(repo_obj.get("name") or "")
    return owner == repository_owner and repo == repository_name


def count_same_repo_duplicates(
    prs: list[dict[str, Any]],
    *,
    branch_prefix: str,
    repository_owner: str,
    repository_name: str,
) -> int:
    return sum(
        1
        for pr in prs
        if is_same_repo_cursor_task_duplicate(
            pr,
            branch_prefix=branch_prefix,
            repository_owner=repository_owner,
            repository_name=repository_name,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prs_json", nargs="?", help="JSON array from gh pr list --json")
    parser.add_argument("--branch-prefix", required=True)
    parser.add_argument("--owner", required=True, help="Current repository owner login")
    parser.add_argument("--repo", required=True, help="Current repository name")
    args = parser.parse_args()

    if args.prs_json:
        raw = open(args.prs_json, encoding="utf-8").read()
    else:
        raw = sys.stdin.read()
    prs = json.loads(raw)
    if not isinstance(prs, list):
        raise SystemExit("expected JSON array of pull requests")

    count = count_same_repo_duplicates(
        prs,
        branch_prefix=args.branch_prefix,
        repository_owner=args.owner,
        repository_name=args.repo,
    )
    print(count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
