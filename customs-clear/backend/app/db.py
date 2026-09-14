from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker


_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_RAW_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./customs.db")
_READ_ONLY_TRUE_VALUES = {"1", "true", "yes", "on"}
READ_ONLY_MODE = (os.getenv("CUSTOMSCLEAR_READ_ONLY") or "").strip().lower() in _READ_ONLY_TRUE_VALUES
REGULATORY_ADAPTER_MODE = (
    (os.getenv("CUSTOMSCLEAR_REGULATORY_ADAPTER_MODE") or "").strip().lower()
    in _READ_ONLY_TRUE_VALUES
)
_REGULATORY_ALLOWED_WRITE_TABLES = frozenset(
    item.strip().lower()
    for item in (os.getenv("REGULATORY_SYNC_ALLOWED_WRITE_TABLES") or "").split(",")
    if item.strip()
)

_WRITE_TABLE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r'\binsert(?:\s+or\s+[a-zA-Z]+)?\s+into\s+["`\[]?([a-zA-Z0-9_.]+)',
        re.IGNORECASE,
    ),
    re.compile(r'\bupdate\s+(?!set\b)["`\[]?([a-zA-Z0-9_.]+)', re.IGNORECASE),
    re.compile(r'\bdelete\s+from\s+["`\[]?([a-zA-Z0-9_.]+)', re.IGNORECASE),
    re.compile(r'\breplace\s+into\s+["`\[]?([a-zA-Z0-9_.]+)', re.IGNORECASE),
)
_UNSAFE_SQL = re.compile(
    r"\b(?:alter|attach|call|copy|create|detach|drop|merge|pragma|reindex|truncate|vacuum)\b",
    re.IGNORECASE,
)
_SQL_COMMENTS = re.compile(r"/\*.*?\*/|--[^\r\n]*", re.DOTALL)


def _mutated_tables(statement: str) -> tuple[str, ...]:
    """Return every normalized DML target table in an adapter statement."""
    statement = _SQL_COMMENTS.sub(" ", statement or "")
    tables: set[str] = set()
    for pattern in _WRITE_TABLE_PATTERNS:
        for match in pattern.finditer(statement or ""):
            tables.add(match.group(1).split(".")[-1].strip('"`[]').lower())
    return tuple(sorted(tables))


def _assert_regulatory_adapter_write_allowed(statement: str) -> None:
    """Fail closed when a source adapter attempts an undeclared DB write."""
    if not REGULATORY_ADAPTER_MODE:
        return
    normalized = _SQL_COMMENTS.sub(" ", statement or "")
    if _UNSAFE_SQL.search(normalized):
        raise PermissionError("Regulatory source adapters may not execute unsafe SQL")
    without_trailing_terminator = re.sub(r";\s*$", "", normalized)
    if ";" in without_trailing_terminator:
        raise PermissionError("Regulatory source adapters may not execute multiple SQL statements")
    for table in _mutated_tables(normalized):
        if table not in _REGULATORY_ALLOWED_WRITE_TABLES:
            raise PermissionError(
                f"Regulatory source adapter attempted a write outside its allowlist: {table}"
            )


_SQLITE_DENIED_ACTIONS = frozenset(
    action
    for action in (
        getattr(sqlite3, name, None)
        for name in (
            "SQLITE_ALTER_TABLE",
            "SQLITE_ATTACH",
            "SQLITE_CREATE_INDEX",
            "SQLITE_CREATE_TABLE",
            "SQLITE_CREATE_TEMP_INDEX",
            "SQLITE_CREATE_TEMP_TABLE",
            "SQLITE_CREATE_TEMP_TRIGGER",
            "SQLITE_CREATE_TEMP_VIEW",
            "SQLITE_CREATE_TRIGGER",
            "SQLITE_CREATE_VIEW",
            "SQLITE_DETACH",
            "SQLITE_DROP_INDEX",
            "SQLITE_DROP_TABLE",
            "SQLITE_DROP_TEMP_INDEX",
            "SQLITE_DROP_TEMP_TABLE",
            "SQLITE_DROP_TEMP_TRIGGER",
            "SQLITE_DROP_TEMP_VIEW",
            "SQLITE_DROP_TRIGGER",
            "SQLITE_DROP_VIEW",
            "SQLITE_PRAGMA",
        )
    )
    if action is not None
)
_SQLITE_WRITE_ACTIONS = frozenset(
    action
    for action in (
        getattr(sqlite3, "SQLITE_INSERT", None),
        getattr(sqlite3, "SQLITE_UPDATE", None),
        getattr(sqlite3, "SQLITE_DELETE", None),
    )
    if action is not None
)


def _regulatory_sqlite_authorizer(
    action: int,
    arg1: str | None,
    arg2: str | None,
    db_name: str | None,
    trigger_name: str | None,
) -> int:
    """SQLite-level fail-closed boundary, including CTE and commented statements."""
    if action in _SQLITE_DENIED_ACTIONS:
        return sqlite3.SQLITE_DENY
    if action in _SQLITE_WRITE_ACTIONS:
        table = (arg1 or "").split(".")[-1].strip('"`[]').lower()
        if table not in _REGULATORY_ALLOWED_WRITE_TABLES:
            return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def _resolve_database_url(raw_url: str) -> str:
    """Resolve relative sqlite URL against backend root (stable from any cwd)."""
    url = (raw_url or "").strip()
    if not url.startswith("sqlite:///"):
        return url
    path_raw = url.replace("sqlite:///", "", 1)
    path = Path(path_raw)
    if path.is_absolute():
        return url
    abs_path = (_BACKEND_ROOT / path).resolve()
    return f"sqlite:///{abs_path}"


def _sqlite_read_only_url(url: str) -> str:
    """Convert an absolute SQLite URL to a URI that SQLite opens with mode=ro."""
    if not url.startswith("sqlite:///"):
        return url
    raw_path = url.replace("sqlite:///", "", 1)
    if raw_path.startswith("file:"):
        return url
    encoded_path = quote(raw_path, safe="/:")
    return f"sqlite:///file:{encoded_path}?mode=ro&uri=true"


_RESOLVED_DATABASE_URL = _resolve_database_url(_RAW_DATABASE_URL)
DATABASE_URL = (
    _sqlite_read_only_url(_RESOLVED_DATABASE_URL)
    if READ_ONLY_MODE
    else _RESOLVED_DATABASE_URL
)


def is_read_only_mode() -> bool:
    """Whether this process opened its database in strict acceptance read-only mode."""
    return READ_ONLY_MODE

_engine_kwargs: dict = {}
if DATABASE_URL.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {
        "check_same_thread": False,
        # wait for write lock instead of immediate "database is locked"
        "timeout": 60,
    }
else:
    # PostgreSQL и др.: проверка соединений перед использованием
    _engine_kwargs["pool_pre_ping"] = True

engine = create_engine(DATABASE_URL, **_engine_kwargs)

if REGULATORY_ADAPTER_MODE:
    if not _REGULATORY_ALLOWED_WRITE_TABLES:
        raise RuntimeError(
            "CUSTOMSCLEAR_REGULATORY_ADAPTER_MODE requires "
            "REGULATORY_SYNC_ALLOWED_WRITE_TABLES"
        )

    @event.listens_for(engine, "before_cursor_execute")
    def _guard_regulatory_adapter_writes(  # type: ignore[no-redef]
        conn,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ):
        _assert_regulatory_adapter_write_allowed(str(statement or ""))

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):  # type: ignore[no-redef]
        cur = dbapi_connection.cursor()
        try:
            if READ_ONLY_MODE:
                cur.execute("PRAGMA query_only=ON")
            else:
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=60000")
            cur.execute("PRAGMA foreign_keys=ON")
        finally:
            cur.close()
        if REGULATORY_ADAPTER_MODE:
            dbapi_connection.set_authorizer(_regulatory_sqlite_authorizer)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
