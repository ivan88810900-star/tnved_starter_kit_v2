#!/usr/bin/env python3
"""Capture two observed tariff-relief/GSP pages and their directly linked PDFs."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ett_artifacts import LocalArtifactStore
from app.services.ett_tariff_relief_capture import MAX_REPORT_BYTES, capture_tariff_relief, selected_details
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


def main(argv=None, *, fetch=fetch_official) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--detail-url", action="append", default=[],
                        help="An explicitly observed canonical official detail URL; no discovery or URL synthesis")
    args = parser.parse_args(argv)
    try:
        details = selected_details(tuple(args.detail_url))
        if os.path.lexists(args.output) or not args.output.parent.is_dir():
            raise ValueError("output_unavailable")
        report = capture_tariff_relief(LocalArtifactStore(args.store_root), detail_urls=details, fetch=fetch)
        raw = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        if len(raw) > MAX_REPORT_BYTES:
            raise ValueError("report_limit")
        _publish_exclusive(args.output, raw)
    except Exception:
        print(json.dumps({"status": "error", "reason": "capture_setup_or_report_failed", "production_ready": False}))
        return 2
    print(json.dumps({"status": "captured" if report["capture_complete"] else "incomplete",
                      "captured_sources": report["captured_sources"], "failed_sources": report["failed_sources"],
                      "source_inventory_complete": False, "legal_ready": False, "production_ready": False}))
    return 0 if report["capture_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
