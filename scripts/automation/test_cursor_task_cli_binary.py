"""Static checks for cursor-task automation CLI binary name."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parent / "run_cursor_task_from_issue.py"
    spec = importlib.util.spec_from_file_location("run_cursor_task_from_issue", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_default_cursor_agent_bin_is_cursor_agent() -> None:
    mod = _load_module()
    assert mod.DEFAULT_CURSOR_AGENT_BIN == "cursor-agent"


def test_run_agent_source_uses_default_constant() -> None:
    source = (Path(__file__).resolve().parent / "run_cursor_task_from_issue.py").read_text(
        encoding="utf-8"
    )
    assert 'os.environ.get("CURSOR_AGENT_BIN", DEFAULT_CURSOR_AGENT_BIN)' in source
    assert ', "agent")' not in source
    assert '", "agent"' not in source


def test_existing_pr_context_is_rendered_into_prompt() -> None:
    mod = _load_module()
    prompt = mod.build_agent_prompt(
        {
            "number": 57,
            "title": "Fix workflow",
            "body": "Issue body",
            "html_url": "https://example.test/issues/57",
        },
        Path(__file__).resolve().parents[2],
        {
            "number": 56,
            "url": "https://example.test/pull/56",
            "head_branch": "cursor/issue-55-example",
            "comments": {"reviews": [{"body": "REQUEST_CHANGES"}]},
        },
    )
    assert "Existing PR update context" in prompt
    assert "https://example.test/pull/56" in prompt
    assert "cursor/issue-55-example" in prompt
    assert "REQUEST_CHANGES" in prompt
    assert "Do not create a new branch or PR" in prompt
