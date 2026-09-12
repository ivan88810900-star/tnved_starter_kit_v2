#!/usr/bin/env python3
"""Resume an identical discovery capture using verified original HTTP responses."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ett_artifacts import LocalArtifactStore
from app.services.ett_legal_resume import MAX_REPORT_BYTES, resume_legal_documents
from app.services.ett_transport import fetch_official
from scripts.capture_ett_legal_documents import _write_report


def _read(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("source report unavailable")
    with path.open("rb") as stream:
        return stream.read(MAX_REPORT_BYTES + 1)


def main(argv=None, *, fetch=fetch_official) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-capture-report", type=Path, required=True)
    parser.add_argument("--discovery-report", type=Path, required=True)
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink() or not args.output.parent.is_dir():
            raise ValueError("report destination unavailable")
        result = resume_legal_documents(LocalArtifactStore(args.store_root), _read(args.source_capture_report),
                                        _read(args.discovery_report), fetch=fetch)
        _write_report(args.output, result)
    except Exception:
        print(json.dumps({"status": "ERROR", "reason": "legal_resume_input_or_report_failed", "production_ready": False}))
        return 2
    print(json.dumps({"status": result["status"], "captured_unique_pdfs": result["captured_unique_pdfs"],
                      "failed_operations": result["failed_operations"], "stop_reason": result["stop_reason"],
                      "reused_html_responses": result["resume_evidence"]["reused_html_responses"],
                      "reused_pdf_responses": result["resume_evidence"]["reused_pdf_responses"],
                      "new_request_count": result["resume_evidence"]["new_request_count"], "production_ready": False}))
    return 0 if result["supported_capture_plan_completed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
