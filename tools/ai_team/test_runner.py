"""Offline safety regressions. All outbound calls are replaced with mocks."""
import copy
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("tariff_ai_runner", Path(__file__).with_name("runner.py"))
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
HEAD, BASE = "a" * 40, "b" * 40
PATH = "customs-clear/backend/app/services/example.py"
CONTEXT = {"repository": r.REPOSITORY, "pr": 1, "head_sha": HEAD, "base_sha": BASE, "coverage": "patch_only", "files": [{"path": PATH, "patch": "@@ -1 +1 @@\n-old\n+new", "status": "modified"}]}
REVIEW = {"summary": "Patch-only advice; tests not run.", "findings": []}


def pr():
    return {"number": 1, "state": "open", "changed_files": 1, "head": {"sha": HEAD, "repo": {"full_name": r.REPOSITORY}}, "base": {"sha": BASE, "repo": {"full_name": r.REPOSITORY}}}


def source():
    text = "Synthetic fixture text, not a legal claim."
    return {"id": "fixture", "url": "https://docs.eaeunion.org/docs/example", "text": text, "text_sha256": r.digest(text.encode()), "document_sha256": "c" * 64, "captured_at": "2026-09-05T10:00:00+00:00"}


class SafetyTests(unittest.TestCase):
    def test_safe_edit_path(self):
        self.assertEqual(r.path_safe(PATH, editable=True), PATH)

    def test_path_attacks(self):
        for name in ("../x.py", "/x.py", "a/../x.py", "a//x.py", "a/./x.py", "a\\x.py", ".github/workflows/x.yml", "a/.env.json", "a/secret.py", "x.db", "a/space name.py", "a/\x00x.py"):
            with self.subTest(name=name), self.assertRaises(r.PolicyError): r.path_safe(name)

    def test_edit_protected(self):
        for name in ("backend/x.py", "AGENTS.md", "tools/ai_team/runner.py", "docs/ai-workflow/CURRENT_PROJECT_FOCUS.md", "customs-clear/backend/app/services/settings.py", "customs-clear/backend/app/services/migration.py"):
            with self.subTest(name=name), self.assertRaises(r.PolicyError): r.path_safe(name, editable=True)

    def test_secret_scan(self):
        for text in ("sk-" + "x" * 30, "sk-ant-" + "x" * 30, "AIza" + "x" * 35, "-----BEGIN PRIVATE KEY-----"):
            with self.subTest(text=text[:8]), self.assertRaises(r.PolicyError): r.text_safe(text)

    def test_no_redirect(self):
        with self.assertRaises(r.PolicyError): r.NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.com")

    def test_endpoint_overrides_forbidden(self):
        for url in ("http://api.anthropic.com/v1/messages", "https://api.anthropic.com.evil.test/x", "https://x:y@api.anthropic.com/x", "https://api.anthropic.com:444/x"):
            with self.subTest(url=url), self.assertRaises(r.PolicyError): r.request(url, {})

    def test_check_pr(self): r.check_pr(pr(), 1, HEAD, BASE)

    def test_fork(self):
        v = pr(); v["head"]["repo"]["full_name"] = "attacker/fork"
        with self.assertRaises(r.PolicyError): r.check_pr(v, 1, HEAD)

    def test_closed_pr(self):
        v = pr(); v["state"] = "closed"
        with self.assertRaises(r.PolicyError): r.check_pr(v, 1, HEAD)

    def test_stale_head(self):
        with self.assertRaises(r.PolicyError): r.check_pr(pr(), 1, "c" * 40)

    def test_stale_base(self):
        with self.assertRaises(r.PolicyError): r.check_pr(pr(), 1, HEAD, "c" * 40)

    def test_short_sha(self):
        with self.assertRaises(r.PolicyError): r.check_pr(pr(), 1, "abc1234")

    def test_collect_pr(self):
        f = {"filename": PATH, "patch": "@@ -1 +1 @@\n-old\n+new", "status": "modified", "additions": 1, "deletions": 1}
        with patch.object(r, "github", side_effect=[pr(), [f], pr()]):
            self.assertEqual(r.collect_pr(1, HEAD), CONTEXT)

    def test_collect_rejects_incomplete_patch(self):
        f = {"filename": PATH, "patch": "+new", "status": "modified", "additions": 2, "deletions": 0}
        with patch.object(r, "github", side_effect=[pr(), [f]]), self.assertRaises(r.PolicyError): r.collect_pr(1, HEAD)

    def test_collect_rejects_missing_patch(self):
        with patch.object(r, "github", side_effect=[pr(), [{"filename": PATH}]]), self.assertRaises(r.PolicyError): r.collect_pr(1, HEAD)

    def test_collect_rejects_missing_file(self):
        with patch.object(r, "github", side_effect=[pr(), []]), self.assertRaises(r.PolicyError): r.collect_pr(1, HEAD)

    def test_disabled_makes_zero_requests(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(r, "request") as req, self.assertRaises(r.PolicyError):
            r.review(CONTEXT, "claude", "model")
        req.assert_not_called()

    def test_missing_model_makes_zero_requests(self):
        with patch.dict(os.environ, {"TARIFF_AI_ENABLED": "true"}, clear=True), patch.object(r, "request") as req, self.assertRaises(r.PolicyError):
            r.review(CONTEXT, "claude", "")
        req.assert_not_called()

    def test_missing_key_makes_zero_requests(self):
        with patch.dict(os.environ, {"TARIFF_AI_ENABLED": "true"}, clear=True), patch.object(r, "request") as req, self.assertRaises(r.PolicyError):
            r.review(CONTEXT, "claude", "model")
        req.assert_not_called()

    def test_missing_evidence_is_not_pass(self):
        with patch.dict(os.environ, {"TARIFF_AI_ENABLED": "true"}, clear=True), patch.object(r, "request") as req:
            result = r.review(CONTEXT, "gemini", "model")
        self.assertEqual(result["status"], "NEEDS_EVIDENCE")
        self.assertFalse(result["merge_authorized"])
        req.assert_not_called()

    def test_claude_no_tools_one_call(self):
        response = {"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(REVIEW)}]}
        with patch.dict(os.environ, {"TARIFF_AI_ENABLED": "true", "ANTHROPIC_API_KEY": "test-only"}, clear=True), patch.object(r, "request", return_value=response) as req:
            result = r.review(CONTEXT, "claude", "model")
        self.assertEqual(req.call_count, 1)
        self.assertNotIn("tools", req.call_args.args[2])
        self.assertEqual(req.call_args.args[2]["max_tokens"], 6000)
        self.assertEqual(result["status"], "ADVISORY_ONLY")
        self.assertFalse(result["merge_authorized"])
        self.assertFalse(result["tests_executed"])

    def test_gemini_one_call_no_tools(self):
        s = source(); s["captured_at"] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)).isoformat()
        response = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(REVIEW)}]}}]}
        with patch.dict(os.environ, {"TARIFF_AI_ENABLED": "true", "GEMINI_API_KEY": "test-only"}, clear=True), patch.object(r, "request", return_value=response) as req:
            result = r.review(CONTEXT, "gemini", "model", {"sources": [s]})
        self.assertEqual(req.call_count, 1)
        self.assertNotIn("tools", req.call_args.args[2])
        self.assertNotIn("key=", req.call_args.args[0])
        self.assertEqual(result["coverage"], "provided_extracts_only_not_live_verification")
        self.assertFalse(result["merge_authorized"])

    def test_gemini_truncated_result(self):
        s = source(); s["captured_at"] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)).isoformat()
        with patch.dict(os.environ, {"TARIFF_AI_ENABLED": "true", "GEMINI_API_KEY": "test-only"}, clear=True), patch.object(r, "request", return_value={"candidates": [{"finishReason": "MAX_TOKENS"}]}), self.assertRaises(r.PolicyError):
            r.review(CONTEXT, "gemini", "model", {"sources": [s]})

    def test_truncated_result_not_success(self):
        with patch.dict(os.environ, {"TARIFF_AI_ENABLED": "true", "ANTHROPIC_API_KEY": "test-only"}, clear=True), patch.object(r, "request", return_value={"stop_reason": "max_tokens"}), self.assertRaises(r.PolicyError):
            r.review(CONTEXT, "claude", "model")

    def test_provider_error_no_retry(self):
        with patch.dict(os.environ, {"TARIFF_AI_ENABLED": "true", "ANTHROPIC_API_KEY": "test-only"}, clear=True), patch.object(r, "request", side_effect=r.PolicyError("provider_or_network_error")) as req, self.assertRaises(r.PolicyError):
            r.review(CONTEXT, "claude", "model")
        self.assertEqual(req.call_count, 1)

    def test_cannot_emit_approval(self):
        v = {**REVIEW, "merge_authorized": True}
        with self.assertRaises(r.PolicyError): r.validate_review(v, {PATH}, set())

    def test_invented_path(self):
        v = {"summary": "x", "findings": [{"path": "invented.py", "severity": "high", "evidence": "x", "recommendation": "y", "source_ids": []}]}
        with self.assertRaises(r.PolicyError): r.validate_review(v, {PATH}, set())

    def test_invented_source(self):
        v = {"summary": "x", "findings": [{"path": PATH, "severity": "high", "evidence": "x", "recommendation": "y", "source_ids": ["invented"]}]}
        with self.assertRaises(r.PolicyError): r.validate_review(v, {PATH}, set())

    def test_good_finding(self):
        v = {"summary": "x", "findings": [{"path": PATH, "severity": "high", "evidence": "x", "recommendation": "y", "source_ids": ["fixture"]}]}
        self.assertEqual(r.validate_review(v, {PATH}, {"fixture"}), v)

    def test_evidence_valid(self):
        now = dt.datetime(2026, 9, 5, 12, tzinfo=dt.timezone.utc)
        self.assertEqual(len(r.evidence_valid({"sources": [source()]}, now)), 1)

    def test_evidence_bad_fields(self):
        now = dt.datetime(2026, 9, 5, 12, tzinfo=dt.timezone.utc)
        for key, value in (("text_sha256", "d" * 64), ("document_sha256", ""), ("url", "https://docs.eaeunion.org.evil.test/x"), ("url", "http://docs.eaeunion.org/x"), ("url", "https://x:y@docs.eaeunion.org/x"), ("captured_at", "2020-01-01T00:00:00Z"), ("captured_at", "2099-01-01T00:00:00Z"), ("synthetic", True)):
            s = source(); s[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(r.PolicyError): r.evidence_valid({"sources": [s]}, now)

    def test_duplicate_evidence(self):
        now = dt.datetime(2026, 9, 5, 12, tzinfo=dt.timezone.utc)
        with self.assertRaises(r.PolicyError): r.evidence_valid({"sources": [source(), source()]}, now)

    def test_empty_evidence(self):
        with self.assertRaises(r.PolicyError): r.evidence_valid({"sources": []})

    def test_file_size_limit(self):
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "x"; f.write_bytes(b"1234")
            with self.assertRaises(r.PolicyError): r.read_bytes(f, 3)

    def test_read_symlink(self):
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "x"; f.write_text("x")
            s = Path(t) / "y"; s.symlink_to(f)
            with self.assertRaises(r.PolicyError): r.read_bytes(s)

    def test_workflows_pinned_and_read_only(self):
        root = Path(__file__).parents[2]
        # Two credentialed workflows must remain manual-only and require an
        # owner, exact trusted commit, protected environment and opt-in vars.
        for name in ("tariff-ai-review.yml", "tariff-ai-implement.yml"):
            text = (root / ".github/workflows" / name).read_text()
            self.assertIn("workflow_dispatch:", text)
            for event in ("pull_request_target:", "issue_comment:", "schedule:", "workflow_run:"):
                self.assertNotIn(event, text)
            for guard in ("TARIFF_AI_ENABLED == 'true'", "TARIFF_AI_APPROVED_SHA", "TARIFF_AI_TRUSTED_REF", "github.triggering_actor == github.repository_owner", "persist-credentials: false"):
                self.assertIn(guard, text)
            self.assertNotIn(": write", text)
            import re
            for pin in re.findall(r"uses: \S+@(\S+)", text): self.assertRegex(pin, r"^[0-9a-f]{40}$")


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root, self.frozen, self.out = base / "repo", base / "control", base / "out"
        (self.root / "tools/ai_team/tasks").mkdir(parents=True)
        (self.root / "docs").mkdir()
        (self.root / "docs/smoke.md").write_text("old\n")
        (self.root / "tools/ai_team/tasks/smoke.json").write_text(json.dumps({"goal": "Change the smoke note only.", "allowed_paths": ["docs/smoke.md"]}))
        r.prepare(self.root, "smoke", self.frozen)

    def test_candidate_only(self):
        (self.root / "docs/smoke.md").write_text("new\n")
        result = r.collect_candidate(self.root, self.frozen, self.out)
        self.assertEqual(result["status"], "CANDIDATE_ONLY")
        self.assertFalse(result["merge_authorized"])
        self.assertFalse(result["tests_verified"])
        self.assertIn("+new", (self.out / "candidate.patch").read_text())

    def test_new_file(self):
        task = {"goal": "Add only this note.", "allowed_paths": ["docs/new.md"]}
        (self.root / "tools/ai_team/tasks/smoke.json").write_text(json.dumps(task))
        r.prepare(self.root, "smoke", self.frozen)
        (self.root / "docs/new.md").write_text("new\n")
        r.collect_candidate(self.root, self.frozen, self.out)
        self.assertIn("--- /dev/null", (self.out / "candidate.patch").read_text())

    def test_no_changes(self):
        with self.assertRaises(r.PolicyError): r.collect_candidate(self.root, self.frozen, self.out)

    def test_scope_escape(self):
        (self.root / "docs/other.md").write_text("unexpected\n")
        with self.assertRaises(r.PolicyError): r.collect_candidate(self.root, self.frozen, self.out)
        self.assertFalse(self.out.exists())

    def test_hidden_file_not_ignored(self):
        (self.root / ".hidden").write_text("unexpected\n")
        with self.assertRaises(r.PolicyError): r.collect_candidate(self.root, self.frozen, self.out)

    def test_cannot_change_validator(self):
        (self.root / "tools/ai_team/runner.py").write_text("print('fake pass')\n")
        with self.assertRaises(r.PolicyError): r.collect_candidate(self.root, self.frozen, self.out)

    def test_cannot_delete(self):
        (self.root / "docs/smoke.md").unlink()
        with self.assertRaises(r.PolicyError): r.collect_candidate(self.root, self.frozen, self.out)

    def test_symlink_escape(self):
        (self.root / "docs/escape").symlink_to(self.frozen, target_is_directory=True)
        with self.assertRaises(r.PolicyError): r.collect_candidate(self.root, self.frozen, self.out)

    def test_mode_change(self):
        (self.root / "docs/smoke.md").chmod(0o755)
        with self.assertRaises(r.PolicyError): r.collect_candidate(self.root, self.frozen, self.out)

    def test_secret_candidate(self):
        (self.root / "docs/smoke.md").write_text("sk-" + "x" * 30 + "\n")
        with self.assertRaises(r.PolicyError): r.collect_candidate(self.root, self.frozen, self.out)

    def test_missing_newline(self):
        (self.root / "docs/smoke.md").write_text("new")
        with self.assertRaises(r.PolicyError): r.collect_candidate(self.root, self.frozen, self.out)

    def test_git_state_tampering(self):
        (self.root / ".git").mkdir()
        (self.root / ".git/config").write_text("tampered\n")
        with self.assertRaises(r.PolicyError): r.collect_candidate(self.root, self.frozen, self.out)

    def test_control_in_workspace_rejected(self):
        with self.assertRaises(r.PolicyError): r.prepare(self.root, "smoke", self.root / "frozen")

    def test_preexisting_output_rejected(self):
        (self.root / "docs/smoke.md").write_text("new\n")
        self.out.mkdir()
        with self.assertRaises(r.PolicyError): r.collect_candidate(self.root, self.frozen, self.out)

    def test_task_traversal(self):
        with self.assertRaises(r.PolicyError): r.prepare(self.root, "../smoke", self.frozen)


if __name__ == "__main__": unittest.main()
