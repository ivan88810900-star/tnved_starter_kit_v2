"""Unit tests for cursor-task trusted actor authorization."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from authorize_cursor_task_actor import (  # noqa: E402
    DEFAULT_TRUSTED_ACTOR,
    is_authorized,
    trusted_actor_logins,
)


def test_default_trusted_actor() -> None:
    assert DEFAULT_TRUSTED_ACTOR == "ivan88810900-star"
    assert is_authorized("ivan88810900-star", "")


def test_extra_trusted_actors_from_variable() -> None:
    actors = trusted_actor_logins("maintainer-a, maintainer-b")
    assert "ivan88810900-star" in actors
    assert "maintainer-a" in actors
    assert "maintainer-b" in actors
    assert is_authorized("maintainer-a", "maintainer-a, maintainer-b")
    assert not is_authorized("random-triage-user", "maintainer-a")


def test_unauthorized_actor_rejected() -> None:
    assert not is_authorized("evil-user", "")
