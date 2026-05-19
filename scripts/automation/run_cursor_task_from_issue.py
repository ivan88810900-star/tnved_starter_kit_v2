#!/usr/bin/env python3
"""Run Cursor CLI agent for a GitHub issue labeled cursor-task (CI / local dry-run)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_issue_context(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("issue-context.json must be an object")
    number = int(raw.get("number") or 0)
    title = str(raw.get("title") or "").strip()
    body = str(raw.get("body") or "")
    if number <= 0:
        raise ValueError("issue context missing valid issue number")
    return {
        "number": number,
        "title": title,
        "body": body,
        "html_url": str(raw.get("html_url") or "").strip(),
    }


def build_agent_prompt(ctx: dict[str, Any], repo_root: Path) -> str:
    agents = repo_root / "AGENTS.md"
    focus = repo_root / "docs" / "ai-workflow" / "CURRENT_PROJECT_FOCUS.md"
    agents_hint = f"Read `{agents.relative_to(repo_root)}`" if agents.is_file() else "Read AGENTS.md"
    focus_hint = (
        f"Read `{focus.relative_to(repo_root)}`"
        if focus.is_file()
        else "Read docs/ai-workflow/CURRENT_PROJECT_FOCUS.md"
    )
    return f"""You are implementing a Cursor Task from GitHub issue #{ctx["number"]}.

## Issue
Title: {ctx["title"]}
URL: {ctx.get("html_url") or "(see CI logs)"}

## Issue body
{ctx["body"]}

## Mandatory context (read before coding)
- {agents_hint}
- {focus_hint}

## Repository rules
- Follow acceptance criteria and tests listed in the issue body.
- Primary product backend: `customs-clear/backend/` (not legacy root `backend/`).
- Do not enable feature flags by default.
- Do not change broker enforcement / missing-check unless the issue explicitly requires it.
- Keep changes focused; no unrelated refactors.

## CI constraints (important)
- Do NOT create branches, push, or open pull requests — GitHub Actions handles git/PR after you finish.
- Apply file changes in the current working tree only.
- Run relevant tests/commands from the issue when specified (e.g. pytest).

## If blocked
If legal/product interpretation is ambiguous, create a short draft at
`docs/ai-workflow/.cursor-agent-blocked-issue-{ctx["number"]}.md` explaining why you stopped.
Do not guess strategic direction.
"""


def run_agent(prompt: str) -> None:
    api_key = os.environ.get("CURSOR_API_KEY", "").strip()
    if not api_key:
        print("::error::CURSOR_API_KEY is not set", file=sys.stderr)
        sys.exit(1)

    agent_bin = os.environ.get("CURSOR_AGENT_BIN", "agent")
    cmd = [agent_bin, "-p", "--force", "--output-format", "text", prompt]
    print(f"Running: {agent_bin} -p --force (prompt length={len(prompt)} chars)")
    subprocess.run(cmd, check=True)


def main() -> int:
    context_path = Path(os.environ.get("ISSUE_CONTEXT_PATH", "issue-context.json"))
    if not context_path.is_file():
        print(f"::error::Missing issue context file: {context_path}", file=sys.stderr)
        return 1

    ctx = load_issue_context(context_path)
    repo_root = _repo_root()
    os.chdir(repo_root)
    prompt = build_agent_prompt(ctx, repo_root)

    if os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes"):
        print("=== DRY_RUN: prompt preview (first 2000 chars) ===")
        print(prompt[:2000])
        if len(prompt) > 2000:
            print(f"... [{len(prompt) - 2000} more chars]")
        return 0

    run_agent(prompt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
