"""Ensure cursor-task workflow does not embed user-controlled issue fields in shell."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "cursor-task-agent.yml"
RENDER_TITLE = Path(__file__).resolve().parent / "render_cursor_task_pr_title.py"

FORBIDDEN_IN_RUN_BLOCKS = (
    "${{ github.event.issue.title }}",
    "${{ github.event.issue.body }}",
)


def _run_blocks(text: str) -> str:
    parts = re.split(r"\n      - name:", text)
    chunks: list[str] = []
    for part in parts[1:]:
        if "run: |" in part:
            chunks.append(part.split("run: |", 1)[1])
    return "\n".join(chunks)


def test_workflow_run_blocks_avoid_direct_issue_title_body_interpolation() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    run_text = _run_blocks(text)
    for forbidden in FORBIDDEN_IN_RUN_BLOCKS:
        assert forbidden not in run_text, f"found unsafe interpolation in run: block: {forbidden}"


def test_workflow_open_pr_uses_pr_title_renderer() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    open_block = text.split("- name: Open pull request", 1)[1].split("- name:", 1)[0]
    assert "render_cursor_task_pr_title.py" in open_block
    assert 'PR_TITLE=$(python3 scripts/automation/render_cursor_task_pr_title.py' in open_block
    assert '"${PR_TITLE}"' in open_block


def test_pr_title_renderer_preserves_malicious_title_as_literal_string() -> None:
    malicious = 'bad " title $(echo pwned)\nx"; echo hacked; #'
    ctx = {
        "number": 42,
        "title": malicious,
        "body": "",
        "html_url": "https://github.com/example/issues/42",
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
        fh.write(json.dumps(ctx))
        path = Path(fh.name)
    out = subprocess.check_output(
        [sys.executable, str(RENDER_TITLE), str(path)],
        text=True,
    ).strip()
    assert out == f"Cursor task: #42 {malicious}"
    assert "$(echo pwned)" in out
