"""Strict database protections used by the local MVP acceptance gate."""

from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import subprocess
import sys


BACKEND_ROOT = Path(__file__).resolve().parent.parent


def test_sqlite_acceptance_mode_allows_reads_and_rejects_writes(tmp_path) -> None:
    database_path = tmp_path / "acceptance database.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample (value) VALUES ('before')")

    before = database_path.stat()
    env = os.environ.copy()
    env.update(
        {
            "CUSTOMSCLEAR_READ_ONLY": "1",
            "DATABASE_URL": f"sqlite:///{database_path}",
            "PYTHONPATH": str(BACKEND_ROOT),
        }
    )
    probe = """
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from app.db import engine, is_read_only_mode

assert is_read_only_mode()
with engine.connect() as connection:
    assert connection.execute(text("SELECT value FROM sample")).scalar_one() == "before"
    assert connection.execute(text("PRAGMA query_only")).scalar_one() == 1

try:
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO sample (value) VALUES ('after')"))
except OperationalError:
    print("READ_ONLY_OK")
else:
    raise AssertionError("SQLite write unexpectedly succeeded")
"""

    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "READ_ONLY_OK" in result.stdout
    after = database_path.stat()
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sample").fetchone()[0] == 1
