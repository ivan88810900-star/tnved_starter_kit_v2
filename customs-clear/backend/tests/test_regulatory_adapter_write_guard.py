"""Fail-closed SQL allowlist used by regulatory update subprocesses."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app import db as db_module


def test_guard_allows_reads_and_declared_table_writes() -> None:
    with (
        patch.object(db_module, "REGULATORY_ADAPTER_MODE", True),
        patch.object(db_module, "_REGULATORY_ALLOWED_WRITE_TABLES", frozenset({"source_status"})),
    ):
        db_module._assert_regulatory_adapter_write_allowed("SELECT * FROM users")
        db_module._assert_regulatory_adapter_write_allowed(
            "INSERT INTO source_status (source_code) VALUES ('CBRF')"
        )
        db_module._assert_regulatory_adapter_write_allowed(
            "UPDATE source_status SET status='ok' WHERE source_code='CBRF'"
        )
        db_module._assert_regulatory_adapter_write_allowed(
            "DELETE FROM source_status WHERE source_code='CBRF'"
        )


@pytest.mark.parametrize(
    "statement",
    (
        "UPDATE users SET role='admin'",
        "INSERT INTO users (role) VALUES ('admin')",
        "INSERT OR REPLACE INTO users (role) VALUES ('admin')",
        "INSERT OR IGNORE INTO users (role) VALUES ('admin')",
        "REPLACE INTO users (role) VALUES ('admin')",
        "DELETE FROM users WHERE role='viewer'",
    ),
)
def test_guard_rejects_write_outside_adapter_allowlist(statement: str) -> None:
    with (
        patch.object(db_module, "REGULATORY_ADAPTER_MODE", True),
        patch.object(db_module, "_REGULATORY_ALLOWED_WRITE_TABLES", frozenset({"source_status"})),
        pytest.raises(PermissionError, match="outside its allowlist: users"),
    ):
        db_module._assert_regulatory_adapter_write_allowed(statement)


@pytest.mark.parametrize(
    "statement",
    (
        "CREATE TABLE shadow (id INTEGER)",
        "ALTER TABLE source_status ADD COLUMN unsafe TEXT",
        "DROP TABLE source_status",
        "TRUNCATE TABLE source_status",
    ),
)
def test_guard_rejects_schema_changes(statement: str) -> None:
    with (
        patch.object(db_module, "REGULATORY_ADAPTER_MODE", True),
        patch.object(db_module, "_REGULATORY_ALLOWED_WRITE_TABLES", frozenset({"source_status"})),
        pytest.raises(PermissionError, match="unsafe SQL"),
    ):
        db_module._assert_regulatory_adapter_write_allowed(statement)


def test_guard_is_inert_outside_adapter_subprocess() -> None:
    with (
        patch.object(db_module, "REGULATORY_ADAPTER_MODE", False),
        patch.object(db_module, "_REGULATORY_ALLOWED_WRITE_TABLES", frozenset()),
    ):
        db_module._assert_regulatory_adapter_write_allowed("DROP TABLE anything")


@pytest.mark.parametrize(
    "statement",
    (
        "WITH chosen AS (SELECT 1) DELETE FROM users WHERE id IN (SELECT * FROM chosen)",
        "/* harmless-looking prefix */ UPDATE users SET role='admin'",
        "-- comment\nINSERT INTO users (role) VALUES ('admin')",
    ),
)
def test_guard_rejects_cte_and_commented_write_bypasses(statement: str) -> None:
    with (
        patch.object(db_module, "REGULATORY_ADAPTER_MODE", True),
        patch.object(db_module, "_REGULATORY_ALLOWED_WRITE_TABLES", frozenset({"source_status"})),
        pytest.raises(PermissionError, match="outside its allowlist: users"),
    ):
        db_module._assert_regulatory_adapter_write_allowed(statement)


def test_guard_checks_every_cte_write_target() -> None:
    statement = (
        "WITH wiped AS (DELETE FROM users RETURNING id) "
        "INSERT INTO source_status (source_code) SELECT 'CBRF' FROM wiped"
    )
    with (
        patch.object(db_module, "REGULATORY_ADAPTER_MODE", True),
        patch.object(db_module, "_REGULATORY_ALLOWED_WRITE_TABLES", frozenset({"source_status"})),
        pytest.raises(PermissionError, match="outside its allowlist: users"),
    ):
        db_module._assert_regulatory_adapter_write_allowed(statement)


def test_guard_rejects_multiple_statements_even_when_first_target_is_allowed() -> None:
    statement = "INSERT INTO source_status (source_code) VALUES ('CBRF'); DELETE FROM users"
    with (
        patch.object(db_module, "REGULATORY_ADAPTER_MODE", True),
        patch.object(db_module, "_REGULATORY_ALLOWED_WRITE_TABLES", frozenset({"source_status"})),
        pytest.raises(PermissionError, match="multiple SQL statements"),
    ):
        db_module._assert_regulatory_adapter_write_allowed(statement)


@pytest.mark.parametrize("statement", ("PRAGMA writable_schema=ON", "ATTACH DATABASE 'x' AS other", "VACUUM"))
def test_guard_rejects_unsafe_non_dml_commands(statement: str) -> None:
    with (
        patch.object(db_module, "REGULATORY_ADAPTER_MODE", True),
        patch.object(db_module, "_REGULATORY_ALLOWED_WRITE_TABLES", frozenset({"source_status"})),
        pytest.raises(PermissionError, match="unsafe SQL"),
    ):
        db_module._assert_regulatory_adapter_write_allowed(statement)
