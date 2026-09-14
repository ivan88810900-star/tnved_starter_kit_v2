#!/usr/bin/env python3
"""Capture and inspect two observed official ZIP attachments, without extraction.

This separate archive report is not a PDF receipt or proof of legal identity,
dates, complete inventory, approved text or production readiness. Original ZIP
bytes are retained even if inspection fails. Members remain inert candidates.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ett_artifacts import LocalArtifactStore
from app.services.ett_legal_archives import capture_legal_archives

MAX_REPORT_BYTES = 8 * 1024 * 1024


def _write_report(path: Path, report: dict) -> None:
    payload = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if len(payload) > MAX_REPORT_BYTES:
        raise ValueError("archive report exceeds its bound")
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".ett-archive-probe-", delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
            os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def main(argv=None, *, fetch=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink() or not args.output.parent.is_dir():
            raise ValueError("archive report destination unavailable")
        report = capture_legal_archives(LocalArtifactStore(args.store_root), fetch=fetch)
        _write_report(args.output, report)
    except Exception:
        print(json.dumps({"status": "ERROR", "reason": "archive_setup_or_report_failed", "production_ready": False}))
        return 2
    print(json.dumps({"status": "inspected" if report["all_selected_archives_inspected"] else "incomplete",
                      "attempted_sources": report["attempted_sources"], "inspected_sources": report["inspected_sources"],
                      "failed_sources": report["failed_sources"], "production_ready": False}))
    return 0 if report["all_selected_archives_inspected"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
