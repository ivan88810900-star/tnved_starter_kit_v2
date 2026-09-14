"""Pinned, immutable AD30 source observations for offline review only.

Record integrity is not PDF transcription verification, legal applicability,
producer identity, a complete amendment inventory, or authority to admit rates.
No network, application database, clock, rate selection, or approval path exists.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

from app.services.official_rate_validation import load_official_rate_json

DOSSIER_SHA256 = "f3f9722c1f67ec0ea4cc2fa6d495d54d0de981cb351d8aef71104ec6eb584894"
_DOSSIER_PATH = "customs-clear/backend/app/data/official_sources/ad30_source_facts_v1.json"
_EVIDENCE_PATHS = frozenset({
    "docs/ai-workflow/evidence/eec-ad30-decision12-capture-review-20260912.json",
    "docs/ai-workflow/evidence/eec-ad30-decision4-notice-review-20260912.json",
    "docs/ai-workflow/evidence/eec-ad30-source-discovery-20260912.json",
})
_MAX_BYTES = 256 * 1024


class AD30SourceFactsError(ValueError):
    """Pinned source records or a caller's immutable dossier do not match."""


@dataclass(frozen=True, slots=True)
class AD30SourceFact:
    fact_id: str
    value_json: str
    evidence_path: str
    evidence_file_sha256: str
    json_pointer: str
    body_sha256: str
    source_url: str
    page: int | None
    locator: str | None
    observation_kind: str


@dataclass(frozen=True, slots=True)
class AD30RateRow:
    row_id: str
    producer_name: str
    producer_address: str | None
    rate_percent_literal: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AD30SourceFacts:
    dossier_sha256: str
    facts: tuple[AD30SourceFact, ...]
    rate_rows: tuple[AD30RateRow, ...]
    source_record_integrity_verified: bool = True
    original_artifacts_verified: bool = False
    source_text_verified: bool = False
    legal_review_verified: bool = False
    can_promote: bool = False
    production_ready: bool = False
    active_rates_written: bool = False
    durable_legal_retention_attested: bool = False


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _read(path: Path) -> bytes:
    # Paths are fixed repository resources, never selected by source payloads.
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise AD30SourceFactsError("ad30_source_record_requires_regular_file")
        raw = stream.read(_MAX_BYTES + 1)
    if len(raw) > _MAX_BYTES:
        raise AD30SourceFactsError("ad30_source_record_size_limit")
    return raw


def _pointer(document: Any, pointer: str) -> Any:
    # All pointers are pinned, not a generic caller-provided traversal language.
    value = document
    for token in pointer.split("/")[1:]:
        value = value[int(token)] if type(value) is list else value[token]
    return value


def load_ad30_source_facts(repository_root: Path | None = None) -> AD30SourceFacts:
    """Read the fixed dossier and every exact source-record dependency.

    ``repository_root`` supports isolated review worktrees. Content identity is
    pinned in this module; another root cannot substitute its own legal facts.
    Missing/drifted input raises a sanitized ValueError, without an empty/zero
    fallback. A fresh immutable object is returned on every successful load.
    """
    try:
        root = Path(repository_root) if repository_root is not None else Path(__file__).resolve().parents[4]
        dossier = load_official_rate_json(_read(root / _DOSSIER_PATH))
        digest = hashlib.sha256(_canonical(dossier).encode("utf-8")).hexdigest()
        if digest != DOSSIER_SHA256:
            raise AD30SourceFactsError("ad30_dossier_identity_mismatch")
        records = {}
        for record in dossier["evidence_records"]:
            path = record["path"]
            if path not in _EVIDENCE_PATHS or path in records:
                raise AD30SourceFactsError("ad30_evidence_path_mismatch")
            raw = _read(root / path)
            if hashlib.sha256(raw).hexdigest() != record["sha256"]:
                raise AD30SourceFactsError("ad30_evidence_record_hash_mismatch")
            records[path] = load_official_rate_json(raw)
        if set(records) != _EVIDENCE_PATHS:
            raise AD30SourceFactsError("ad30_evidence_record_set_mismatch")
        facts = []
        for fact in dossier["facts"]:
            value = _pointer(records[fact["evidence_path"]], fact["json_pointer"])
            if _canonical(value) != fact["value_json"]:
                raise AD30SourceFactsError("ad30_source_value_mismatch")
            facts.append(AD30SourceFact(**fact))
        rows = tuple(AD30RateRow(**{**row, "evidence_ids": tuple(row["evidence_ids"])})
                     for row in dossier["rate_rows"])
        return AD30SourceFacts(dossier_sha256=digest, facts=tuple(facts), rate_rows=rows)
    except AD30SourceFactsError:
        raise
    except (OSError, ValueError, TypeError, KeyError, IndexError, UnicodeError, RecursionError) as exc:
        raise AD30SourceFactsError("ad30_source_records_unavailable_or_invalid") from exc


def _exact_fields(value: object, model: type, nullable: frozenset[str] = frozenset()) -> bool:
    if type(value) is not model:
        return False
    for field in fields(model):
        item = getattr(value, field.name)
        if item is None and field.name in nullable:
            continue
        if field.name == "page":
            if type(item) is not int:
                return False
        elif field.name == "evidence_ids":
            if type(item) is not tuple or not all(type(entry) is str for entry in item):
                return False
        elif type(item) is not str:
            return False
    return True


def validate_ad30_source_facts(bundle: object) -> AD30SourceFacts:
    """Reject substituted DTOs, including changed row values with copied hashes.

    Comparison uses strict primitive types and the pinned records reloaded from
    this checkout, not a caller's claimed digest or boolean. The returned object
    is the reloaded canonical DTO rather than the supplied instance.
    """
    if type(bundle) is not AD30SourceFacts:
        raise AD30SourceFactsError("ad30_source_facts_type_mismatch")
    if type(bundle.dossier_sha256) is not str or type(bundle.facts) is not tuple or type(bundle.rate_rows) is not tuple:
        raise AD30SourceFactsError("ad30_source_facts_type_mismatch")
    if len(bundle.facts) != 24 or len(bundle.rate_rows) != 3:
        raise AD30SourceFactsError("ad30_source_facts_identity_mismatch")
    if not all(_exact_fields(fact, AD30SourceFact, frozenset({"page", "locator"})) for fact in bundle.facts):
        raise AD30SourceFactsError("ad30_source_facts_type_mismatch")
    if not all(_exact_fields(row, AD30RateRow, frozenset({"producer_address"})) for row in bundle.rate_rows):
        raise AD30SourceFactsError("ad30_source_facts_type_mismatch")
    for field in fields(AD30SourceFacts):
        if field.name not in {"dossier_sha256", "facts", "rate_rows"} and type(getattr(bundle, field.name)) is not bool:
            raise AD30SourceFactsError("ad30_source_facts_type_mismatch")
    expected = load_ad30_source_facts()
    if bundle != expected:
        raise AD30SourceFactsError("ad30_source_facts_identity_mismatch")
    return expected
