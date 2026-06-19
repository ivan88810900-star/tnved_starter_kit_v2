#!/usr/bin/env python3
"""Unified data refresh: CBR rates, excise, anti-dumping freshness check.

Usage:
    cd customs-clear/backend
    python3 -m scripts.data_refresh [--check-only] [--json]
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))


async def main() -> int:
    check_only = "--check-only" in sys.argv
    json_output = "--json" in sys.argv

    from app.services.data_refresh_service import check_data_freshness, run_full_data_refresh

    if check_only:
        report = check_data_freshness()
        if json_output:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            _print_freshness(report)
        return 0 if report["all_fresh"] else 1

    result = await run_full_data_refresh(dry_run=True)

    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_refresh_result(result)

    return 0 if result["status"] == "ok" else 1


def _print_freshness(report: dict) -> None:
    print(f"Data Freshness Report — {report['checked_at']}")
    print(f"Stale threshold: {report['stale_threshold_days']} days")
    print()

    cur = report["currency"]
    stale_mark = "STALE" if cur["is_stale"] else "OK"
    age = cur.get("age_hours", "?")
    print(f"  CBRF currency rates: [{stale_mark}] age={age}h, currencies={cur.get('currencies', 0)}")

    for d in report["domains"]:
        stale_mark = "STALE" if d["is_stale"] else "OK"
        age = d.get("age_days", "?")
        rev = d.get("revision_date", "missing")
        print(f"  {d['domain']}: [{stale_mark}] rev={rev}, age={age} days")

    print()
    if report["all_fresh"]:
        print("All data sources are fresh.")
    else:
        print(f"WARNING: {report['stale_count']} stale domain(s) detected.")


def _print_refresh_result(result: dict) -> None:
    print(f"Data Refresh Result — status={result['status']}")
    print()

    for r in result["results"]:
        status = r.get("status", "?")
        domain = r.get("domain", "?")
        extra = ""
        if r.get("error"):
            extra = f" error={r['error']}"
        elif r.get("source"):
            extra = f" source={r['source']} date={r.get('date', '')}"
        elif r.get("action"):
            extra = f" action={r['action']} rows={r.get('rows_total', 0)}"
        print(f"  {domain}: [{status}]{extra}")

    if result.get("pending_apply"):
        print()
        print(f"Pending apply: {', '.join(result['pending_apply'])}")
        print("  Use the dedicated API endpoints to apply these changes.")

    print()
    freshness = result.get("freshness", {})
    stale = freshness.get("stale_count", 0)
    if stale:
        print(f"WARNING: {stale} stale domain(s) in freshness check.")
    else:
        print("All data sources are fresh.")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
