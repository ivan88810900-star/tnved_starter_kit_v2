"""Fail-closed contracts for deprecated source automation entry points."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from scripts import auto_updater, initial_sync


BACKEND_ROOT = Path(__file__).resolve().parent.parent
LEGACY_OPT_IN = "CUSTOMSCLEAR_ALLOW_LEGACY_AUTOMATION"


def _env_without_legacy_opt_in() -> dict[str, str]:
    env = dict(os.environ)
    env.pop(LEGACY_OPT_IN, None)
    return env


def test_auto_updater_refuses_to_schedule_or_run_without_explicit_opt_in() -> None:
    with (
        patch.dict(os.environ, {}, clear=True),
        patch.object(sys, "argv", ["auto_updater.py", "--run-once", "rates"]),
        patch.object(auto_updater, "run_subprocess") as run,
        patch.object(auto_updater, "build_scheduler") as build,
    ):
        assert auto_updater.main() == 2
    run.assert_not_called()
    build.assert_not_called()


def test_initial_sync_refuses_all_writes_without_explicit_opt_in() -> None:
    with (
        patch.dict(os.environ, {}, clear=True),
        patch.object(sys, "argv", ["initial_sync.py", "--skip-ifcg"]),
        patch.object(initial_sync, "run_one") as run,
    ):
        assert initial_sync.main() == 2
    run.assert_not_called()


@pytest.mark.parametrize("script_name", ("auto_update.sh", "run_critical_syncs.sh"))
def test_legacy_shell_entrypoint_exits_before_work_without_opt_in(script_name: str) -> None:
    result = subprocess.run(
        ["bash", str(BACKEND_ROOT / "scripts" / script_name)],
        cwd=BACKEND_ROOT,
        env=_env_without_legacy_opt_in(),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 2
    assert "CUSTOMSCLEAR_ALLOW_LEGACY_AUTOMATION=1" in result.stderr


@pytest.mark.parametrize(
    ("script", "url"),
    (
        ("scripts/sync_ofac_sanctions.py", ""),
        ("scripts/sync_eu_sanctions.py", ""),
        ("scripts/sync_ofac_sanctions.py", "https://fixture.invalid/ofac.xml"),
        ("scripts/sync_eu_sanctions.py", "https://fixture.invalid/eu.xml"),
    ),
)
def test_initial_sync_sanctions_commands_are_always_validation_only(
    script: str,
    url: str,
) -> None:
    argv = initial_sync._sanctions_validation_argv(script, url)
    assert argv[0] == script
    assert {"--validate-only", "--strict", "--json"}.issubset(argv)
    assert "--apply" not in argv
    if url:
        assert argv[-2:] == ["--url", url]
        assert "--official-only" not in argv
    else:
        assert "--official-only" in argv


def test_critical_sync_sanctions_are_official_validation_only() -> None:
    content = (BACKEND_ROOT / "scripts" / "run_critical_syncs.sh").read_text(encoding="utf-8")
    for script in ("sync_ofac_sanctions.py", "sync_eu_sanctions.py"):
        line_start = content.index(script)
        command = content[line_start : line_start + 180]
        assert "--official-only" in command
        assert "--validate-only" in command
        assert "--strict" in command
        assert "--json" in command
