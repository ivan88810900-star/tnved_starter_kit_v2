"""The offline snapshot validator must not acquire controller authority."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[2]


def run(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "tools.tariff_agents", "--repo", str(root),
         *arguments],
        cwd=PROJECT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments], capture_output=True, text=True,
        timeout=60,
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


def board() -> dict:
    return {
        "schema_version": 1,
        "revision": 7,
        "max_concurrent_subagents": 3,
        "tasks": [],
        "findings": [],
        "runs": [],
        "updated_at": "2026-09-14T00:00:00+00:00",
    }


class SnapshotValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        git(self.root, "init", "-b", "agent/ci-fixture")
        git(self.root, "config", "user.email", "fixture@example.invalid")
        git(self.root, "config", "user.name", "Fixture")

    def commit_board(self, value: object) -> None:
        path = self.root / ".ai" / "TASK_BOARD.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, str):
            path.write_text(value, encoding="utf-8")
        else:
            path.write_text(json.dumps(value), encoding="utf-8")
        git(self.root, "add", ".ai/TASK_BOARD.json")
        git(self.root, "commit", "-m", "snapshot fixture")

    def authority_path(self) -> Path:
        common = Path(git(
            self.root, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        return common / "tariff-agents" / "authority.json"

    def test_valid_committed_snapshot_is_read_only_without_authority(self) -> None:
        self.commit_board(board())
        snapshot = (self.root / ".ai/TASK_BOARD.json").read_bytes()
        status = git(self.root, "status", "--porcelain=v1", "--untracked-files=all")

        result = run(self.root, "validate-snapshot")

        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertTrue(receipt["valid"])
        self.assertEqual(receipt["revision"], 7)
        self.assertEqual(receipt["head_sha"], git(self.root, "rev-parse", "HEAD"))
        self.assertEqual((self.root / ".ai/TASK_BOARD.json").read_bytes(), snapshot)
        self.assertEqual(
            git(self.root, "status", "--porcelain=v1", "--untracked-files=all"),
            status,
        )
        self.assertFalse(self.authority_path().exists())

    def test_missing_and_malformed_committed_snapshots_fail(self) -> None:
        (self.root / "README.md").write_text("fixture\n", encoding="utf-8")
        git(self.root, "add", "README.md")
        git(self.root, "commit", "-m", "missing snapshot")
        missing = run(self.root, "validate-snapshot")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("git_command_failed", missing.stderr)
        self.assertFalse(self.authority_path().exists())

        self.commit_board("{not-json")
        malformed = run(self.root, "validate-snapshot")
        self.assertNotEqual(malformed.returncode, 0)
        self.assertIn("invalid_json_state", malformed.stderr)
        self.assertFalse(self.authority_path().exists())

        invalid_schema = board()
        invalid_schema["max_concurrent_subagents"] = 4
        self.commit_board(invalid_schema)
        invalid = run(self.root, "validate-snapshot")
        self.assertNotEqual(invalid.returncode, 0)
        self.assertIn("invalid_board_config", invalid.stderr)
        self.assertFalse(self.authority_path().exists())

    def test_authoritative_commands_still_fail_closed(self) -> None:
        self.commit_board(board())
        for arguments in (
            ("validate",),
            ("init",),
            ("add", "T1", "--owner", "A1", "--file", "docs/a.md",
             "--goal", "fixture", "--required-check", "offline"),
        ):
            with self.subTest(arguments=arguments):
                result = run(self.root, *arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("state_authority_missing", result.stderr)
                self.assertFalse(self.authority_path().exists())

    def test_safety_workflow_admits_live_bridge_changes(self) -> None:
        workflow = (PROJECT / ".github/workflows/tariff-agent-safety.yml").read_text(
            encoding="utf-8")
        pull_request = workflow.split("  pull_request:\n", 1)[1].split(
            "  push:\n", 1)[0]
        self.assertIn("'.github/workflows/tariff-a6-live.yml'", pull_request)


if __name__ == "__main__":
    unittest.main()
