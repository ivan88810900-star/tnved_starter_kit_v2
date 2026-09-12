"""Atomic staging and integrity-checked previews, never production promotion.

Local hashes prove retained bytes, not their download origin or legal meaning.
No function here writes hs_rates, marks EEC_ETT fresh, or approves a manifest.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..models.ett import ETTArtifact, ETTCodeVersion, ETTFootnote, ETTRateRule, ETTSnapshot
from .ett_artifacts import LocalArtifactStore
from .ett_derived_inventory import verify_derived_amendment_inventory
from .ett_manifest import ETTManifest, canonical_manifest_bytes, manifest_sha256, validate_manifest
from .opendata_snapshot_evidence import acquire_opendata_write_lock


class ETTCandidateError(ValueError):
    """Candidate missing, inconsistent or unsafe for the requested operation."""


_PROJECTIONS = (
    (ETTArtifact, "artifacts", "artifact_id"),
    (ETTCodeVersion, "codes", "code"),
    (ETTFootnote, "footnotes", "footnote_id"),
    (ETTRateRule, "rate_rules", "rule_id"),
)


def _digest(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ETTCandidateError("Invalid manifest digest")
    return value


def _payload(value: Any) -> dict[str, Any]:
    return value.model_dump(mode="json")


def _key(value: Any, key: str, collection: str) -> str:
    identity = getattr(value, key)
    return f"{identity}@{value.valid_from.isoformat()}" if collection == "codes" else identity


def _code_index(manifest: ETTManifest):
    result = defaultdict(list)
    for code in manifest.codes:
        result[code.code].append(code)
    return result


def _code_version_start(index: dict, rule: Any):
    matches = [code.valid_from for code in index.get(rule.code, ()) if code.valid_from <= rule.valid_from and rule.valid_to <= code.valid_to]
    if len(matches) != 1:
        raise ETTCandidateError("Rate has no unique code validity interval")
    return matches[0]


def _verify_artifacts(manifest: ETTManifest, store: LocalArtifactStore) -> None:
    for artifact in manifest.artifacts:
        store.verify(artifact.sha256, artifact.size_bytes)
    verify_derived_amendment_inventory(manifest, store)


def stage_candidate(db: Session, store: LocalArtifactStore, manifest: ETTManifest) -> dict[str, Any]:
    """Own a fresh DB transaction; atomically stage all five projections.

Immutable local objects may survive a DB rollback; these unreferenced objects
cannot become rates. Repeat imports are idempotent only if every byte agrees.
"""
    if db.in_transaction() or db.new or db.dirty or db.deleted:
        raise ETTCandidateError("Staging requires a fresh dedicated session")
    manifest = validate_manifest(_payload(manifest))
    canonical = canonical_manifest_bytes(manifest)
    digest = manifest_sha256(manifest)
    code_index = _code_index(manifest)
    _verify_artifacts(manifest, store)
    if store.put(canonical) != digest:
        raise ETTCandidateError("Manifest content-address mismatch")
    try:
        acquire_opendata_write_lock(db, source_key="ett_candidate", dataset_id="schema_v2")
        existing = db.scalar(select(ETTSnapshot).where(ETTSnapshot.snapshot_id == manifest.snapshot_id))
        if existing is not None:
            if existing.manifest_sha256 != digest:
                raise ETTCandidateError("A snapshot ID cannot be reused with different content")
            load_candidate(db, store, digest)
            db.commit()
            return {"manifest_sha256": digest, "created": False, "status": "candidate", "production_ready": False}
        db.add(ETTSnapshot(
            manifest_sha256=digest,
            snapshot_id=manifest.snapshot_id,
            coverage_from=manifest.coverage_from,
            coverage_to=manifest.coverage_to,
            status="candidate",
            storage_kind="local_development",
            manifest_json=_payload(manifest),
        ))
        db.flush()
        for model, collection, key in _PROJECTIONS:
            for item in getattr(manifest, collection):
                fields = {"snapshot_sha256": digest, key: getattr(item, key), "payload": _payload(item)}
                if model is ETTCodeVersion:
                    fields.update(valid_from=item.valid_from, valid_to=item.valid_to)
                if model is ETTRateRule:
                    fields.update(code=item.code, code_valid_from=_code_version_start(code_index, item), valid_from=item.valid_from, valid_to=item.valid_to)
                db.add(model(**fields))
            # Explicit order also works without ORM relationships and with FKs on.
            db.flush()
        load_candidate(db, store, digest)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"manifest_sha256": digest, "created": True, "status": "candidate", "production_ready": False}


def load_candidate(db: Session, store: LocalArtifactStore, digest: str) -> ETTManifest:
    """Fail closed on missing artifacts, altered DB metadata or partial rows."""
    digest = _digest(digest)
    # SQLAlchemy's SQLite autobegin alone does not pin a read snapshot.
    if db.get_bind().dialect.name == "sqlite":
        if not db.connection().connection.driver_connection.in_transaction:
            db.execute(text("BEGIN"))
    elif db.get_bind().dialect.name == "postgresql" and not db.in_transaction():
        db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
    snapshot = db.get(ETTSnapshot, digest, populate_existing=True)
    if snapshot is None:
        raise ETTCandidateError("Unknown ETT candidate")
    manifest = validate_manifest(snapshot.manifest_json)
    code_index = _code_index(manifest)
    canonical = canonical_manifest_bytes(manifest)
    if manifest_sha256(manifest) != digest or store.read(digest) != canonical:
        raise ETTCandidateError("ETT manifest integrity failure")
    if (
        snapshot.snapshot_id != manifest.snapshot_id
        or snapshot.coverage_from != manifest.coverage_from
        or snapshot.coverage_to != manifest.coverage_to
        or snapshot.status != "candidate"
        or snapshot.storage_kind != "local_development"
    ):
        raise ETTCandidateError("ETT snapshot metadata integrity failure")
    for model, collection, key in _PROJECTIONS:
        expected = {_key(item, key, collection): _payload(item) for item in getattr(manifest, collection)}
        rows = db.scalars(select(model).where(model.snapshot_sha256 == digest).execution_options(populate_existing=True)).all()
        actual = {_key(row, key, collection): row.payload for row in rows}
        if actual != expected:
            raise ETTCandidateError(f"ETT {collection} projection integrity failure")
        if model is ETTRateRule:
            for row in rows:
                if row.code != row.payload["code"] or row.valid_from.isoformat() != row.payload["valid_from"] or row.valid_to.isoformat() != row.payload["valid_to"] or row.code_valid_from != _code_version_start(code_index, row):
                    raise ETTCandidateError("ETT rate index integrity failure")
        elif model is ETTCodeVersion:
            for row in rows:
                if row.valid_to.isoformat() != row.payload["valid_to"]:
                    raise ETTCandidateError("ETT code interval integrity failure")
    _verify_artifacts(manifest, store)
    return manifest


def candidate_readiness(manifest: ETTManifest) -> dict[str, Any]:
    """Architecture approval is not a legal review of any particular dataset."""
    return {
        "snapshot_id": manifest.snapshot_id,
        "manifest_sha256": manifest_sha256(manifest),
        "status": "candidate",
        "mode": "candidate_preview",
        "production_ready": False,
        "can_promote": False,
        "active_rates_written": False,
        "coverage_from": manifest.coverage_from.isoformat(),
        "coverage_to_exclusive": manifest.coverage_to.isoformat(),
        "artifacts": len(manifest.artifacts),
        "codes": len(manifest.codes),
        "rate_rules": len(manifest.rate_rules),
        "blockers": [
            "local_development_storage_is_not_retention_attestation",
            "official_acquisition_and_pdf_row_binding_not_attested",
            "complete_current_legal_inventory_not_independently_verified",
            "manifest_bound_legal_review_missing",
            "production_promotion_not_implemented",
        ],
    }


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def semantic_diff(before: ETTManifest | None, after: ETTManifest) -> dict[str, Any]:
    """Review a change by code/rule/footnote; source-only changes remain visible."""
    after = validate_manifest(_payload(after))
    before = validate_manifest(_payload(before)) if before is not None else None
    result: dict[str, Any] = {
        "before_manifest_sha256": manifest_sha256(before) if before else None,
        "after_manifest_sha256": manifest_sha256(after),
        "review_required": True,
        "coverage_changed": before is None or (before.coverage_from, before.coverage_to) != (after.coverage_from, after.coverage_to),
        "parser_changed": before is None or before.parser != after.parser,
        "derived_amendment_inventory_changed": before is None or before.derived_amendment_inventory != after.derived_amendment_inventory,
    }
    for _, collection, key in _PROJECTIONS:
        old = {_key(item, key, collection): _payload(item) for item in getattr(before, collection)} if before else {}
        new = {_key(item, key, collection): _payload(item) for item in getattr(after, collection)}
        shared = old.keys() & new.keys()
        changed = sorted(k for k in shared if _hash_payload(old[k]) != _hash_payload(new[k]))
        result[collection] = {"added": sorted(new.keys() - old.keys()), "removed": sorted(old.keys() - new.keys()), "changed": changed}
    return result
