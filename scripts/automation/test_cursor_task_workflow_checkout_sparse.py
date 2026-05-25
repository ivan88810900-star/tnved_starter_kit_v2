"""Static checks for cursor-task workflow sparse checkout."""

from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "cursor-task-agent.yml"

EXCLUDED_PATH = "customs-clear/backend/downloads/tamdoc_archive"

REQUIRED_SPARSE_PATHS = (
    ".github",
    "scripts",
    "docs",
    "AGENTS.md",
    "customs-clear/backend/app",
    "customs-clear/backend/tests",
    "customs-clear/backend/data",
)


def _checkout_block() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.find("- uses: actions/checkout@v4")
    assert start != -1, "checkout step not found"
    return text[start : start + 1200]


def test_checkout_uses_persist_credentials_false() -> None:
    block = _checkout_block()
    assert "persist-credentials: false" in block


def test_checkout_uses_sparse_checkout() -> None:
    block = _checkout_block()
    assert "sparse-checkout:" in block
    assert "sparse-checkout-cone-mode: true" in block


def test_sparse_checkout_excludes_tamdoc_archive() -> None:
    block = _checkout_block()
    assert EXCLUDED_PATH not in block
    assert "customs-clear/backend/downloads" not in block


def test_sparse_checkout_includes_key_project_paths() -> None:
    block = _checkout_block()
    for path in REQUIRED_SPARSE_PATHS:
        assert path in block, f"missing sparse path: {path}"


def test_security_hardening_unchanged() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Authorize trusted actor" in text
    assert "workflow_dispatch:" in text
    assert "Initialize runtime paths" in text
    assert "${RUNNER_TEMP}/cursor-task" in text
    assert "validate_cursor_task_staged_changes.py" in text
