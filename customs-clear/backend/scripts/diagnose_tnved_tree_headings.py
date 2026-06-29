#!/usr/bin/env python3
"""Диагностика дерева ТН ВЭД: проблемные heading-узлы (in-memory, один проход)."""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.api.tnved_catalog import (  # noqa: E402
    _build_tree,
    _collect_chapter_notes,
    _digits,
    _exclude_obsolete_reserved,
    _node_level,
)
from app.db import SessionLocal
from app.models.tnved import Commodity


def _count_db_descendants(codes: set[str], heading4: str) -> int:
    pad = heading4 + "000000"
    return sum(1 for c in codes if c.startswith(heading4) and c != pad)


def _leaf_self_refs_in_tree(flat: list[dict]) -> list[str]:
    issues: list[str] = []

    def walk(node: dict) -> None:
        code10 = _digits(node.get("code") or "").zfill(10)[:10]
        children = node.get("children") or []
        if _node_level(code10) == 10 and len(children) == 1:
            ch = children[0]
            if _digits(ch.get("code") or "") == code10 and ch.get("is_leaf"):
                issues.append(f"{code10}: tree node has synthesized self-child")
        for ch in children:
            walk(ch)

    for n in flat:
        walk(n)
    return issues


def main() -> int:
    db = SessionLocal()
    try:
        rows = (
            _exclude_obsolete_reserved(db.query(Commodity).order_by(Commodity.code.asc()))
            .limit(2_000_000)
            .all()
        )
        all_codes = {_digits(r.code or "").zfill(10)[:10] for r in rows if r.code}
        pad_headings = {c[:4] for c in all_codes if c.endswith("000000")}

        flat = _build_tree(rows, _collect_chapter_notes(db))
        by4 = {n["code"]: n for n in flat}

        issues: list[str] = []
        for heading4 in sorted(pad_headings):
            node = by4.get(heading4)
            if not node:
                continue
            db_count = _count_db_descendants(all_codes, heading4)
            if db_count == 0:
                continue
            children = node.get("children") or []
            if len(children) == 1 and children[0].get("is_codeless") and db_count > 1:
                issues.append(
                    f"{heading4}: single codeless child, db has {db_count} descendants "
                    f"(child={children[0].get('code')!r})"
                )
            if len(children) == 0 and db_count > 0:
                issues.append(f"{heading4}: no tree children, db has {db_count} descendants")

        issues.extend(_leaf_self_refs_in_tree(flat))

        print(f"Checked {len(pad_headings)} pad headings")
        print(f"Issues found: {len(issues)}")
        for line in issues[:50]:
            print(f"  - {line}")
        if len(issues) > 50:
            print(f"  ... +{len(issues) - 50} more")
        return 1 if issues else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
