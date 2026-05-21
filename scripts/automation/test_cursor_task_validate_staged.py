"""Unit tests for cursor-task staged change validation."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from validate_cursor_task_staged_changes import (  # noqa: E402
    diff_has_secret_markers,
    path_is_denied,
)


def test_path_is_denied_blocks_env_files() -> None:
    assert path_is_denied(".env") == "env file"
    assert path_is_denied("backend/.env.local") == "env file"


def test_path_is_denied_blocks_db_log_and_artifacts() -> None:
    assert path_is_denied("data/app.db") == "database file"
    assert path_is_denied("logs/run.log") == "log file"
    assert path_is_denied("issue-context.json") == "workflow artifact"
    assert path_is_denied(".cursor/cache") == "cursor runtime path"


def test_path_is_denied_allows_normal_source_files() -> None:
    assert path_is_denied("customs-clear/backend/app/main.py") is None
    assert path_is_denied("scripts/automation/foo.py") is None


def test_diff_has_secret_markers() -> None:
    errors = diff_has_secret_markers("+CURSOR_API_KEY=sk-secret\n", [])
    assert errors
    assert "secret marker" in errors[0]


def test_diff_blocks_literal_secret_value() -> None:
    errors = diff_has_secret_markers("+token = abcdefgh\n", ["abcdefgh"])
    assert any("literal secret" in err for err in errors)


def test_diff_allows_normal_code_changes() -> None:
    diff = "+def hello():\n+    return 'TOKEN is not a secret here'\n"
    assert not diff_has_secret_markers(diff, [])
