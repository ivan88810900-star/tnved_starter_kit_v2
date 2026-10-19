"""Fail-closed raw NSI page ingestion into an explicitly supplied staging DB.

This module deliberately has no dependency on :mod:`app.db`.  A caller must
provide a staging ``Session`` (or a factory for the bounded worker), and must
provide immutable page and manifest bytes read inside its controlled runtime.
The loader performs no normalization or legal admission.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Integer,
    JSON,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session


COLLECTED_UNVERIFIED = "COLLECTED_UNVERIFIED"
PARSER_VERSION = "nsi-immutable-page-staging-v1"
DEFAULT_SCHEMA = "tariff_ingest"
STABLE_CURSOR_CONTRACT = "nsi-1995-id-version-offset-overlap-v1"
STABLE_CURSOR_SORT = [
    {"field": "id", "direction": "asc"},
    {"field": "versionId", "direction": "asc"},
]
MEDIA_TYPE_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*$"
)


class StagingIngestError(RuntimeError):
    """The candidate page cannot safely advance the staging checkpoint."""


@dataclass(frozen=True)
class SourceObject:
    source_id: str
    authority: str
    dataset: str
    source_url: str
    source_revision: str
    object_bucket: str
    object_key: str
    sha256: str
    size_bytes: int
    media_type: str
    captured_at: datetime


@dataclass(frozen=True)
class ImmutablePage:
    page_source: SourceObject
    manifest_source: SourceObject
    page_bytes: bytes
    manifest_bytes: bytes


@dataclass(frozen=True)
class Checkpoint:
    generation: int = 0
    next_offset: int = 0
    trailing_overlap_sha256: str | None = None
    trailing_overlap_count: int = 0
    source_total: int | None = None
    snapshot_id: str | None = None
    complete: bool = False
    run_id: str | None = None


@dataclass(frozen=True)
class PageResult:
    run_id: str
    next_checkpoint: Checkpoint
    physical_rows: int
    globally_unique_ids: int
    replayed: bool


@dataclass(frozen=True)
class WorkerLimits:
    max_pages: int
    max_rows: int
    max_source_bytes: int
    max_seconds: float

    def validate(self) -> None:
        if self.max_pages <= 0:
            raise ValueError("max_pages must be positive")
        if self.max_rows <= 0:
            raise ValueError("max_rows must be positive")
        if self.max_source_bytes <= 0:
            raise ValueError("max_source_bytes must be positive")
        if not math.isfinite(self.max_seconds) or self.max_seconds <= 0:
            raise ValueError("max_seconds must be finite and positive")


@dataclass(frozen=True)
class WorkerResult:
    checkpoint: Checkpoint
    pages_committed: int
    physical_rows: int
    source_bytes: int


def staging_tables(metadata: MetaData, *, schema: str | None = DEFAULT_SCHEMA) -> dict[str, Table]:
    """Return the existing staging contract (portable to SQLite tests)."""

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
    )
    global_records = Table(
        "sgr_global_records",
        metadata,
        Column("global_record_id", Text, primary_key=True),
        Column("source_record_id", Text, nullable=False),
        Column("source_version_id", Text),
        Column("first_source_id", Text, nullable=False),
        Column("raw_json", Text, nullable=False),
        Column("row_sha256", Text, nullable=False),
        Column("status", Text, nullable=False),
        schema=schema,
    )
    run_rows = Table(
        "sgr_run_rows",
        metadata,
        Column("run_id", Text, primary_key=True),
        Column("ordinal", Integer, nullable=False),
        Column("global_record_id", Text, nullable=False),
        Column("source_id", Text, nullable=False),
        Column("sgr_number", Text, nullable=False),
        Column("date_time_from", Text, nullable=False),
        Column("date_time_to", Text, nullable=False),
        Column("update_datetime", Text, nullable=False),
        Column("date_time_updated", Text, nullable=False),
        Column("row_sha256", Text, primary_key=True),
        Column("status", Text, nullable=False),
        UniqueConstraint("run_id", "ordinal"),
        schema=schema,
    )
    checkpoints = Table(
        "ingest_checkpoints",
        metadata,
        Column("epoch_id", Text, primary_key=True),
        Column("dataset", Text, primary_key=True),
        Column("generation", Integer, nullable=False),
        Column("next_offset", Integer, nullable=False),
        Column("trailing_overlap_sha256", Text),
        Column("trailing_overlap_count", Integer, nullable=False),
        Column("source_total", Integer),
        Column("snapshot_id", Text),
        Column("complete", Boolean, nullable=False),
        Column("run_id", Text),
        Column("updated_at", DateTime(timezone=True), nullable=False),
        schema=schema,
    )
    return {
        "source_objects": source_objects,
        "ingest_runs": ingest_runs,
        "global_records": global_records,
        "run_rows": run_rows,
        "checkpoints": checkpoints,
    }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _row_sha256(item: Mapping[str, Any]) -> str:
    return _sha256(_canonical_json(item).encode("utf-8"))


def _source_identity(item: Mapping[str, Any]) -> str:
    source_id = str(item.get("id") or "").strip()
    return source_id or f"sha256:{_row_sha256(item)}"


def _overlap_sha256(items: Sequence[Mapping[str, Any]]) -> str:
    payload = "".join(f"{_row_sha256(item)}\n" for item in items).encode("ascii")
    return _sha256(payload)


def _decode_object(raw: bytes, *, label: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StagingIngestError(f"{label} is not strict UTF-8 JSON") from exc


def _verify_source(source: SourceObject, raw: bytes) -> None:
    if not source.source_id.strip():
        raise StagingIngestError("source_id is required")
    if source.source_id != source.source_id.strip():
        raise StagingIngestError("source_id must be canonical")
    required_text = {
        "authority": source.authority,
        "dataset": source.dataset,
        "source_revision": source.source_revision,
        "object_bucket": source.object_bucket,
        "object_key": source.object_key,
        "media_type": source.media_type,
    }
    for name, value in required_text.items():
        normalized = str(value or "").strip()
        if not normalized:
            raise StagingIngestError(f"source {name} is required")
        if value != normalized:
            raise StagingIngestError(f"source {name} must be canonical")
    source_url = str(source.source_url or "").strip()
    if source.source_url != source_url:
        raise StagingIngestError("source_url must be canonical")
    parsed_url = urlsplit(source_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise StagingIngestError("source_url must be an absolute HTTP(S) URL")
    if MEDIA_TYPE_RE.fullmatch(source.media_type) is None:
        raise StagingIngestError("source media_type is malformed")
    if not isinstance(source.captured_at, datetime) or source.captured_at.utcoffset() is None:
        raise StagingIngestError("source captured_at must include a timezone")
    if source.size_bytes != len(raw):
        raise StagingIngestError(f"source size mismatch for {source.source_id}")
    if _sha256(raw) != source.sha256:
        raise StagingIngestError(f"source checksum mismatch for {source.source_id}")
    if len(source.sha256) != 64 or any(ch not in "0123456789abcdef" for ch in source.sha256):
        raise StagingIngestError("source SHA-256 must be lowercase hexadecimal")


def _stable_key(item: Mapping[str, Any]) -> tuple[str, str]:
    source_id = str(item.get("id") or "").strip()
    if not source_id:
        raise StagingIngestError("stable-cursor row has no source id")
    return source_id, str(item.get("versionId") or "").strip()


def _ordering_snapshot(
    manifest: Mapping[str, Any],
    *,
    page_source: SourceObject,
    manifest_source: SourceObject,
    payload: Sequence[Mapping[str, Any]],
) -> str:
    proof = manifest.get("ordering_proof")
    if not isinstance(proof, dict):
        raise StagingIngestError("manifest lacks ordering_proof")
    snapshot_id = str(proof.get("snapshot_id") or "").strip()
    kind = str(proof.get("kind") or "").strip()
    if not snapshot_id:
        raise StagingIngestError("ordering_proof requires snapshot_id")
    if snapshot_id not in {page_source.source_revision, manifest_source.source_revision}:
        raise StagingIngestError("ordering proof is not bound to both source revisions")
    if page_source.source_revision != manifest_source.source_revision:
        raise StagingIngestError("page and manifest source revisions differ")
    if kind == "immutable_official_snapshot":
        if set(proof) != {"kind", "snapshot_id", "immutable", "official"}:
            raise StagingIngestError("official snapshot proof has unsupported fields")
        if proof.get("immutable") is not True or proof.get("official") is not True:
            raise StagingIngestError("official immutable snapshot proof is not asserted")
        if len(snapshot_id) != 64 or any(ch not in "0123456789abcdef" for ch in snapshot_id):
            raise StagingIngestError("official snapshot id must be its SHA-256")
        return snapshot_id
    if kind == "stable_cursor":
        if set(proof) != {"kind", "snapshot_id", "sort", "cursor_contract"}:
            raise StagingIngestError("stable cursor proof has unsupported fields")
        if proof.get("sort") != STABLE_CURSOR_SORT:
            raise StagingIngestError("stable cursor proof has an unsupported exact sort")
        if proof.get("cursor_contract") != STABLE_CURSOR_CONTRACT:
            raise StagingIngestError("stable cursor proof has an unsupported contract")
        keys = [_stable_key(item) for item in payload]
        if any(left >= right for left, right in zip(keys, keys[1:])):
            raise StagingIngestError("stable cursor page is not strictly ordered")
        return snapshot_id
    raise StagingIngestError("unsupported ordering proof")


def _manifest_int(manifest: Mapping[str, Any], key: str) -> int:
    value = manifest.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise StagingIngestError(f"manifest field {key!r} must be a non-negative integer")
    return value


def _table_map(session: Session, schema: str | None) -> dict[str, Table]:
    # Define rather than import application models: staging is an isolated DB contract.
    return staging_tables(MetaData(), schema=schema)


def _insert_ignore(session: Session, table: Table, values: Mapping[str, Any]) -> None:
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        session.execute(postgresql_insert(table).values(**values).on_conflict_do_nothing())
    elif dialect == "sqlite":
        session.execute(sqlite_insert(table).values(**values).on_conflict_do_nothing())
    else:
        session.execute(table.insert().values(**values))


def _assert_exact_existing(
    session: Session,
    table: Table,
    key_columns: Sequence[str],
    values: Mapping[str, Any],
    *,
    ignored_columns: Sequence[str] = (),
) -> None:
    predicate = [table.c[name] == values[name] for name in key_columns]
    row = session.execute(select(table).where(*predicate)).mappings().one_or_none()
    if row is None:
        raise StagingIngestError(f"idempotent insert missing from {table.name}")
    for name, expected in values.items():
        if name in ignored_columns:
            continue
        actual = row[name]
        if isinstance(actual, datetime) and isinstance(expected, datetime):
            if actual.replace(tzinfo=actual.tzinfo or timezone.utc) == expected.replace(
                tzinfo=expected.tzinfo or timezone.utc
            ):
                continue
        if actual != expected:
            raise StagingIngestError(f"conflicting replay for {table.name}.{name}")


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


def load_checkpoint(
    session: Session,
    *,
    epoch_id: str,
    dataset: str,
    schema: str | None = DEFAULT_SCHEMA,
    _validate_history: bool = True,
) -> Checkpoint:
    """Read the single CAS checkpoint row for one isolated epoch."""

    canonical_epoch = str(epoch_id or "").strip()
    canonical_dataset = str(dataset or "").strip()
    if not canonical_epoch or epoch_id != canonical_epoch:
        raise ValueError("staging epoch_id must be nonblank and canonical")
    if not canonical_dataset or dataset != canonical_dataset:
        raise ValueError("staging dataset must be nonblank and canonical")

    tables = _table_map(session, schema)
    checkpoints = tables["checkpoints"]
    row = session.execute(
        select(checkpoints).where(
            checkpoints.c.epoch_id == canonical_epoch,
            checkpoints.c.dataset == canonical_dataset,
        )
    ).mappings().one_or_none()
    if row is None:
        return Checkpoint()
    generation = int(row["generation"])
    next_offset = int(row["next_offset"])
    overlap_count = int(row["trailing_overlap_count"])
    overlap_sha = row["trailing_overlap_sha256"]
    source_total = row["source_total"]
    snapshot_id = row["snapshot_id"]
    run_id = row["run_id"]
    complete = row["complete"] is True
    if generation < 1 or next_offset < 0:
        raise StagingIngestError("stored checkpoint is malformed")
    if not isinstance(source_total, int) or source_total < 0 or next_offset > source_total:
        raise StagingIngestError("stored checkpoint has an invalid source total")
    if not isinstance(snapshot_id, str) or not snapshot_id.strip() or snapshot_id != snapshot_id.strip():
        raise StagingIngestError("stored checkpoint has an invalid snapshot id")
    if not isinstance(run_id, str) or not run_id.strip() or run_id != run_id.strip():
        raise StagingIngestError("stored checkpoint has an invalid run id")
    if overlap_count < 0 or overlap_count > 20:
        raise StagingIngestError("stored checkpoint has an invalid overlap count")
    if overlap_count == 0:
        if overlap_sha is not None:
            raise StagingIngestError("stored checkpoint has an unexpected overlap hash")
    elif not isinstance(overlap_sha, str) or len(overlap_sha) != 64 or any(
        ch not in "0123456789abcdef" for ch in overlap_sha
    ):
        raise StagingIngestError("stored checkpoint has an invalid overlap hash")
    if complete and next_offset != source_total:
        raise StagingIngestError("stored checkpoint completion does not reconcile")
    if generation > max(1, next_offset):
        raise StagingIngestError("stored checkpoint generation is impossible")

    run = session.execute(
        select(tables["ingest_runs"]).where(tables["ingest_runs"].c.run_id == run_id)
    ).mappings().one_or_none()
    expected_cursor = {
        "next_offset": next_offset,
        "trailing_overlap_sha256": overlap_sha,
        "trailing_overlap_count": overlap_count,
        "source_total": source_total,
        "snapshot_id": snapshot_id,
        "complete": complete,
    }
    scope = run["scope"] if run is not None else None
    required_scope = {
        "epoch_id",
        "dataset",
        "logical_offset",
        "request_offset",
        "page_source_id",
        "page_source_sha256",
        "page_source_size_bytes",
        "manifest_source_id",
        "manifest_source_sha256",
        "manifest_source_size_bytes",
        "ordering_proof",
    }
    logical_offset = scope.get("logical_offset") if isinstance(scope, dict) else None
    request_offset = scope.get("request_offset") if isinstance(scope, dict) else None
    page_source_id = scope.get("page_source_id") if isinstance(scope, dict) else None
    page_source_sha256 = scope.get("page_source_sha256") if isinstance(scope, dict) else None
    page_source_size_bytes = scope.get("page_source_size_bytes") if isinstance(scope, dict) else None
    manifest_source_id = scope.get("manifest_source_id") if isinstance(scope, dict) else None
    manifest_source_sha256 = (
        scope.get("manifest_source_sha256") if isinstance(scope, dict) else None
    )
    manifest_source_size_bytes = (
        scope.get("manifest_source_size_bytes") if isinstance(scope, dict) else None
    )
    ordering_proof = scope.get("ordering_proof") if isinstance(scope, dict) else None
    raw_count = run["raw_count"] if run is not None else None
    unique_count = run["unique_count"] if run is not None else None
    proof_kind = ordering_proof.get("kind") if isinstance(ordering_proof, dict) else None
    stable_proof_valid = (
        isinstance(ordering_proof, dict)
        and set(ordering_proof) == {"kind", "snapshot_id", "sort", "cursor_contract"}
        and proof_kind == "stable_cursor"
        and ordering_proof.get("snapshot_id") == snapshot_id
        and ordering_proof.get("sort") == STABLE_CURSOR_SORT
        and ordering_proof.get("cursor_contract") == STABLE_CURSOR_CONTRACT
    )
    immutable_proof_valid = (
        isinstance(ordering_proof, dict)
        and set(ordering_proof) == {"kind", "snapshot_id", "immutable", "official"}
        and proof_kind == "immutable_official_snapshot"
        and ordering_proof.get("snapshot_id") == snapshot_id
        and ordering_proof.get("immutable") is True
        and ordering_proof.get("official") is True
        and len(snapshot_id) == 64
        and all(ch in "0123456789abcdef" for ch in snapshot_id)
    )
    if (
        run is None
        or run["parser_version"] != PARSER_VERSION
        or run["status"] != COLLECTED_UNVERIFIED
        or run["resume_cursor"] != expected_cursor
        or not isinstance(scope, dict)
        or set(scope) != required_scope
        or scope.get("epoch_id") != canonical_epoch
        or scope.get("dataset") != canonical_dataset
        or isinstance(logical_offset, bool)
        or not isinstance(logical_offset, int)
        or logical_offset < 0
        or isinstance(request_offset, bool)
        or not isinstance(request_offset, int)
        or request_offset < 0
        or request_offset > logical_offset
        or not isinstance(page_source_id, str)
        or not page_source_id.strip()
        or page_source_id != page_source_id.strip()
        or not isinstance(page_source_sha256, str)
        or len(page_source_sha256) != 64
        or any(ch not in "0123456789abcdef" for ch in page_source_sha256)
        or isinstance(page_source_size_bytes, bool)
        or not isinstance(page_source_size_bytes, int)
        or page_source_size_bytes < 0
        or not isinstance(manifest_source_id, str)
        or not manifest_source_id.strip()
        or manifest_source_id != manifest_source_id.strip()
        or manifest_source_id == page_source_id
        or not isinstance(manifest_source_sha256, str)
        or len(manifest_source_sha256) != 64
        or any(ch not in "0123456789abcdef" for ch in manifest_source_sha256)
        or isinstance(manifest_source_size_bytes, bool)
        or not isinstance(manifest_source_size_bytes, int)
        or manifest_source_size_bytes < 0
        or run["source_id"] != page_source_id
        or isinstance(raw_count, bool)
        or not isinstance(raw_count, int)
        or raw_count < 0
        or unique_count != raw_count
        or run["normalized_count"] != 0
        or run["rejected_count"] != 0
        or logical_offset + raw_count != next_offset
        or (source_total > 0 and raw_count == 0)
        or not (stable_proof_valid or immutable_proof_valid)
    ):
        raise StagingIngestError("stored checkpoint is not bound to its ingest run")

    source_rows = session.execute(
        select(tables["source_objects"]).where(
            tables["source_objects"].c.source_id.in_([page_source_id, manifest_source_id])
        )
    ).mappings().all()
    sources = {source["source_id"]: source for source in source_rows}
    page_source = sources.get(page_source_id)
    manifest_source = sources.get(manifest_source_id)
    if (
        page_source is None
        or manifest_source is None
        or len(sources) != 2
        or page_source["dataset"] != canonical_dataset
        or manifest_source["dataset"] != canonical_dataset
        or page_source["source_revision"] != snapshot_id
        or manifest_source["source_revision"] != snapshot_id
        or page_source["authority"] != manifest_source["authority"]
        or page_source["object_bucket"] != manifest_source["object_bucket"]
        or page_source["status"] != COLLECTED_UNVERIFIED
        or manifest_source["status"] != COLLECTED_UNVERIFIED
        or page_source["sha256"] != page_source_sha256
        or page_source["size_bytes"] != page_source_size_bytes
        or manifest_source["sha256"] != manifest_source_sha256
        or manifest_source["size_bytes"] != manifest_source_size_bytes
        or run_id
        != f"{canonical_epoch}:{logical_offset}:{page_source['sha256'][:16]}"
    ):
        raise StagingIngestError("stored checkpoint source lineage is inconsistent")

    run_rows = tables["run_rows"]
    global_records = tables["global_records"]
    def physical_rows_for(expected_run_id: str) -> list[Mapping[str, Any]]:
        return session.execute(
            select(
                run_rows.c.run_id,
                run_rows.c.ordinal,
                run_rows.c.source_id,
                run_rows.c.global_record_id,
                run_rows.c.sgr_number,
                run_rows.c.date_time_from,
                run_rows.c.date_time_to,
                run_rows.c.update_datetime,
                run_rows.c.date_time_updated,
                run_rows.c.row_sha256,
                run_rows.c.status,
                global_records.c.global_record_id.label("bound_global_record_id"),
                global_records.c.source_record_id.label("global_source_record_id"),
                global_records.c.source_version_id.label("global_source_version_id"),
                global_records.c.first_source_id.label("global_first_source_id"),
                global_records.c.raw_json.label("global_raw_json"),
                global_records.c.row_sha256.label("global_row_sha256"),
                global_records.c.status.label("global_status"),
            )
            .outerjoin(
                global_records,
                global_records.c.global_record_id == run_rows.c.global_record_id,
            )
            .where(run_rows.c.run_id == expected_run_id)
            .order_by(run_rows.c.ordinal)
        ).mappings().all()

    physical_rows = physical_rows_for(run_id)

    first_source_ids: set[str] = set()
    first_capture_pairs: set[tuple[str, str]] = set()

    def physical_row_matches(
        index: int,
        physical: Mapping[str, Any],
        *,
        expected_run_id: str = run_id,
        expected_logical_offset: int = logical_offset,
        expected_page_source_id: str = page_source_id,
        collect_first_capture: bool = True,
    ) -> bool:
        ordinal = expected_logical_offset + index + 1
        raw_json = physical["global_raw_json"]
        first_source_id = physical["global_first_source_id"]
        if (
            physical["run_id"] != expected_run_id
            or physical["ordinal"] != ordinal
            or physical["source_id"] != expected_page_source_id
            or physical["status"] != COLLECTED_UNVERIFIED
            or physical["bound_global_record_id"] != physical["global_record_id"]
            or physical["global_status"] != COLLECTED_UNVERIFIED
            or not isinstance(raw_json, str)
            or not isinstance(first_source_id, str)
            or not first_source_id.strip()
            or first_source_id != first_source_id.strip()
        ):
            return False
        try:
            item = json.loads(raw_json)
            if not isinstance(item, dict) or _canonical_json(item) != raw_json:
                return False
            record = _record_values(item, first_source_id=first_source_id)
            expected_physical = _physical_values(
                item,
                record=record,
                run_id=expected_run_id,
                source_id=expected_page_source_id,
                ordinal=ordinal,
            )
        except (json.JSONDecodeError, StagingIngestError, TypeError, ValueError):
            return False
        stored_record = {
            "global_record_id": physical["bound_global_record_id"],
            "source_record_id": physical["global_source_record_id"],
            "source_version_id": physical["global_source_version_id"],
            "first_source_id": first_source_id,
            "raw_json": raw_json,
            "row_sha256": physical["global_row_sha256"],
            "status": physical["global_status"],
        }
        stored_physical = {
            key: physical[key]
            for key in (
                "run_id",
                "source_id",
                "ordinal",
                "global_record_id",
                "sgr_number",
                "date_time_from",
                "date_time_to",
                "update_datetime",
                "date_time_updated",
                "row_sha256",
                "status",
            )
        }
        if stored_record != record or stored_physical != expected_physical:
            return False
        if collect_first_capture:
            first_source_ids.add(first_source_id)
            first_capture_pairs.add((record["global_record_id"], first_source_id))
        return True

    if len(physical_rows) != raw_count or any(
        not physical_row_matches(index, physical)
        for index, physical in enumerate(physical_rows)
    ):
        raise StagingIngestError("stored checkpoint physical capture is inconsistent")
    if first_source_ids:
        first_sources = session.execute(
            select(tables["source_objects"]).where(
                tables["source_objects"].c.source_id.in_(first_source_ids)
            )
        ).mappings().all()
        if len(first_sources) != len(first_source_ids) or any(
            source["dataset"] != canonical_dataset
            or source["status"] != COLLECTED_UNVERIFIED
            for source in first_sources
        ):
            raise StagingIngestError("stored checkpoint physical capture is inconsistent")
        capture_rows = session.execute(
            select(
                run_rows.c.run_id.label("capture_run_id"),
                run_rows.c.global_record_id,
                run_rows.c.source_id,
                run_rows.c.ordinal.label("capture_ordinal"),
                run_rows.c.sgr_number.label("capture_sgr_number"),
                run_rows.c.date_time_from.label("capture_date_time_from"),
                run_rows.c.date_time_to.label("capture_date_time_to"),
                run_rows.c.update_datetime.label("capture_update_datetime"),
                run_rows.c.date_time_updated.label("capture_date_time_updated"),
                run_rows.c.row_sha256.label("capture_row_sha256"),
                run_rows.c.status.label("capture_status"),
                tables["ingest_runs"].c.source_id.label("capture_run_source_id"),
                tables["ingest_runs"].c.scope.label("capture_scope"),
                tables["ingest_runs"].c.status.label("capture_run_status"),
                tables["ingest_runs"].c.parser_version.label("capture_parser_version"),
                tables["ingest_runs"].c.raw_count.label("capture_raw_count"),
                tables["ingest_runs"].c.unique_count.label("capture_unique_count"),
                tables["ingest_runs"].c.normalized_count.label("capture_normalized_count"),
                tables["ingest_runs"].c.rejected_count.label("capture_rejected_count"),
                tables["ingest_runs"].c.resume_cursor.label("capture_resume_cursor"),
            )
            .join(
                tables["ingest_runs"],
                tables["ingest_runs"].c.run_id == run_rows.c.run_id,
            )
            .where(
                run_rows.c.source_id.in_(first_source_ids),
                run_rows.c.global_record_id.in_(
                    {global_record_id for global_record_id, _source_id in first_capture_pairs}
                ),
            )
        ).mappings().all()
        run_validation: dict[str, bool] = {}

        def capture_run_is_valid(capture: Mapping[str, Any]) -> bool:
            capture_run_id = capture["capture_run_id"]
            if capture_run_id in run_validation:
                return run_validation[capture_run_id]
            scope = capture["capture_scope"]
            cursor = capture["capture_resume_cursor"]
            valid = False
            if isinstance(scope, dict) and isinstance(cursor, dict):
                logical = scope.get("logical_offset")
                request = scope.get("request_offset")
                capture_page_source = scope.get("page_source_id")
                capture_page_sha256 = scope.get("page_source_sha256")
                capture_page_size_bytes = scope.get("page_source_size_bytes")
                capture_manifest_source = scope.get("manifest_source_id")
                capture_manifest_sha256 = scope.get("manifest_source_sha256")
                capture_manifest_size_bytes = scope.get("manifest_source_size_bytes")
                proof = scope.get("ordering_proof")
                capture_raw_count = capture["capture_raw_count"]
                next_cursor = cursor.get("next_offset")
                cursor_total = cursor.get("source_total")
                cursor_overlap_count = cursor.get("trailing_overlap_count")
                cursor_overlap_sha = cursor.get("trailing_overlap_sha256")
                cursor_snapshot = cursor.get("snapshot_id")
                cursor_complete = cursor.get("complete")
                manifest_overlap = (
                    logical - request
                    if isinstance(logical, int)
                    and not isinstance(logical, bool)
                    and isinstance(request, int)
                    and not isinstance(request, bool)
                    else None
                )
                expected_trailing_count = (
                    min(20, manifest_overlap + capture_raw_count)
                    if isinstance(manifest_overlap, int)
                    and isinstance(capture_raw_count, int)
                    and not isinstance(capture_raw_count, bool)
                    else None
                )
                stable = (
                    isinstance(proof, dict)
                    and set(proof) == {"kind", "snapshot_id", "sort", "cursor_contract"}
                    and proof.get("kind") == "stable_cursor"
                    and proof.get("snapshot_id") == cursor_snapshot
                    and proof.get("sort") == STABLE_CURSOR_SORT
                    and proof.get("cursor_contract") == STABLE_CURSOR_CONTRACT
                )
                immutable = (
                    isinstance(proof, dict)
                    and set(proof) == {"kind", "snapshot_id", "immutable", "official"}
                    and proof.get("kind") == "immutable_official_snapshot"
                    and proof.get("snapshot_id") == cursor_snapshot
                    and proof.get("immutable") is True
                    and proof.get("official") is True
                    and isinstance(cursor_snapshot, str)
                    and len(cursor_snapshot) == 64
                    and all(ch in "0123456789abcdef" for ch in cursor_snapshot)
                )
                structure_valid = (
                    set(scope) == required_scope
                    and isinstance(scope.get("epoch_id"), str)
                    and bool(scope["epoch_id"].strip())
                    and scope["epoch_id"] == scope["epoch_id"].strip()
                    and scope.get("dataset") == canonical_dataset
                    and isinstance(logical, int)
                    and not isinstance(logical, bool)
                    and logical >= 0
                    and isinstance(request, int)
                    and not isinstance(request, bool)
                    and 0 <= request <= logical
                    and (
                        (logical == 0 and request == 0 and manifest_overlap == 0)
                        or (logical > 0 and 1 <= manifest_overlap <= 20)
                    )
                    and isinstance(capture_page_source, str)
                    and bool(capture_page_source.strip())
                    and capture_page_source == capture_page_source.strip()
                    and isinstance(capture_page_sha256, str)
                    and len(capture_page_sha256) == 64
                    and all(ch in "0123456789abcdef" for ch in capture_page_sha256)
                    and isinstance(capture_page_size_bytes, int)
                    and not isinstance(capture_page_size_bytes, bool)
                    and capture_page_size_bytes >= 0
                    and isinstance(capture_manifest_source, str)
                    and bool(capture_manifest_source.strip())
                    and capture_manifest_source == capture_manifest_source.strip()
                    and capture_manifest_source != capture_page_source
                    and isinstance(capture_manifest_sha256, str)
                    and len(capture_manifest_sha256) == 64
                    and all(ch in "0123456789abcdef" for ch in capture_manifest_sha256)
                    and isinstance(capture_manifest_size_bytes, int)
                    and not isinstance(capture_manifest_size_bytes, bool)
                    and capture_manifest_size_bytes >= 0
                    and capture["capture_parser_version"] == PARSER_VERSION
                    and capture["capture_run_status"] == COLLECTED_UNVERIFIED
                    and capture["capture_run_source_id"] == capture_page_source
                    and isinstance(capture_raw_count, int)
                    and not isinstance(capture_raw_count, bool)
                    and capture_raw_count >= 0
                    and (cursor_total == 0 or capture_raw_count > 0)
                    and capture["capture_unique_count"] == capture_raw_count
                    and capture["capture_normalized_count"] == 0
                    and capture["capture_rejected_count"] == 0
                    and set(cursor)
                    == {
                        "next_offset",
                        "trailing_overlap_sha256",
                        "trailing_overlap_count",
                        "source_total",
                        "snapshot_id",
                        "complete",
                    }
                    and next_cursor == logical + capture_raw_count
                    and isinstance(cursor_total, int)
                    and not isinstance(cursor_total, bool)
                    and cursor_total >= next_cursor
                    and isinstance(cursor_complete, bool)
                    and (not cursor_complete or next_cursor == cursor_total)
                    and isinstance(cursor_overlap_count, int)
                    and not isinstance(cursor_overlap_count, bool)
                    and cursor_overlap_count == expected_trailing_count
                    and (
                        (cursor_overlap_count == 0 and cursor_overlap_sha is None)
                        or (
                            cursor_overlap_count > 0
                            and isinstance(cursor_overlap_sha, str)
                            and len(cursor_overlap_sha) == 64
                            and all(ch in "0123456789abcdef" for ch in cursor_overlap_sha)
                        )
                    )
                    and (stable or immutable)
                )
                if structure_valid:
                    capture_sources = session.execute(
                        select(tables["source_objects"]).where(
                            tables["source_objects"].c.source_id.in_(
                                [capture_page_source, capture_manifest_source]
                            )
                        )
                    ).mappings().all()
                    capture_source_map = {
                        source["source_id"]: source for source in capture_sources
                    }
                    capture_page = capture_source_map.get(capture_page_source)
                    capture_manifest = capture_source_map.get(capture_manifest_source)
                    capture_physical = physical_rows_for(capture_run_id)
                    valid = (
                        capture_page is not None
                        and capture_manifest is not None
                        and len(capture_source_map) == 2
                        and capture_page["dataset"] == canonical_dataset
                        and capture_manifest["dataset"] == canonical_dataset
                        and capture_page["source_revision"] == cursor_snapshot
                        and capture_manifest["source_revision"] == cursor_snapshot
                        and capture_page["sha256"] == capture_page_sha256
                        and capture_page["size_bytes"] == capture_page_size_bytes
                        and capture_manifest["sha256"] == capture_manifest_sha256
                        and capture_manifest["size_bytes"] == capture_manifest_size_bytes
                        and capture_run_id
                        == f"{scope['epoch_id']}:{logical}:{capture_page['sha256'][:16]}"
                        and capture_page["authority"] == capture_manifest["authority"]
                        and capture_page["object_bucket"] == capture_manifest["object_bucket"]
                        and capture_page["status"] == COLLECTED_UNVERIFIED
                        and capture_manifest["status"] == COLLECTED_UNVERIFIED
                        and len(capture_physical) == capture_raw_count
                        and all(
                            physical_row_matches(
                                index,
                                row,
                                expected_run_id=capture_run_id,
                                expected_logical_offset=logical,
                                expected_page_source_id=capture_page_source,
                                collect_first_capture=False,
                            )
                            for index, row in enumerate(capture_physical)
                        )
                        and (
                            logical > 0
                            or cursor_overlap_sha
                            == _sha256(
                                "".join(
                                    f"{row['row_sha256']}\n"
                                    for row in capture_physical[-cursor_overlap_count:]
                                ).encode("ascii")
                            )
                        )
                    )
            run_validation[capture_run_id] = valid
            return valid

        if _validate_history:
            history_rows = session.execute(
                select(
                    tables["ingest_runs"].c.run_id.label("capture_run_id"),
                    tables["ingest_runs"].c.source_id.label("capture_run_source_id"),
                    tables["ingest_runs"].c.scope.label("capture_scope"),
                    tables["ingest_runs"].c.status.label("capture_run_status"),
                    tables["ingest_runs"].c.parser_version.label("capture_parser_version"),
                    tables["ingest_runs"].c.raw_count.label("capture_raw_count"),
                    tables["ingest_runs"].c.unique_count.label("capture_unique_count"),
                    tables["ingest_runs"].c.normalized_count.label("capture_normalized_count"),
                    tables["ingest_runs"].c.rejected_count.label("capture_rejected_count"),
                    tables["ingest_runs"].c.resume_cursor.label("capture_resume_cursor"),
                )
            ).mappings().all()
            committed_history = [
                candidate
                for candidate in history_rows
                if isinstance(candidate["capture_scope"], dict)
                and candidate["capture_scope"].get("epoch_id") == canonical_epoch
                and candidate["capture_scope"].get("dataset") == canonical_dataset
            ]
            committed_history.sort(
                key=lambda candidate: candidate["capture_scope"].get("logical_offset", -1)
            )
            history_next_offset = 0
            history_valid = len(committed_history) == generation
            for history_index, candidate in enumerate(committed_history):
                history_scope = candidate["capture_scope"]
                history_cursor = candidate["capture_resume_cursor"]
                history_logical = history_scope.get("logical_offset")
                if (
                    not history_valid
                    or not isinstance(history_cursor, dict)
                    or history_logical != history_next_offset
                    or history_cursor.get("snapshot_id") != snapshot_id
                    or history_cursor.get("source_total") != source_total
                    or history_cursor.get("complete") is not (
                        complete if history_index == generation - 1 else False
                    )
                    or not capture_run_is_valid(candidate)
                ):
                    history_valid = False
                    break
                history_next_offset = history_cursor["next_offset"]
            if (
                not history_valid
                or history_next_offset != next_offset
                or not committed_history
                or committed_history[-1]["capture_run_id"] != run_id
            ):
                raise StagingIngestError("stored checkpoint history is inconsistent")

        proven_first_captures: set[tuple[str, str]] = set()
        global_by_id = {
            physical["global_record_id"]: physical for physical in physical_rows
        }
        for capture in capture_rows:
            current = global_by_id.get(capture["global_record_id"])
            if current is None or not capture_run_is_valid(capture):
                continue
            try:
                item = json.loads(current["global_raw_json"])
                expected_capture = _physical_values(
                    item,
                    record={
                        "global_record_id": current["bound_global_record_id"],
                        "row_sha256": current["global_row_sha256"],
                    },
                    run_id=capture["capture_run_id"],
                    source_id=capture["source_id"],
                    ordinal=capture["capture_ordinal"],
                )
            except (json.JSONDecodeError, StagingIngestError, TypeError, ValueError):
                continue
            stored_capture = {
                key: capture[f"capture_{key}"]
                for key in (
                    "run_id",
                    "ordinal",
                    "sgr_number",
                    "date_time_from",
                    "date_time_to",
                    "update_datetime",
                    "date_time_updated",
                    "row_sha256",
                    "status",
                )
            }
            stored_capture["source_id"] = capture["source_id"]
            stored_capture["global_record_id"] = capture["global_record_id"]
            if stored_capture == expected_capture:
                proven_first_captures.add(
                    (capture["global_record_id"], capture["source_id"])
                )
        if not first_capture_pairs.issubset(proven_first_captures):
            raise StagingIngestError("stored checkpoint physical capture is inconsistent")
    elif _validate_history:
        empty_history_rows = session.execute(
            select(
                tables["ingest_runs"].c.run_id,
                tables["ingest_runs"].c.scope,
            )
        ).mappings().all()
        empty_history = [
            candidate
            for candidate in empty_history_rows
            if isinstance(candidate["scope"], dict)
            and candidate["scope"].get("epoch_id") == canonical_epoch
            and candidate["scope"].get("dataset") == canonical_dataset
        ]
        if (
            generation != 1
            or next_offset != 0
            or source_total != 0
            or len(empty_history) != 1
            or empty_history[0]["run_id"] != run_id
        ):
            raise StagingIngestError("stored checkpoint history is inconsistent")
    return Checkpoint(
        generation=generation,
        next_offset=next_offset,
        trailing_overlap_sha256=overlap_sha,
        trailing_overlap_count=overlap_count,
        source_total=source_total,
        snapshot_id=snapshot_id,
        complete=complete,
        run_id=run_id,
    )


def _record_values(item: Mapping[str, Any], *, first_source_id: str) -> dict[str, Any]:
    source_record_id = _source_identity(item)
    source_version_id = str(item.get("versionId") or "").strip() or None
    raw_json = _canonical_json(item)
    global_record_id = _sha256(
        _canonical_json([source_record_id, source_version_id]).encode("utf-8")
    )
    return {
        "global_record_id": global_record_id,
        "source_record_id": source_record_id,
        "source_version_id": source_version_id,
        "first_source_id": first_source_id,
        "raw_json": raw_json,
        "row_sha256": _sha256(raw_json.encode("utf-8")),
        "status": COLLECTED_UNVERIFIED,
    }


def _physical_values(
    item: Mapping[str, Any],
    *,
    record: Mapping[str, Any],
    run_id: str,
    source_id: str,
    ordinal: int,
) -> dict[str, Any]:
    data = item.get("data")
    if not isinstance(data, dict):
        raise StagingIngestError("NSI row has no data object")
    sgr_number = str(data.get("NUMB_DOC") or "").strip()
    if not sgr_number:
        raise StagingIngestError("NSI row has no NUMB_DOC")
    return {
        "run_id": run_id,
        "source_id": source_id,
        "ordinal": ordinal,
        "global_record_id": record["global_record_id"],
        "sgr_number": sgr_number,
        "date_time_from": str(item.get("dateTimeFrom") or ""),
        "date_time_to": str(item.get("dateTimeTo") or ""),
        "update_datetime": str(item.get("updateDateTime") or ""),
        "date_time_updated": str(item.get("dateTimeUpdated") or ""),
        "row_sha256": record["row_sha256"],
        "status": COLLECTED_UNVERIFIED,
    }


def ingest_page(
    session: Session,
    *,
    page: ImmutablePage,
    checkpoint: Checkpoint,
    epoch_id: str,
    dataset: str,
    schema: str | None = DEFAULT_SCHEMA,
    now: datetime | None = None,
) -> PageResult:
    """Atomically stage one verified page inside the caller's transaction."""

    if session is None:
        raise ValueError("an explicit staging Session is required")
    canonical_epoch = str(epoch_id or "").strip()
    expected_dataset = str(dataset or "").strip()
    if not canonical_epoch or epoch_id != canonical_epoch:
        raise ValueError("staging epoch_id must be nonblank and canonical")
    if not expected_dataset or dataset != expected_dataset:
        raise ValueError("staging dataset must be nonblank and canonical")
    if page.page_source.dataset != expected_dataset or page.manifest_source.dataset != expected_dataset:
        raise StagingIngestError("source dataset does not match the requested staging dataset")
    if page.page_source.authority != page.manifest_source.authority:
        raise StagingIngestError("page and manifest source authorities differ")
    if page.page_source.object_bucket != page.manifest_source.object_bucket:
        raise StagingIngestError("page and manifest source buckets differ")
    _verify_source(page.page_source, page.page_bytes)
    _verify_source(page.manifest_source, page.manifest_bytes)
    payload = _decode_object(page.page_bytes, label="page")
    manifest = _decode_object(page.manifest_bytes, label="manifest")
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise StagingIngestError("page JSON must be an array of objects")
    if not isinstance(manifest, dict):
        raise StagingIngestError("manifest JSON must be an object")

    snapshot_id = _ordering_snapshot(
        manifest,
        page_source=page.page_source,
        manifest_source=page.manifest_source,
        payload=payload,
    )
    logical_offset = _manifest_int(manifest, "logical_offset")
    request_offset = _manifest_int(manifest, "request_offset")
    returned_count = _manifest_int(manifest, "returned_count")
    overlap_count = _manifest_int(manifest, "overlap_count")
    source_advance = _manifest_int(manifest, "source_advance")
    next_offset = _manifest_int(manifest, "next_offset")
    total_before = _manifest_int(manifest, "total_before")
    total_after = _manifest_int(manifest, "total_after")
    if returned_count != len(payload):
        raise StagingIngestError("manifest returned_count does not match page")
    if total_before != total_after or manifest.get("drift_detected") is True:
        raise StagingIngestError("source total drift forbids checkpoint advancement")
    if request_offset + returned_count > total_after:
        raise StagingIngestError("page exceeds stable source total")
    if next_offset != logical_offset + source_advance:
        raise StagingIngestError("manifest cursor arithmetic is inconsistent")
    if source_advance != returned_count - overlap_count:
        raise StagingIngestError("manifest source_advance is inconsistent")
    if str(manifest.get("page_sha256") or "") != _sha256(_canonical_json(payload).encode("utf-8")):
        raise StagingIngestError("manifest page checksum mismatch")

    trailing_count = min(20, len(payload))
    trailing_overlap_sha256 = _overlap_sha256(payload[-trailing_count:]) if trailing_count else None
    complete = (
        manifest.get("terminal_total_reconciled") is True
        and next_offset == total_after
        and total_before == total_after
    )
    cursor = {
        "next_offset": next_offset,
        "trailing_overlap_sha256": trailing_overlap_sha256,
        "trailing_overlap_count": trailing_count,
        "source_total": total_after,
        "snapshot_id": snapshot_id,
        "complete": complete,
    }
    scope = {
        "epoch_id": epoch_id,
        "dataset": dataset,
        "logical_offset": logical_offset,
        "request_offset": request_offset,
        "page_source_id": page.page_source.source_id,
        "page_source_sha256": page.page_source.sha256,
        "page_source_size_bytes": page.page_source.size_bytes,
        "manifest_source_id": page.manifest_source.source_id,
        "manifest_source_sha256": page.manifest_source.sha256,
        "manifest_source_size_bytes": page.manifest_source.size_bytes,
        "ordering_proof": manifest["ordering_proof"],
    }
    run_id = f"{epoch_id}:{logical_offset}:{page.page_source.sha256[:16]}"
    new_payload = payload[overlap_count:]
    if len(new_payload) != source_advance:
        raise StagingIngestError("page new-row slice is inconsistent")
    seen: dict[str, str] = {}
    global_values: list[dict[str, Any]] = []
    physical_values: list[dict[str, Any]] = []
    for index, item in enumerate(new_payload):
        record = _record_values(item, first_source_id=page.page_source.source_id)
        global_id = str(record["global_record_id"])
        if global_id in seen:
            raise StagingIngestError(
                f"duplicate global source ID/version in page: {record['source_record_id']}"
            )
        seen[global_id] = str(record["row_sha256"])
        global_values.append(record)
        physical_values.append(
            _physical_values(
                item,
                record=record,
                run_id=run_id,
                source_id=page.page_source.source_id,
                ordinal=logical_offset + index + 1,
            )
        )

    tables = _table_map(session, schema)
    runs = tables["ingest_runs"]
    existing_run = session.execute(select(runs).where(runs.c.run_id == run_id)).mappings().one_or_none()
    if existing_run is not None:
        stored_cursor = existing_run["resume_cursor"]
        expected_run = {
            "source_id": page.page_source.source_id,
            "scope": scope,
            "parser_version": PARSER_VERSION,
            "status": COLLECTED_UNVERIFIED,
            "raw_count": len(physical_values),
            "unique_count": len(seen),
            "normalized_count": 0,
            "rejected_count": 0,
            "resume_cursor": cursor,
        }
        if not isinstance(stored_cursor, dict) or any(
            existing_run[name] != expected for name, expected in expected_run.items()
        ):
            raise StagingIngestError("conflicting deterministic run_id")
        for source in (page.page_source, page.manifest_source):
            _assert_exact_existing(
                session,
                tables["source_objects"],
                ["source_id"],
                _source_values(source),
            )
        for values in global_values:
            _assert_exact_existing(
                session,
                tables["global_records"],
                ["global_record_id"],
                values,
                ignored_columns=["first_source_id"],
            )
        for values in physical_values:
            _assert_exact_existing(
                session,
                tables["run_rows"],
                ["run_id", "row_sha256"],
                values,
            )
        committed = load_checkpoint(session, epoch_id=epoch_id, dataset=dataset, schema=schema)
        if committed.generation == 0 or committed.next_offset < int(stored_cursor["next_offset"]):
            raise StagingIngestError("run exists without its committed checkpoint")
        run_rows = tables["run_rows"]
        physical_count = int(
            session.scalar(
                select(func.count()).select_from(run_rows).where(run_rows.c.run_id == run_id)
            )
            or 0
        )
        if physical_count != len(physical_values):
            raise StagingIngestError("run exists with an incomplete physical capture")
        return PageResult(
            run_id=run_id,
            next_checkpoint=committed,
            physical_rows=physical_count,
            globally_unique_ids=int(existing_run["unique_count"]),
            replayed=True,
        )

    if logical_offset != checkpoint.next_offset:
        raise StagingIngestError("page does not start at the committed checkpoint")
    if checkpoint.snapshot_id and checkpoint.snapshot_id != snapshot_id:
        raise StagingIngestError("source snapshot changed between pages")
    if checkpoint.source_total is not None and checkpoint.source_total != total_before:
        raise StagingIngestError("source total changed since the committed checkpoint")
    if logical_offset:
        if overlap_count <= 0 or request_offset != logical_offset - overlap_count:
            raise StagingIngestError("resumed page lacks the required overlap")
        if checkpoint.trailing_overlap_count != overlap_count:
            raise StagingIngestError("resume overlap length differs from the checkpoint")
        overlap_sha = _overlap_sha256(payload[:overlap_count])
        if not checkpoint.trailing_overlap_sha256 or overlap_sha != checkpoint.trailing_overlap_sha256:
            raise StagingIngestError("overlap mismatch forbids checkpoint advancement")
        if manifest.get("expected_overlap_sha256") != checkpoint.trailing_overlap_sha256:
            raise StagingIngestError("manifest expected overlap does not match checkpoint")
    elif overlap_count or request_offset:
        raise StagingIngestError("initial page cannot contain resume overlap")

    for source in (page.page_source, page.manifest_source):
        values = _source_values(source)
        _insert_ignore(session, tables["source_objects"], values)
        _assert_exact_existing(session, tables["source_objects"], ["source_id"], values)

    timestamp = now or datetime.now(timezone.utc)
    run_values = {
        "run_id": run_id,
        "source_id": page.page_source.source_id,
        "scope": scope,
        "parser_version": PARSER_VERSION,
        "status": COLLECTED_UNVERIFIED,
        "raw_count": len(physical_values),
        "unique_count": len(seen),
        "normalized_count": 0,
        "rejected_count": 0,
        "resume_cursor": cursor,
        "started_at": timestamp,
        "completed_at": timestamp,
        "updated_at": timestamp,
    }
    _insert_ignore(session, runs, run_values)
    _assert_exact_existing(session, runs, ["run_id"], run_values)
    for values in global_values:
        _insert_ignore(session, tables["global_records"], values)
        _assert_exact_existing(
            session,
            tables["global_records"],
            ["global_record_id"],
            values,
            ignored_columns=["first_source_id"],
        )
    for values in physical_values:
        _insert_ignore(session, tables["run_rows"], values)
        _assert_exact_existing(session, tables["run_rows"], ["run_id", "row_sha256"], values)

    next_generation = checkpoint.generation + 1
    checkpoint_values = {
        "epoch_id": epoch_id,
        "dataset": dataset,
        "generation": next_generation,
        "next_offset": next_offset,
        "trailing_overlap_sha256": trailing_overlap_sha256,
        "trailing_overlap_count": trailing_count,
        "source_total": total_after,
        "snapshot_id": snapshot_id,
        "complete": complete,
        "run_id": run_id,
        "updated_at": timestamp,
    }
    checkpoints = tables["checkpoints"]
    if checkpoint.generation == 0:
        dialect = session.get_bind().dialect.name
        if dialect == "postgresql":
            statement = postgresql_insert(checkpoints).values(**checkpoint_values)
            result = session.execute(statement.on_conflict_do_nothing())
        elif dialect == "sqlite":
            statement = sqlite_insert(checkpoints).values(**checkpoint_values)
            result = session.execute(statement.on_conflict_do_nothing())
        else:
            result = session.execute(checkpoints.insert().values(**checkpoint_values))
    else:
        result = session.execute(
            checkpoints.update()
            .where(
                checkpoints.c.epoch_id == epoch_id,
                checkpoints.c.dataset == dataset,
                checkpoints.c.generation == checkpoint.generation,
                checkpoints.c.next_offset == checkpoint.next_offset,
            )
            .values(**checkpoint_values)
        )
    if result.rowcount != 1:
        raise StagingIngestError("checkpoint CAS lost to a concurrent worker")
    return PageResult(
        run_id=run_id,
        next_checkpoint=Checkpoint(
            generation=next_generation,
            next_offset=next_offset,
            trailing_overlap_sha256=trailing_overlap_sha256,
            trailing_overlap_count=trailing_count,
            source_total=total_after,
            snapshot_id=snapshot_id,
            complete=complete,
            run_id=run_id,
        ),
        physical_rows=len(physical_values),
        globally_unique_ids=len(seen),
        replayed=False,
    )


def run_bounded_worker(
    *,
    session_factory: Callable[[], Session],
    page_reader: Callable[[Checkpoint, int], ImmutablePage],
    epoch_id: str,
    dataset: str,
    limits: WorkerLimits,
    schema: str | None = DEFAULT_SCHEMA,
    clock: Callable[[], float] = time.monotonic,
) -> WorkerResult:
    """Commit complete pages one by one; a later failure preserves earlier pages."""

    if session_factory is None:
        raise ValueError("an explicit staging session_factory is required")
    limits.validate()
    started = clock()
    with session_factory() as session:
        checkpoint = load_checkpoint(session, epoch_id=epoch_id, dataset=dataset, schema=schema)
    pages_committed = rows_committed = source_bytes = 0
    while not checkpoint.complete and pages_committed < limits.max_pages:
        if clock() - started >= limits.max_seconds:
            break
        byte_budget = limits.max_source_bytes - source_bytes
        if byte_budget <= 0:
            break
        page = page_reader(checkpoint, byte_budget)
        if clock() - started >= limits.max_seconds:
            break
        candidate_bytes = len(page.page_bytes) + len(page.manifest_bytes)
        if source_bytes + candidate_bytes > limits.max_source_bytes:
            break
        with session_factory() as session:
            with session.begin():
                current = load_checkpoint(
                    session,
                    epoch_id=epoch_id,
                    dataset=dataset,
                    schema=schema,
                    _validate_history=False,
                )
                if current != checkpoint:
                    raise StagingIngestError("checkpoint changed concurrently")
                result = ingest_page(
                    session,
                    page=page,
                    checkpoint=checkpoint,
                    epoch_id=epoch_id,
                    dataset=dataset,
                    schema=schema,
                )
                if rows_committed + result.physical_rows > limits.max_rows:
                    raise StagingIngestError("page would exceed max_rows")
                if clock() - started >= limits.max_seconds:
                    raise StagingIngestError("page processing exceeded max_seconds")
        if result.replayed and result.next_checkpoint == checkpoint:
            raise StagingIngestError("page_reader replayed a page without advancing")
        checkpoint = result.next_checkpoint
        pages_committed += 1
        rows_committed += result.physical_rows
        source_bytes += candidate_bytes
    return WorkerResult(
        checkpoint=checkpoint,
        pages_committed=pages_committed,
        physical_rows=rows_committed,
        source_bytes=source_bytes,
    )
