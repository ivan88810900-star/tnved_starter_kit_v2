"""Canonical evidence kept in ``OpendataSyncLog.details`` without a schema change."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
LIVE_DETAILS_CONTRACT = "opendata-live-snapshot/v1"
FSA_DETAILS_CONTRACT = "opendata-fsa-snapshot/v1"


def acquire_opendata_write_lock(
    db: Session,
    *,
    source_key: str,
    dataset_id: str,
) -> None:
    """Serialize a managed source replacement for SQLite and PostgreSQL.

    The lock is transaction-scoped.  It must be acquired before the final
    high-water read and held through live-table replacement plus sync-log
    insert, closing the check/delete race between two scheduler replicas.
    """
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        lock_material = f"customsclear:opendata:{source_key}:{dataset_id}".encode()
        lock_key = int.from_bytes(hashlib.sha256(lock_material).digest()[:8], "big", signed=True)
        db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": lock_key},
        )
        return
    if dialect == "sqlite" and not db.in_transaction():
        # SQLite has one database writer.  Acquiring it before the high-water
        # query provides the same transaction-level serialization.
        db.execute(text("BEGIN IMMEDIATE"))
        db.info["opendata_sqlite_write_transaction"] = db.get_transaction()
        return
    if dialect == "sqlite":
        current_transaction = db.get_transaction()
        if db.info.get("opendata_sqlite_write_transaction") is current_transaction:
            return
        raise RuntimeError(
            "SQLite opendata write lock must be acquired before any database read"
        )


def canonical_rows_fingerprint(rows: Iterable[Sequence[Any]]) -> tuple[int, str]:
    """Hash ordered persisted values independently of surrogate database ids."""
    digest = hashlib.sha256()
    digest.update(b"customsclear-opendata-live-v1\0")
    row_count = 0
    for row in rows:
        payload = json.dumps(
            [value if value is not None else "" for value in row],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
        row_count += 1
    return row_count, digest.hexdigest()


def require_immutable_snapshot_hash(
    current_sha256: str,
    recorded_sha256_values: Iterable[str],
    *,
    source_key: str,
    snapshot_id: str,
    artifact_kind: str = "data",
) -> None:
    """Fail closed when one immutable snapshot id is observed with new bytes."""
    current = str(current_sha256 or "").casefold()
    if not _SHA256_RE.fullmatch(current):
        raise RuntimeError(f"{source_key}: current {artifact_kind} SHA-256 is invalid")
    recorded = {
        str(value or "").casefold()
        for value in recorded_sha256_values
        if _SHA256_RE.fullmatch(str(value or "").casefold())
    }
    conflicts = sorted(recorded - {current})
    if conflicts:
        raise RuntimeError(
            f"{source_key}: immutable {artifact_kind} artifact for snapshot "
            f"{snapshot_id!r} changed; live data preserved"
        )


def fsa_structure_sha_from_details(details: str) -> str:
    try:
        payload = json.loads(str(details or ""))
    except (TypeError, ValueError):
        return ""
    if not isinstance(payload, dict):
        return ""
    structure = payload.get("structure")
    if payload.get("contract") != FSA_DETAILS_CONTRACT or not isinstance(structure, dict):
        return ""
    value = str(structure.get("sha256") or "").casefold()
    return value if _SHA256_RE.fullmatch(value) else ""


def encode_live_snapshot_details(
    *,
    source_key: str,
    dataset_id: str,
    snapshot_id: str,
    artifact_url: str,
    artifact_sha256: str,
    live_rows: int,
    live_fingerprint_sha256: str,
    stats: dict[str, Any] | None = None,
) -> str:
    payload = {
        "contract": LIVE_DETAILS_CONTRACT,
        "source_key": source_key,
        "dataset_id": dataset_id,
        "snapshot_id": snapshot_id,
        "artifact": {"url": artifact_url, "sha256": artifact_sha256},
        "live": {
            "row_count": int(live_rows),
            "fingerprint_sha256": live_fingerprint_sha256,
        },
        "stats": stats or {},
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def live_snapshot_details_match(
    details: str,
    *,
    source_key: str,
    dataset_id: str,
    snapshot_id: str,
    artifact_url: str,
    artifact_sha256: str,
    live_rows: int,
    live_fingerprint_sha256: str,
) -> bool:
    try:
        payload = json.loads(str(details or ""))
    except (TypeError, ValueError):
        return False
    artifact = payload.get("artifact") if isinstance(payload, dict) else None
    live = payload.get("live") if isinstance(payload, dict) else None
    if not isinstance(artifact, dict) or not isinstance(live, dict):
        return False
    expected_sha = str(artifact_sha256 or "").casefold()
    expected_live_sha = str(live_fingerprint_sha256 or "").casefold()
    return bool(
        payload.get("contract") == LIVE_DETAILS_CONTRACT
        and payload.get("source_key") == source_key
        and payload.get("dataset_id") == dataset_id
        and payload.get("snapshot_id") == snapshot_id
        and artifact.get("url") == artifact_url
        and artifact.get("sha256") == expected_sha
        and _SHA256_RE.fullmatch(expected_sha)
        and live.get("row_count") == int(live_rows)
        and live.get("fingerprint_sha256") == expected_live_sha
        and _SHA256_RE.fullmatch(expected_live_sha)
    )


def encode_fsa_snapshot_details(
    *,
    source_key: str,
    dataset_id: str,
    snapshot_id: str,
    artifact_url: str,
    artifact_sha256: str,
    structure_url: str,
    structure_sha256: str,
    live_rows: int,
    live_fingerprint_sha256: str,
    stats: dict[str, Any],
) -> str:
    payload = {
        "contract": FSA_DETAILS_CONTRACT,
        "source_key": source_key,
        "dataset_id": dataset_id,
        "snapshot_id": snapshot_id,
        "artifact": {"url": artifact_url, "sha256": artifact_sha256},
        "structure": {"url": structure_url, "sha256": structure_sha256},
        "live": {
            "row_count": int(live_rows),
            "fingerprint_sha256": live_fingerprint_sha256,
        },
        "stats": stats,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fsa_snapshot_details_match(
    details: str,
    *,
    source_key: str,
    dataset_id: str,
    snapshot_id: str,
    artifact_url: str,
    artifact_sha256: str,
    structure_url: str,
    structure_sha256: str,
    live_rows: int,
    live_fingerprint_sha256: str,
    require_live: bool = True,
) -> bool:
    try:
        payload = json.loads(str(details or ""))
    except (TypeError, ValueError):
        return False
    artifact = payload.get("artifact") if isinstance(payload, dict) else None
    structure = payload.get("structure") if isinstance(payload, dict) else None
    live = payload.get("live") if isinstance(payload, dict) else None
    if (
        not isinstance(artifact, dict)
        or not isinstance(structure, dict)
        or not isinstance(live, dict)
    ):
        return False
    artifact_sha = str(artifact.get("sha256") or "").casefold()
    expected_artifact_sha = str(artifact_sha256 or "").casefold()
    structure_sha = str(structure.get("sha256") or "").casefold()
    expected_structure_sha = str(structure_sha256 or "").casefold()
    live_sha = str(live.get("fingerprint_sha256") or "").casefold()
    expected_live_sha = str(live_fingerprint_sha256 or "").casefold()
    stored_live_evidence_valid = bool(
        isinstance(live.get("row_count"), int)
        and live.get("row_count") > 0
        and _SHA256_RE.fullmatch(live_sha)
    )
    current_live_matches = bool(
        live.get("row_count") == int(live_rows)
        and live_sha == expected_live_sha
        and _SHA256_RE.fullmatch(expected_live_sha)
    )
    return bool(
        payload.get("contract") == FSA_DETAILS_CONTRACT
        and payload.get("source_key") == source_key
        and payload.get("dataset_id") == dataset_id
        and payload.get("snapshot_id") == snapshot_id
        and artifact.get("url") == artifact_url
        and artifact_sha == expected_artifact_sha
        and _SHA256_RE.fullmatch(expected_artifact_sha)
        and structure.get("url") == structure_url
        and structure_sha == expected_structure_sha
        and _SHA256_RE.fullmatch(expected_structure_sha)
        and _SHA256_RE.fullmatch(artifact_sha)
        and _SHA256_RE.fullmatch(structure_sha)
        and stored_live_evidence_valid
        and (current_live_matches if require_live else True)
    )
