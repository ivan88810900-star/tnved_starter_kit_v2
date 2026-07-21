from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker


_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_RAW_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./customs.db")
_READ_ONLY_TRUE_VALUES = {"1", "true", "yes", "on"}
READ_ONLY_MODE = (os.getenv("CUSTOMSCLEAR_READ_ONLY") or "").strip().lower() in _READ_ONLY_TRUE_VALUES


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

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
