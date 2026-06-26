#!/usr/bin/env python3
"""Validate staged changes before cursor-task automation commit."""

from __future__ import annotations

import fnmatch
import os
import subprocess
import sys
from pathlib import PurePosixPath

DENIED_BASENAMES = frozenset(
    {
        "issue-context.json",
        "open-prs.json",
        "pr-body.md",
    }
)

SECRET_MARKERS = (
    "CURSOR_API_KEY=",
    "OPENAI_API_KEY=",
    "GEMINI_API_KEY=",
    "GOOGLE_API_KEY=",
    "ANTHROPIC_API_KEY=",
    "SECRET_KEY=",
    "PASSWORD=",
    "TOKEN=",
)

LITERAL_SECRET_ENV_VARS = ("CURSOR_API_KEY",)


def _git_output(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True)


def path_is_denied(rel_path: str) -> str | None:
    path = rel_path.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    if not path:
        return None

    parts = PurePosixPath(path).parts
    name = parts[-1] if parts else path

    if name == ".env" or name.startswith(".env."):
        return "env file"
    if fnmatch.fnmatch(name, "*.db") or fnmatch.fnmatch(name, "*.sqlite"):
        return "database file"
    if fnmatch.fnmatch(name, "*.log"):
        return "log file"
    if "logs" in parts:
        return "logs path"
    if "tmp" in parts:
        return "tmp path"
    if name in DENIED_BASENAMES:
        return "workflow artifact"
    if path == ".cursor" or path.startswith(".cursor/"):
        return "cursor runtime path"
    return None


def diff_has_secret_markers(diff: str, literal_values: list[str]) -> list[str]:
    errors: list[str] = []
    upper = diff.upper()
    for marker in SECRET_MARKERS:
        if marker in upper:
            errors.append(f"staged diff contains secret marker {marker!r}")
    for value in literal_values:
        if len(value) >= 8 and value in diff:
            errors.append("staged diff contains literal secret value")
    return errors


def collect_literal_secret_values() -> list[str]:
    values: list[str] = []
    for name in LITERAL_SECRET_ENV_VARS:
        value = os.environ.get(name, "").strip()
        if value:
            values.append(value)
    return values


def validate_staged() -> list[str]:
    errors: list[str] = []

    try:
        names_raw = _git_output("diff", "--cached", "--name-only")
    except subprocess.CalledProcessError as exc:
        return [f"git diff --cached --name-only failed: {exc}"]

    for rel in names_raw.splitlines():
        rel = rel.strip()
        if not rel:
            continue
        reason = path_is_denied(rel)
        if reason:
            errors.append(f"denied staged path {rel!r}: {reason}")

    try:
        diff = _git_output("diff", "--cached", "--")
    except subprocess.CalledProcessError as exc:
        errors.append(f"git diff --cached failed: {exc}")
        return errors

    errors.extend(diff_has_secret_markers(diff, collect_literal_secret_values()))
    return errors


def main() -> int:
    errors = validate_staged()
    if not errors:
        print("Staged changes passed cursor-task validation.")
        return 0

    for err in errors:
        print(f"::error::{err}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
