#!/usr/bin/env python3
"""Генерация матрицы покрытия РОП по 97 главам ТН ВЭД (#144)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from app.db import SessionLocal  # noqa: E402
from app.services.rop_coverage_audit import build_rop_chapter_coverage, coverage_summary  # noqa: E402

OUTPUT = _ROOT / "data" / "rop_chapter_coverage.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--output", type=Path, default=OUTPUT)
    args = ap.parse_args()

    session = SessionLocal()
    try:
        matrix = build_rop_chapter_coverage(session, calendar_year=args.year)
    finally:
        session.close()

    doc = {
        "calendar_year": args.year,
        "summary": coverage_summary(matrix),
        "chapters": matrix,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(doc["summary"], ensure_ascii=False, indent=2))
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
