"""Unit tests for strict workflow_dispatch issue_number validation."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from validate_cursor_task_issue_number import (  # noqa: E402
    parse_strict_issue_number,
)


@pytest.mark.parametrize("raw", ["6", "42", "999"])
def test_valid_issue_numbers(raw: str) -> None:
    assert parse_strict_issue_number(raw) == int(raw)


@pytest.mark.parametrize(
    "raw",
    ["6.9", "6abc", "0", "-1", "", "abc", "006", " 6 ", "6 ", " 6"],
)
def test_invalid_issue_numbers(raw: str) -> None:
    with pytest.raises(ValueError, match="Invalid issue_number"):
        parse_strict_issue_number(raw)
