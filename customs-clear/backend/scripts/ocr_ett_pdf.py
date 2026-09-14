#!/usr/bin/env python3
"""Explicit review-only OCR for one hash-verified PDF; no API/runtime rollout."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.ett_artifacts import LocalArtifactStore
from app.services.ett_ocr_candidates import ocr_pdf_candidate


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--artifact-id", required=True)
    parser.add_argument("--model-directory", type=Path, required=True)
    parser.add_argument("--output-store-root", type=Path, required=True)
    parser.add_argument("--pages", type=int, nargs="+", help="Explicit page numbers; required for large/rotated PDF inspection fallback; native-text pages are skipped")
    args = parser.parse_args(argv)
    try:
        result = ocr_pdf_candidate(
            LocalArtifactStore(args.store_root, create=False), args.source_sha256,
            artifact_id=args.artifact_id, model_directory=args.model_directory,
            output_store=LocalArtifactStore(args.output_store_root),
            pages=tuple(args.pages) if args.pages is not None else None,
        )
    except Exception:
        print(json.dumps({"status": "ERROR", "reason": "ocr_input_or_evidence_storage_failed", "production_ready": False}))
        return 2
    print(json.dumps({key: result[key] for key in ("status", "report_sha256", "source_pdf_sha256", "source_page_count", "inspection_method", "selected_pages", "pages_succeeded", "pages_failed", "ocr_complete", "entire_source_ocr_complete", "pages_not_inspected_ranges", "production_ready")}, sort_keys=True))
    return 0 if result["ocr_complete"] or result["status"] == "native_text_available" else 2


if __name__ == "__main__":
    raise SystemExit(main())
