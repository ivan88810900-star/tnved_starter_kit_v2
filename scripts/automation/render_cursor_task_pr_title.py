#!/usr/bin/env python3
"""Render PR title for cursor-task automation from issue-context.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def pr_title_from_context(ctx: dict) -> str:
    number = int(ctx["number"])
    title = str(ctx.get("title") or "").strip()
    return f"Cursor task: #{number} {title}".strip()


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "issue-context.json")
    ctx = json.loads(path.read_text(encoding="utf-8"))
    print(pr_title_from_context(ctx))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
