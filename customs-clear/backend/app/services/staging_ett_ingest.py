"""Atomic raw ETT capture into a caller-owned staging transaction.

This adapter is intentionally separate from the paged NSI/SGR loader.  It
captures one immutable, bounded ETT source object without normalizing rates or
admitting them as legally verified data.  The caller owns the ``Session`` and
the surrounding transaction; this module never commits it.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    func,
    or_,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .staging_nsi_ingest import COLLECTED_UNVERIFIED, SourceObject, StagingIngestError


ETT_PARSER_VERSION = "ett-immutable-group-pdf-staging-v1"
DEFAULT_SCHEMA = "tariff_ingest"
MAX_ETT_ROWS = 86
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_HS_CODE_RE = re.compile(r"^[0-9]{10}$")
_MEDIA_TYPE_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*$"
)


@dataclass(frozen=True)
class EttCollectedRow:
    ordinal: int
    hs_code: str
    description: str
    supplementary_unit: str
    duty_text: str
    page_number: int
    line_number: int
    raw_line: str


@dataclass(frozen=True)
class EttIngestResult:
    run_id: str
    source_id: str
    raw_count: int
    unique_count: int
    next_ordinal: int
    replayed: bool


def ett_staging_tables(
    metadata: MetaData, *, schema: str | None = DEFAULT_SCHEMA
) -> dict[str, Table]:
    """Define the existing minimal ETT staging contract for this adapter."""

    source_objects = Table(
        "source_objects",
        metadata,
        Column("source_id", Text, primary_key=True),
        Column("authority", Text, nullable=False),
        Column("dataset", Text, nullable=False),
        Column("source_url", Text, nullable=False),
        Column("source_revision", Text, nullable=False),
        Column("object_bucket", Text, nullable=False),
        Column("object_key", Text, nullable=False),
        Column("sha256", Text, nullable=False),
        Column("size_bytes", BigInteger, nullable=False),
        Column("media_type", Text, nullable=False),
        Column("captured_at", DateTime(timezone=True), nullable=False),
        Column("status", Text, nullable=False),
        UniqueConstraint("object_bucket", "object_key"),
        schema=schema,
        extend_existing=True,
    )
    ingest_runs = Table(
        "ingest_runs",
        metadata,
        Column("run_id", Text, primary_key=True),
        Column("source_id", Text, nullable=False),
        Column("scope", JSON, nullable=False),
        Column("parser_version", Text, nullable=False),
        Column("status", Text, nullable=False),
        Column("raw_count", Integer, nullable=False),
        Column("unique_count", Integer, nullable=False),
        Column("normalized_count", Integer, nullable=False),
        Column("rejected_count", Integer, nullable=False),
        Column("resume_cursor", JSON, nullable=False),
        Column("started_at", DateTime(timezone=True), nullable=False),
        Column("completed_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
        schema=schema,
        extend_existing=True,
    )
    rows = Table(
        "ett_collected_rows",
        metadata,
        Column(
            "source_id",
            Text,
            ForeignKey(
                f"{schema}.source_objects.source_id"
                if schema
                else "source_objects.source_id"
            ),
            primary_key=True,
        ),
        Column("hs_code", Text, nullable=False),
        Column("description", Text, nullable=False),
        Column("supplementary_unit", Text, nullable=False),
        Column("duty_text", Text, nullable=False),
        Column("raw_line", Text, nullable=False),
        Column("row_sha256", Text, primary_key=True),
        Column("status", Text, nullable=False),
        Column("ordinal", Integer, nullable=False),
        UniqueConstraint("source_id", "hs_code"),
        schema=schema,
        extend_existing=True,
    )
    return {
        "source_objects": source_objects,
        "ingest_runs": ingest_runs,
        "ett_collected_rows": rows,
    }


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _row_text(value: Any, name: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str):
        raise StagingIngestError(f"ETT row {name} must be a string")
    if nonempty and not value.strip():
        raise StagingIngestError(f"ETT row {name} is required")
    return value


def _source_values(source: SourceObject) -> dict[str, Any]:
    return {
        "source_id": source.source_id,
        "authority": source.authority,
        "dataset": source.dataset,
        "source_url": source.source_url,
        "source_revision": source.source_revision,
        "object_bucket": source.object_bucket,
        "object_key": source.object_key,
        "sha256": source.sha256,
        "size_bytes": source.size_bytes,
        "media_type": source.media_type,
        "captured_at": source.captured_at,
        "status": COLLECTED_UNVERIFIED,
    }


def _validate_source(source: SourceObject, source_bytes: bytes) -> None:
    for name in (
        "source_id",
        "authority",
        "dataset",
        "source_revision",
        "object_bucket",
        "object_key",
    ):
        value = getattr(source, name)
        if not isinstance(value, str) or not value or value != value.strip():
            raise StagingIngestError(f"source {name} must be a nonempty canonical string")
    if source.dataset != "EEC-ETT":
        raise StagingIngestError("ETT adapter requires dataset EEC-ETT")
    if source.authority != "EEC":
        raise StagingIngestError("ETT adapter requires authority EEC")
    if (
        not isinstance(source.source_url, str)
        or source.source_url != source.source_url.strip()
    ):
        raise StagingIngestError("source_url must be canonical")
    parsed = urlsplit(source.source_url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise StagingIngestError("source_url contains an invalid port") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != "eec.eaeunion.org"
        or parsed.netloc != "eec.eaeunion.org"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.fragment
    ):
        raise StagingIngestError(
            "source_url must be credential-free HTTPS on eec.eaeunion.org"
        )
    if (
        not isinstance(source.media_type, str)
        or _MEDIA_TYPE_RE.fullmatch(source.media_type) is None
    ):
        raise StagingIngestError("source media_type is malformed")
    if not isinstance(source.captured_at, datetime) or source.captured_at.utcoffset() is None:
        raise StagingIngestError("source captured_at must include a timezone")
    if not isinstance(source_bytes, bytes):
        raise StagingIngestError("source bytes must be immutable bytes")
    if (
        isinstance(source.size_bytes, bool)
        or not isinstance(source.size_bytes, int)
        or source.size_bytes < 1
    ):
        raise StagingIngestError("source size_bytes must be a positive integer")
    if source.size_bytes != len(source_bytes):
        raise StagingIngestError("source size mismatch")
    if not isinstance(source.sha256, str) or _SHA256_RE.fullmatch(source.sha256) is None:
        raise StagingIngestError("source sha256 must be lowercase canonical SHA-256")
    if _sha256(source_bytes) != source.sha256:
        raise StagingIngestError("source sha256 mismatch")


def _validate_scope(scope: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(scope, Mapping):
        raise StagingIngestError("ETT scope must be a mapping")
    try:
        canonical = json.loads(_canonical_json(dict(scope)))
    except (TypeError, ValueError) as exc:
        raise StagingIngestError("ETT scope must be canonical JSON") from exc
    if not canonical or any(not isinstance(key, str) or not key for key in canonical):
        raise StagingIngestError("ETT scope must be nonempty with string keys")
    return canonical


def _row_values(row: EttCollectedRow, *, source_id: str) -> dict[str, Any]:
    if isinstance(row.ordinal, bool) or not isinstance(row.ordinal, int) or row.ordinal < 1:
        raise StagingIngestError("ETT row ordinal must be a positive integer")
    if not isinstance(row.hs_code, str) or _HS_CODE_RE.fullmatch(row.hs_code) is None:
        raise StagingIngestError("ETT hs_code must be an exact 10-digit string")
    description = _row_text(row.description, "description")
    supplementary_unit = _row_text(
        row.supplementary_unit, "supplementary_unit", nonempty=False
    )
    duty_text = _row_text(row.duty_text, "duty_text", nonempty=False)
    raw_line = _row_text(row.raw_line, "raw_line")
    if (
        isinstance(row.page_number, bool)
        or not isinstance(row.page_number, int)
        or row.page_number < 1
    ):
        raise StagingIngestError("ETT row page_number must be a positive integer")
    if (
        isinstance(row.line_number, bool)
        or not isinstance(row.line_number, int)
        or row.line_number < 1
    ):
        raise StagingIngestError("ETT row line_number must be a positive integer")
    hash_payload = {
        "hs_code": row.hs_code,
        "description": description,
        "supplementary_unit": supplementary_unit,
        "duty_text": duty_text,
        "page_number": row.page_number,
        "line_number": row.line_number,
        "raw_line": raw_line,
    }
    return {
        "source_id": source_id,
        "hs_code": row.hs_code,
        "description": description,
        "supplementary_unit": supplementary_unit,
        "duty_text": duty_text,
        "raw_line": raw_line,
        "row_sha256": _sha256(_canonical_json(hash_payload).encode("utf-8")),
        "status": COLLECTED_UNVERIFIED,
        "ordinal": row.ordinal,
    }


def _same(actual: Any, expected: Any) -> bool:
    if isinstance(actual, datetime) and isinstance(expected, datetime):
        return actual.replace(tzinfo=actual.tzinfo or timezone.utc) == expected.replace(
            tzinfo=expected.tzinfo or timezone.utc
        )
    return actual == expected


def _assert_exact(
    row: Mapping[str, Any],
    expected: Mapping[str, Any],
    label: str,
    *,
    ignored: Sequence[str] = (),
) -> None:
    for name, value in expected.items():
        if name not in ignored and not _same(row[name], value):
            raise StagingIngestError(f"conflicting existing {label}.{name}")


def ingest_ett_rows(
    session: Session,
    *,
    source: SourceObject,
    source_bytes: bytes,
    rows: Sequence[EttCollectedRow],
    scope: Mapping[str, Any],
    schema: str | None = DEFAULT_SCHEMA,
    now: datetime | None = None,
) -> EttIngestResult:
    """Validate and atomically stage one immutable ETT object.

    No writes occur until all input and current-state checks have passed.  The
    caller must commit (or roll back) the enclosing transaction; an insert-time
    integrity race fails that transaction rather than committing a partial set.
    """

    _validate_source(source, source_bytes)
    canonical_scope = _validate_scope(scope)
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise StagingIngestError("ETT rows must be a bounded sequence")
    if not rows or len(rows) > MAX_ETT_ROWS:
        raise StagingIngestError(f"ETT row count must be between 1 and {MAX_ETT_ROWS}")

    identity = {
        "source_id": source.source_id,
        "source_sha256": source.sha256,
        "source_size_bytes": source.size_bytes,
        "source_url": source.source_url,
        "source_revision": source.source_revision,
        "object_bucket": source.object_bucket,
        "object_key": source.object_key,
        "scope": canonical_scope,
        "parser_version": ETT_PARSER_VERSION,
    }
    identity_hash = _sha256(_canonical_json(identity).encode("utf-8"))
    run_id = f"ett:{identity_hash}"
    row_values = [_row_values(row, source_id=source.source_id) for row in rows]
    ordinals = [value["ordinal"] for value in row_values]
    if ordinals != list(range(1, len(rows) + 1)):
        raise StagingIngestError("ETT ordinals must be exactly contiguous from 1")
    for field in ("ordinal", "row_sha256", "hs_code"):
        values = [value[field] for value in row_values]
        if len(values) != len(set(values)):
            raise StagingIngestError(f"duplicate ETT {field}")

    tables = ett_staging_tables(MetaData(), schema=schema)
    sources = tables["source_objects"]
    runs = tables["ingest_runs"]
    captured = tables["ett_collected_rows"]
    source_values = _source_values(source)
    cursor = {"next_ordinal": len(rows) + 1, "raw_count": len(rows), "complete": True}
    row_provenance = [
        {
            "ordinal": row.ordinal,
            "hs_code": values["hs_code"],
            "row_sha256": values["row_sha256"],
            "page_number": row.page_number,
            "line_number": row.line_number,
        }
        for row, values in zip(rows, row_values)
    ]
    run_expected = {
        "run_id": run_id,
        "source_id": source.source_id,
        "scope": {
            **canonical_scope,
            "source_identity": identity,
            "stage_counts": {
                "normalized": 0,
                "verified": 0,
                "admitted": 0,
            },
            "row_provenance": row_provenance,
        },
        "parser_version": ETT_PARSER_VERSION,
        "status": COLLECTED_UNVERIFIED,
        "raw_count": len(rows),
        "unique_count": len(rows),
        "normalized_count": 0,
        "rejected_count": 0,
        "resume_cursor": cursor,
    }

    existing_source = session.execute(
        select(sources).where(
            or_(
                sources.c.source_id == source.source_id,
                (sources.c.object_bucket == source.object_bucket)
                & (sources.c.object_key == source.object_key),
            )
        )
    ).mappings().all()
    if len(existing_source) > 1:
        raise StagingIngestError("source identity resolves to multiple existing objects")
    if existing_source:
        _assert_exact(existing_source[0], source_values, "source_objects")

    existing_run = (
        session.execute(select(runs).where(runs.c.run_id == run_id))
        .mappings()
        .one_or_none()
    )
    existing_rows = (
        session.execute(
            select(captured).where(captured.c.source_id == source.source_id)
        )
        .mappings()
        .all()
    )
    if existing_run is not None:
        _assert_exact(existing_run, run_expected, "ingest_runs")
        if existing_source == []:
            raise StagingIngestError("deterministic run exists without its source object")
        if len(existing_rows) != len(row_values):
            raise StagingIngestError("deterministic run has incomplete or extra ETT rows")
        by_ordinal = {row["ordinal"]: row for row in existing_rows}
        if len(by_ordinal) != len(existing_rows):
            raise StagingIngestError("deterministic run has duplicate ETT ordinals")
        for expected in row_values:
            actual = by_ordinal.get(expected["ordinal"])
            if actual is None:
                raise StagingIngestError("deterministic run is missing an ETT ordinal")
            _assert_exact(actual, expected, "ett_collected_rows")
        return EttIngestResult(
            run_id, source.source_id, len(rows), len(rows), len(rows) + 1, True
        )
    if existing_rows:
        raise StagingIngestError("ETT rows exist without their deterministic run")

    timestamp = now or datetime.now(timezone.utc)
    if not isinstance(timestamp, datetime) or timestamp.utcoffset() is None:
        raise StagingIngestError("ingest timestamp must include a timezone")
    run_values = {
        **run_expected,
        "started_at": timestamp,
        "completed_at": timestamp,
        "updated_at": timestamp,
    }
    try:
        if not existing_source:
            session.execute(sources.insert().values(**source_values))
        session.execute(runs.insert().values(**run_values))
        session.execute(captured.insert(), row_values)
        count = int(
            session.scalar(
                select(func.count())
                .select_from(captured)
                .where(captured.c.source_id == source.source_id)
            )
            or 0
        )
        if count != len(row_values):
            raise StagingIngestError("ETT atomic insert did not persist the exact row count")
    except IntegrityError as exc:
        raise StagingIngestError("conflicting concurrent ETT staging state") from exc
    return EttIngestResult(
        run_id, source.source_id, len(rows), len(rows), len(rows) + 1, False
    )
