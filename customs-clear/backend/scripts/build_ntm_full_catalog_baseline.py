#!/usr/bin/env python3
"""Build or verify the pinned full-catalog baseline used by the NTM audit."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ntm_catalog_baseline import (  # noqa: E402
    DEFAULT_BASELINE_PATH,
    DEFAULT_ETT_PATH,
    DEFAULT_PDF_SOURCE_DIR,
    active_ett_fingerprint,
    catalog_fingerprint,
    compare_source_baseline,
    load_catalog_baseline,
    parser_fingerprint,
    pdf_source_manifest,
)


def _read_catalog(database: Path) -> dict[str, Any]:
    if not database.is_file():
        raise FileNotFoundError(f"catalog database not found: {database}")
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        sections = sorted(
            str(row[0] or "").strip()
            for row in connection.execute("SELECT roman_number FROM tnved_sections")
        )
        chapters = sorted(
            str(row[0] or "").strip()
            for row in connection.execute("SELECT code FROM tnved_chapters")
        )
        rows = list(
            connection.execute(
                "SELECT code, description FROM tnved_commodities ORDER BY code"
            )
        )
    finally:
        connection.close()
    return {
        "section_count": len(sections),
        "section_codes": sections,
        "chapter_count": len(chapters),
        "chapter_codes": chapters,
        **catalog_fingerprint(rows),
    }


def build_baseline(
    database: Path,
    *,
    pdf_dir: Path = DEFAULT_PDF_SOURCE_DIR,
    ett_path: Path = DEFAULT_ETT_PATH,
) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "validation_mode": "quarantine_only",
        "dataset_id": "ntm-full-catalog-reference-20260815",
        "qualification": (
            "Full 21/96/17809 reference corpus. Catalog structure is reproducible, "
            "but the bundled ETT rates are quarantined and must not be used as a "
            "current legal tariff source."
        ),
        # Baseline generation is deliberately unable to self-approve legal
        # freshness.  A separately reviewed official EEC manifest and temporal
        # footnote audit must explicitly replace this closed gate.
        "staging_release_gate": {
            "current_official_ett_verified": False,
            "temporal_footnotes_verified": False,
            "positive_snapshot_allowed": False,
            "reason": (
                "The local ETT bundle is DB-derived, contains invalid and "
                "duplicate/conflicting rows, and does not independently prove "
                "the current EEC revision or temporary as-of footnotes."
            ),
        },
        "parser": parser_fingerprint(),
        "pdf_source": pdf_source_manifest(pdf_dir),
        "active_ett": active_ett_fingerprint(ett_path),
        "catalog": _read_catalog(database),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path)
    parser.add_argument("--pdf-dir", type=Path, default=DEFAULT_PDF_SOURCE_DIR)
    parser.add_argument("--ett", type=Path, default=DEFAULT_ETT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_BASELINE_PATH)
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--check-sources-only",
        action="store_true",
        help="Verify tracked PDF and ETT fingerprints without a rebuilt database",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.check_sources_only:
        baseline = load_catalog_baseline(args.output)
        comparison = compare_source_baseline(
            baseline,
            pdf_source=pdf_source_manifest(args.pdf_dir),
            active_ett=active_ett_fingerprint(args.ett),
        )
        report = {**comparison, "ok": all(comparison.values())}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1

    if args.database is None:
        parser.error("--database is required unless --check-sources-only is used")
    candidate = build_baseline(args.database, pdf_dir=args.pdf_dir, ett_path=args.ett)
    if args.check:
        expected = load_catalog_baseline(args.output)
        ok = candidate == expected
        print(json.dumps({"ok": ok, "dataset_id": candidate["dataset_id"]}, ensure_ascii=False))
        return 0 if ok else 1
    if args.output.exists() and not args.force:
        parser.error(f"output already exists: {args.output}; use --force")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "ok": True,
        "output": str(args.output),
        "pdf_files": candidate["pdf_source"]["file_count"],
        "catalog_rows": candidate["catalog"]["rows"],
        "active_ett_codes": candidate["active_ett"]["unique_codes"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
