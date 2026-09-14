"""Independent A5 fault injection: crash recovery and persisted review forgery."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from tools.tariff_agents.control import StateStore
from tools.tariff_agents import verify


class IndependentA5Tests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name) / "repository"
        self.root.mkdir()
        self.git(self.root, "init", "-b", "agent/orchestration-state")
        self.git(self.root, "config", "user.name", "Independent QA fixture")
        self.git(self.root, "config", "user.email", "qa@example.org")
        (self.root / "document.md").write_text("baseline\n")
        self.git(self.root, "add", "document.md")
        self.git(self.root, "commit", "-m", "isolated non-secret baseline")
        self.base = self.git(self.root, "rev-parse", "HEAD")
        self.store = StateStore(self.root)
        self.store.bootstrap_authority(
            "ivan88810900-star/tnved_starter_kit_v2",
            "refs/heads/agent/orchestration-state", self.base)
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

    def test_verifier_requires_independent_a5_module_and_nonzero_tests(self):
        self.assertIn("test_a5_independent", verify.REQUIRED)
        directory = Path(self.scratch.name) / "missing-a5"
        directory.mkdir()
        with self.assertRaisesRegex(RuntimeError, "test_a5_independent"):
            verify._load_required(directory, "test_a5_independent",
                                  unittest.TestLoader())
        (directory / "test_a5_independent.py").write_text('"""empty"""\n')
        with self.assertRaisesRegex(RuntimeError, "test_a5_independent"):
            verify._load_required(directory, "test_a5_independent",
                                  unittest.TestLoader())

    def test_bridge_admission_is_conditional_and_fails_closed(self):
        fixture = Path(self.scratch.name) / "bridge-admission"
        directory = fixture / "tests/agent_orchestration"
        directory.mkdir(parents=True)
        self.assertNotIn(verify.BRIDGE_TEST,
                         verify._required_names(fixture, directory))

        # Each individual artifact is sufficient to require bridge tests.
        for index, artifact in enumerate(verify.BRIDGE_ARTIFACTS):
            root = fixture / str(index)
            tests = root / "tests/agent_orchestration"
            tests.mkdir(parents=True)
            marker = root / artifact
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("fixture\n")
            self.assertIn(verify.BRIDGE_TEST,
                          verify._required_names(root, tests))

        root = fixture / "missing-tests"
        tests = root / "tests/agent_orchestration"
        tests.mkdir(parents=True)
        marker = root / verify.BRIDGE_ARTIFACTS[0]
        marker.parent.mkdir(parents=True)
        marker.write_text("fixture\n")
        self.assertIn(verify.BRIDGE_TEST, verify._required_names(root, tests))
        with self.assertRaisesRegex(RuntimeError, verify.BRIDGE_TEST):
            verify._load_required(tests, verify.BRIDGE_TEST,
                                  unittest.TestLoader())
        (tests / "test_audit_bridge.py").write_text('"""empty"""\n')
        with self.assertRaisesRegex(RuntimeError, verify.BRIDGE_TEST):
            verify._load_required(tests, verify.BRIDGE_TEST,
                                  unittest.TestLoader())

    def test_broken_symlink_bridge_artifact_fails_admission(self):
        root = Path(self.scratch.name) / "broken-bridge"
        directory = root / "tests/agent_orchestration"
        directory.mkdir(parents=True)
        marker = root / verify.BRIDGE_ARTIFACTS[0]
        marker.parent.mkdir(parents=True)
        marker.symlink_to("missing-workflow.yml")
        with self.assertRaisesRegex(RuntimeError, "Invalid bridge artifact"):
            verify._required_names(root, directory)

        root = Path(self.scratch.name) / "nonregular-bridge"
        directory = root / "tests/agent_orchestration"
        directory.mkdir(parents=True)
        marker = root / verify.BRIDGE_ARTIFACTS[1]
        marker.mkdir(parents=True)
        with self.assertRaisesRegex(RuntimeError, "Invalid bridge artifact"):
            verify._required_names(root, directory)

    def test_required_suite_ignores_ambient_import_and_rejects_nonregular(self):
        fixture = Path(self.scratch.name) / "exact-suite"
        directory = fixture / "repository-tests"
        ambient = fixture / "ambient"
        directory.mkdir(parents=True)
        ambient.mkdir()
        (directory / "test_control.py").write_text(
            "import unittest\n"
            "class ExactTest(unittest.TestCase):\n"
            "    def test_exact_repository_file(self): self.assertTrue(True)\n")
        (ambient / "test_control.py").write_text("raise RuntimeError('ambient')\n")
        poisoned = types.ModuleType("test_control")
        poisoned.__file__ = str(ambient / "test_control.py")
        with patch.dict(sys.modules, {
                "test_control": poisoned,
                "_tariff_required_test_control": poisoned,
        }), patch.object(sys, "path", [str(ambient), *sys.path]), patch.dict(
                os.environ, {"PYTHONPATH": str(ambient)}):
            suite = verify._load_required(directory, "test_control",
                                          unittest.TestLoader())
            result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(result.testsRun, 1)

        symlink = directory / "test_runtime.py"
        symlink.symlink_to("missing.py")
        with self.assertRaisesRegex(RuntimeError, "Invalid required test file"):
            verify._load_required(directory, "test_runtime",
                                  unittest.TestLoader())
        nonregular = directory / "test_audit.py"
        nonregular.mkdir()
        with self.assertRaisesRegex(RuntimeError, "Invalid required test file"):
            verify._load_required(directory, "test_audit",
                                  unittest.TestLoader())


if __name__ == "__main__":
    unittest.main()
