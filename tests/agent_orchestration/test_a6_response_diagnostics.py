"""Regression coverage for response discriminators and scrubbed diagnostics.

Every response and credential in this suite is synthetic; the HTTP adapter is
patched for every run. Packet, Git, response and receipt validators remain real.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.tariff_agents import audit, audit_bridge, verify


class A6ResponseDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="a6-diagnostics-")
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_NO_REPLACE_OBJECTS="1", GIT_TERMINAL_PROMPT="0")

        def git(*args):
            return subprocess.run(
                ["git", "-c", "core.hooksPath=" + os.devnull, *args],
                cwd=self.repo, env=env, check=True, capture_output=True,
                text=True).stdout.strip()

        git("init", "-q")
        git("config", "user.name", "Offline fixture")
        git("config", "user.email", "fixture@example.com")
        (self.repo / ".ai/orchestration").mkdir(parents=True)
        (self.repo / audit.CONTRACT_PATH).write_text("Advisory evidence only.\n")
        (self.repo / "sample.py").write_text("VALUE = 1\n")
        git("add", ".")
        git("commit", "-qm", "Synthetic fixture")
        self.sha = git("rev-parse", "HEAD")
        payload = {
            "request_id": "diagnostic-fixture", "base_sha": self.sha,
            "head_sha": self.sha, "contract_sha": self.sha,
            "paths_json": '["sample.py"]', "official_sources_json": "[]",
        }
        event = self.repo / "event.json"
        event.write_text(json.dumps({"repository": {"default_branch": "main"},
                                     "action": "tariff-a6-live",
                                     "client_payload": payload}))
        self.env = {
            "GITHUB_EVENT_NAME": "repository_dispatch", "GITHUB_EVENT_PATH": str(event),
            "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": self.sha,
            "GITHUB_RUN_ID": "123", "GITHUB_REPOSITORY": "fixture/repo",
            "TARIFF_ANTHROPIC_MODEL": "claude-fixture",
        }
        self.env["ANTHROPIC_" + "API_KEY"] = "offline-fixture-not-a-real-key"
        self.packet_path = self.repo / "packet.json"
        audit_bridge.prepare(
            self.repo, request_id="diagnostic-fixture", base=self.sha, head=self.sha,
            contract=self.sha, paths_json=payload["paths_json"], sources_json="[]",
            output=self.packet_path, environ=self.env, fetch=False)
        self.packet = json.loads(self.packet_path.read_text())
        self.output = {"head_sha": self.sha, "packet_sha256": self.packet["packet_sha256"],
                       "findings": [], "limitations": []}
        self.text = {"type": "text", "text": json.dumps(self.output)}
        self.valid = {"id": "msg_fixture", "stop_reason": "end_turn",
                      "content": [self.text]}

    def malformed_responses(self):
        for value in ([], {}):
            yield {**self.valid, "stop_reason": value}, "STOP_OTHER"
            yield {**self.valid, "content": [{"type": value}, self.text]}, "CONTENT_SHAPE"

    def assert_single_request(self, request):
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.kwargs["timeout"], 300)
        self.assertNotIn("tools", request.call_args.kwargs["payload"])

    def test_non_string_discriminators_are_bounded_unavailable(self):
        for response, expected in self.malformed_responses():
            with self.subTest(response=response), patch.object(
                    audit, "request_json", return_value=copy.deepcopy(response)) as request:
                result = audit.run_audit(self.repo, self.packet, environ=self.env)
                self.assertEqual(result["status"], "UNAVAILABLE")
                self.assertIs(result["live_verified"], False)
                self.assertEqual(result["failure_code"], expected)
                self.assert_single_request(request)

    def test_bridge_preserves_validated_binding_on_malformed_provider_response(self):
        for index, (response, expected) in enumerate(self.malformed_responses()):
            with self.subTest(index=index), patch.object(
                    audit, "request_json", return_value=copy.deepcopy(response)) as request:
                receipt, code = audit_bridge.run(
                    self.repo, request_id="diagnostic-fixture", base=self.sha,
                    head=self.sha, contract=self.sha, packet_path=self.packet_path,
                    receipt_path=self.repo / f"receipt-{index}.json", environ=self.env)
                self.assertEqual(code, 2)
                self.assertEqual(receipt["bridge_status"], "UNAVAILABLE")
                self.assertEqual(receipt["provider_failure_code"], expected)
                self.assertEqual(receipt["packet_sha256"], self.packet["packet_sha256"])
                self.assertEqual(receipt["base_sha"], self.sha)
                self.assertEqual(receipt["head_sha"], self.sha)
                self.assertEqual(receipt["contract_sha"], self.sha)
                self.assertEqual(receipt["trusted_workflow_sha"], self.sha)
                self.assertEqual(receipt["request_id"], "diagnostic-fixture")
                self.assertEqual(receipt["workflow_run_id"], "123")
                unsigned = dict(receipt)
                saved_hash = unsigned.pop("receipt_sha256")
                self.assertEqual(saved_hash, hashlib.sha256(
                    audit_bridge._canonical(unsigned)).hexdigest())
                self.assert_single_request(request)

    def receipt_for_code(self, code):
        context = audit_bridge.validate_trusted_context(self.repo, environ=self.env)
        return audit_bridge._receipt(
            context, "diagnostic-fixture", self.packet,
            {"status": "UNAVAILABLE", "failure_code": code}, "UNAVAILABLE")

    def test_known_failure_codes_round_trip(self):
        codes = sorted(audit.A6_FAILURE_CODES) + [
            "PROVIDER_HTTP_400", "PROVIDER_HTTP_401", "PROVIDER_HTTP_429", "PROVIDER_HTTP_529"]
        for code in codes:
            with self.subTest(code=code):
                self.assertIs(audit.is_safe_failure_code(code), True)
                self.assertEqual(self.receipt_for_code(code)["provider_failure_code"], code)

    def test_unknown_diagnostics_cannot_be_persisted(self):
        for code in (None, True, 529, [], {}, "", "UNTRUSTED_UPPERCASE_PAYLOAD",
                     "PROVIDER_HTTP_000", "PROVIDER_HTTP_600", "PROVIDER_HTTP_1000"):
            with self.subTest(code=code):
                self.assertIs(audit.is_safe_failure_code(code), False)
                self.assertNotIn("provider_failure_code", self.receipt_for_code(code))
                result = audit._unavailable({}, code)
                self.assertEqual(result["failure_code"], "PROVIDER_RUNTIME_BLOCKED")
                self.assertIs(result["live_verified"], False)

    def test_thinking_contents_are_not_persisted(self):
        marker = "OPAQUE_THINKING_NOT_FOR_RECEIPT"
        response = {**self.valid, "content": [
            {"type": "thinking", "thinking": marker, "signature": "fixture"},
            {"type": "redacted_thinking", "data": marker}, self.text]}
        with patch.object(audit, "request_json", return_value=response) as request:
            target = self.repo / "thinking-receipt.json"
            receipt, code = audit_bridge.run(
                self.repo, request_id="diagnostic-fixture", base=self.sha,
                head=self.sha, contract=self.sha, packet_path=self.packet_path,
                receipt_path=target, environ=self.env)
            self.assertEqual(code, 0)
            self.assertIs(receipt["live_verified"], True)  # Synthetic response only.
            self.assertNotIn(marker, target.read_text())
            self.assertNotIn(self.env["ANTHROPIC_" + "API_KEY"], target.read_text())
            self.assert_single_request(request)

    def test_runtime_exception_text_is_not_persisted(self):
        marker = "UNTRUSTED_PROVIDER_EXCEPTION_PAYLOAD"
        with patch.object(audit, "request_json", side_effect=audit.RuntimeBlocked(marker)) as request:
            target = self.repo / "exception-receipt.json"
            receipt, code = audit_bridge.run(
                self.repo, request_id="diagnostic-fixture", base=self.sha,
                head=self.sha, contract=self.sha, packet_path=self.packet_path,
                receipt_path=target, environ=self.env)
            self.assertEqual(code, 2)
            self.assertEqual(receipt["provider_failure_code"], "PROVIDER_RUNTIME_BLOCKED")
            self.assertNotIn(marker, target.read_text())
            self.assert_single_request(request)

    def test_diagnostic_suite_is_mandatory(self):
        self.assertIn("test_a6_response_diagnostics", verify.REQUIRED)


if __name__ == "__main__":
    unittest.main()
