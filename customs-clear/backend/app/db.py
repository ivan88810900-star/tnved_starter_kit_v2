from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker


_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_RAW_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./customs.db")


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


DATABASE_URL = _resolve_database_url(_RAW_DATABASE_URL)

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
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=60000")
            cur.execute("PRAGMA foreign_keys=ON")
        finally:
            cur.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

