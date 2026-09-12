#!/usr/bin/env python3
"""Review-only inspection of invoice codes; AI rate/obligation application is closed.

--dry-run parses invoice codes. An explicit --database may inspect a bounded,
consistent SQLite snapshot without opening it through SQLite. Neither mode calls
an AI provider, creates placeholder commodities or changes active rates/NTM.
"""

from __future__ import annotations

import argparse
from contextlib import closing
import json
import hashlib
import os
import re
import sys
import sqlite3
import stat
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
    raw = df["suggested_hs_code"].astype(str).map(lambda x: re.sub(r"\D", "", x)[:10])
    return sorted({c for c in raw if len(c) == 10})


_MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024


def _file_identity(info) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_mode)


def _snapshot_identity(database: Path) -> tuple[int, ...]:
    """Reject changing paths and every sidecar, including dangling symlinks."""
    info = database.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("An explicit regular non-symlink SQLite snapshot is required")
    if any(os.path.lexists(str(database) + suffix) for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError("Live SQLite journal/sidecar detected; prepare a consistent isolated snapshot")
    return _file_identity(info)


def _snapshot_bytes(database: Path) -> bytes:
    """Bounded no-follow read; SQLite never opens the user's source path."""
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_NONBLOCK"):
        raise ValueError("Safe non-following snapshot reads are unavailable on this platform")
    before = _snapshot_identity(database)
    fd = os.open(database, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or _file_identity(opened) != before:
            raise ValueError("SQLite snapshot identity changed before opening")
        if opened.st_size > _MAX_SNAPSHOT_BYTES:
            raise ValueError("unsupported_snapshot_size: prepare a consistent hs_rates snapshot within 64 MiB")
        header = os.read(fd, 100)
        if len(header) != 100 or not header.startswith(b"SQLite format 3\x00"):
            raise ValueError("A valid existing SQLite snapshot is required")
        if header[18:20] != b"\x01\x01":
            raise ValueError("WAL or unsupported SQLite snapshot format; prepare a consistent rollback-format snapshot")
        chunks = [header]
        total = len(header)
        while True:
            chunk = os.read(fd, min(1024 * 1024, _MAX_SNAPSHOT_BYTES + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_SNAPSHOT_BYTES:
                raise ValueError("unsupported_snapshot_size: snapshot grew beyond 64 MiB")
            chunks.append(chunk)
        if total != opened.st_size or _file_identity(os.fstat(fd)) != before:
            raise ValueError("SQLite snapshot changed during bounded read")
        if _snapshot_identity(database) != before:
            raise ValueError("SQLite snapshot identity changed during bounded read")
        return b"".join(chunks)
    finally:
        os.close(fd)


def _inspect_rate_codes(codes: list[str], database: Path | None = None) -> dict:
    """Inspect a selected consistent snapshot without source DB or sidecar writes.

    WAL and live-journal snapshots are unsupported, not read with ignored WAL.
    Only verified bounded bytes are deserialized into an isolated memory database.
    """
    if database is None or not database.is_file() or database.is_symlink():
        raise ValueError("An explicit existing SQLite --database is required")
    content = _snapshot_bytes(database)
    with closing(sqlite3.connect(":memory:")) as db:
        if not hasattr(db, "deserialize"):
            raise ValueError("SQLite snapshot deserialization is unavailable on this platform")
        db.deserialize(content)
        db.execute("PRAGMA query_only=ON")
        missing = [code for code in codes if db.execute(
            "SELECT 1 FROM hs_rates WHERE hs_code = ? LIMIT 1", (code,)
        ).fetchone() is None]
    return {
        "missing_rate_codes": missing,
        "database_sha256": hashlib.sha256(content).hexdigest(),
        "database_size_bytes": len(content),
        "database_read_method": "bounded_in_memory_snapshot",
    }


def _missing_hs_rate_codes(codes: list[str], database: Path | None = None) -> list[str]:
    return _inspect_rate_codes(codes, database)["missing_rate_codes"]


def _blocked_result() -> dict:
    from app.services.official_payment_admission import blocked_payment_import

    result = blocked_payment_import(source="sync_invoice_codes", domain="import_duty")
    result["active_measures_written"] = False
    result["blockers"].append("ai_normative_review_required: inferred rates, codes and obligations are unreviewed")
    return result


def _ensure_commodity(db, hs10: str, description: str) -> bool:
    raise PermissionError(_blocked_result()["blockers"][-1])


def _gemini_payload(hs10: str) -> dict | None:
    raise PermissionError(_blocked_result()["blockers"][-1])


def _apply_payload(hs10: str, data: dict) -> None:
    raise PermissionError(_blocked_result()["blockers"][-1])


def main() -> None:
    parser = argparse.ArgumentParser(description="Review-only invoice code inspection; AI application is blocked")
    parser.add_argument("--excel", type=Path, default=None, help="processed_*.xlsx (default: most recent)")
    parser.add_argument("--dry-run", action="store_true", help="Inspect invoice codes without AI or active writes")
    parser.add_argument("--database", type=Path, help="Explicit consistent rollback-format SQLite snapshot, at most 64 MiB")
    args = parser.parse_args()

    if not args.dry_run:
        print(json.dumps(_blocked_result(), ensure_ascii=False))
        raise SystemExit(2)

    path = args.excel.resolve() if args.excel else _latest_processed_excel()
    if not path.is_file():
        print(f"Файл не найден: {path}", file=sys.stderr)
        raise SystemExit(1)
    codes = _codes_from_excel(path)
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
