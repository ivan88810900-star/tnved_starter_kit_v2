#!/usr/bin/env python3
"""Static fail-closed validation for the regulatory scheduled workflow.

The PR gate must exercise the same locked dependency environment as the cron
job and reject malformed embedded Bash, Python or github-script JavaScript
before the workflow reaches the default branch.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "scheduled-data-refresh.yml"
MONITOR_SCRIPT = Path(__file__).resolve().with_name("monitor_official_ntm_sources.py")
PINNED_ACTION_RE = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
HEREDOC_RE = re.compile(r"\bpython(?:3)?\b[^\n]*<<-?'([A-Za-z_][A-Za-z0-9_]*)'")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _monitor_state_schema_version() -> int:
    tree = ast.parse(MONITOR_SCRIPT.read_text(encoding="utf-8"), filename=str(MONITOR_SCRIPT))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == "STATE_SCHEMA_VERSION" for target in targets):
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, int):
            return value.value
    raise RuntimeError("monitor script must define an integer STATE_SCHEMA_VERSION")


def _jobs(document: dict[str, Any]) -> dict[str, Any]:
    jobs = document.get("jobs")
    _require(isinstance(jobs, dict) and jobs, "workflow jobs must be a non-empty mapping")
    return jobs


def _steps(jobs: dict[str, Any]) -> Iterable[tuple[str, int, dict[str, Any]]]:
    for job_id, job in jobs.items():
        _require(isinstance(job, dict), f"job {job_id!r} must be a mapping")
        steps = job.get("steps")
        _require(isinstance(steps, list) and steps, f"job {job_id!r} has no steps")
        seen_ids: set[str] = set()
        for index, step in enumerate(steps, start=1):
            _require(isinstance(step, dict), f"job {job_id!r} step {index} is not a mapping")
            step_id = str(step.get("id") or "").strip()
            if step_id:
                _require(step_id not in seen_ids, f"job {job_id!r} repeats step id {step_id!r}")
                seen_ids.add(step_id)
            yield str(job_id), index, step


def _check_bash(script: str, *, label: str) -> None:
    result = subprocess.run(
        ["bash", "-n"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )
    _require(result.returncode == 0, f"{label}: invalid Bash: {result.stderr.strip()}")


def _python_heredocs(script: str, *, label: str) -> Iterable[tuple[str, str]]:
    lines = script.splitlines()
    index = 0
    while index < len(lines):
        match = HEREDOC_RE.search(lines[index])
        if not match:
            index += 1
            continue
        marker = match.group(1)
        body_start = index + 1
        cursor = body_start
        while cursor < len(lines) and lines[cursor].strip() != marker:
            cursor += 1
        _require(cursor < len(lines), f"{label}: unterminated Python heredoc {marker!r}")
        yield marker, "\n".join(lines[body_start:cursor]) + "\n"
        index = cursor + 1


def _check_python(script: str, *, label: str) -> int:
    count = 0
    for marker, body in _python_heredocs(script, label=label):
        try:
            compile(body, f"<{label}:{marker}>", "exec")
        except SyntaxError as exc:
            raise RuntimeError(f"{label}: invalid Python heredoc {marker!r}: {exc}") from exc
        count += 1
    return count


def _check_javascript(script: str, *, label: str) -> None:
    wrapped = "async function __github_script_contract__() {\n" + script + "\n}\n"
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8") as handle:
        handle.write(wrapped)
        handle.flush()
        result = subprocess.run(
            ["node", "--check", handle.name],
            text=True,
            capture_output=True,
            check=False,
        )
    _require(result.returncode == 0, f"{label}: invalid JavaScript: {result.stderr.strip()}")


def validate_workflow(path: Path) -> dict[str, int]:
    raw = path.read_text(encoding="utf-8")
    try:
        document = yaml.load(raw, Loader=yaml.BaseLoader)
    except yaml.YAMLError as exc:
        raise RuntimeError(f"invalid workflow YAML: {exc}") from exc
    _require(isinstance(document, dict), "workflow root must be a mapping")

    triggers = document.get("on")
    _require(isinstance(triggers, dict), "workflow must define an event mapping")
    _require("schedule" in triggers, "workflow must keep its scheduled trigger")
    _require("workflow_dispatch" in triggers, "workflow must keep manual review dispatch")

    state_version = _monitor_state_schema_version()
    cache_versions = set(re.findall(r"regulatory-source-monitor-v([0-9]+)-", raw))
    _require(
        cache_versions == {str(state_version)},
        "workflow cache namespace must match monitor STATE_SCHEMA_VERSION; "
        f"workflow={sorted(cache_versions)!r}, monitor={state_version}",
    )
    gate_versions = set(
        re.findall(r'state\.get\("version"\)\s*!=\s*([0-9]+)', raw)
    )
    _require(
        gate_versions == {str(state_version)},
        "workflow persistence gate must match monitor STATE_SCHEMA_VERSION; "
        f"workflow={sorted(gate_versions)!r}, monitor={state_version}",
    )

    jobs = _jobs(document)
    _require({"monitor", "notify"}.issubset(jobs), "workflow must contain monitor and notify jobs")

    action_count = 0
    bash_count = 0
    python_count = 0
    javascript_count = 0
    for job_id, index, step in _steps(jobs):
        label = f"{job_id} step {index} ({step.get('name') or 'unnamed'})"
        uses = str(step.get("uses") or "").strip()
        if uses:
            _require(PINNED_ACTION_RE.fullmatch(uses) is not None, f"{label}: action is not SHA-pinned: {uses}")
            action_count += 1
        run = step.get("run")
        if isinstance(run, str):
            _check_bash(run, label=label)
            bash_count += 1
            python_count += _check_python(run, label=label)
        with_block = step.get("with")
        if uses.startswith("actions/github-script@") and isinstance(with_block, dict):
            script = with_block.get("script")
            _require(isinstance(script, str) and script.strip(), f"{label}: github-script body is empty")
            _check_javascript(script, label=label)
            javascript_count += 1

    _require(action_count > 0, "workflow contains no external actions")
    _require(bash_count > 0, "workflow contains no shell contracts")
    _require(python_count > 0, "workflow contains no embedded Python contracts")
    _require(javascript_count > 0, "workflow contains no github-script contract")
    return {
        "actions": action_count,
        "bash_blocks": bash_count,
        "python_heredocs": python_count,
        "javascript_blocks": javascript_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", type=Path, default=DEFAULT_WORKFLOW)
    args = parser.parse_args()
    counts = validate_workflow(args.workflow.resolve())
    print(
        "scheduled workflow contract OK: "
        + ", ".join(f"{name}={value}" for name, value in counts.items())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
