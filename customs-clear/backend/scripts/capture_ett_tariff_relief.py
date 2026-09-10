#!/usr/bin/env python3
"""Capture two observed tariff-relief/GSP pages and their directly linked PDFs."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ett_artifacts import LocalArtifactStore
from app.services.ett_tariff_relief_capture import (
    MAX_OBSERVED_BASELINE_BYTES, MAX_REPORT_BYTES, capture_tariff_relief,
    load_observed_baseline, reconcile_tariff_relief, selected_details,
)
from app.services.ett_transport import fetch_official


def _publish_exclusive(path: Path, raw: bytes) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=".ett-relief-", delete=False) as target:
            temporary = Path(target.name)
            target.write(raw)
            target.flush()
            os.fsync(target.fileno())
        os.link(temporary, path, follow_symlinks=False)
    finally:
        if temporary is not None:
            temporary.unlink()


def _read_observed_baseline(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= MAX_OBSERVED_BASELINE_BYTES:
            raise ValueError("invalid_observation_file")
        with os.fdopen(descriptor, "rb") as source:
            descriptor = None
            raw = source.read(MAX_OBSERVED_BASELINE_BYTES + 1)
    finally:
        if descriptor is not None:
            os.close(descriptor)
    load_observed_baseline(raw)
    return raw


def main(argv=None, *, fetch=fetch_official) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--detail-url", action="append", default=[],
                        help="An explicitly observed canonical official detail URL; no discovery or URL synthesis")
    parser.add_argument("--observed-baseline", type=Path,
                        help="Compare with an existing unapproved observation file; never create or accept a baseline")
    args = parser.parse_args(argv)
    try:
        details = selected_details(tuple(args.detail_url))
        if os.path.lexists(args.output) or not args.output.parent.is_dir():
            raise ValueError("output_unavailable")
        observed = _read_observed_baseline(args.observed_baseline) if args.observed_baseline else None
        store = LocalArtifactStore(args.store_root)
        report = capture_tariff_relief(store, detail_urls=details, fetch=fetch)
        if args.observed_baseline:
            report["reconciliation"] = reconcile_tariff_relief(report, store, observed_baseline=observed)
        raw = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        if len(raw) > MAX_REPORT_BYTES:
            raise ValueError("report_limit")
        _publish_exclusive(args.output, raw)
    except Exception:
        print(json.dumps({"status": "error", "reason": "capture_setup_or_report_failed", "production_ready": False}))
        return 2
    reconciliation = report.get("reconciliation", {})
    status = "incomplete" if not report["capture_complete"] else (
        "observed_unreviewed" if reconciliation.get("operational_ok") is True else
        "review_required" if args.observed_baseline else "captured")
    print(json.dumps({"status": status,
                      "captured_sources": report["captured_sources"], "failed_sources": report["failed_sources"],
                      "reconciliation_status": reconciliation.get("status"),
                      "operational_ok": reconciliation.get("operational_ok"),
                      "source_inventory_complete": False, "legal_ready": False, "production_ready": False}))
    if not report["capture_complete"] or report.get("reconciliation", {}).get("status") == "evidence_invalid":
        return 2
    return 3 if args.observed_baseline and reconciliation.get("operational_ok") is not True else 0


if __name__ == "__main__":
    raise SystemExit(main())
