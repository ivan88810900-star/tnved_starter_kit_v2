#!/usr/bin/env python3
"""Replay retained ETT legal discovery and save an observed capture plan."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ett_artifacts import LocalArtifactStore
from app.services.ett_discovery_audit import MAX_REPORT_BYTES, audit_legal_discovery


def _read(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_REPORT_BYTES:
        raise ValueError("input must be a bounded regular report")
    with path.open("rb") as stream:
        raw = stream.read(MAX_REPORT_BYTES + 1)
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError("input exceeds report bound")
    return raw


def _write_report(path: Path, report: dict) -> None:
    raw = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError("discovery report exceeds bound")
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".ett-discovery-", delete=False) as target:
        temporary = Path(target.name)
        try:
            target.write(raw)
            target.flush()
            os.fsync(target.fileno())
            os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("index", "inventory", "notes", "pagination", "store-root", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--supplementary", type=Path, action="append", default=[])
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink() or not args.output.parent.is_dir():
            raise ValueError("report destination unavailable")
        if len(args.supplementary) > 4:
            raise ValueError("supplementary report bound exceeded")
        store = LocalArtifactStore(args.store_root, create=False)
        originals = tuple(_read(path) for path in (args.index, args.inventory, args.notes, args.pagination))
        supplemental = tuple(_read(path) for path in args.supplementary)
        report = audit_legal_discovery(*originals, store.read, supplementary_report_raws=supplemental)
        # Preserve exact report bytes, not a reserialization, so a capture
        # consumer can independently reproduce every SHA-bound audit input.
        writable = LocalArtifactStore(args.store_root)
        for raw in (*originals, *supplemental):
            writable.put(raw)
        _write_report(args.output, report)
    except Exception:
        print(json.dumps({"status": "ERROR", "reason": "discovery_replay_or_report_failed", "production_ready": False}))
        return 2
    print(json.dumps({"status": "discovery_replayed", "capture_target_count": report["capture_target_count"],
                      "matched_amendment_count": report["matched_amendment_count"],
                      "matched_notes_identity_count": report["matched_notes_identity_count"],
                      "legal_inventory_complete": False, "production_ready": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
