"""Issue #51: print coverage table and dry-run backfill plan for 6 official payment domains.

Usage:
    python3 -m app.scripts.coverage_backfill_plan
    python3 -m app.scripts.coverage_backfill_plan --json
"""

from __future__ import annotations

import argparse
import json
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Official payment coverage table and backfill plan.")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Output full JSON report")
    args = parser.parse_args()

    from app.services.official_payment_coverage_audit import (
        build_backfill_plan,
        build_coverage_table,
    )

    table = build_coverage_table()
    plan = build_backfill_plan()

    if args.as_json:
        report = {
            "coverage_table": table,
            "backfill_plan": plan,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print("=== Official Payment Coverage Table ===\n")
    print(table["text_table"])
    print(f"\nGenerated at: {table['generated_at']}  |  db_mutated: {table['db_mutated']}")

    print("\n=== Backfill Plan (dry-run) ===\n")
    print(
        f"Domains: {plan['total_domains']}  |  "
        f"Needing action: {plan['domains_needing_action']}"
    )
    for item in plan["plan"]:
        action = item["action"]
        marker = "  " if action == "none" else "→ "
        notes_str = "; ".join(item["notes"]) if item["notes"] else ""
        line = f"{marker}[{item['domain_key']}] {action}"
        if notes_str:
            line += f"  # {notes_str}"
        print(line)

    if plan["notes"]:
        print()
        for note in plan["notes"]:
            print(f"  * {note}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
