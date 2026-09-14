#!/usr/bin/env python3
"""Extract native text from retained source-bound legal PDFs, without OCR or DB."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ett_artifacts import LocalArtifactStore
from app.services.ett_legal_text import MAX_REPORT_BYTES, extract_legal_documents
from app.services.ett_pdf_evidence import extract_pdf_evidence


def _write_report(path: Path, report: dict) -> None:
    raw = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError("native text report exceeds its bound")
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".ett-legal-text-", delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
            os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def main(argv=None, *, extract=extract_pdf_evidence) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-report", type=Path, required=True)
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink() or not args.output.parent.is_dir():
            raise ValueError("report destination unavailable")
        if args.capture_report.is_symlink() or not args.capture_report.is_file():
            raise ValueError("capture report unavailable")
        with args.capture_report.open("rb") as stream:
            raw = stream.read(MAX_REPORT_BYTES + 1)
        report = extract_legal_documents(LocalArtifactStore(args.store_root), raw, extract=extract)
        _write_report(args.output, report)
    except Exception:
        print(json.dumps({"status": "ERROR", "reason": "legal_text_input_or_report_failed", "production_ready": False}))
        return 2
    print(json.dumps({key: report[key] for key in (
        "status", "declared_successful_pdfs", "extracted_pdfs", "failed_pdfs", "page_count",
        "word_count", "no_native_text_page_count", "stop_reason", "production_ready",
    )}))
    return 0 if report["all_declared_successful_pdfs_extracted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
