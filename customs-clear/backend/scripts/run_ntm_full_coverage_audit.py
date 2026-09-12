#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))
os.environ.setdefault("CUSTOMSCLEAR_READ_ONLY", "1")

from app.services.ntm_full_coverage_audit import build_ntm_full_coverage_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail-closed NTM audit of the pinned 21/96/17809 TN VED reference corpus "
            "and 100% described active ETT code scope"
        ),
    )
    parser.add_argument("--limit", type=int, help="Diagnostic sample; never counts as full")
    parser.add_argument(
        "--database",
        type=Path,
        help="Explicit SQLite catalog opened read-only",
    )
    parser.add_argument("--catalog-json", type=Path)
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Allow diagnostic success without the 21/96/17809 full-catalog gate",
    )
    parser.add_argument(
        "--require-code-catalog",
        action="store_true",
        help="In partial mode, require at least 10k ETT/DB codes",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    kwargs = {
        "require_code_catalog": args.require_code_catalog,
        "require_full_catalog": not args.allow_partial,
    }
    if args.database:
        kwargs["database_path"] = args.database
    if args.catalog_json:
        kwargs["catalog_path"] = args.catalog_json
    report = build_ntm_full_coverage_report(args.limit, **kwargs)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    if report["ok"]:
        return 0
    if report["full_catalog_required"] and not report["catalog_complete"]:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
