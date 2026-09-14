#!/usr/bin/env python3
"""Capture a revalidated observed legal-document plan, without DB or approval."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ett_artifacts import LocalArtifactStore
from app.services.ett_legal_capture import MAX_REPORT_BYTES, capture_legal_documents
from app.services.ett_transport import fetch_official


def _write_report(path: Path, report: dict) -> None:
    raw = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError("capture report exceeds its bound")
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".ett-legal-capture-", delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
            os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def main(argv=None, *, fetch=fetch_official) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discovery-report", type=Path, required=True)
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink() or not args.output.parent.is_dir():
            raise ValueError("report destination unavailable")
        if args.discovery_report.is_symlink() or not args.discovery_report.is_file():
            raise ValueError("discovery report unavailable")
        with args.discovery_report.open("rb") as stream:
            raw = stream.read(MAX_REPORT_BYTES + 1)
        report = capture_legal_documents(LocalArtifactStore(args.store_root), raw, fetch=fetch)
        _write_report(args.output, report)
    except Exception:
        print(json.dumps({"status": "ERROR", "reason": "legal_capture_input_or_report_failed", "production_ready": False}))
        return 2
    print(json.dumps({key: report[key] for key in (
        "status", "planned_document_pages", "captured_document_pages", "captured_unique_pdfs",
        "failed_operations", "stop_reason", "production_ready",
    )}))
    return 0 if report["supported_capture_plan_completed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
