#!/usr/bin/env python3
"""Prepare a bounded, raw-first ETT JSON batch without writing a database."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.staging_raw_ingest import (
    StagingRawIngestError,
    prepare_ett_staging_batch,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--pdf", type=Path, help="ETT PDF to extract using pdftotext")
    inputs.add_argument("--text", type=Path, help="Existing pdftotext -layout UTF-8 file")
    parser.add_argument("--start-ordinal", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--output", type=Path, help="JSON output path (default: stdout)")
    return parser


def _read_pdf(path: Path) -> bytes:
    source = path.resolve(strict=True)
    try:
        result = subprocess.run(
            ["pdftotext", "-enc", "UTF-8", "-layout", str(source), "-"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise StagingRawIngestError("pdftotext executable is unavailable") from exc
    if result.returncode != 0:
        diagnostic = result.stderr.decode("utf-8", errors="replace").strip()
        raise StagingRawIngestError(
            f"pdftotext failed with exit code {result.returncode}: {diagnostic}"
        )
    return result.stdout


def _read_source(args: argparse.Namespace) -> bytes:
    if args.pdf is not None:
        return _read_pdf(args.pdf)
    return args.text.resolve(strict=True).read_bytes()


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        source_bytes = _read_source(args)
        payload = prepare_ett_staging_batch(
            source_bytes,
            start_ordinal=args.start_ordinal,
            batch_size=args.batch_size,
        )
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"
        if args.output is None:
            sys.stdout.write(serialized)
        else:
            args.output.write_text(serialized, encoding="utf-8")
    except (OSError, StagingRawIngestError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
