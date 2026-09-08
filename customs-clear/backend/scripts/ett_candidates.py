#!/usr/bin/env python3
"""Explicit local ETT candidate staging/preview; no promotion command exists."""
from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import sys
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.encoders import jsonable_encoder
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.services.ett_artifacts import LocalArtifactStore
from app.services.ett_manifest import validate_manifest
from app.services.ett_repository import candidate_readiness, load_candidate, semantic_diff, stage_candidate
from app.services.ett_resolver import resolve_rate


def read_json(path: Path):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("Non-finite JSON number")

    with path.open("rb") as source:
        raw = source.read(64 * 1024 * 1024 + 1)
    if len(raw) > 64 * 1024 * 1024:
        raise ValueError("ETT input exceeds the size limit")
    return json.loads(raw, object_pairs_hook=unique_pairs, parse_constant=invalid_constant)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("manifest", type=Path)
    diff = commands.add_parser("diff")
    diff.add_argument("before", type=Path)
    diff.add_argument("after", type=Path)
    stage = commands.add_parser("stage")
    stage.add_argument("manifest", type=Path)
    acquire = commands.add_parser("acquire", help="Capture the actual official index and linked documents; no database writes")
    acquire.add_argument("--store-root", required=True, type=Path)
    extract = commands.add_parser("extract", help="Extract coordinate-bound PDF evidence from a verified acquisition receipt")
    extract.add_argument("digest")
    extract.add_argument("--store-root", required=True, type=Path)
    verify_rows = commands.add_parser("verify-rows", help="Re-extract PDF quotes referenced by a candidate; does not approve rates or dates")
    verify_rows.add_argument("manifest", type=Path)
    verify_rows.add_argument("--store-root", required=True, type=Path)
    preview = commands.add_parser("preview")
    preview.add_argument("digest")
    preview.add_argument("--code", required=True)
    preview.add_argument("--as-of", required=True, type=date.fromisoformat)
    preview.add_argument("--destination", required=True, choices=["AM", "BY", "KZ", "KG", "RU"])
    preview.add_argument("--facts", type=Path)
    for command in (stage, preview):
        command.add_argument("--database", required=True, type=Path, help="Explicit migrated local SQLite candidate database")
        command.add_argument("--store-root", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            result = candidate_readiness(validate_manifest(read_json(args.manifest)))
        elif args.command == "diff":
            result = semantic_diff(validate_manifest(read_json(args.before)), validate_manifest(read_json(args.after)))
        elif args.command in {"acquire", "extract"}:
            from app.services.ett_acquisition import acquire_official, extract_acquisition
            store = LocalArtifactStore(args.store_root)
            result = acquire_official(store) if args.command == "acquire" else extract_acquisition(store, args.digest)
        elif args.command == "verify-rows":
            from app.services.ett_evidence_binding import verify_manifest_source_rows
            store = LocalArtifactStore(args.store_root, create=False)
            result = verify_manifest_source_rows(validate_manifest(read_json(args.manifest)), store)
        else:
            if not args.database.is_file() or args.database.is_symlink():
                raise ValueError("An explicit existing migrated SQLite database is required")
            store = LocalArtifactStore(args.store_root, create=args.command == "stage")
            mode = "rw" if args.command == "stage" else "ro"
            uri = "file:" + quote(str(args.database.absolute()), safe="/") + "?mode=" + mode
            def connect():
                connection = sqlite3.connect(uri, uri=True)
                connection.execute("PRAGMA foreign_keys=ON")
                if mode == "ro":
                    connection.execute("PRAGMA query_only=ON")
                return connection
            engine = create_engine("sqlite://", creator=connect)
            try:
                with Session(engine) as db:
                    if args.command == "stage":
                        result = stage_candidate(db, store, validate_manifest(read_json(args.manifest)))
                    else:
                        manifest = load_candidate(db, store, args.digest)
                        result = resolve_rate(manifest, args.code, args.as_of, args.destination, read_json(args.facts) if args.facts else None)
            finally:
                engine.dispose()
        print(json.dumps(jsonable_encoder(result, custom_encoder={Decimal: str}), ensure_ascii=False, allow_nan=False))
        if args.command == "verify-rows" and not result["rows_verified"]:
            return 2
        return 0
    except Exception as exc:
        # Structured failure, no secret-bearing source payload or database path.
        print(json.dumps({"status": "ERROR", "error": "ETT candidate validation or operation failed", "error_type": type(exc).__name__, "production_ready": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
