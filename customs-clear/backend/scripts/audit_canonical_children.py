#!/usr/bin/env python3
"""Gate-2: полный offline-аудит `/children` legacy vs canonical."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.db import SessionLocal  # noqa: E402
from app.services.tree_engine.audit import audit_canonical_children  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="вывести только JSON")
    parser.add_argument("--max-examples", type=int, default=20)
    parser.add_argument("--prefix", default="", help="диагностический префикс; Gate-2 запускается без него")
    args = parser.parse_args()

    with SessionLocal() as db:
        report = audit_canonical_children(
            db,
            max_examples=args.max_examples,
            prefix=args.prefix,
        )
    payload = report.as_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            "Canonical /children audit: "
            f"scope={'full' if not report.prefix else 'prefix:' + report.prefix}, "
            f"commodities={report.commodity_count}, checked={report.checked}, "
            f"match={report.matches}, mismatch={report.mismatches}, "
            f"unresolved={report.unresolved}, duration_ms={report.duration_ms}"
        )
        for example in report.examples:
            print(
                f"- {example.code}: {example.reason} "
                f"legacy={example.legacy_count} canonical={example.canonical_count}"
            )

    if report.commodity_count == 0 and not args.json:
        print("BLOCKED: tnved_commodities is empty; Gate-2 requires a populated database.")
    if report.commodity_count == 0:
        return 2
    if not report.ok:
        return 1
    # Prefix полезен для smoke/диагностики, но не может дать зелёный Gate-2.
    return 0 if report.gate2_ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
