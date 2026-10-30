"""Deterministic, technical-only normalization of staged ETT duty text.

The raw ETT capture remains immutable. This module validates the complete raw
package and its canonical row hashes before producing syntax-only results. It
never infers legal applicability, reads ambient configuration, uses the network,
creates schema objects, commits, or writes product payment tables.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKeyConstraint,
    Integer,
    JSON,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .staging_nsi_ingest import StagingIngestError


DEFAULT_SCHEMA = "tariff_ingest"
ETT_NORMALIZER_VERSION = "ett-duty-syntax-v1"
COLLECTED_UNVERIFIED = "COLLECTED_UNVERIFIED"
LEGAL_STATUS_UNVERIFIED = "UNVERIFIED"
SYNTAX_PARSED = "PARSED"
SYNTAX_AMBIGUOUS = "AMBIGUOUS"
MAX_ETT_ROWS = 86

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_HS_CODE_RE = re.compile(r"^[0-9]{10}$")
_VERSION_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_PLAIN_RATE_RE = re.compile(r"^(?:0|[1-9][0-9]*)(?:[.,][0-9]+)?(?:[ \t]*%)?$")


@dataclass(frozen=True)
class NormalizedEttRow:
    source_id: str
    raw_row_sha256: str
    ordinal: int
    parser_version: str
    source_revision: str
    hs_code: str
    page_number: int
    line_number: int
    original_description: str
    original_supplementary_unit: str
    original_duty_text: str
    original_raw_line: str
    syntax_status: str
    normalized_rate_text: str | None
    is_ambiguous: bool
    ambiguity_reason: str | None
    legal_status: str
    verified: bool
    admitted: bool
    result_sha256: str

    def values(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class EttNormalizationPlan:
    source_id: str
    source_revision: str
    parser_version: str
    raw_count: int
    parsed_count: int
    ambiguous_count: int
    digest: str
    rows: tuple[NormalizedEttRow, ...]


@dataclass(frozen=True)
class EttNormalizationResult:
    plan: EttNormalizationPlan
    dry_run: bool
    replayed: bool
    mutation_count: int


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256_text(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def ett_normalization_table(
    metadata: MetaData, *, schema: str | None = DEFAULT_SCHEMA
) -> Table:
    raw_key = f"{schema}.ett_collected_rows" if schema else "ett_collected_rows"
    if raw_key not in metadata.tables:
        Table(
            "ett_collected_rows",
            metadata,
            Column("source_id", Text, primary_key=True),
            Column("row_sha256", Text, primary_key=True),
            schema=schema,
            extend_existing=True,
        )
    raw_target = (
        f"{schema}.ett_collected_rows.source_id"
        if schema
        else "ett_collected_rows.source_id"
    )
    raw_hash_target = (
        f"{schema}.ett_collected_rows.row_sha256"
        if schema
        else "ett_collected_rows.row_sha256"
    )
    return Table(
        "ett_normalization_results",
        metadata,
        Column("source_id", Text, nullable=False),
        Column("raw_row_sha256", Text, nullable=False),
        Column("ordinal", Integer, nullable=False),
        Column("parser_version", Text, nullable=False),
        Column("source_revision", Text, nullable=False),
        Column("hs_code", Text, nullable=False),
        Column("page_number", Integer, nullable=False),
        Column("line_number", Integer, nullable=False),
        Column("original_description", Text, nullable=False),
        Column("original_supplementary_unit", Text, nullable=False),
        Column("original_duty_text", Text, nullable=False),
        Column("original_raw_line", Text, nullable=False),
        Column("syntax_status", Text, nullable=False),
        Column("normalized_rate_text", Text, nullable=True),
        Column("is_ambiguous", Boolean, nullable=False),
        Column("ambiguity_reason", Text, nullable=True),
        Column("legal_status", Text, nullable=False),
        Column("verified", Boolean, nullable=False),
        Column("admitted", Boolean, nullable=False),
        Column("result_sha256", Text, nullable=False),
        PrimaryKeyConstraint("source_id", "raw_row_sha256", "parser_version"),
        UniqueConstraint(
            "source_id",
            "ordinal",
            "parser_version",
            name="uq_ett_normalization_source_ordinal_version",
        ),
        UniqueConstraint("result_sha256", name="uq_ett_normalization_result_sha256"),
        ForeignKeyConstraint(
            ["source_id", "raw_row_sha256"],
            [raw_target, raw_hash_target],
            name="fk_ett_normalization_raw_row",
        ),
        schema=schema,
        extend_existing=True,
    )


def _raw_tables(metadata: MetaData, *, schema: str | None) -> dict[str, Table]:
    return {
        "source_objects": Table(
            "source_objects",
            metadata,
            Column("source_id", Text, primary_key=True),
            Column("source_revision", Text, nullable=False),
            schema=schema,
            extend_existing=True,
        ),
        "ingest_runs": Table(
            "ingest_runs",
            metadata,
            Column("run_id", Text, primary_key=True),
            Column("source_id", Text, nullable=False),
            Column("scope", JSON, nullable=False),
            Column("status", Text, nullable=False),
            Column("raw_count", Integer, nullable=False),
            Column("unique_count", Integer, nullable=False),
            schema=schema,
            extend_existing=True,
        ),
        "ett_collected_rows": Table(
            "ett_collected_rows",
            metadata,
            Column("source_id", Text, primary_key=True),
            Column("row_sha256", Text, primary_key=True),
            Column("ordinal", Integer, nullable=False),
            Column("hs_code", Text, nullable=False),
            Column("description", Text, nullable=False),
            Column("supplementary_unit", Text, nullable=False),
            Column("duty_text", Text, nullable=False),
            Column("raw_line", Text, nullable=False),
            Column("status", Text, nullable=False),
            schema=schema,
            extend_existing=True,
        ),
    }


def _required_string(value: Any, label: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        raise StagingIngestError(f"{label} must be a string")
    return value


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise StagingIngestError(f"{label} must be a positive integer")
    return value


def _parse_rate(duty_text: str) -> tuple[str, str | None, bool, str | None]:
    candidate = duty_text.strip()
    if not candidate or _PLAIN_RATE_RE.fullmatch(candidate) is None:
        return SYNTAX_AMBIGUOUS, None, True, "QUALIFIED_OR_UNKNOWN_TEXT"
    numeric = candidate[:-1].rstrip() if candidate.endswith("%") else candidate
    numeric = numeric.replace(",", ".")
    try:
        value = Decimal(numeric)
    except InvalidOperation as exc:  # defensive; regex already fences the grammar
        raise StagingIngestError("plain ETT rate is not a decimal") from exc
    canonical = format(value, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    return SYNTAX_PARSED, canonical, False, None


def _result_row(
    *,
    source_id: str,
    source_revision: str,
    parser_version: str,
    raw: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> NormalizedEttRow:
    syntax_status, rate, ambiguous, reason = _parse_rate(raw["duty_text"])
    payload = {
        "source_id": source_id,
        "raw_row_sha256": raw["row_sha256"],
        "ordinal": raw["ordinal"],
        "parser_version": parser_version,
        "source_revision": source_revision,
        "hs_code": raw["hs_code"],
        "page_number": provenance["page_number"],
        "line_number": provenance["line_number"],
        "original_description": raw["description"],
        "original_supplementary_unit": raw["supplementary_unit"],
        "original_duty_text": raw["duty_text"],
        "original_raw_line": raw["raw_line"],
        "syntax_status": syntax_status,
        "normalized_rate_text": rate,
        "is_ambiguous": ambiguous,
        "ambiguity_reason": reason,
        "legal_status": LEGAL_STATUS_UNVERIFIED,
        "verified": False,
        "admitted": False,
    }
    return NormalizedEttRow(**payload, result_sha256=_sha256_text(payload))


def build_ett_normalization_plan(
    *,
    source: Mapping[str, Any],
    ingest_run: Mapping[str, Any],
    raw_rows: Sequence[Mapping[str, Any]],
    parser_version: str = ETT_NORMALIZER_VERSION,
) -> EttNormalizationPlan:
    """Validate the complete package and return a pure deterministic plan."""

    source_id = _required_string(source.get("source_id"), "source_id")
    source_revision = _required_string(source.get("source_revision"), "source_revision")
    if not isinstance(parser_version, str) or _VERSION_RE.fullmatch(parser_version) is None:
        raise StagingIngestError("parser_version is not canonical")
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)):
        raise StagingIngestError("raw_rows must be a bounded sequence")
    if not raw_rows or len(raw_rows) > MAX_ETT_ROWS:
        raise StagingIngestError(f"raw row count must be between 1 and {MAX_ETT_ROWS}")
    if ingest_run.get("source_id") != source_id:
        raise StagingIngestError("ingest run source_id mismatch")
    if ingest_run.get("status") != COLLECTED_UNVERIFIED:
        raise StagingIngestError("raw ingest run is not COLLECTED_UNVERIFIED")
    if ingest_run.get("raw_count") != len(raw_rows) or ingest_run.get("unique_count") != len(raw_rows):
        raise StagingIngestError("raw ingest counts do not match the complete package")

    scope = ingest_run.get("scope")
    if not isinstance(scope, Mapping):
        raise StagingIngestError("ingest run scope is missing")
    identity = scope.get("source_identity")
    if not isinstance(identity, Mapping) or identity.get("source_revision") != source_revision:
        raise StagingIngestError("scope source revision mismatch")
    provenance_rows = scope.get("row_provenance")
    if not isinstance(provenance_rows, list) or len(provenance_rows) != len(raw_rows):
        raise StagingIngestError("complete row_provenance is required")

    ordered_raw = sorted(raw_rows, key=lambda item: item.get("ordinal", 0))
    ordered_provenance = sorted(provenance_rows, key=lambda item: item.get("ordinal", 0) if isinstance(item, Mapping) else 0)
    expected_ordinals = list(range(1, len(raw_rows) + 1))
    raw_ordinals = [item.get("ordinal") for item in ordered_raw]
    provenance_ordinals = [item.get("ordinal") if isinstance(item, Mapping) else None for item in ordered_provenance]
    if raw_ordinals != expected_ordinals:
        raise StagingIngestError("raw ordinals must be unique and contiguous from 1")
    if provenance_ordinals != expected_ordinals:
        raise StagingIngestError("provenance ordinals must be unique and contiguous from 1")

    normalized: list[NormalizedEttRow] = []
    seen_hashes: set[str] = set()
    seen_codes: set[str] = set()
    for ordinal, (raw, provenance) in enumerate(zip(ordered_raw, ordered_provenance), start=1):
        if raw.get("source_id") != source_id:
            raise StagingIngestError("raw row source_id mismatch")
        if raw.get("status") != COLLECTED_UNVERIFIED:
            raise StagingIngestError("raw row is not COLLECTED_UNVERIFIED")
        hs_code = _required_string(raw.get("hs_code"), "hs_code")
        if _HS_CODE_RE.fullmatch(hs_code) is None:
            raise StagingIngestError("hs_code must be an exact ASCII 10-digit string")
        for name in ("description", "supplementary_unit", "duty_text", "raw_line"):
            _required_string(raw.get(name), name, nonempty=name not in {"supplementary_unit", "duty_text"})
        row_sha = _required_string(raw.get("row_sha256"), "row_sha256")
        if _SHA256_RE.fullmatch(row_sha) is None:
            raise StagingIngestError("row_sha256 is malformed")
        if row_sha in seen_hashes or hs_code in seen_codes:
            raise StagingIngestError("duplicate raw row hash or hs_code")
        seen_hashes.add(row_sha)
        seen_codes.add(hs_code)
        if not isinstance(provenance, Mapping):
            raise StagingIngestError("row provenance entry must be a mapping")
        page_number = _positive_int(provenance.get("page_number"), "page_number")
        line_number = _positive_int(provenance.get("line_number"), "line_number")
        if provenance.get("hs_code") != hs_code or provenance.get("row_sha256") != row_sha:
            raise StagingIngestError("row provenance identity mismatch")
        hash_payload = {
            "hs_code": hs_code,
            "description": raw["description"],
            "supplementary_unit": raw["supplementary_unit"],
            "duty_text": raw["duty_text"],
            "page_number": page_number,
            "line_number": line_number,
            "raw_line": raw["raw_line"],
        }
        if _sha256_text(hash_payload) != row_sha:
            raise StagingIngestError(f"canonical raw row SHA mismatch at ordinal {ordinal}")
        normalized.append(
            _result_row(
                source_id=source_id,
                source_revision=source_revision,
                parser_version=parser_version,
                raw=raw,
                provenance=provenance,
            )
        )

    digest = _sha256_text([row.values() for row in normalized])
    parsed = sum(row.syntax_status == SYNTAX_PARSED for row in normalized)
    ambiguous = sum(row.is_ambiguous for row in normalized)
    return EttNormalizationPlan(
        source_id=source_id,
        source_revision=source_revision,
        parser_version=parser_version,
        raw_count=len(normalized),
        parsed_count=parsed,
        ambiguous_count=ambiguous,
        digest=digest,
        rows=tuple(normalized),
    )


def _assert_existing(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    for name, value in expected.items():
        if actual[name] != value:
            raise StagingIngestError(f"conflicting existing normalization result.{name}")


def normalize_staged_ett(
    session: Session,
    *,
    source_id: str,
    parser_version: str = ETT_NORMALIZER_VERSION,
    schema: str | None = DEFAULT_SCHEMA,
    dry_run: bool = False,
) -> EttNormalizationResult:
    """Read, validate, plan, and optionally insert one complete result version.

    The caller owns the transaction. Validation and conflict checks finish before
    the first insert. Dry-run never references the result table, so it cannot run
    migrations or mutate an otherwise raw-only staging database.
    """

    metadata = MetaData()
    tables = _raw_tables(metadata, schema=schema)
    source = session.execute(
        select(tables["source_objects"]).where(tables["source_objects"].c.source_id == source_id)
    ).mappings().one_or_none()
    if source is None:
        raise StagingIngestError("staged ETT source does not exist")
    runs = session.execute(
        select(tables["ingest_runs"]).where(tables["ingest_runs"].c.source_id == source_id)
    ).mappings().all()
    if len(runs) != 1:
        raise StagingIngestError("staged ETT source must have exactly one raw ingest run")
    raw_rows = session.execute(
        select(tables["ett_collected_rows"])
        .where(tables["ett_collected_rows"].c.source_id == source_id)
        .order_by(tables["ett_collected_rows"].c.ordinal)
    ).mappings().all()
    plan = build_ett_normalization_plan(
        source=source,
        ingest_run=runs[0],
        raw_rows=raw_rows,
        parser_version=parser_version,
    )
    if dry_run:
        return EttNormalizationResult(plan, True, False, 0)

    results = ett_normalization_table(MetaData(), schema=schema)
    existing = session.execute(
        select(results).where(
            (results.c.source_id == source_id)
            & (results.c.parser_version == parser_version)
        )
    ).mappings().all()
    if existing:
        if len(existing) != plan.raw_count:
            raise StagingIngestError("normalization result version is incomplete or extra")
        by_ordinal = {row["ordinal"]: row for row in existing}
        if len(by_ordinal) != len(existing):
            raise StagingIngestError("normalization result version has duplicate ordinals")
        for expected_row in plan.rows:
            actual = by_ordinal.get(expected_row.ordinal)
            if actual is None:
                raise StagingIngestError("normalization result version is missing an ordinal")
            _assert_existing(actual, expected_row.values())
        return EttNormalizationResult(plan, False, True, 0)

    try:
        session.execute(results.insert(), [row.values() for row in plan.rows])
    except IntegrityError as exc:
        raise StagingIngestError("conflicting concurrent normalization state") from exc
    return EttNormalizationResult(plan, False, False, plan.raw_count)

