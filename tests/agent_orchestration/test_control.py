"""Real temporary Git repositories exercise state, isolation and review gates."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

MODULE = Path(__file__).resolve().parents[2] / "tools/tariff_agents/control.py"
spec = importlib.util.spec_from_file_location("control", MODULE)
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)

TESTS = [{"command": "python -m unittest", "exit_code": 0, "output": "Ran 3 tests: OK"}]


def git(root, *args):
    p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if p.returncode:
        raise AssertionError(p.stderr)
    return p.stdout.strip()


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        git(self.root, "init", "-b", "agent/integration")
        git(self.root, "config", "user.email", "fixture@example.invalid")
        git(self.root, "config", "user.name", "Fixture")
        (self.root / "docs").mkdir()
        (self.root / "docs/base.md").write_text("baseline\n")
        (self.root / ".ai").mkdir()
        (self.root / ".ai/CURRENT_STATE.md").write_text("legacy state preserved\n")
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", "fixture")
        self.base = git(self.root, "rev-parse", "HEAD")
        self.store = c.StateStore(self.root)
        self.store.initialize()

    def task(self, name="T1", risk="low", files=None):
        self.store.add_task(name, "A1", files or ["docs/" + name + ".md"], risk=risk, required_checks=["offline"])
        return self.store.allocate(name, self.base)

    def candidate(self, name="T1", risk="low"):
        task = self.task(name, risk)
        path = Path(task["worktree"])
        self.store.start(name, "author-" + name)
        for filename in task["files"]:
            (path / filename).parent.mkdir(parents=True, exist_ok=True)
            (path / filename).write_text("safe candidate\n")
        git(path, "add", *task["files"])
        git(path, "commit", "-m", "safe candidate")
        head = git(path, "rev-parse", "HEAD")
        self.store.finish_session("author-" + name)
        self.store.implemented(name, head, TESTS)
        return task, head

    def qa(self, name="T1", risk="low"):
        task, head = self.candidate(name, risk)
        self.store.start(name, "qa-" + name, "A5")
        self.store.record_qa(name, head, "qa-" + name, TESTS)
        self.store.finish_session("qa-" + name)
        return task, head

    def check(self, head, conclusion="success", name="offline", run_id=123):
        return {"name": name, "head_sha": head, "conclusion": conclusion, "run_id": run_id, "url": f"https://github.com/{c.REPOSITORY}/actions/runs/{run_id}"}

    def ready(self, name="T1"):
        task, head = self.qa(name)
        self.store.record_audit(name, head, "NOT_REQUIRED", "low-risk documentation")
        self.store.record_ci(name, head, [self.check(head)])
        return task, head

    def test_initialization_preserves_legacy_and_derives_companions(self):
        self.assertEqual((self.root / ".ai/CURRENT_STATE.md").read_text(), "legacy state preserved\n")
        self.assertEqual(self.store.initialize()["tasks"], [])
        self.store.add_task("T1", "A1", ["docs/T1.md"])
        (self.root / ".ai/AGENT_OWNERSHIP.json").write_text('{"corrupted":"projection"}')
        report = c.StateStore(self.root).recover()
        self.assertEqual(report["board"]["tasks"][0]["id"], "T1")
        self.assertEqual(json.loads((self.root / ".ai/AGENT_OWNERSHIP.json").read_text())["board_revision"], report["board"]["revision"])

    def test_idempotent_creation_and_scope_conflict(self):
        self.store.add_task("T1", "A1", ["docs/a.md"])
        self.store.add_task("T1", "A1", ["docs/a.md"])
        self.assertEqual(len(self.store.load()["tasks"]), 1)
        with self.assertRaisesRegex(c.PolicyError, "task_id_conflict"):
            self.store.add_task("T1", "A1", ["docs/b.md"])

    def test_dependency_cycle_and_unknown_dependency_atomic_rejection(self):
        self.store.add_task("A", "A1", ["docs/a.md"])
        self.store.add_task("B", "A2", ["docs/b.md"], dependencies=["A"])
        before = self.store.load()
        with self.assertRaisesRegex(c.PolicyError, "dependency_cycle"):
            self.store.update_task("A", dependencies=["B"])
        self.assertEqual(self.store.load(), before)
        with self.assertRaisesRegex(c.PolicyError, "unknown_dependency"):
            self.store.update_task("A", dependencies=["missing"])
        with self.assertRaisesRegex(c.PolicyError, "dependencies_incomplete"):
            self.store.allocate("B", self.base)

    def test_no_arbitrary_protected_branch_or_path(self):
        for value in ("main", "feat/canonical-read-path", "feat/ntm-official-full-contours", "agent/a/../../main", "agent/a.lock", "--evil"):
            with self.subTest(branch=value), self.assertRaises(c.PolicyError):
                c.safe_branch(value)
        for value in ("../docs/a.md", "docs//a.md", "docs/./a.md", "/tmp/a.md", ".git/config", "docs\\a.md", ".env", "x/.env.production", "prod.db", "keys/token.txt"):
            with self.subTest(path=value), self.assertRaises(c.PolicyError):
                c.safe_path(value)

    def test_real_isolated_worktrees_and_shared_authority(self):
        a, b = self.task("A"), self.task("B")
        self.assertNotEqual(a["worktree"], b["worktree"])
        self.assertNotEqual(a["branch"], b["branch"])
        self.assertEqual(git(Path(a["worktree"]), "rev-parse", "HEAD"), self.base)
        (Path(a["worktree"]) / "docs/A.md").write_text("one workspace only\n")
        self.assertFalse((Path(b["worktree"]) / "docs/A.md").exists())
        self.assertEqual(c.StateStore(a["worktree"]).load(), self.store.load())
        self.assertEqual(self.store.allocate("B", self.base)["worktree"], b["worktree"])

    def test_lock_cross_process_and_worktree(self):
        task = self.task()
        script = "import importlib.util,sys; s=importlib.util.spec_from_file_location('c',sys.argv[1]); c=importlib.util.module_from_spec(s); s.loader.exec_module(c); c.StateStore(sys.argv[2]).load()"
        with self.store.lock():
            p = subprocess.run([sys.executable, "-c", script, str(MODULE), task["worktree"]], capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("a0_lock_busy", p.stderr)
        self.assertEqual(c.StateStore(task["worktree"]).load()["tasks"][0]["id"], "T1")

    def test_two_tasks_cannot_own_same_file_or_directory(self):
        self.task("A", files=["docs/shared.md"])
        self.store.add_task("B", "A2", ["docs/shared.md"])
        with self.assertRaisesRegex(c.PolicyError, "duplicate_file"):
            self.store.allocate("B", self.base)
        self.assertIsNone(self.store.load()["tasks"][1]["worktree"])
        self.store.add_task("C", "A3", ["docs"])
        with self.assertRaisesRegex(c.PolicyError, "exact_file_required"):
            self.store.allocate("C", self.base)

    def test_dirty_source_rejected_and_worker_symlink_rejected(self):
        self.store.add_task("T1", "A1", ["docs/T1.md"])
        (self.root / "docs/unrelated.md").write_text("user work\n")
        with self.assertRaisesRegex(c.PolicyError, "dirty_worktree"):
            self.store.allocate("T1", self.base)
        (self.root / "docs/unrelated.md").unlink()
        task = self.store.allocate("T1", self.base)
        self.store.start("T1", "author")
        path = Path(task["worktree"])
        (path / "docs/T1.md").symlink_to("base.md")
        git(path, "add", "docs/T1.md")
        git(path, "commit", "-m", "link attack")
        with self.assertRaisesRegex(c.PolicyError, "symlink_forbidden"):
            self.store.implemented("T1", git(path, "rev-parse", "HEAD"), TESTS)

    def test_state_and_parent_symlinks_rejected(self):
        board = self.root / ".ai/TASK_BOARD.json"
        backup = self.root / "saved.json"
        board.rename(backup)
        board.symlink_to(backup)
        with self.assertRaisesRegex(c.PolicyError, "symlink_forbidden"):
            self.store.load()

    def test_three_concurrent_sessions_including_qa(self):
        _, head = self.candidate("Q")
        self.store.start("Q", "qa", "A5")
        for name in ("A", "B", "C"):
            self.task(name)
        self.store.start("A", "a")
        self.store.start("B", "b")
        with self.assertRaisesRegex(c.PolicyError, "concurrency_limit"):
            self.store.start("C", "c")
        self.assertEqual(len([r for r in self.store.load()["runs"] if r["status"] == "RUNNING"]), 3)
        self.store.finish_session("qa")
        self.store.start("C", "c")

    def test_author_cannot_claim_qa_or_fabricate_missing_session(self):
        _, head = self.candidate()
        with self.assertRaisesRegex(c.PolicyError, "independent_qa_required"):
            self.store.record_qa("T1", head, "author-T1", TESTS)
        with self.assertRaisesRegex(c.PolicyError, "independent_qa_session_required"):
            self.store.record_qa("T1", head, "invented", TESTS)

    def test_claim_without_isolation_or_tests_fails(self):
        self.store.add_task("T1", "A1", ["docs/T1.md"])
        with self.assertRaisesRegex(c.PolicyError, "task_not_allocated"):
            self.store.start("T1", "author")
        with self.assertRaisesRegex(c.PolicyError, "tests_required"):
            self.store.implemented("T1", self.base, [])
        with self.assertRaisesRegex(c.PolicyError, "test_failed"):
            self.store.implemented("T1", self.base, [{"command": "false", "exit_code": 1, "output": "failed"}])

    def test_out_of_scope_commit_rejected(self):
        task, _ = self.candidate()
        path = Path(task["worktree"])
        (path / "docs/elsewhere.md").write_text("out of scope\n")
        git(path, "add", "docs/elsewhere.md")
        git(path, "commit", "-m", "scope escape")
        with self.assertRaisesRegex(c.PolicyError, "candidate_outside_file_ownership"):
            self.store.implemented("T1", git(path, "rev-parse", "HEAD"), TESTS)

    def test_ready_requires_all_successful_current_ci_checks(self):
        _, head = self.qa()
        self.store.record_audit("T1", head, "NOT_REQUIRED", "low risk")
        for checks in ([], [self.check(head, name="wrong")], [self.check(head, conclusion="skipped")], [self.check("f" * 40)], [self.check(head), self.check(head)]):
            with self.subTest(checks=checks), self.assertRaises(c.PolicyError):
                self.store.record_ci("T1", head, checks)
        task = self.store.record_ci("T1", head, [self.check(head)])
        self.assertEqual(task["status"], "READY_FOR_HUMAN_APPROVAL")

    def test_high_risk_unavailable_external_audit_cannot_greenwash(self):
        _, head = self.qa(risk="high")
        with self.assertRaisesRegex(c.PolicyError, "high_risk_audit_required"):
            self.store.record_audit("T1", head, "NOT_REQUIRED", "claim")
        self.store.record_audit("T1", head, "UNAVAILABLE", "Anthropic credentials absent")
        task = self.store.record_ci("T1", head, [self.check(head)])
        self.assertEqual(task["status"], "CI_PENDING")
        self.assertEqual(task["external_audit"]["status"], "UNAVAILABLE")

    def test_new_commit_and_dirty_tree_revoke_readiness_on_recovery(self):
        task, head = self.ready()
        path = Path(task["worktree"])
        (path / "docs/T1.md").write_text("changed after checks\n")
        with self.assertRaisesRegex(c.PolicyError, "dirty_worktree"):
            self.store.record_ci("T1", head, [self.check(head)])
        git(path, "add", "docs/T1.md")
        git(path, "commit", "-m", "new candidate")
        result = self.store.recover()
        row = result["board"]["tasks"][0]
        self.assertEqual(result["worktree_issues"], ["T1"])
        self.assertEqual(row["status"], "CHANGES_REQUESTED")
        self.assertIsNone(row["qa"])
        self.assertIsNone(row["external_audit"])
        self.assertIsNone(row["ci"])
        self.assertEqual(result["ready_tasks"], [])

    def test_confirmed_finding_invalidates_gates_and_routes_owner(self):
        task, head = self.ready()
        self.store.add_finding("F1", "T1", "A6", "reproducible issue", head)
        self.assertEqual(self.store.load()["tasks"][0]["status"], "CI_PENDING")
        self.store.validate_finding("F1", True, "A0 reproduced failing edge case")
        row = self.store.load()["tasks"][0]
        self.assertEqual(row["owner"], "A1")
        self.assertEqual(row["status"], "CHANGES_REQUESTED")
        self.assertIsNone(row["qa"])
        with self.assertRaisesRegex(c.PolicyError, "new_fix_commit_required"):
            self.store.resolve_finding("F1", head, "same code cannot resolve")

    def test_resume_fresh_clone_from_git_state_reports_missing_worktrees(self):
        self.ready()
        git(self.root, "add", ".ai")
        git(self.root, "commit", "-m", "persist state")
        clone = Path(self.temp.name) / "fresh"
        git(self.root, "clone", "--no-hardlinks", str(self.root), str(clone))
        recovered = c.StateStore(clone).recover()
        self.assertEqual(recovered["worktree_issues"], ["T1"])
        self.assertFalse(recovered["duplicate_launch_authorized"])
        self.assertEqual(recovered["board"]["tasks"][0]["status"], "CHANGES_REQUESTED")

    def test_stale_sessions_never_implicitly_finish_or_duplicate(self):
        self.task()
        self.store.start("T1", "actual-session")
        board = self.store.load()
        board["runs"][0]["updated_at"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        (self.root / ".ai/TASK_BOARD.json").write_text(json.dumps(board))
        report = c.StateStore(self.root).recover(60)
        self.assertEqual(report["stale_sessions"], ["actual-session"])
        self.assertEqual(report["board"]["runs"][0]["status"], "RUNNING")
        with self.assertRaises(c.PolicyError):
            self.store.start("T1", "duplicate-session")

    def test_cancel_does_not_delete_branch_or_worktree(self):
        task = self.task()
        self.store.cancel_task("T1")
        self.assertTrue(Path(task["worktree"]).is_dir())
        self.assertEqual(git(self.root, "rev-parse", task["branch"]), self.base)

    def test_actual_native_session_ids_preserved(self):
        self.task()
        run = self.store.start("T1", "/root/discovery_repo")
        self.assertEqual(run["session_id"], "/root/discovery_repo")
        self.assertEqual(self.store.load()["runs"][0]["session_id"], "/root/discovery_repo")

    def test_persisted_ready_without_gates_fails_closed(self):
        self.store.add_task("T1", "A1", ["docs/T1.md"], risk="high", required_checks=["offline"])
        board = self.store.load()
        board["tasks"][0]["status"] = "READY_FOR_HUMAN_APPROVAL"
        (self.root / ".ai/TASK_BOARD.json").write_text(json.dumps(board))
        with self.assertRaises(c.PolicyError):
            c.StateStore(self.root).recover()

    def test_release_ownership_requires_handoff_then_allows_followup(self):
        task, head = self.ready()
        with self.assertRaisesRegex(c.PolicyError, "integration_content_differs"):
            self.store.release_ownership("T1", self.base, "not yet integrated")
        released = self.store.release_ownership("T1", head, "identical candidate accepted into integration review")
        self.assertEqual(released["status"], "INTEGRATED")
        self.assertTrue(Path(task["worktree"]).exists())
        self.store.add_task("T2", "A1", task["files"], dependencies=["T1"])
        with self.assertRaisesRegex(c.PolicyError, "dependency_content_missing_from_base"):
            self.store.allocate("T2", self.base)
        new = self.store.allocate("T2", head)
        self.assertNotEqual(new["worktree"], task["worktree"])

    def test_external_pass_requires_live_receipt_and_a0_adjudication(self):
        task, head = self.qa(risk="high")
        with self.assertRaisesRegex(c.PolicyError, "bound_audit_result_required"):
            self.store.record_audit("T1", head, "PASSED", "Claude said okay")
        result = {"auditor": "A6", "head_sha": head, "base_sha": self.base,
                  "packet_sha256": "a" * 64, "live_verified": True,
                  "advisory_only": True, "message_id": "msg_fixture", "model": "fixture",
                  "a0_validated": True, "unresolved_findings": 0, "findings": []}
        missing = dict(result)
        missing.pop("message_id")
        with self.assertRaisesRegex(c.PolicyError, "audit_provider_receipt_required"):
            self.store.record_audit("T1", head, "PASSED", missing)
        findings = dict(result, findings=[{"id": "F1"}])
        with self.assertRaisesRegex(c.PolicyError, "audit_finding_not_adjudicated"):
            self.store.record_audit("T1", head, "PASSED", findings)
        self.store.record_audit("T1", head, "PASSED", result)
        self.assertEqual(self.store.record_ci("T1", head, [self.check(head)])["status"], "READY_FOR_HUMAN_APPROVAL")

    def unavailable_receipt(self, head, **fields):
        return {"auditor": "A6", "base_sha": self.base, "head_sha": head,
                "packet_sha256": "b" * 64, "advisory_only": True,
                "a0_validation": "PENDING", "status": "UNAVAILABLE",
                "live_verified": False, **fields}

    def test_optional_a6_not_configured_receipt_allows_high_risk_readiness(self):
        _, head = self.qa(risk="high")
        receipt = self.unavailable_receipt(head, missing=["ANTHROPIC_API_KEY", "TARIFF_ANTHROPIC_MODEL"])
        self.store.record_audit("T1", head, "UNAVAILABLE", receipt)
        task = self.store.record_ci("T1", head, [self.check(head)])
        self.assertEqual(task["status"], "READY_FOR_HUMAN_APPROVAL")
        self.assertEqual(task["external_audit"]["status"], "UNAVAILABLE")
        self.assertEqual(task["external_audit"]["availability"], "NOT_CONFIGURED")
        self.assertEqual(c.StateStore(self.root).recover()["ready_tasks"], ["T1"])

    def test_configured_a6_failure_stays_blocking_and_cannot_claim_missing(self):
        _, head = self.qa(risk="high")
        failure = self.unavailable_receipt(head, reason="External audit failed or returned invalid evidence")
        self.store.record_audit("T1", head, "UNAVAILABLE", failure)
        self.assertEqual(self.store.record_ci("T1", head, [self.check(head)])["status"], "CI_PENDING")
        for invalid in (dict(failure, missing=["ANTHROPIC_API_KEY"]), self.unavailable_receipt(head, missing=[]), self.unavailable_receipt("a" * 40, missing=["ANTHROPIC_API_KEY"]), self.unavailable_receipt(head, missing=["network"])):
            with self.subTest(receipt=invalid), self.assertRaises(c.PolicyError):
                self.store.record_audit("T1", head, "UNAVAILABLE", invalid)

    def test_same_native_qa_session_can_review_sequential_tasks(self):
        _, first = self.candidate("A")
        _, second = self.candidate("B")
        session = "/root/a5_independent_qa"
        self.store.start("A", session, "A5")
        with self.assertRaisesRegex(c.PolicyError, "session_id_conflict"):
            self.store.start("B", session, "A5")
        self.store.record_qa("A", first, session, TESTS)
        self.store.finish_session(session)
        self.store.start("B", session, "A5")
        self.store.record_qa("B", second, session, TESTS)
        self.store.finish_session(session)
        runs = [r for r in self.store.load()["runs"] if r["session_id"] == session]
        self.assertEqual(len(runs), 2)
        self.assertNotEqual(runs[0]["run_id"], runs[1]["run_id"])
        self.assertEqual({r["task_id"] for r in runs}, {"A", "B"})

    def test_native_author_can_resume_after_confirmed_finding(self):
        task, head = self.ready()
        self.store.add_finding("F1", "T1", "A5", "reproduction", head)
        self.store.validate_finding("F1", True, "A0 reproduction evidence")
        run = self.store.start("T1", "author-T1")
        self.assertEqual(run["session_id"], "author-T1")
        self.store.finish_session("author-T1")
        path = Path(task["worktree"])
        (path / "docs/T1.md").write_text("fixed candidate\n")
        git(path, "add", "docs/T1.md")
        git(path, "commit", "-m", "corrective followup")
        changed = git(path, "rev-parse", "HEAD")
        self.store.implemented("T1", changed, TESTS)
        with self.assertRaisesRegex(c.PolicyError, "independent_qa_session_required"):
            self.store.record_qa("T1", changed, "qa-T1", TESTS)
        self.store.start("T1", "qa-T1", "A5")
        self.store.record_qa("T1", changed, "qa-T1", TESTS)


if __name__ == "__main__":
    unittest.main()
