"""Fail-closed ingestion of an accepted TN VED structure SQLite into staging.

The accepted recovery database is a structural catalogue, not a statement of
legal applicability.  This module therefore stores only the compatibility
``tnved_entries`` projection plus immutable artifact provenance.  It never
stores rates or NTM data and every row remains ``COLLECTED_UNVERIFIED``.

The caller owns the transaction and must explicitly initialize the additive
staging tables before the first load.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import Session


DEFAULT_SCHEMA = "tariff_ingest"
STATUS = "COLLECTED_UNVERIFIED"
PARSER_VERSION = "tnved-structure-sqlite-staging-v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_HS_RE = re.compile(r"^[0-9]{2,10}$")


class StructureIngestError(RuntimeError):
    """The artifact or existing staging state is not safe to ingest."""


@dataclass(frozen=True)
class StructureArtifact:
    sha256: str
    logical_sha256: str
    size_bytes: int
    catalog_id: str
    generated_at_source: datetime
    source_count: int
    edition_count: int
    entry_count: int


@dataclass(frozen=True)
class StructureRow:
    ordinal: int
    hs_code: str
    parent_hs: str
    level: int
    title: str
    path_json: str
    chapter: str
    source_url: str
    source_revision: str
    row_sha256: str


@dataclass(frozen=True)
class StructureIngestResult:
    run_id: str
    row_count: int
    unique_code_count: int
    replayed: bool


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _logical_digest(connection: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    for table in (
        "recovery_metadata", "recovery_sources", "recovery_editions",
        "recovery_notes", "recovery_sections", "recovery_section_chapters",
        "recovery_nodes", "recovery_node_notes", "tnved_entries",
    ):
        digest.update((table + "\n").encode())
        columns = [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
        if not columns:
            raise StructureIngestError(f"accepted SQLite is missing {table}")
        order = ",".join(str(index + 1) for index in range(len(columns)))
        for row in connection.execute(f"SELECT * FROM {table} ORDER BY {order}"):
            digest.update((_canonical_json(list(row)) + "\n").encode())
    return digest.hexdigest()


def _same(actual: Any, expected: Any) -> bool:
    if isinstance(actual, datetime) and isinstance(expected, datetime):
        return actual.replace(tzinfo=actual.tzinfo or timezone.utc) == expected.replace(
            tzinfo=expected.tzinfo or timezone.utc
        )
    return actual == expected


def _validate_artifact(artifact: StructureArtifact) -> None:
    if not isinstance(artifact, StructureArtifact):
        raise StructureIngestError("artifact must use the validated structure contract")
    if not _SHA256_RE.fullmatch(artifact.sha256) or not _SHA256_RE.fullmatch(artifact.logical_sha256):
        raise StructureIngestError("artifact hashes must be canonical SHA-256")
    counts = (artifact.size_bytes, artifact.source_count, artifact.edition_count, artifact.entry_count)
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in counts):
        raise StructureIngestError("artifact counts and size must be positive")
    if not artifact.catalog_id or artifact.catalog_id != artifact.catalog_id.strip():
        raise StructureIngestError("artifact catalog_id must be canonical")
    if not isinstance(artifact.generated_at_source, datetime) or artifact.generated_at_source.utcoffset() is None:
        raise StructureIngestError("artifact generated_at_source must be timezone-aware")


def _validate_row(row: StructureRow) -> None:
    if not isinstance(row, StructureRow):
        raise StructureIngestError("row must use the validated structure contract")
    if isinstance(row.ordinal, bool) or not isinstance(row.ordinal, int) or row.ordinal < 1 or not isinstance(row.hs_code, str) or not _HS_RE.fullmatch(row.hs_code):
        raise StructureIngestError("structure row ordinal and HS code must be canonical")
    if row.parent_hs and (not _HS_RE.fullmatch(row.parent_hs) or len(row.parent_hs) >= len(row.hs_code)):
        raise StructureIngestError("structure row parent is invalid")
    if isinstance(row.level, bool) or not isinstance(row.level, int) or row.level != len(row.hs_code):
        raise StructureIngestError("structure row level does not match HS length")
    if not row.title or row.title != row.title.strip():
        raise StructureIngestError("structure row title must be canonical")
    try:
        path_value = json.loads(row.path_json)
    except (TypeError, ValueError) as exc:
        raise StructureIngestError("structure row path is malformed") from exc
    if not isinstance(path_value, list) or not path_value or path_value[-1] != row.title or _canonical_json(path_value) != row.path_json:
        raise StructureIngestError("structure row path is not canonical")
    if row.chapter != row.hs_code[:2]:
        raise StructureIngestError("structure row chapter does not match HS code")
    parsed = urlsplit(row.source_url)
    if parsed.scheme != "https" or parsed.hostname != "eec.eaeunion.org" or parsed.netloc != "eec.eaeunion.org" or parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise StructureIngestError("structure row source URL must be credential-free official EEC HTTPS")
    try:
        if parsed.port is not None:
            raise StructureIngestError("structure row source URL must not use an explicit port")
    except ValueError as exc:
        raise StructureIngestError("structure row source URL contains an invalid port") from exc
    if not row.source_revision or row.source_revision != row.source_revision.strip():
        raise StructureIngestError("structure row source revision must be canonical")
    payload = {"hs_code": row.hs_code, "parent_hs": row.parent_hs, "level": row.level, "title": row.title, "description": row.path_json, "chapter": row.chapter, "source_url": row.source_url, "source_revision": row.source_revision}
    expected_hash = _sha256(_canonical_json(payload).encode("utf-8"))
    if not _SHA256_RE.fullmatch(row.row_sha256) or row.row_sha256 != expected_hash:
        raise StructureIngestError("structure row SHA-256 mismatch")


def staging_tables(metadata: MetaData, *, schema: str | None = DEFAULT_SCHEMA) -> Mapping[str, Table]:
    artifacts = Table(
        "tnved_structure_artifacts",
        metadata,
        Column("artifact_sha256", Text, primary_key=True),
        Column("logical_sha256", Text, nullable=False),
        Column("size_bytes", BigInteger, nullable=False),
        Column("catalog_id", Text, nullable=False),
        Column("generated_at_source", DateTime(timezone=True), nullable=False),
        Column("source_count", Integer, nullable=False),
        Column("edition_count", Integer, nullable=False),
        Column("entry_count", Integer, nullable=False),
        Column("status", Text, nullable=False),
        schema=schema,
    )
    runs = Table(
        "tnved_structure_runs",
        metadata,
        Column("run_id", Text, primary_key=True),
        Column("artifact_sha256", Text, ForeignKey(f"{schema}.tnved_structure_artifacts.artifact_sha256" if schema else "tnved_structure_artifacts.artifact_sha256"), nullable=False),
        Column("parser_version", Text, nullable=False),
        Column("row_count", Integer, nullable=False),
        Column("unique_code_count", Integer, nullable=False),
        Column("status", Text, nullable=False),
        Column("inserted_at", DateTime(timezone=True), nullable=False),
        schema=schema,
    )
    rows = Table(
        "tnved_structure_rows",
        metadata,
        Column("artifact_sha256", Text, ForeignKey(f"{schema}.tnved_structure_artifacts.artifact_sha256" if schema else "tnved_structure_artifacts.artifact_sha256"), primary_key=True),
        Column("hs_code", Text, primary_key=True),
        Column("parent_hs", Text, nullable=False),
        Column("level", Integer, nullable=False),
        Column("title", Text, nullable=False),
        Column("path_json", Text, nullable=False),
        Column("chapter", Text, nullable=False),
        Column("source_url", Text, nullable=False),
        Column("source_revision", Text, nullable=False),
        Column("row_sha256", Text, nullable=False),
        Column("status", Text, nullable=False),
        Column("ordinal", Integer, nullable=False),
        UniqueConstraint("artifact_sha256", "ordinal"),
        UniqueConstraint("artifact_sha256", "row_sha256"),
        schema=schema,
    )
    return {"artifacts": artifacts, "runs": runs, "rows": rows}


def read_accepted_sqlite(path: Path, *, expected_sha256: str, expected_logical_sha256: str) -> tuple[StructureArtifact, list[StructureRow]]:
    if not _SHA256_RE.fullmatch(expected_sha256) or not _SHA256_RE.fullmatch(expected_logical_sha256):
        raise StructureIngestError("expected hashes must be canonical SHA-256")
    raw = path.read_bytes()
    if _sha256(raw) != expected_sha256:
        raise StructureIngestError("artifact SHA-256 mismatch")
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise StructureIngestError("SQLite quick_check failed")
        metadata = dict(connection.execute("SELECT key, value FROM recovery_metadata"))
        if _logical_digest(connection) != expected_logical_sha256:
            raise StructureIngestError("logical SHA-256 mismatch")
        catalog_id = metadata.get("catalog_id", "")
        generated = metadata.get("generated_at_source", "")
        generated_at = datetime.fromisoformat(generated)
        if generated_at.utcoffset() is None:
            raise StructureIngestError("generated_at_source must be timezone-aware")
        source_count = connection.execute("SELECT count(*) FROM recovery_sources").fetchone()[0]
        edition_count = connection.execute("SELECT count(*) FROM recovery_editions").fetchone()[0]
        records = connection.execute(
            "SELECT id, hs_code, parent_hs, level, title, description, chapter, source_url, source_revision FROM tnved_entries ORDER BY id"
        ).fetchall()
    except (sqlite3.Error, KeyError, ValueError, TypeError) as exc:
        if isinstance(exc, StructureIngestError):
            raise
        raise StructureIngestError("accepted SQLite contract is malformed") from exc
    finally:
        connection.close()
    rows: list[StructureRow] = []
    seen: set[str] = set()
    for expected_ordinal, record in enumerate(records, 1):
        if record["id"] != expected_ordinal:
            raise StructureIngestError("tnved_entries ids must be contiguous from 1")
        payload = {key: record[key] for key in ("hs_code", "parent_hs", "level", "title", "description", "chapter", "source_url", "source_revision")}
        if not _HS_RE.fullmatch(payload["hs_code"]) or payload["hs_code"] in seen:
            raise StructureIngestError("tnved_entries contains invalid or duplicate HS code")
        if payload["parent_hs"] and (not _HS_RE.fullmatch(payload["parent_hs"]) or len(payload["parent_hs"]) >= len(payload["hs_code"])):
            raise StructureIngestError("tnved_entries contains invalid parent")
        if payload["level"] != len(payload["hs_code"]):
            raise StructureIngestError("tnved_entries level does not match HS length")
        path_value = json.loads(payload["description"])
        if not isinstance(path_value, list) or not path_value or path_value[-1] != payload["title"]:
            raise StructureIngestError("tnved_entries path is malformed")
        seen.add(payload["hs_code"])
        rows.append(StructureRow(expected_ordinal, payload["hs_code"], payload["parent_hs"], payload["level"], payload["title"], _canonical_json(path_value), payload["chapter"], payload["source_url"], payload["source_revision"], _sha256(_canonical_json(payload).encode("utf-8"))))
    if not rows or len(rows) != len(seen):
        raise StructureIngestError("tnved_entries must be nonempty and unique")
    artifact = StructureArtifact(expected_sha256, expected_logical_sha256, len(raw), catalog_id, generated_at, source_count, edition_count, len(rows))
    return artifact, rows


def ingest_structure(session: Session, *, artifact: StructureArtifact, rows: Sequence[StructureRow], schema: str | None = DEFAULT_SCHEMA, initialize_schema: bool = False, now: datetime) -> StructureIngestResult:
    _validate_artifact(artifact)
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise StructureIngestError("ingest time must be timezone-aware")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise StructureIngestError("rows must be a bounded sequence")
    if artifact.entry_count != len(rows) or not rows:
        raise StructureIngestError("artifact entry count mismatch")
    for row in rows:
        _validate_row(row)
    if [row.ordinal for row in rows] != list(range(1, len(rows) + 1)):
        raise StructureIngestError("row ordinals must be contiguous from 1")
    if len({row.hs_code for row in rows}) != len(rows) or len({row.row_sha256 for row in rows}) != len(rows):
        raise StructureIngestError("rows must have unique codes and hashes")
    codes = {row.hs_code for row in rows}
    if any(row.parent_hs and row.parent_hs not in codes for row in rows):
        raise StructureIngestError("row parent is missing from the same artifact")
    metadata = MetaData()
    tables = staging_tables(metadata, schema=schema)
    if initialize_schema:
        metadata.create_all(session.get_bind())
    artifact_values = {"artifact_sha256": artifact.sha256, "logical_sha256": artifact.logical_sha256, "size_bytes": artifact.size_bytes, "catalog_id": artifact.catalog_id, "generated_at_source": artifact.generated_at_source, "source_count": artifact.source_count, "edition_count": artifact.edition_count, "entry_count": artifact.entry_count, "status": STATUS}
    run_id = f"tnved-structure:{artifact.sha256}"
    run_values = {"run_id": run_id, "artifact_sha256": artifact.sha256, "parser_version": PARSER_VERSION, "row_count": len(rows), "unique_code_count": len(rows), "status": STATUS}
    existing_artifact = session.execute(select(tables["artifacts"]).where(tables["artifacts"].c.artifact_sha256 == artifact.sha256)).mappings().one_or_none()
    existing_run = session.execute(select(tables["runs"]).where(tables["runs"].c.run_id == run_id)).mappings().one_or_none()
    existing_rows = session.execute(select(tables["rows"]).where(tables["rows"].c.artifact_sha256 == artifact.sha256).order_by(tables["rows"].c.ordinal)).mappings().all()
    if existing_artifact is not None or existing_run is not None or existing_rows:
        if existing_artifact is None or existing_run is None or len(existing_rows) != len(rows):
            raise StructureIngestError("incomplete existing structural ingest")
        for key, value in artifact_values.items():
            if not _same(existing_artifact[key], value):
                raise StructureIngestError(f"conflicting existing artifact.{key}")
        for key, value in run_values.items():
            if not _same(existing_run[key], value):
                raise StructureIngestError(f"conflicting existing run.{key}")
        for actual, expected in zip(existing_rows, rows):
            values = _row_values(artifact.sha256, expected)
            if any(actual[key] != value for key, value in values.items()):
                raise StructureIngestError("conflicting existing structure row")
        return StructureIngestResult(run_id, len(rows), len(rows), True)
    session.execute(tables["artifacts"].insert().values(**artifact_values))
    session.execute(tables["runs"].insert().values(**run_values, inserted_at=now))
    session.execute(tables["rows"].insert(), [_row_values(artifact.sha256, row) for row in rows])
    return StructureIngestResult(run_id, len(rows), len(rows), False)


def _row_values(artifact_sha256: str, row: StructureRow) -> dict[str, Any]:
    return {"artifact_sha256": artifact_sha256, "hs_code": row.hs_code, "parent_hs": row.parent_hs, "level": row.level, "title": row.title, "path_json": row.path_json, "chapter": row.chapter, "source_url": row.source_url, "source_revision": row.source_revision, "row_sha256": row.row_sha256, "status": STATUS, "ordinal": row.ordinal}
