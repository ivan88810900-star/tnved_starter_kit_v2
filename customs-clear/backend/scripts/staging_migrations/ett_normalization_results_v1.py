"""Caller-bound migration for technical ETT normalization results.

This module does not resolve a database URL, open a connection, create the
staging schema, or commit. The caller supplies the already-authorized staging
connection and owns the transaction.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa

from app.services.staging_ett_normalization import ett_normalization_table


@dataclass(frozen=True)
class MigrationResult:
    table_name: str
    created: bool


def _existing_columns(connection, *, schema: str | None) -> tuple[str, ...] | None:
    inspector = sa.inspect(connection)
    names = inspector.get_table_names(schema=schema)
    if "ett_normalization_results" not in names:
        return None
    return tuple(
        column["name"]
        for column in inspector.get_columns(
            "ett_normalization_results", schema=schema
        )
    )


def apply(
    connection, *, schema: str | None = "tariff_ingest"
) -> MigrationResult:
    """Create exactly one staging table or validate an identical replay."""

    table = ett_normalization_table(sa.MetaData(), schema=schema)
    existing = _existing_columns(connection, schema=schema)
    expected = tuple(table.c.keys())
    if existing is not None:
        if existing != expected:
            raise RuntimeError(
                "conflicting existing staging ett_normalization_results contract"
            )
        return MigrationResult(table.fullname, False)
    table.create(bind=connection)
    return MigrationResult(table.fullname, True)


def revert(
    connection, *, schema: str | None = "tariff_ingest"
) -> MigrationResult:
    """Drop only the technical result table; caller owns the transaction."""

    table = ett_normalization_table(sa.MetaData(), schema=schema)
    existing = _existing_columns(connection, schema=schema)
    if existing is None:
        return MigrationResult(table.fullname, False)
    if existing != tuple(table.c.keys()):
        raise RuntimeError(
            "refusing to drop conflicting staging ett_normalization_results contract"
        )
    table.drop(bind=connection)
    return MigrationResult(table.fullname, True)

