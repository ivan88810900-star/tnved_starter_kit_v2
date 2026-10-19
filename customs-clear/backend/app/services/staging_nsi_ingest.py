"""Fail-closed raw NSI page ingestion into an explicitly supplied staging DB.

This module deliberately has no dependency on :mod:`app.db`.  A caller must
provide a staging ``Session`` (or a factory for the bounded worker), and must
provide immutable page and manifest bytes read inside its controlled runtime.
The loader performs no normalization or legal admission.
"""

from __future__ import annotations

import hashlib
import json
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
        if self.max_seconds <= 0:
            raise ValueError("max_seconds must be positive")


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
        if proof.get("immutable") is not True or proof.get("official") is not True:
            raise StagingIngestError("official immutable snapshot proof is not asserted")
        if len(snapshot_id) != 64 or any(ch not in "0123456789abcdef" for ch in snapshot_id):
            raise StagingIngestError("official snapshot id must be its SHA-256")
        return snapshot_id
    if kind == "stable_cursor":
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
) -> Checkpoint:
    """Read the single CAS checkpoint row for one isolated epoch."""

    canonical_epoch = str(epoch_id or "").strip()
    canonical_dataset = str(dataset or "").strip()
    if not canonical_epoch or epoch_id != canonical_epoch:
        raise ValueError("staging epoch_id must be nonblank and canonical")
    if not canonical_dataset or dataset != canonical_dataset:
        raise ValueError("staging dataset must be nonblank and canonical")

    checkpoints = _table_map(session, schema)["checkpoints"]
    row = session.execute(
        select(checkpoints).where(
            checkpoints.c.epoch_id == canonical_epoch,
            checkpoints.c.dataset == canonical_dataset,
        )
    ).mappings().one_or_none()
    if row is None:
        return Checkpoint()
    if row["generation"] < 1 or row["next_offset"] < 0:
        raise StagingIngestError("stored checkpoint is malformed")
    return Checkpoint(
        generation=int(row["generation"]),
        next_offset=int(row["next_offset"]),
        trailing_overlap_sha256=row["trailing_overlap_sha256"],
        trailing_overlap_count=int(row["trailing_overlap_count"]),
        source_total=row["source_total"],
        snapshot_id=row["snapshot_id"],
        complete=row["complete"] is True,
        run_id=row["run_id"],
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
        "manifest_source_id": page.manifest_source.source_id,
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
        candidate_bytes = len(page.page_bytes) + len(page.manifest_bytes)
        if source_bytes + candidate_bytes > limits.max_source_bytes:
            break
        with session_factory() as session:
            with session.begin():
                current = load_checkpoint(session, epoch_id=epoch_id, dataset=dataset, schema=schema)
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
