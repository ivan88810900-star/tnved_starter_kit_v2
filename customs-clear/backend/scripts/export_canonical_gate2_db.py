#!/usr/bin/env python3
"""Export a compact SQLite database containing only Canonical Gate-2 inputs.

The source database is opened read-only and copied inside one read transaction.
Only columns used by the structural audit are exported. From ``hs_rates`` only
leaf markers for ambiguous commodity codes ending in ``0000`` are retained.
Operational and user tables are never copied.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any
import zipfile


GATE2_TABLES = (
    "tnved_sections",
    "tnved_chapters",
    "tnved_commodities",
    "hs_rates",
)

_TABLE_COLUMNS = {
    "tnved_sections": ("id", "roman_number", "title", "notes"),
    "tnved_chapters": ("id", "section_id", "code", "title", "notes"),
    "tnved_commodities": (
        "id",
        "chapter_id",
        "code",
        "description",
        "unit",
        "import_duty",
        "supp_unit",
        "weight_coeff",
    ),
    "hs_rates": ("id", "hs_code"),
}

_TARGET_SCHEMA = {
    "tnved_sections": """
        CREATE TABLE tnved_sections (
            id INTEGER PRIMARY KEY,
            roman_number VARCHAR(16),
            title TEXT,
            notes TEXT
        )
    """,
    "tnved_chapters": """
        CREATE TABLE tnved_chapters (
            id INTEGER PRIMARY KEY,
            section_id INTEGER REFERENCES tnved_sections(id),
            code VARCHAR(16) NOT NULL,
            title TEXT,
            notes TEXT
        )
    """,
    "tnved_commodities": """
        CREATE TABLE tnved_commodities (
            id INTEGER PRIMARY KEY,
            chapter_id INTEGER REFERENCES tnved_chapters(id),
            code VARCHAR(32) NOT NULL,
            description TEXT,
            unit VARCHAR(64),
            import_duty TEXT,
            supp_unit VARCHAR(16),
            weight_coeff FLOAT
        )
    """,
    "hs_rates": """
        CREATE TABLE hs_rates (
            id INTEGER PRIMARY KEY,
            hs_code VARCHAR(10)
        )
    """,
}

_TARGET_INDEXES = (
    "CREATE INDEX ix_tnved_chapters_code ON tnved_chapters(code)",
    "CREATE INDEX ix_tnved_chapters_section_id ON tnved_chapters(section_id)",
    "CREATE UNIQUE INDEX uq_tnved_commodities_code ON tnved_commodities(code)",
    "CREATE INDEX ix_tnved_commodities_chapter_id ON tnved_commodities(chapter_id)",
    "CREATE INDEX ix_hs_rates_hs_code ON hs_rates(hs_code)",
)


@dataclass(frozen=True)
class Gate2ExportReport:
    source: str
    output: str
    source_size_bytes: int
    output_size_bytes: int
    output_sha256: str
    table_rows: dict[str, int]
    archive: str | None = None
    archive_size_bytes: int | None = None
    archive_sha256: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_destination(path: Path, *, force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"destination already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)


def _source_connection(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


def _validate_source_table(source: sqlite3.Connection, table: str) -> None:
    exists = source.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    if exists is None:
        raise RuntimeError(f"required table is missing: {table}")
    columns = {
        str(info[1])
        for info in source.execute(f"PRAGMA table_info({_quote_identifier(table)})")
    }
    missing = set(_TABLE_COLUMNS[table]) - columns
    if missing:
        raise RuntimeError(f"required columns are missing from {table}: {sorted(missing)}")


def _copy_query(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    table: str,
    columns: tuple[str, ...],
    select_sql: str,
    *,
    batch_size: int,
) -> int:
    quoted_table = _quote_identifier(table)
    quoted_columns = ", ".join(_quote_identifier(column) for column in columns)
    placeholders = ", ".join("?" for _ in columns)
    select_cursor = source.execute(select_sql)
    insert_sql = f"INSERT INTO {quoted_table} ({quoted_columns}) VALUES ({placeholders})"
    copied = 0
    while rows := select_cursor.fetchmany(batch_size):
        target.executemany(insert_sql, rows)
        copied += len(rows)
    return copied


def _create_archive(database: Path, archive: Path) -> None:
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{archive.name}.",
        suffix=".tmp",
        dir=archive.parent,
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with zipfile.ZipFile(
            temp_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as bundle:
            bundle.write(database, arcname=database.name)
        os.replace(temp_path, archive)
    finally:
        temp_path.unlink(missing_ok=True)


def export_gate2_database(
    source_path: str | Path,
    output_path: str | Path,
    *,
    archive_path: str | Path | None = None,
    force: bool = False,
    batch_size: int = 10_000,
) -> Gate2ExportReport:
    """Create an atomic compact copy of the four tables required by Gate-2."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    source = Path(source_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    archive = Path(archive_path).expanduser().resolve() if archive_path else None
    if not source.is_file():
        raise FileNotFoundError(f"source database not found: {source}")
    if source == output:
        raise ValueError("source and output must be different files")
    if archive is not None and archive in {source, output}:
        raise ValueError("archive must differ from source and output")
    _check_destination(output, force=force)
    if archive is not None:
        _check_destination(archive, force=force)

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{output.name}.",
        suffix=".tmp",
        dir=output.parent,
    )
    os.close(fd)
    temp_output = Path(temp_name)
    source_db: sqlite3.Connection | None = None
    target_db: sqlite3.Connection | None = None
    table_rows: dict[str, int] = {}
    try:
        source_db = _source_connection(source)
        target_db = sqlite3.connect(temp_output)
        source_db.execute("BEGIN")
        target_db.execute("PRAGMA foreign_keys=OFF")
        target_db.execute("PRAGMA synchronous=OFF")

        for table in GATE2_TABLES:
            _validate_source_table(source_db, table)
            target_db.execute(_TARGET_SCHEMA[table])

        for table in GATE2_TABLES[:-1]:
            columns = _TABLE_COLUMNS[table]
            quoted_columns = ", ".join(_quote_identifier(column) for column in columns)
            table_rows[table] = _copy_query(
                source_db,
                target_db,
                table,
                columns,
                f"SELECT {quoted_columns} FROM {_quote_identifier(table)}",
                batch_size=batch_size,
            )
        # Structural classification consults hs_rates only for real commodity
        # codes ending in 0000; values/provenance and all other rate rows are irrelevant.
        table_rows["hs_rates"] = _copy_query(
            source_db,
            target_db,
            "hs_rates",
            _TABLE_COLUMNS["hs_rates"],
            """
            SELECT min(rate.id), rate.hs_code
            FROM hs_rates AS rate
            JOIN tnved_commodities AS commodity ON commodity.code = rate.hs_code
            WHERE commodity.code LIKE '%0000'
            GROUP BY rate.hs_code
            ORDER BY rate.hs_code
            """,
            batch_size=batch_size,
        )
        for statement in _TARGET_INDEXES:
            target_db.execute(statement)

        target_db.commit()
        source_db.rollback()
        integrity = target_db.execute("PRAGMA integrity_check").fetchone()
        if integrity != ("ok",):
            raise RuntimeError(f"exported database failed integrity_check: {integrity}")
        foreign_key_issues = target_db.execute("PRAGMA foreign_key_check").fetchmany(20)
        if foreign_key_issues:
            raise RuntimeError(f"exported database failed foreign_key_check: {foreign_key_issues}")
        target_db.execute("VACUUM")
        target_db.close()
        target_db = None
        source_db.close()
        source_db = None
        os.replace(temp_output, output)

        if archive is not None:
            _create_archive(output, archive)

        return Gate2ExportReport(
            source=str(source),
            output=str(output),
            source_size_bytes=source.stat().st_size,
            output_size_bytes=output.stat().st_size,
            output_sha256=_sha256(output),
            table_rows=table_rows,
            archive=str(archive) if archive is not None else None,
            archive_size_bytes=archive.stat().st_size if archive is not None else None,
            archive_sha256=_sha256(archive) if archive is not None else None,
        )
    finally:
        if target_db is not None:
            target_db.close()
        if source_db is not None:
            source_db.close()
        temp_output.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="path to the full customs.db")
    parser.add_argument("--output", required=True, help="path for compact Gate-2 SQLite DB")
    parser.add_argument("--archive", help="optional ZIP path for transfer")
    parser.add_argument("--force", action="store_true", help="replace existing output/archive")
    parser.add_argument("--batch-size", type=int, default=10_000)
    args = parser.parse_args()
    report = export_gate2_database(
        args.source,
        args.output,
        archive_path=args.archive,
        force=args.force,
        batch_size=args.batch_size,
    )
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
