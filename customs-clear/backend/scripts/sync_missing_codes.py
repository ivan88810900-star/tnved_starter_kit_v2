#!/usr/bin/env python3
"""Inspect missing invoice codes without applying AI-estimated rates.

--dry-run parses invoice codes; --database selects a bounded consistent SQLite
snapshot. No implicit application DB access or model-generated rate write exists.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env")
load_dotenv()


def _latest_processed_excel() -> Path:
    d = _ROOT / "data" / "processed_invoices"
    if not d.is_dir():
        raise FileNotFoundError(f"Нет каталога {d}")
    files = sorted(d.glob("processed_*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"В {d} нет processed_*.xlsx")
    return files[0].resolve()


def _codes_from_excel(path: Path) -> list[str]:
    import pandas as pd

    df = pd.read_excel(path)
    if "suggested_hs_code" not in df.columns:
        raise ValueError(f"В {path} нет колонки suggested_hs_code")
    first = df.columns[0]
    mask = df[first].astype(str).str.strip().str.upper() != "ИТОГО"
    df = df.loc[mask]
    raw = (
        df["suggested_hs_code"]
        .astype(str)
        .map(lambda x: re.sub(r"\D", "", x)[:10])
    )
    return sorted({c for c in raw if len(c) == 10})


def _missing_in_hs_rates(codes: list[str], database: Path | None = None) -> list[str]:
    from scripts.sync_invoice_codes import _missing_hs_rate_codes

    return _missing_hs_rate_codes(codes, database)


def _blocked_result() -> dict:
    from scripts.sync_invoice_codes import _blocked_result as blocked_invoice_result

    result = blocked_invoice_result()
    result["source"] = "sync_missing_codes"
    return result


def _gemini_rate_row(hs10: str) -> dict[str, object] | None:
    raise PermissionError(_blocked_result()["blockers"][-1])


def main() -> None:
    parser = argparse.ArgumentParser(description="Review-only missing invoice code inspection; AI application is blocked")
    parser.add_argument("--excel", type=Path, default=None, help="processed_*.xlsx (default: most recent)")
    parser.add_argument("--dry-run", action="store_true", help="Inspect invoice codes without AI or active writes")
    parser.add_argument("--database", type=Path, help="Explicit consistent rollback-format SQLite snapshot, at most 64 MiB")
    parser.add_argument("--print-tks94-command", action="store_true", help="Show the source-review limitation and exit")
    args = parser.parse_args()

    if args.print_tks94_command:
        print("Historical crawling produces unreviewed extraction evidence only. "
              "A commercial mirror cannot approve official rates or obligations.")
        return
    if not args.dry_run:
        print(json.dumps(_blocked_result(), ensure_ascii=False))
        raise SystemExit(2)

    path = args.excel.resolve() if args.excel else _latest_processed_excel()
    if not path.is_file():
        print(f"Файл не найден: {path}", file=sys.stderr)
        raise SystemExit(1)
    codes = _codes_from_excel(path)
    from scripts.sync_invoice_codes import _inspect_rate_codes
    inspection = _inspect_rate_codes(codes, args.database) if args.database else {
        "missing_rate_codes": None, "database_sha256": None, "database_size_bytes": None,
        "database_read_method": None,
    }
    print(json.dumps({
        **_blocked_result(), "dry_run": True, "invoice_codes": codes,
        **inspection, "database_checked": args.database is not None,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
