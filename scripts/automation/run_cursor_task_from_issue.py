#!/usr/bin/env python3
"""Run Claude Code CLI agent for a GitHub issue labeled cursor-task (CI / local dry-run)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_CLAUDE_AGENT_BIN = "claude"


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


def load_existing_pr_context(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("existing PR context must be an object")
    return raw


def _render_existing_pr_context(ctx: dict[str, Any] | None) -> str:
    if not ctx:
        return ""

    number = ctx.get("number") or "unknown"
    url = ctx.get("url") or "(unknown)"
    head_branch = ctx.get("head_branch") or "(unknown)"
    comments = ctx.get("comments") or {}
    rendered = json.dumps(comments, ensure_ascii=False, indent=2, sort_keys=True)
    if len(rendered) > 20000:
        rendered = rendered[:20000] + "\n... [truncated]"

    return f"""
## Existing PR update context

This is an update run for an already open Cursor Task PR.

- PR: #{number}
- URL: {url}
- Head branch: `{head_branch}`

Use the review and conversation context below to address requested changes.
Update the current working tree only. Do not create a new branch or PR.

```json
{rendered}
```
"""


def build_agent_prompt(
    ctx: dict[str, Any], repo_root: Path, existing_pr_ctx: dict[str, Any] | None = None
) -> str:
    agents = repo_root / "AGENTS.md"
    focus = repo_root / "docs" / "ai-workflow" / "CURRENT_PROJECT_FOCUS.md"
    agents_hint = f"Read `{agents.relative_to(repo_root)}`" if agents.is_file() else "Read AGENTS.md"
    focus_hint = (
        f"Read `{focus.relative_to(repo_root)}`"
        if focus.is_file()
        else "Read docs/ai-workflow/CURRENT_PROJECT_FOCUS.md"
    )
    existing_pr_block = _render_existing_pr_context(existing_pr_ctx)
    return f"""You are implementing a Cursor Task from GitHub issue #{ctx["number"]}.

## Issue
Title: {ctx["title"]}
URL: {ctx.get("html_url") or "(see CI logs)"}

## Issue body
{ctx["body"]}
{existing_pr_block}
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
`docs/ai-workflow/.claude-agent-blocked-issue-{ctx["number"]}.md` explaining why you stopped.
Do not guess strategic direction.
"""


def run_agent(prompt: str) -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("::error::ANTHROPIC_API_KEY is not set", file=sys.stderr)
        sys.exit(1)

    agent_bin = os.environ.get("CLAUDE_AGENT_BIN", DEFAULT_CLAUDE_AGENT_BIN)
    cmd = [agent_bin, "--print", "--output-format", "text", prompt]
    print(f"Running: {agent_bin} --print (prompt length={len(prompt)} chars)")
    subprocess.run(cmd, check=True)


def main() -> int:
    context_path = Path(os.environ.get("ISSUE_CONTEXT_PATH", "issue-context.json"))
    if not context_path.is_file():
        print(f"::error::Missing issue context file: {context_path}", file=sys.stderr)
        return 1

    existing_pr_path_raw = os.environ.get("EXISTING_PR_CONTEXT_PATH", "").strip()
    existing_pr_path = Path(existing_pr_path_raw) if existing_pr_path_raw else None

    ctx = load_issue_context(context_path)
    existing_pr_ctx = load_existing_pr_context(existing_pr_path)
    repo_root = _repo_root()
    os.chdir(repo_root)
    prompt = build_agent_prompt(ctx, repo_root, existing_pr_ctx)

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
