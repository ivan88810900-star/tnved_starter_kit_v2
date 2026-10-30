"""Deterministic, technical-only normalization of staged ETT duty text.

The raw ETT capture remains immutable. This module validates the complete raw
package and its canonical row hashes before producing syntax-only results. It
never infers legal applicability, reads ambient configuration, uses the network,
creates schema objects, commits, or writes product payment tables.
"""

from __future__ import annotations

from dataclasses import dataclass
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

from .staging_ett_normalization_core import (
    COLLECTED_UNVERIFIED,
    ETT_NORMALIZER_VERSION,
    LEGAL_STATUS_UNVERIFIED,
    SYNTAX_AMBIGUOUS,
    SYNTAX_PARSED,
    EttNormalizationError,
    EttNormalizationPlan,
    NormalizedEttRow,
    build_ett_normalization_plan as _build_core_plan,
    canonical_json as _canonical_json,
    sha256_json as _sha256_text,
)
from .staging_nsi_ingest import StagingIngestError


DEFAULT_SCHEMA = "tariff_ingest"


@dataclass(frozen=True)
class EttNormalizationResult:
    plan: EttNormalizationPlan
    dry_run: bool
    replayed: bool
    mutation_count: int


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
            Column("source_url", Text, nullable=False),
            Column("source_revision", Text, nullable=False),
            Column("object_bucket", Text, nullable=False),
            Column("object_key", Text, nullable=False),
            Column("sha256", Text, nullable=False),
            Column("size_bytes", Integer, nullable=False),
            schema=schema,
            extend_existing=True,
        ),
        "ingest_runs": Table(
            "ingest_runs",
            metadata,
            Column("run_id", Text, primary_key=True),
            Column("source_id", Text, nullable=False),
            Column("scope", JSON, nullable=False),
            Column("parser_version", Text, nullable=False),
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


def build_ett_normalization_plan(
    *,
    source: Mapping[str, Any],
    ingest_run: Mapping[str, Any],
    raw_rows: Sequence[Mapping[str, Any]],
    parser_version: str = ETT_NORMALIZER_VERSION,
) -> EttNormalizationPlan:
    """Preserve the service API while delegating semantics to the pure core."""

    try:
        return _build_core_plan(
            source=source,
            ingest_run=ingest_run,
            raw_rows=raw_rows,
            parser_version=parser_version,
        )
    except EttNormalizationError as exc:
        raise StagingIngestError(str(exc)) from exc


def _assert_existing(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    for name, value in expected.items():
        if actual[name] != value:
            raise StagingIngestError(f"conflicting existing normalization result.{name}")


def _read_normalization_plan(
    session: Session,
    *,
    source_id: str,
    parser_version: str,
    schema: str | None,
) -> EttNormalizationPlan:
    metadata = MetaData()
    tables = _raw_tables(metadata, schema=schema)
    with session.no_autoflush:
        source = session.execute(
            select(tables["source_objects"]).where(
                tables["source_objects"].c.source_id == source_id
            )
        ).mappings().one_or_none()
        if source is None:
            raise StagingIngestError("staged ETT source does not exist")
        runs = session.execute(
            select(tables["ingest_runs"]).where(
                tables["ingest_runs"].c.source_id == source_id
            )
        ).mappings().all()
        if len(runs) != 1:
            raise StagingIngestError(
                "staged ETT source must have exactly one raw ingest run"
            )
        raw_rows = session.execute(
            select(tables["ett_collected_rows"])
            .where(tables["ett_collected_rows"].c.source_id == source_id)
            .order_by(tables["ett_collected_rows"].c.ordinal)
        ).mappings().all()
        return build_ett_normalization_plan(
            source=source,
            ingest_run=runs[0],
            raw_rows=raw_rows,
            parser_version=parser_version,
        )


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

    plan = _read_normalization_plan(
        session,
        source_id=source_id,
        parser_version=parser_version,
        schema=schema,
    )
    if dry_run:
        return EttNormalizationResult(plan, True, False, 0)

    results = ett_normalization_table(MetaData(), schema=schema)
    with session.no_autoflush:
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

