#!/usr/bin/env python3
"""Validate GitHub issue payload for cursor-task automation."""

from __future__ import annotations

from typing import Any


def issue_label_names(issue: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for label in issue.get("labels") or []:
        if isinstance(label, str):
            names.append(label)
        elif isinstance(label, dict):
            name = str(label.get("name") or "").strip()
            if name:
                names.append(name)
    return names


def validate_cursor_task_issue(issue: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    if issue.get("pull_request"):
        errors.append("target is a pull request, not an ordinary issue")

    if str(issue.get("state") or "").lower() == "closed":
        errors.append(f"issue #{issue.get('number')} is closed")

    if "cursor-task" not in issue_label_names(issue):
        errors.append("issue does not have label cursor-task")

    number = issue.get("number")
    if not isinstance(number, int) or number <= 0:
        errors.append("issue number is missing or invalid")

    return errors


def issue_context_from_payload(issue: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": int(issue["number"]),
        "title": str(issue.get("title") or "").strip(),
        "body": str(issue.get("body") or ""),
        "html_url": str(issue.get("html_url") or "").strip(),
    }


def branch_name_from_context(ctx: dict[str, Any]) -> str:
    slug = (
        (ctx.get("title") or "task")
        .lower()
        .replace(" ", "-")
    )
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")[:40] or "task"
    return f"cursor/issue-{ctx['number']}-{slug}"
