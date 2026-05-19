#!/usr/bin/env python3
"""Derive branch name cursor/issue-<n>-<slug> from issue-context.json."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def slugify(title: str, *, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return (slug[:max_len] or "task").strip("-")


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "issue-context.json")
    ctx = json.loads(path.read_text(encoding="utf-8"))
    number = int(ctx["number"])
    branch = f"cursor/issue-{number}-{slugify(str(ctx.get('title') or ''))}"
    print(branch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
