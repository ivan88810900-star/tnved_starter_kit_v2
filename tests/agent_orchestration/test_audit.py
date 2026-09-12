"""MOCK external audit tests: real local Git, no live Anthropic API calls."""

import copy
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.tariff_agents import audit


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Audit Fixture")
        self.git("config", "user.email", "audit@example.com")
        self.write(audit.CONTRACT_PATH, "A0 verifies findings; no production writes.\n")
        self.write("src/payments.py", "amount = 10\n")
        self.write("tests/check.py", "assert 1 + 1 == 2\n")
        self.base = self.commit()
        self.write("src/payments.py", "amount = 11\n")
        self.head = self.commit()
        self.paths = [audit.CONTRACT_PATH, "src/payments.py", "tests/check.py"]
        self.env = {"ANTHROPIC_API_KEY": "fixture-anthropic-credential",
                    "TARIFF_ANTHROPIC_MODEL": "explicit-fixture-model"}

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.repo, stderr=subprocess.DEVNULL).decode().strip()

    def write(self, path, text):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD")

    def packet(self, **kwargs):
        return audit.build_packet(self.repo, self.base, self.head, self.paths, environ={}, **kwargs)

    def findings(self, packet):
        return {"packet_sha256": packet["packet_sha256"], "head_sha": packet["head_sha"],
                "findings": [{"id": "F1", "severity": "high", "category": "payment",
                              "path": "src/payments.py", "line": 1,
                              "claim": "Unexplained amount change", "evidence": "10 changed to 11",
                              "suggested_fix": "Check intended amount", "official_source_urls": []}],
                "limitations": ["No normative source content provided"]}

    def test_packet_binds_complete_committed_diff_not_dirty_worktree(self):
        packet = self.packet()
        self.write("src/payments.py", "uncommitted = 999\n")
        self.assertEqual(self.packet(), packet)
        self.assertEqual(packet["head_sha"], self.head)
        self.assertEqual(packet["changed_paths"], ["src/payments.py"])
        self.assertIn("-amount = 10", packet["diff"])
        self.assertIn("+amount = 11", packet["diff"])
        self.assertEqual(audit.validate_packet(self.repo, packet, environ={}), packet)

    def test_unlisted_changed_or_untracked_files_block(self):
        for paths in ([audit.CONTRACT_PATH], self.paths + ["missing.py"]):
            with self.assertRaises(audit.AuditBlocked):
                audit.build_packet(self.repo, self.base, self.head, paths, environ={})

    def test_contract_required_and_must_survive(self):
        with self.assertRaises(audit.AuditBlocked):
            audit.build_packet(self.repo, self.base, self.head, ["src/payments.py"])
        (self.repo / audit.CONTRACT_PATH).unlink()
        head = self.commit()
        with self.assertRaises(audit.AuditBlocked):
            audit.build_packet(self.repo, self.base, head, self.paths)

    def test_rejects_binary_symlink_and_oversize_without_truncation(self):
        for name, prepare in (
            ("src/binary.py", lambda p: p.write_bytes(b"\x00\xff")),
            ("src/link.py", lambda p: p.symlink_to("payments.py")),
            ("src/large.py", lambda p: p.write_text("x" * (audit.MAX_FILE_BYTES + 1))),
        ):
            prepare(self.repo / name)
            head = self.commit()
            with self.assertRaises(audit.AuditBlocked):
                audit.build_packet(self.repo, self.head, head, [audit.CONTRACT_PATH, name], environ={})
            self.head = head

    def test_path_restrictions(self):
        for path in ("../x.py", "/x.py", "a/../x.py", ".env", ".env.example", "private/a.py",
                     "prod/a.json", "db.sqlite", "x/*.py", "x\\a.py", "x//a.py", "./a.py"):
            with self.subTest(path=path), self.assertRaises(audit.AuditBlocked):
                audit.ensure_safe_path(path)

    def test_deleted_secret_lines_also_block(self):
        secret = "sk-" + "a" * 30
        self.write("src/payments.py", "value = '" + secret + "'\n")
        base = self.commit()
        (self.repo / "src/payments.py").unlink()
        head = self.commit()
        with self.assertRaises(audit.AuditBlocked):
            audit.build_packet(self.repo, base, head, self.paths, environ={})

    def test_known_credential_and_contact_data_block(self):
        for text in ("value: " + self.env["ANTHROPIC_API_KEY"], "person@private.test"):
            with self.assertRaises(audit.AuditBlocked):
                audit.ensure_safe_text(text, environ=self.env)

    def test_packet_tamper_blocks_before_network(self):
        packet = self.packet()
        packet["files"][1]["head"]["text"] = "other = 12\n"
        with patch.object(audit, "request_json") as request:
            with self.assertRaises(audit.AuditBlocked):
                audit.run_audit(self.repo, packet, environ=self.env)
            request.assert_not_called()

    def test_ambient_git_dir_cannot_redirect_evidence(self):
        packet = self.packet()
        with patch.dict(os.environ, {"GIT_DIR": "/not/a/repo", "GIT_WORK_TREE": "/"}):
            self.assertEqual(audit.validate_packet(self.repo, packet, environ={}), packet)

    def test_only_official_public_source_urls(self):
        self.assertEqual(self.packet(official_sources=["https://docs.eaeunion.org/documents"]) ["official_sources"],
                         ["https://docs.eaeunion.org/documents"])
        for url in ("https://attacker.test", "http://docs.eaeunion.org", "https://docs.eaeunion.org?token=x",
                    "https://docs.eaeunion.org.attacker.test", "https://user:pass@docs.eaeunion.org"):
            with self.assertRaises(audit.AuditBlocked):
                self.packet(official_sources=[url])

    @patch.object(audit, "request_json")
    def test_absent_credentials_explicitly_unavailable(self, request):
        result = audit.run_audit(self.repo, self.packet(), environ={})
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertFalse(result["live_verified"])
        request.assert_not_called()

    @patch.object(audit, "request_json")
    def test_mock_a6_request_is_no_tools_strict_json_and_advisory(self, request):
        packet = self.packet()
        request.return_value = {"id": "msg_mock", "stop_reason": "end_turn",
                                "content": [{"type": "text", "text": json.dumps(self.findings(packet))}]}
        result = audit.run_audit(self.repo, packet, environ=self.env)
        self.assertEqual(result["status"], "NEEDS_A0_VALIDATION")
        self.assertEqual(result["a0_validation"], "PENDING")
        self.assertEqual(result["message_id"], "msg_mock")
        self.assertTrue(result["advisory_only"])
        url = request.call_args.args[0]
        payload = request.call_args.kwargs["payload"]
        self.assertEqual(url, "https://api.anthropic.com/v1/messages")
        self.assertNotIn("tools", payload)
        self.assertNotIn("mcp_servers", payload)
        self.assertEqual(payload["output_config"]["format"]["type"], "json_schema")
        self.assertNotIn(self.env["ANTHROPIC_API_KEY"], json.dumps(payload))

    def test_invalid_findings_binding_scope_lines_and_extra_keys(self):
        packet = self.packet()
        for mutate in (
            lambda r: r.update(head_sha="wrong"),
            lambda r: r["findings"][0].update(path="outside.py"),
            lambda r: r["findings"][0].update(line=2),
            lambda r: r["findings"][0].update(line=True),
            lambda r: r["findings"][0].update(command="execute this"),
            lambda r: r["findings"][0].update(official_source_urls=["https://attacker.test"]),
        ):
            findings = copy.deepcopy(self.findings(packet))
            mutate(findings)
            with self.assertRaises(audit.AuditBlocked):
                audit.validate_findings(findings, packet, environ={})

    @patch.object(audit, "request_json")
    def test_refusal_tool_output_truncation_and_errors_never_pass(self, request):
        packet = self.packet()
        responses = [
            {"id": "msg_mock", "stop_reason": "max_tokens", "content": []},
            {"id": "msg_mock", "stop_reason": "end_turn", "content": [{"type": "tool_use"}]},
            {"id": "msg_mock", "stop_reason": "end_turn", "content": [{"type": "text", "text": "not json"}]},
        ]
        for response in responses:
            request.return_value = response
            self.assertEqual(audit.run_audit(self.repo, packet, environ=self.env)["status"], "UNAVAILABLE")
        request.side_effect = audit.RuntimeBlocked(self.env["ANTHROPIC_API_KEY"])
        result = audit.run_audit(self.repo, packet, environ=self.env)
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertNotIn(self.env["ANTHROPIC_API_KEY"], json.dumps(result))


if __name__ == "__main__":
    unittest.main()
