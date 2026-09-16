"""Offline security tests for the trusted A6 live bridge; no provider calls."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.tariff_agents import audit, audit_bridge
from tools.tariff_agents.runtime import RuntimeBlocked


class AuditBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.email", "bridge@example.com")
        self.git("config", "user.name", "Bridge Test")
        self.write(audit.CONTRACT_PATH, "A0 independently validates A6 findings.\n")
        self.write("src/rates.py", "RATE = 1\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.base = self.sha()
        self.write("src/rates.py", "RATE = 2\n")
        self.git("commit", "-qam", "head")
        self.head = self.sha()
        self.workflow_sha = self.head
        self.event = self.repo / "event.json"
        self.payload = {
            "request_id": "A6-123", "base_sha": self.base, "head_sha": self.head,
            "contract_sha": self.head, "paths_json": json.dumps(["src/rates.py"]),
            "official_sources_json": "[]",
        }
        self.event.write_text(json.dumps({"action": "tariff-a6-live",
                                         "client_payload": self.payload,
                                         "repository": {"default_branch": "main"}}))
        self.env = {
            "GITHUB_EVENT_NAME": "repository_dispatch",
            "GITHUB_EVENT_PATH": str(self.event),
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_SHA": self.workflow_sha,
            "GITHUB_RUN_ID": "123456",
            "GITHUB_REPOSITORY": "owner/repository",
            "ANTHROPIC_API_KEY": "safe-test-key-value",
            "TARIFF_ANTHROPIC_MODEL": "claude-test",
        }
        # The contract comes from the explicit contract commit and is therefore
        # deliberately not duplicated in the candidate path list.
        self.paths = self.payload["paths_json"]

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.repo, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def sha(self):
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo,
                                       text=True).strip()

    def write(self, path, value):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value, encoding="utf-8")

    def prepare(self):
        output = self.repo / "packet.json"
        audit_bridge.prepare(self.repo, request_id="A6-123", base=self.base,
                             head=self.head, contract=self.head,
                             paths_json=self.paths, sources_json="[]", output=output,
                             environ=self.env, fetch=False)
        return output

    def valid_result(self, packet):
        return {
            "auditor": "A6", "base_sha": self.base, "head_sha": self.head,
            "packet_sha256": packet["packet_sha256"], "advisory_only": True,
            "a0_validation": "PENDING", "status": "NEEDS_A0_VALIDATION",
            "live_verified": True, "message_id": "msg_test_123",
            "model": "claude-test", "findings": [], "limitations": [],
        }

    def test_prepare_and_live_receipt_are_exactly_bound(self):
        packet_path = self.prepare()
        packet = json.loads(packet_path.read_text())
        receipt_path = self.repo / "receipt.json"
        with patch.object(audit, "run_audit", return_value=self.valid_result(packet)):
            receipt, code = audit_bridge.run(
                self.repo, request_id="A6-123", base=self.base, head=self.head,
                contract=self.head, packet_path=packet_path, receipt_path=receipt_path,
                environ=self.env)
        self.assertEqual(code, 0)
        self.assertEqual(receipt["bridge_status"], "LIVE_VERIFIED")
        self.assertEqual(receipt["audit_status"], "NEEDS_A0_VALIDATION")
        self.assertEqual(receipt["a0_validation"], "PENDING")
        self.assertEqual(receipt["packet_sha256"], packet["packet_sha256"])
        saved = json.loads(receipt_path.read_text())
        digest = saved.pop("receipt_sha256")
        self.assertEqual(digest, audit_bridge._sha256(audit_bridge._canonical(saved)))

    def test_wrong_ref_and_non_manual_event_block_before_audit(self):
        for key, value in (("GITHUB_REF", "refs/heads/agent/evil"),
                           ("GITHUB_EVENT_NAME", "workflow_dispatch"),
                           ("GITHUB_SHA", self.base)):
            env = dict(self.env)
            env[key] = value
            with self.subTest(key=key), self.assertRaises(audit_bridge.BridgeBlocked):
                audit_bridge.validate_trusted_context(self.repo, environ=env)

    def test_malicious_inputs_and_mismatched_bindings_block(self):
        bad_cases = (
            {"request_id": "ok; echo pwned"},
            {"base": "refs/heads/main"},
            {"paths_json": '{"src/rates.py": true}'},
            {"paths_json": '["src/rates.py", "../secret.txt"]'},
            {"sources_json": '["https://evil.example/file"]'},
        )
        defaults = {"request_id": "A6-123", "base": self.base, "head": self.head,
                    "contract": self.head, "paths_json": self.paths,
                    "sources_json": "[]", "output": self.repo / "never.json",
                    "environ": self.env, "fetch": False}
        for changes in bad_cases:
            values = {**defaults, **changes}
            with self.subTest(changes=changes), self.assertRaises(RuntimeBlocked):
                audit_bridge.prepare(self.repo, **values)

        packet_path = self.prepare()
        receipt_path = self.repo / "mismatch.json"
        with self.assertRaisesRegex(audit_bridge.BridgeBlocked, "differ"):
            audit_bridge.run(
                self.repo, request_id="A6-123", base=self.head, head=self.head,
                contract=self.head, packet_path=packet_path, receipt_path=receipt_path,
                environ=self.env)

    def test_wrong_dispatch_action_payload_or_command_binding_blocks(self):
        variants = []
        wrong_action = {"action": "other", "client_payload": self.payload,
                        "repository": {"default_branch": "main"}}
        variants.append(wrong_action)
        extra = dict(self.payload, extra="not-allowed")
        variants.append({"action": "tariff-a6-live", "client_payload": extra,
                         "repository": {"default_branch": "main"}})
        for index, event in enumerate(variants):
            path = self.repo / f"bad-event-{index}.json"
            path.write_text(json.dumps(event))
            env = dict(self.env, GITHUB_EVENT_PATH=str(path))
            with self.subTest(index=index), self.assertRaises(audit_bridge.BridgeBlocked):
                audit_bridge.validate_trusted_context(self.repo, environ=env)

        with self.assertRaisesRegex(audit_bridge.BridgeBlocked, "differ"):
            audit_bridge.prepare(
                self.repo, request_id="A6-124", base=self.base, head=self.head,
                contract=self.head, paths_json=self.paths, sources_json="[]",
                output=self.repo / "not-written.json", environ=self.env, fetch=False)

        packet_path = self.prepare()
        changed_payload = dict(self.payload, paths_json='["src/rates.py","README.md"]')
        changed_event = {"action": "tariff-a6-live", "client_payload": changed_payload,
                         "repository": {"default_branch": "main"}}
        changed_path = self.repo / "changed-event.json"
        changed_path.write_text(json.dumps(changed_event))
        changed_env = dict(self.env, GITHUB_EVENT_PATH=str(changed_path))
        receipt_path = self.repo / "never-receipt.json"
        receipt, code = audit_bridge.run(
            self.repo, request_id="A6-123", base=self.base, head=self.head,
            contract=self.head, packet_path=packet_path, receipt_path=receipt_path,
            environ=changed_env)
        self.assertEqual((receipt["bridge_status"], code), ("BLOCKED", 2))

    def test_missing_config_is_unavailable_and_no_secret_is_persisted(self):
        packet_path = self.prepare()
        packet = json.loads(packet_path.read_text())
        unavailable = {**self.valid_result(packet), "status": "UNAVAILABLE",
                       "live_verified": False, "missing": ["ANTHROPIC_API_KEY"]}
        receipt_path = self.repo / "unavailable.json"
        with patch.object(audit, "run_audit", return_value=unavailable):
            receipt, code = audit_bridge.run(
                self.repo, request_id="A6-123", base=self.base, head=self.head,
                contract=self.head, packet_path=packet_path, receipt_path=receipt_path,
                environ=self.env)
        saved = receipt_path.read_text()
        self.assertEqual((receipt["bridge_status"], code), ("UNAVAILABLE", 2))
        self.assertNotIn(self.env["ANTHROPIC_API_KEY"], saved)
        self.assertNotIn("missing", saved)

    def test_unavailable_receipt_keeps_only_bounded_safe_provider_failure_code(self):
        packet_path = self.prepare()
        packet = json.loads(packet_path.read_text())
        unavailable = {**self.valid_result(packet), "status": "UNAVAILABLE",
                       "live_verified": False, "failure_code": "CONTENT_SHAPE"}
        receipt_path = self.repo / "safe-diagnostic.json"
        with patch.object(audit, "run_audit", return_value=unavailable):
            receipt, code = audit_bridge.run(
                self.repo, request_id="A6-123", base=self.base, head=self.head,
                contract=self.head, packet_path=packet_path, receipt_path=receipt_path,
                environ=self.env)
        self.assertEqual(code, 2)
        self.assertEqual(receipt["provider_failure_code"], "CONTENT_SHAPE")
        self.assertNotIn(self.env["ANTHROPIC_API_KEY"], receipt_path.read_text())

    def test_invalid_or_secret_shaped_adapter_result_fails_closed(self):
        packet_path = self.prepare()
        packet = json.loads(packet_path.read_text())
        for index, mutate in enumerate((
            lambda result: result.update(head_sha=self.base),
            lambda result: result.update(message_id=self.env["ANTHROPIC_API_KEY"]),
            lambda result: result.update(live_verified=False),
            lambda result: result.update(findings=[{"id": "invalid"}]),
        )):
            result = self.valid_result(packet)
            mutate(result)
            receipt_path = self.repo / f"invalid-{index}.json"
            with patch.object(audit, "run_audit", return_value=result):
                receipt, code = audit_bridge.run(
                    self.repo, request_id="A6-123", base=self.base, head=self.head,
                    contract=self.head, packet_path=packet_path,
                    receipt_path=receipt_path, environ=self.env)
            self.assertEqual(code, 2)
            self.assertEqual(receipt["bridge_status"], "BLOCKED")
            self.assertNotIn(self.env["ANTHROPIC_API_KEY"], receipt_path.read_text())

    def test_workflow_has_static_security_boundary(self):
        workflow = (Path(__file__).resolve().parents[2] /
                    ".github/workflows/tariff-a6-live.yml").read_text()
        self.assertIn("on:\n  repository_dispatch:\n    types: [tariff-a6-live]", workflow)
        self.assertNotIn("workflow_dispatch:", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("pull_request_target:", workflow)
        self.assertNotIn("\n  push:", workflow)
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn("github.event.repository.default_branch", workflow)
        self.assertIn("  context-gate:\n", workflow)
        self.assertIn("    needs: context-gate\n", workflow)
        self.assertIn("    environment: tariff-a6-trusted\n", workflow)
        self.assertNotIn("if: github.ref ==", workflow)
        self.assertIn('test "$A6_ACTUAL_REF" = "$A6_EXPECTED_REF"', workflow)
        self.assertIn('test "$A6_EVENT_ACTION" = tariff-a6-live', workflow)
        self.assertIn('test "$(git rev-parse HEAD)" = "$A6_WORKFLOW_SHA"', workflow)
        self.assertIn("ref: ${{ github.sha }}", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertEqual(workflow.count("secrets.ANTHROPIC_API_KEY"), 1)
        self.assertEqual(workflow.count("vars.TARIFF_ANTHROPIC_MODEL"), 1)
        documentation = (Path(__file__).resolve().parents[2] /
                         ".ai/orchestration/A6_LIVE_BRIDGE.md").read_text()
        self.assertIn(
            "former\n  repository-level copies have been removed", documentation)
        self.assertIn("This is an owner assertion", documentation)
        self.assertIn("Provider status remains\n  `BLOCKED`", documentation)
        self.assertIn("deployment-branch policy", documentation)
        self.assertNotIn("checkout candidate", workflow.lower())
        self.assertRegex(workflow, r"actions/checkout@[0-9a-f]{40}")
        self.assertRegex(workflow, r"actions/upload-artifact@[0-9a-f]{40}")


if __name__ == "__main__":
    unittest.main()
