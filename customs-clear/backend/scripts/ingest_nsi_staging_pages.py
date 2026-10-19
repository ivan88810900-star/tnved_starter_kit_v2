#!/usr/bin/env python3
"""Ingest locally mounted immutable NSI pages into an explicit staging DB.

The database URL is read only from the environment variable named by the
required ``--database-url-env`` option.  There is no fallback to app.db or the
application's default database.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.staging_nsi_ingest import (  # noqa: E402
    Checkpoint,
    ImmutablePage,
    SourceObject,
    WorkerLimits,
    run_bounded_worker,
    staging_tables,
)


def _source(raw: dict[str, Any]) -> SourceObject:
    return SourceObject(
        source_id=str(raw["source_id"]),
        authority=str(raw["authority"]),
        dataset=str(raw["dataset"]),
        source_url=str(raw["source_url"]),
        source_revision=str(raw["source_revision"]),
        object_bucket=str(raw["object_bucket"]),
        object_key=str(raw["object_key"]),
        sha256=str(raw["sha256"]),
        size_bytes=int(raw["size_bytes"]),
        media_type=str(raw["media_type"]),
        captured_at=datetime.fromisoformat(str(raw["captured_at"]).replace("Z", "+00:00")),
    )


def _read_limited(path: Path, byte_budget: int) -> bytes:
    """Read at most one bounded source object without allocating it first."""

    if byte_budget < 0:
        raise RuntimeError("source byte budget is exhausted")
    size = path.stat().st_size
    if size > byte_budget:
        raise RuntimeError(
            f"source object {path} is {size} bytes; remaining budget is {byte_budget}"
        )
    with path.open("rb") as handle:
        raw = handle.read(byte_budget + 1)
    if len(raw) > byte_budget or len(raw) != size:
        raise RuntimeError(f"source object {path} changed or exceeded its byte budget")
    return raw


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url-env", required=True)
    parser.add_argument("--expected-database-name", required=True)
    parser.add_argument("--job-file", required=True, type=Path)
    parser.add_argument("--schema", default="tariff_ingest")
    parser.add_argument(
        "--initialize-schema",
        action="store_true",
        help=(
            "explicitly create missing additive staging tables in the selected "
            "database before ingestion"
        ),
    )
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--max-rows", type=int, default=1000)
    parser.add_argument("--max-source-bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--max-seconds", type=float, default=300.0)
    args = parser.parse_args()

    database_url = os.environ.get(args.database_url_env, "").strip()
    if not database_url:
        parser.error(f"environment variable {args.database_url_env!r} is unset")
    actual_database = make_url(database_url).database
    if actual_database != args.expected_database_name:
        parser.error(
            "explicit database mismatch: connection URL does not select "
            f"{args.expected_database_name!r}"
        )
    job = json.loads(args.job_file.read_text(encoding="utf-8"))
    base = args.job_file.resolve().parent
    pages_by_offset: dict[int, dict[str, Any]] = {}
    for item in job["pages"]:
        offset = int(item["logical_offset"])
        if offset in pages_by_offset:
            parser.error(f"duplicate logical_offset {offset}")
        pages_by_offset[offset] = item

    def read_page(checkpoint: Checkpoint, byte_budget: int) -> ImmutablePage:
        try:
            item = pages_by_offset[checkpoint.next_offset]
        except KeyError as exc:
            raise RuntimeError(f"job has no page for offset {checkpoint.next_offset}") from exc
        page_path = base / item["page_path"]
        manifest_path = base / item["manifest_path"]
        page_size = page_path.stat().st_size
        manifest_size = manifest_path.stat().st_size
        if page_size + manifest_size > byte_budget:
            raise RuntimeError(
                "candidate page objects exceed the remaining source byte budget"
            )
        page_bytes = _read_limited(page_path, byte_budget)
        manifest_bytes = _read_limited(manifest_path, byte_budget - len(page_bytes))
        return ImmutablePage(
            page_source=_source(item["page_source"]),
            manifest_source=_source(item["manifest_source"]),
            page_bytes=page_bytes,
            manifest_bytes=manifest_bytes,
        )

    engine = create_engine(database_url)
    try:
        if args.initialize_schema:
            metadata = MetaData()
            staging_tables(metadata, schema=args.schema or None)
            metadata.create_all(engine, checkfirst=True)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        result = run_bounded_worker(
            session_factory=factory,
            page_reader=read_page,
            epoch_id=str(job["epoch_id"]),
            dataset=str(job["dataset"]),
            schema=args.schema or None,
            limits=WorkerLimits(
                max_pages=args.max_pages,
                max_rows=args.max_rows,
                max_source_bytes=args.max_source_bytes,
                max_seconds=args.max_seconds,
            ),
        )
    finally:
        engine.dispose()
    print(
        json.dumps(
            {
                "pages_committed": result.pages_committed,
                "physical_rows": result.physical_rows,
                "source_bytes": result.source_bytes,
                "next_offset": result.checkpoint.next_offset,
                "complete": result.checkpoint.complete,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
