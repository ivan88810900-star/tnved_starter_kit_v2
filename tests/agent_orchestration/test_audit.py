"""MOCK external audit tests: real local Git, no live Anthropic API calls."""

import base64
import copy
import io
import json
import os
import subprocess
import tempfile
import unittest
import urllib.parse
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tools.tariff_agents import audit


def authenticated_connection_url(scheme, password, *, user="fixture", suffix="/tariff"):
    return scheme + "://" + user + ":" + password + "@" + "localhost.test" + suffix


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
        provider_key = "ANTHROPIC_" + "API_KEY"
        provider_credential = "fixture-anthropic-" + "credential"
        self.env = {provider_key: provider_credential,
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

    def cross_branch_candidate(self):
        """Independent product history deliberately omits the orchestration contract."""
        contract_ref = self.base
        self.git("switch", "-q", "--orphan", "product-fixture")
        self.write("src/payments.py", "amount = 11\n")
        self.write("tests/check.py", "assert 1 + 1 == 2\n")
        product_base = self.commit()
        self.write("src/payments.py", "amount = 12\n")
        product_head = self.commit()
        paths = ["src/payments.py", "tests/check.py"]
        return contract_ref, product_base, product_head, paths

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

    def test_explicit_contract_ref_supports_product_only_commits(self):
        contract_ref, base, head, paths = self.cross_branch_candidate()
        packet = audit.build_packet(self.repo, base, head, paths,
                                    contract_ref=contract_ref, environ={})
        self.assertEqual(packet["base_sha"], base)
        self.assertEqual(packet["head_sha"], head)
        self.assertEqual(packet["changed_paths"], ["src/payments.py"])
        self.assertNotIn(audit.CONTRACT_PATH, packet["paths"])
        self.assertEqual(packet["contract"]["mode"], "explicit_ref")
        self.assertEqual(packet["contract"]["requested_ref"], contract_ref)
        self.assertEqual(packet["contract"]["resolved_commit"], contract_ref)
        self.assertRegex(packet["contract"]["git_oid"], r"^[0-9a-f]{40,64}$")
        self.assertEqual(packet["contract"]["sha256"],
                         audit._sha(packet["contract"]["text"].encode()))
        self.assertEqual(audit.validate_packet(self.repo, packet, environ={}), packet)
        findings = self.findings(packet)
        findings["findings"][0].update(path=audit.CONTRACT_PATH, line=1,
                                        evidence="Contract boundary requires A0 verification")
        self.assertEqual(audit.validate_findings(findings, packet, environ={}), findings)
        findings["findings"][0]["line"] = 2
        with self.assertRaises(audit.AuditBlocked):
            audit.validate_findings(findings, packet, environ={})

    def test_cli_build_accepts_explicit_contract_ref(self):
        contract_ref, base, head, paths = self.cross_branch_candidate()
        output = self.repo / "audit-packet.json"
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            rc = audit.main(["--repo", str(self.repo), "build", "--base", base,
                             "--head", head, "--path", paths[0], "--path", paths[1],
                             "--contract-ref", contract_ref, "--output", str(output)])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "PACKET_BUILT")
        packet = json.loads(output.read_text())
        self.assertEqual(packet["contract"]["resolved_commit"], contract_ref)
        self.assertEqual(audit.validate_packet(self.repo, packet, environ={}), packet)

    def test_explicit_contract_ref_absent_or_missing_contract_blocks(self):
        contract_ref, base, head, paths = self.cross_branch_candidate()
        for ref in ("refs/heads/absent-contract", head):
            with self.subTest(ref=ref), self.assertRaises(audit.AuditBlocked):
                audit.build_packet(self.repo, base, head, paths,
                                   contract_ref=ref, environ={})

    def test_secret_shaped_and_known_credential_contract_refs_block(self):
        secret_ref = "sk-ant-" + "a" * 24
        paths = ["src/payments.py", "tests/check.py"]
        for ref, env in ((secret_ref, {}),
                         (self.env["ANTHROPIC_API_KEY"], self.env)):
            with self.subTest(ref_kind="static" if not env else "environment"), \
                    patch.object(audit, "_commit", wraps=audit._commit) as commit:
                with self.assertRaises(audit.AuditBlocked):
                    audit.build_packet(self.repo, self.base, self.head, paths,
                                       contract_ref=ref, environ=env)
                resolved_refs = [item.args[1] for item in commit.call_args_list]
                self.assertNotIn(ref, resolved_refs, "contract ref must be scanned before resolution")

    def test_known_credential_ref_validation_blocks_before_network(self):
        credential_ref = self.env["ANTHROPIC_API_KEY"]
        self.git("branch", credential_ref, self.base)
        _, base, head, paths = self.cross_branch_candidate()
        packet = audit.build_packet(self.repo, base, head, paths,
                                    contract_ref=credential_ref, environ={})
        with patch.object(audit, "request_json") as request:
            with self.assertRaises(audit.AuditBlocked):
                audit.run_audit(self.repo, packet, environ=self.env)
            request.assert_not_called()

    def test_explicit_contract_packet_tamper_and_stale_ref_block(self):
        self.git("branch", "contract-source", self.base)
        _, base, head, paths = self.cross_branch_candidate()
        packet = audit.build_packet(self.repo, base, head, paths,
                                    contract_ref="contract-source", environ={})
        for field, value in (("text", "tampered\n"),
                             ("git_oid", "0" * 40),
                             ("sha256", "0" * 64),
                             ("resolved_commit", self.head),
                             ("requested_ref", self.base)):
            tampered = copy.deepcopy(packet)
            tampered["contract"][field] = value
            with self.subTest(field=field), self.assertRaises(audit.AuditBlocked):
                audit.validate_packet(self.repo, tampered, environ={})
        self.git("branch", "-f", "contract-source", self.head)
        with self.assertRaises(audit.AuditBlocked):
            audit.validate_packet(self.repo, packet, environ={})

    def test_explicit_contract_mode_keeps_diff_complete_and_scans_contract(self):
        contract_ref, base, head, paths = self.cross_branch_candidate()
        with self.assertRaises(audit.AuditBlocked):
            audit.build_packet(self.repo, base, head, ["tests/check.py"],
                               contract_ref=contract_ref, environ={})
        secret = "sk-ant-" + "a" * 24
        self.git("switch", "-q", "--detach", contract_ref)
        self.write(audit.CONTRACT_PATH, "credential = '" + secret + "'\n")
        secret_contract = self.commit()
        with self.assertRaises(audit.AuditBlocked):
            audit.build_packet(self.repo, base, head, paths,
                               contract_ref=secret_contract, environ={})

    def test_candidate_head_contract_deletion_line_remains_in_finding_scope(self):
        self.write(audit.CONTRACT_PATH, "retained line\ndeleted line\n")
        base = self.commit()
        self.write(audit.CONTRACT_PATH, "retained line\n")
        head = self.commit()
        packet = audit.build_packet(self.repo, base, head, [audit.CONTRACT_PATH], environ={})
        findings = self.findings(packet)
        findings["findings"][0].update(path=audit.CONTRACT_PATH, line=2,
                                        evidence="The second contract line was deleted")
        self.assertEqual(audit.validate_findings(findings, packet, environ={}), findings)
        findings["findings"][0]["line"] = 3
        with self.assertRaises(audit.AuditBlocked):
            audit.validate_findings(findings, packet, environ={})

    def test_persisted_v1_packet_rejects_fail_closed(self):
        packet = self.packet()
        packet["schema_version"] = 1
        packet.pop("contract")
        for entry in packet["files"]:
            for side in ("base", "head"):
                if entry[side]:
                    entry[side].pop("git_oid")
        with self.assertRaises(audit.AuditBlocked):
            audit.validate_packet(self.repo, packet, environ={})

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
        private_contact = "person@" + "private.test"
        for text in ("value: " + self.env["ANTHROPIC_API_KEY"], private_contact):
            with self.assertRaises(audit.AuditBlocked):
                audit.ensure_safe_text(text, environ=self.env)

    def test_ambient_password_and_connection_credentials_block(self):
        fixtures = (
            ("DB_PASS", "fixture-db-password-123", "fixture-db-password-123"),
            ("DB_PASSWD", "fixture-db-passwd-456", "fixture-db-passwd-456"),
            ("DATABASE_URL", authenticated_connection_url("postgresql", "postgres-pass-123"),
             "postgres-pass-123"),
            ("DATABASE_URL", authenticated_connection_url("mongodb", "mongo-pass-123"),
             "mongo-pass-123"),
            ("REDIS_URL", authenticated_connection_url(
                "redis", "redis-pass-123", user="default", suffix=":6379/0"),
             "redis-pass-123"),
            ("REDIS_URL", authenticated_connection_url(
                "rediss", "rediss-pass-123", user="default", suffix=":6380/0"),
             "rediss-pass-123"),
        )
        for key, value, password in fixtures:
            variants = {value, base64.b64encode(value.encode()).decode(),
                        value.encode().hex(), urllib.parse.quote(value, safe=""),
                        password, base64.b64encode(password.encode()).decode(),
                        password.encode().hex(), urllib.parse.quote(password, safe="")}
            for variant in variants:
                with self.subTest(key=key, variant_kind=len(variant)), \
                        self.assertRaises(audit.AuditBlocked):
                    audit.ensure_safe_text("candidate=" + variant, environ={key: value})

    def test_canonical_ambient_credential_aliases_block_encoded_variants(self):
        fixtures = (
            ("PG" + "PASSWORD", "fixture-pg-" + "credential"),
            ("MYSQL_" + "PWD", "fixture-mysql-" + "credential"),
            ("REDISCLI_" + "AUTH", "fixture-redis-" + "credential"),
        )
        for key, credential in fixtures:
            for variant in audit._credential_variants(credential, minimum_length=4):
                with self.subTest(key=key, variant_length=len(variant)), \
                        self.assertRaises(audit.AuditBlocked):
                    audit.ensure_safe_text("candidate=" + variant, environ={key: credential})

    def test_short_authenticated_url_passwords_block(self):
        for key, scheme, password in (
            ("DATABASE_URL", "postgresql", "p4ss"),
            ("DATABASE_URL", "mongodb", "m0ng0"),
            ("REDIS_URL", "redis", "r3ds"),
            ("REDIS_URL", "rediss", "tls42"),
        ):
            value = authenticated_connection_url(scheme, password)
            for variant in audit._credential_variants(password, minimum_length=4):
                with self.subTest(key=key, scheme=scheme, variant_length=len(variant)), \
                        self.assertRaises(audit.AuditBlocked):
                    audit.ensure_safe_text("candidate=" + variant, environ={key: value})

    def test_percent_encoded_connection_password_blocks_decoded_and_encoded_forms(self):
        value = authenticated_connection_url(
            "rediss", "rediss%40pass%2F123", user="default", suffix=":6380/0")
        for credential in ("rediss%40pass%2F123", "rediss@pass/123"):
            for variant in audit._credential_variants(credential):
                with self.subTest(credential=credential, variant=variant), \
                        self.assertRaises(audit.AuditBlocked):
                    audit.ensure_safe_text(variant, environ={"REDIS_URL": value})

    def test_static_authenticated_connection_urls_block(self):
        for url in (
            authenticated_connection_url("postgresql", "password123"),
            authenticated_connection_url("mongodb", "password123"),
            authenticated_connection_url("mongodb+srv", "password123"),
            authenticated_connection_url("redis", "password123", user="", suffix=":6379/0"),
            authenticated_connection_url("rediss", "password123", suffix=":6380/0"),
        ):
            with self.subTest(url=url), self.assertRaises(audit.AuditBlocked):
                audit.ensure_safe_text(url, environ={})

    def test_database_dump_markers_remain_blocked(self):
        dump_markers = (
            audit.SQLITE_HEADER,
            audit.POSTGRES_DUMP_HEADER,
            audit.COPY_KEYWORD + " fixture_table (id) FROM " + audit.STDIN_KEYWORD,
        )
        for marker in dump_markers:
            with self.subTest(marker_length=len(marker)), self.assertRaises(audit.AuditBlocked):
                audit.ensure_safe_text(marker, environ={})

    def test_long_database_dump_copy_header_remains_blocked(self):
        columns = ", ".join("column_" + str(index) + " text" for index in range(80))
        marker = (audit.COPY_KEYWORD + " fixture_table (" + columns + ") FROM " +
                  audit.STDIN_KEYWORD)
        self.assertGreater(len(marker), 1000)
        with self.assertRaises(audit.AuditBlocked):
            audit.ensure_safe_text(marker, environ={})

    def test_public_and_unauthenticated_urls_remain_safe(self):
        fixtures = {
            "PUBLIC_URL": "https://example.com/public/docs",
            "CALLBACK_URI": "https://example.org/callback",
            "DATABASE_URL": "postgresql://localhost.test/tariff",
            "REDIS_URL": "rediss://localhost.test:6380/0",
        }
        for key, value in fixtures.items():
            with self.subTest(key=key):
                self.assertEqual(audit.ensure_safe_text(value, environ={key: value}), value)

    def test_negative_fixtures_do_not_make_committed_test_source_unsafe(self):
        for path in (Path(audit.__file__), Path(__file__)):
            source = path.read_text()
            with self.subTest(path=path.name):
                self.assertEqual(audit.ensure_safe_text(source, environ={}), source)
                serialized = json.dumps({"text": source}, separators=(",", ":"))
                self.assertEqual(audit.ensure_safe_text(serialized, environ={}), serialized)

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
                    "https://docs.eaeunion.org.attacker.test",
                    "https://" + "user:" + "pass@" + "docs.eaeunion.org"):
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
