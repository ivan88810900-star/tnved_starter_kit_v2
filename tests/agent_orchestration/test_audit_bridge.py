"""Offline security tests for the trusted A6 live bridge; no provider calls."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from io import BytesIO
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

    def issue_comment_env(self, *, body=audit_bridge.COMMENT_COMMAND,
                          actor="owner", association="OWNER", consumed=False,
                          expires_at="2099-01-01T00:00:00.000Z",
                          prepared_at="2026-09-24T08:00:00Z"):
        state = self.repo / ".a6-state"
        state.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=state, check=True)
        subprocess.run(["git", "config", "user.email", "state@example.com"],
                       cwd=state, check=True)
        subprocess.run(["git", "config", "user.name", "State Test"],
                       cwd=state, check=True)
        packet = audit.build_packet(
            self.repo, self.base, self.head, ["src/rates.py"],
            contract_ref=self.head, official_sources=[], environ={})
        status = {
            "schema_version": 1,
            "live_verified": False,
            "pending_live_smoke": {
                "request_id": "A6-pending-123",
                "base_sha": self.base,
                "head_sha": self.head,
                "contract_sha": self.head,
                "paths_json": '["src/rates.py"]',
                "official_sources_json": "[]",
                "packet_sha256": packet["packet_sha256"],
                "packet_validation": "PASSED_OFFLINE_WITHOUT_CREDENTIALS",
                "prepared_at": prepared_at,
                "dispatched": False,
                "consumed": consumed,
            },
        }
        lease = {
            "schema_version": 1,
            "state": "active",
            "holder": "/root/a0_test",
            "token": "1" * 32,
            "generation": 7,
            "updated_at": "2026-09-23T00:00:00.000Z",
            "expires_at": expires_at,
        }
        status_path = state / ".ai/orchestration/A6_LIVE_STATUS.json"
        lease_path = state / ".ai/COORDINATOR_LEASE.json"
        status_path.parent.mkdir(parents=True)
        status_path.write_text(json.dumps(status), encoding="utf-8")
        lease_path.write_text(json.dumps(lease), encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=state, check=True)
        subprocess.run(["git", "commit", "-qm", "state"], cwd=state, check=True)
        event = {
            "action": "created",
            "repository": {"default_branch": "main", "owner": {"login": "owner"}},
            "sender": {"login": actor},
            "issue": {"number": 214},
            "comment": {"id": 987654, "body": body,
                        "author_association": association,
                        "user": {"login": actor}},
        }
        event_path = self.repo / "issue-comment.json"
        event_path.write_text(json.dumps(event), encoding="utf-8")
        return {
            **self.env,
            "GITHUB_EVENT_NAME": "issue_comment",
            "GITHUB_EVENT_PATH": str(event_path),
            "A6_STATE_ROOT": str(state),
            "A6_STATUS_PATH": str(status_path),
            "A6_LEASE_PATH": str(lease_path),
        }, packet

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

    def test_owner_comment_resolves_only_authoritative_pending_request(self):
        env, packet = self.issue_comment_env()
        request_path = self.repo / "resolved-request.json"
        request = audit_bridge.resolve(self.repo, output=request_path, environ=env)
        self.assertEqual(request["request_id"], "A6-pending-123")
        self.assertEqual(request["packet_sha256"], packet["packet_sha256"])
        self.assertEqual(request["lease_holder"], "/root/a0_test")
        self.assertEqual(request["prepared_at"], "2026-09-24T08:00:00Z")
        self.assertRegex(request["delivery_generation"], r"^[0-9a-f]{64}$")
        self.assertNotIn("token", request)
        saved = request_path.read_text()
        self.assertNotIn("1" * 32, saved)

        packet_path = self.repo / "comment-packet.json"
        audit_bridge.prepare(
            self.repo, request_id=request["request_id"], base=request["base_sha"],
            head=request["head_sha"], contract=request["contract_sha"],
            paths_json=request["paths_json"],
            sources_json=request["official_sources_json"], output=packet_path,
            environ=env, fetch=False)
        receipt_path = self.repo / "comment-receipt.json"
        with patch.object(audit, "run_audit", return_value=self.valid_result(packet)):
            receipt, code = audit_bridge.run(
                self.repo, request_id=request["request_id"], base=request["base_sha"],
                head=request["head_sha"], contract=request["contract_sha"],
                packet_path=packet_path, receipt_path=receipt_path, environ=env)
        self.assertEqual(code, 0)
        self.assertEqual(receipt["trigger"], "issue_comment")
        self.assertEqual(receipt["comment_id"], "987654")
        self.assertEqual(receipt["state_sha"], request["state_sha"])
        self.assertEqual(receipt["lease_generation"], 7)

    def test_delivery_dedupe_is_scoped_to_pending_request_generation(self):
        env, _ = self.issue_comment_env()
        request_path = self.repo / "resolved-dedupe-request.json"
        request = audit_bridge.resolve(self.repo, output=request_path, environ=env)
        ledger_env = {
            "GH_TOKEN": "synthetic-token-not-a-secret",
            "A6_API_URL": "https://api.github.test",
            "A6_REPOSITORY": "owner/repository",
            "A6_REPOSITORY_OWNER": "owner",
            "A6_RUN_ID": "300",
            "GITHUB_RUN_ATTEMPT": "1",
        }

        class Response(BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

        def opener_for(created_at):
            def open_url(_request, timeout):
                self.assertEqual(timeout, 30)
                payload = {"workflow_runs": [{
                    "id": 200,
                    "display_title": "Tariff A6 command /tariff-a6-live run-pending",
                    "actor": {"login": "owner"},
                    "created_at": created_at,
                }]}
                return Response(json.dumps(payload).encode())
            return open_url

        summary = audit_bridge.dedupe_delivery(
            request_path, environ=ledger_env,
            opener=opener_for("2026-09-24T07:59:59Z"))
        self.assertEqual(summary["delivery_generation"],
                         request["delivery_generation"])
        with self.assertRaisesRegex(audit_bridge.BridgeBlocked,
                                    "already delivered"):
            audit_bridge.dedupe_delivery(
                request_path, environ=ledger_env,
                opener=opener_for("2026-09-24T08:00:00Z"))

    def test_delivery_dedupe_rejects_reruns_and_tampered_generation(self):
        env, _ = self.issue_comment_env()
        request_path = self.repo / "resolved-rerun-request.json"
        audit_bridge.resolve(self.repo, output=request_path, environ=env)
        ledger_env = {
            "GH_TOKEN": "synthetic-token-not-a-secret",
            "A6_API_URL": "https://api.github.test",
            "A6_REPOSITORY": "owner/repository",
            "A6_REPOSITORY_OWNER": "owner",
            "A6_RUN_ID": "300",
            "GITHUB_RUN_ATTEMPT": "2",
        }
        with self.assertRaisesRegex(audit_bridge.BridgeBlocked, "reruns"):
            audit_bridge.dedupe_delivery(request_path, environ=ledger_env)
        request = json.loads(request_path.read_text())
        request["delivery_generation"] = "0" * 64
        request_path.unlink()
        request_path.write_text(json.dumps(request))
        ledger_env["GITHUB_RUN_ATTEMPT"] = "1"
        with self.assertRaisesRegex(audit_bridge.BridgeBlocked, "generation"):
            audit_bridge.dedupe_delivery(request_path, environ=ledger_env)

    def test_comment_bridge_rejects_untrusted_or_consumed_commands(self):
        cases = (
            {"body": "/tariff-a6-live run-pending now"},
            {"actor": "attacker", "association": "CONTRIBUTOR"},
            {"consumed": True},
            {"expires_at": "2020-01-01T00:00:00.000Z"},
        )
        for index, changes in enumerate(cases):
            with self.subTest(changes=changes):
                if index:
                    state = self.repo / ".a6-state"
                    if state.exists():
                        import shutil
                        shutil.rmtree(state)
                env, _ = self.issue_comment_env(**changes)
                with self.assertRaises(audit_bridge.BridgeBlocked):
                    audit_bridge.validate_trusted_context(self.repo, environ=env)

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
        self.assertIn("on:\n  issue_comment:\n    types: [created]", workflow)
        self.assertNotIn("workflow_dispatch:", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("pull_request_target:", workflow)
        self.assertNotIn("\n  push:", workflow)
        self.assertIn("permissions:\n  actions: read\n  contents: read", workflow)
        self.assertIn("github.event.repository.default_branch", workflow)
        self.assertIn("  context-gate:\n", workflow)
        self.assertIn("    needs: context-gate\n", workflow)
        self.assertIn("    environment: tariff-a6-trusted\n", workflow)
        self.assertIn("group: tariff-a6-live-pending-request", workflow)
        self.assertIn("dedupe-delivery", workflow)
        self.assertIn("delivery-generation", workflow)
        self.assertIn('test "$A6_RUN_ATTEMPT" = 1', workflow)
        self.assertIn("test \"$A6_ISSUE_NUMBER\" = 214", workflow)
        self.assertIn("test \"$A6_COMMENT_BODY\" = '/tariff-a6-live run-pending'", workflow)
        self.assertIn("test \"$A6_AUTHOR_ASSOCIATION\" = OWNER", workflow)
        self.assertIn("test \"$A6_ACTOR\" = \"$A6_REPOSITORY_OWNER\"", workflow)
        self.assertIn('test "$A6_ACTUAL_REF" = "$A6_EXPECTED_REF"', workflow)
        self.assertIn('test "$(git rev-parse HEAD)" = "$A6_WORKFLOW_SHA"', workflow)
        self.assertIn("ref: ${{ github.sha }}", workflow)
        self.assertIn("ref: agent/orchestration-state", workflow)
        self.assertIn("resolve-pending", workflow)
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
        self.assertIn("A failed first delivery is not retried", documentation)
        self.assertIn("accepts no\nrequest data from the comment", documentation)
        self.assertNotIn("checkout candidate", workflow.lower())
        self.assertRegex(workflow, r"actions/checkout@[0-9a-f]{40}")
        self.assertRegex(workflow, r"actions/upload-artifact@[0-9a-f]{40}")


if __name__ == "__main__":
    unittest.main()
