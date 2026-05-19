#!/usr/bin/env python3
"""Render PR body for cursor-task automation."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "issue-context.json")
    tests = sys.argv[2] if len(sys.argv) > 2 else "(see issue acceptance criteria)"
    ctx = json.loads(path.read_text(encoding="utf-8"))
    n = ctx["number"]
    url = ctx.get("html_url") or f"https://github.com/issues/{n}"
    body = f"""## Summary

Automated implementation for Cursor Task issue #{n} via GitHub Actions + Cursor CLI.

Source issue: {url}

## What changed

See commit diff on this branch. Implementation follows issue acceptance criteria and `AGENTS.md`.

## Tests run

{tests}

## Risks / limitations

- Automated agent run; human review (Codex + Ivan) required before merge.
- Verify feature flags remain default OFF unless issue explicitly enabled them.
- Confirm no broker / missing-check semantic changes unless requested in the issue.

## Follow-up

- Codex review per `docs/ai-workflow/CODEX_REVIEW_CHECKLIST.md`
- Ivan merge when `ready-for-ivan-review`

Relates to #{n}
"""
    print(body.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
