#!/usr/bin/env python3
"""Мониторинг прогресса backfill реестров ФСА (opendata)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.opendata_status import build_backfill_progress_report  # noqa: E402


def main() -> int:
    report = build_backfill_progress_report()
    cert = report.get("fsa_certificates") or {}
    decl = report.get("fsa_declarations") or {}
    trois = report.get("trois") or {}

    print("=== Opendata backfill progress ===")
    print(f"TROIS records:     {trois.get('records', 0):>10,}  as_of={trois.get('as_of', '—')}")
    print(
        f"FSA certificates:  {cert.get('records', 0):>10,}  "
        f"months {cert.get('months_imported', 0)}/{cert.get('months_total', '?')}  "
        f"last={cert.get('last_month', '—')}  "
        f"{'RUNNING' if cert.get('backfill_in_progress') else 'idle'}  "
        f"eta={cert.get('eta') or '—'}"
    )
    print(
        f"FSA declarations:  {decl.get('records', 0):>10,}  "
        f"months {decl.get('months_imported', 0)}/{decl.get('months_total', '?')}  "
        f"last={decl.get('last_month', '—')}  "
        f"{'RUNNING' if decl.get('backfill_in_progress') else 'idle'}  "
        f"eta={decl.get('eta') or '—'}"
    )
    if report.get("backfill_process_running"):
        print("\nBackfill PID active (see logs/fsa_backfill.pid)")
    if report.get("log_tail"):
        print("\n--- log tail ---")
        print(report["log_tail"])
    if "--json" in sys.argv:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
