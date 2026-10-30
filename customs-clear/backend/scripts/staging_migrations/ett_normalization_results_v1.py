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


def _type_affinity(column_type: sa.types.TypeEngine) -> type[sa.types.TypeEngine]:
    return column_type._type_affinity


def _require_caller_transaction(connection) -> sa.engine.Connection:
    if not isinstance(connection, sa.engine.Connection):
        raise TypeError("migration requires a SQLAlchemy Connection, not an Engine")
    if not connection.in_transaction():
        raise RuntimeError("migration requires an active caller-owned transaction")
    return connection


def _expected_contract(table: sa.Table) -> dict[str, object]:
    return {
        "columns": tuple(
            (column.name, _type_affinity(column.type), column.nullable)
            for column in table.columns
        ),
        "primary_key": tuple(column.name for column in table.primary_key.columns),
        "unique": frozenset(
            (constraint.name, tuple(column.name for column in constraint.columns))
            for constraint in table.constraints
            if isinstance(constraint, sa.UniqueConstraint)
        ),
        "foreign_keys": frozenset(
            (
                constraint.name,
                tuple(column.name for column in constraint.columns),
                tuple(
                    (
                        element.column.table.schema,
                        element.column.table.name,
                        element.column.name,
                    )
                    for element in constraint.elements
                ),
            )
            for constraint in table.constraints
            if isinstance(constraint, sa.ForeignKeyConstraint)
        ),
    }


def _existing_contract(
    connection, *, schema: str | None
) -> dict[str, object] | None:
    inspector = sa.inspect(connection)
    names = inspector.get_table_names(schema=schema)
    if "ett_normalization_results" not in names:
        return None
    table_name = "ett_normalization_results"
    columns = inspector.get_columns(table_name, schema=schema)
    primary_key = inspector.get_pk_constraint(table_name, schema=schema)
    unique = inspector.get_unique_constraints(table_name, schema=schema)
    foreign_keys = inspector.get_foreign_keys(table_name, schema=schema)
    return {
        "columns": tuple(
            (column["name"], _type_affinity(column["type"]), column["nullable"])
            for column in columns
        ),
        "primary_key": tuple(primary_key.get("constrained_columns") or ()),
        "unique": frozenset(
            (constraint.get("name"), tuple(constraint["column_names"]))
            for constraint in unique
        ),
        "foreign_keys": frozenset(
            (
                constraint.get("name"),
                tuple(constraint["constrained_columns"]),
                tuple(
                    (
                        constraint.get("referred_schema"),
                        constraint["referred_table"],
                        column,
                    )
                    for column in constraint["referred_columns"]
                ),
            )
            for constraint in foreign_keys
        ),
    }


def apply(
    connection, *, schema: str | None = "tariff_ingest"
) -> MigrationResult:
    """Create exactly one staging table or validate an identical replay."""

    connection = _require_caller_transaction(connection)
    table = ett_normalization_table(sa.MetaData(), schema=schema)
    existing = _existing_contract(connection, schema=schema)
    expected = _expected_contract(table)
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

    connection = _require_caller_transaction(connection)
    table = ett_normalization_table(sa.MetaData(), schema=schema)
    existing = _existing_contract(connection, schema=schema)
    if existing is None:
        return MigrationResult(table.fullname, False)
    if existing != _expected_contract(table):
        raise RuntimeError(
            "refusing to drop conflicting staging ett_normalization_results contract"
        )
    table.drop(bind=connection)
    return MigrationResult(table.fullname, True)

