"""Fail-closed verification for retained payment-source snapshots.

The normalized bundle is not, by itself, evidence that the primary source was
retained.  A companion manifest binds the bundle to immutable source bytes.
This verifier proves only that binding; it does not assert legal completeness.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PLACEHOLDER_TRANSFORMS = {"", "unknown", "placeholder", "todo", "manual", "none", "n/a"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_adjacent_file(bundle_path: Path, name: Any) -> tuple[Path | None, str | None]:
    value = str(name or "").strip()
    if not value:
        return None, "missing_file_name"
    candidate_name = Path(value)
    if candidate_name.is_absolute() or candidate_name.name != value or value in {".", ".."}:
        return None, "unsafe_file_name"
    candidate = bundle_path.parent / value
    if candidate.is_symlink():
        return None, "symlink_not_allowed"
    if not candidate.is_file():
        return None, "file_not_found"
    return candidate, None


def _is_official_eec_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    return parsed.scheme.lower() == "https" and (
        host == "eec.eaeunion.org" or host.endswith(".eec.eaeunion.org")
    )


def _declared_source_url(payload: dict[str, Any]) -> str:
    bundle_url = str(payload.get("official_ett_url") or payload.get("source_url") or "").strip()
    if bundle_url:
        return bundle_url
    raw_rows = payload.get("rates") if isinstance(payload.get("rates"), list) else payload.get("rows")
    row_urls = {
        str(row.get("source_url") or "").strip()
        for row in (raw_rows or [])
        if isinstance(row, dict) and str(row.get("source_url") or "").strip()
    }
    return next(iter(row_urls)) if len(row_urls) == 1 else ""


def _parse_captured_at(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def verify_payment_source_snapshot(
    *,
    bundle_path: Path,
    payload: dict[str, Any],
    domain: str,
    normalized_record_count: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Verify an adjacent ``<bundle>.provenance.json`` and source snapshot.

    The manifest and snapshot must be ordinary adjacent files.  Absolute paths,
    traversal, and symlinks are rejected to keep verification scoped to the
    reviewed evidence directory.
    """
    manifest_path = bundle_path.with_name(bundle_path.name + ".provenance.json")
    base_result: dict[str, Any] = {
        "status": "manual_review_required",
        "manifest_path": manifest_path.name,
    }
    if manifest_path.is_symlink():
        return {**base_result, "reason": "manifest_symlink_not_allowed"}
    if not manifest_path.is_file():
        return {**base_result, "reason": "manifest_missing"}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {**base_result, "reason": "manifest_invalid_json"}
    if not isinstance(manifest, dict):
        return {**base_result, "reason": "manifest_not_object"}

    if manifest.get("schema_version") != 1:
        return {**base_result, "reason": "schema_version_mismatch"}
    if str(manifest.get("domain") or "").strip() != domain:
        return {**base_result, "reason": "domain_mismatch"}

    revision = str(payload.get("revision") or payload.get("source_revision") or "").strip()
    if str(manifest.get("revision") or "").strip() != revision:
        return {**base_result, "reason": "revision_mismatch"}

    source_url = _declared_source_url(payload)
    manifest_url = str(manifest.get("source_url") or "").strip()
    if not source_url or manifest_url != source_url:
        return {**base_result, "reason": "source_url_mismatch"}
    if not _is_official_eec_url(manifest_url):
        return {**base_result, "reason": "source_url_not_official_eec"}

    if str(manifest.get("normalized_bundle_file") or "").strip() != bundle_path.name:
        return {**base_result, "reason": "normalized_bundle_file_mismatch"}
    bundle_hash = str(manifest.get("normalized_bundle_sha256") or "").strip().lower()
    if not _SHA256_RE.fullmatch(bundle_hash):
        return {**base_result, "reason": "normalized_bundle_sha256_invalid"}
    if _sha256(bundle_path) != bundle_hash:
        return {**base_result, "reason": "normalized_bundle_sha256_mismatch"}

    count = manifest.get("normalized_record_count")
    if isinstance(count, bool) or not isinstance(count, int) or count != normalized_record_count:
        return {**base_result, "reason": "normalized_record_count_mismatch"}

    captured_at = _parse_captured_at(manifest.get("captured_at"))
    if captured_at is None:
        return {**base_result, "reason": "captured_at_invalid"}
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if captured_at > current + timedelta(minutes=5):
        return {**base_result, "reason": "captured_at_in_future"}

    transform_id = str(manifest.get("transform_id") or "").strip()
    if transform_id.lower() in _PLACEHOLDER_TRANSFORMS:
        return {**base_result, "reason": "transform_id_missing_or_placeholder"}

    source_path, source_error = _safe_adjacent_file(bundle_path, manifest.get("source_snapshot_file"))
    if source_error:
        return {**base_result, "reason": f"source_snapshot_{source_error}"}
    assert source_path is not None
    if source_path in {bundle_path, manifest_path}:
        return {**base_result, "reason": "source_snapshot_not_distinct"}
    if source_path.stat().st_size <= 0:
        return {**base_result, "reason": "source_snapshot_empty"}
    source_hash = str(manifest.get("source_snapshot_sha256") or "").strip().lower()
    if not _SHA256_RE.fullmatch(source_hash):
        return {**base_result, "reason": "source_snapshot_sha256_invalid"}
    if _sha256(source_path) != source_hash:
        return {**base_result, "reason": "source_snapshot_sha256_mismatch"}

    return {
        "status": "verified",
        "manifest_path": manifest_path.name,
        "source_snapshot_file": source_path.name,
        "source_snapshot_sha256": source_hash,
        "normalized_bundle_sha256": bundle_hash,
        "captured_at": captured_at.isoformat().replace("+00:00", "Z"),
        "transform_id": transform_id,
        "note": "Cryptographic binding verified; legal completeness is not asserted.",
    }
