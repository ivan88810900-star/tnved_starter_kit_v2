"""Independent A5 fault injection: crash recovery and persisted review forgery."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.tariff_agents.control import StateStore


class IndependentA5Tests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name) / "repository"
        self.root.mkdir()
        self.git(self.root, "init", "-b", "agent/independent-fixture")
        self.git(self.root, "config", "user.name", "Independent QA fixture")
        self.git(self.root, "config", "user.email", "qa@example.org")
        (self.root / "document.md").write_text("baseline\n")
        self.git(self.root, "add", "document.md")
        self.git(self.root, "commit", "-m", "isolated non-secret baseline")
        self.base = self.git(self.root, "rev-parse", "HEAD")
        self.store = StateStore(self.root)
        self.store.initialize()

    def git(self, root, *args):
        result = subprocess.run(["git", "-C", str(root), *args], text=True,
                                capture_output=True, check=True)
        return result.stdout.strip()

    def fresh_recovery(self):
        """No in-process StateStore, lock or monkeypatch is inherited by recovery."""
        script = ("import json,sys; from tools.tariff_agents.control import StateStore; "
                  "print(json.dumps(StateStore(sys.argv[1]).recover()))")
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run([sys.executable, "-c", script, str(self.root)],
                              cwd=Path(__file__).resolve().parents[2], env=env,
                              capture_output=True, text=True, timeout=20)

    def test_committed_board_survives_crash_before_projection_write(self):
        before = self.store.load()["revision"]
        with patch.object(self.store, "_project", side_effect=RuntimeError("simulated crash")):
            with self.assertRaisesRegex(RuntimeError, "simulated crash"):
                self.store.add_task("durable-task", "A3", ["document.md"],
                                    required_checks=["source-regression"])
        result = self.fresh_recovery()
        self.assertEqual(result.returncode, 0, result.stderr)
        restored = json.loads(result.stdout)
        self.assertEqual(restored["board"]["revision"], before + 1)
        self.assertEqual([t["id"] for t in restored["board"]["tasks"]], ["durable-task"])
        for name in ("AGENT_OWNERSHIP.json", "FINDINGS.json", "RUN_HISTORY.json"):
            projection = json.loads((self.root / ".ai" / name).read_text())
            self.assertEqual(projection["board_revision"], before + 1)
        self.assertFalse(restored["duplicate_launch_authorized"])

    def test_fresh_session_rejects_persisted_author_as_qa(self):
        self.store.add_task("reviewed-task", "A1", ["document.md"],
                            required_checks=["offline-regression"])
        task = self.store.allocate("reviewed-task", self.base)
        worktree = Path(task["worktree"])
        self.store.start("reviewed-task", "independent-fixture-author")
        (worktree / "document.md").write_text("safe documentation change\n")
        self.git(worktree, "add", "document.md")
        self.git(worktree, "commit", "-m", "isolated candidate")
        head = self.git(worktree, "rev-parse", "HEAD")
        self.store.finish_session("independent-fixture-author")
        # Evidence rows here are explicit test fixtures, not claims of external CI.
        tests = [{"command": "fixture regression", "exit_code": 0, "output": "fixture pass"}]
        self.store.implemented("reviewed-task", head, tests)
        self.store.start("reviewed-task", "independent-fixture-reviewer", "A5")
        self.store.record_qa("reviewed-task", head, "independent-fixture-reviewer", tests)
        self.store.finish_session("independent-fixture-reviewer")
        self.store.record_audit("reviewed-task", head, "NOT_REQUIRED", "low-risk fixture")
        self.store.record_ci("reviewed-task", head, [{"name": "offline-regression",
            "head_sha": head, "conclusion": "success", "run_id": 77,
            "url": "https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/77"}])
        board = self.store.load()
        self.assertEqual(board["tasks"][0]["status"], "READY_FOR_HUMAN_APPROVAL")
        board["tasks"][0]["qa"]["reviewer_session_id"] = "independent-fixture-author"
        (self.root / ".ai/TASK_BOARD.json").write_text(json.dumps(board))
        result = self.fresh_recovery()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("independent_qa_required", result.stderr)
        self.assertNotIn("ready_tasks", result.stdout)


if __name__ == "__main__":
    unittest.main()
