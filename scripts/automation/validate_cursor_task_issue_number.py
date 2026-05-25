#!/usr/bin/env python3
"""Strict validation for workflow_dispatch issue_number input."""

from __future__ import annotations

import re

STRICT_ISSUE_NUMBER_RE = re.compile(r"^[1-9][0-9]*$")


def parse_strict_issue_number(raw: str) -> int:
    """Return positive integer issue number or raise ValueError."""
    value = str(raw or "")
    if not STRICT_ISSUE_NUMBER_RE.fullmatch(value):
        raise ValueError(
            f"Invalid issue_number: {value!r}. Expected a positive integer without leading zeros."
        )
    return int(value)


def is_valid_issue_number(raw: str) -> bool:
    try:
        parse_strict_issue_number(raw)
    except ValueError:
        return False
    return True
