"""Regressions for serialization false positives at BOTH response boundaries."""
from contextlib import ExitStack
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools.tariff_agents import audit, audit_bridge


class StructuredSafetyTests(unittest.TestCase):
    def setUp(self):
        self.packet = {
            'packet_sha256': 'a' * 64, 'head_sha': 'b' * 40,
            'base_sha': 'c' * 40, 'paths': ['src/rates.py'], 'official_sources': [],
            'files': [{'path': 'src/rates.py', 'base': None,
                       'head': {'text': '@pytest.fixture\ndef rate():\n    return 2\n'}}],
            'contract': {'path': '.ai/orchestration/CONTRACT.md',
                         'text': 'Read-only audit.\n', 'resolved_commit': 'd' * 40},
        }
        self.result = {'packet_sha256': 'a' * 64, 'head_sha': 'b' * 40,
                       'findings': [self.finding()], 'limitations': []}

    def finding(self):
        return {'id': 'F1', 'severity': 'low', 'category': 'test',
                'path': 'src/rates.py', 'line': 1, 'claim': 'Fixture example',
                'evidence': 'Decorator follows a newline:\n@pytest.fixture',
                'suggested_fix': 'Check fixture scope.', 'official_source_urls': []}

    def test_baseline_aggregate_reproduces_false_positive(self):
        audit.ensure_safe_text(self.result['findings'][0]['evidence'], environ={})
        with self.assertRaises(audit.AuditBlocked):
            audit.ensure_safe_text(audit._json_bytes(self.result).decode(), environ={})

    def test_original_findings_and_newline_decorator_are_preserved(self):
        before = json.dumps(self.result, sort_keys=True)
        self.assertIs(audit.validate_findings(self.result, self.packet, environ={}), self.result)
        self.assertEqual(json.dumps(self.result, sort_keys=True), before)

    def test_multiline_limitations_preserved(self):
        self.result['limitations'] = ['Fixture metadata is incomplete:\n@unittest.skipUnless']
        audit.validate_findings(self.result, self.packet, environ={})

    def test_real_contact_still_rejected_in_findings(self):
        self.result['findings'][0]['evidence'] = 'Contact person@private.test'
        with self.assertRaisesRegex(audit.FindingsValidationBlocked, 'FINDINGS_CONTENT_SAFETY'):
            audit.validate_findings(self.result, self.packet, environ={})

    def test_contacts_in_nested_values_and_keys_still_rejected(self):
        for value in ({'outer': [{'email': 'person@private.test'}]},
                      {'person@private.test': 'key also scanned'},
                      {'value': 'n@pytest.fixture'}):
            with self.subTest(value=value), self.assertRaises(audit.AuditBlocked):
                audit.ensure_safe_json_value(value, environ={})

    def test_unicode_escaped_contact_still_rejected(self):
        with self.assertRaises(audit.AuditBlocked):
            audit.ensure_safe_json_value({'value': r'person\u0040private.test'}, environ={})

    def test_credentials_not_admitted_by_structured_scan(self):
        credential = 'fixture-credential-value-for-regression'
        with self.assertRaises(audit.AuditBlocked):
            audit.ensure_safe_json_value({'value': credential},
                                        environ={'A6_TOKEN': credential})

    def test_non_json_and_cycles_fail_closed(self):
        circular = []; circular.append(circular)
        for value in ({1: 'non-string key'}, {'value': float('nan')}, circular, {'value': object()}):
            with self.subTest(kind=type(value)), self.assertRaises(audit.AuditBlocked):
                audit.ensure_safe_json_value(value, environ={})

    def test_receipt_writer_preserves_valid_multiline_findings(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'receipt.json'
            audit_bridge._write_exclusive(path, self.result, environ={})
            self.assertEqual(json.loads(path.read_text()), self.result)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                audit_bridge._write_exclusive(path, self.result, environ={})

    def test_receipt_writer_rejects_contact_without_creating_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'receipt.json'
            with self.assertRaises(audit.AuditBlocked):
                audit_bridge._write_exclusive(path, {'contact': 'person@private.test'}, environ={})
            self.assertFalse(path.exists())

    def test_receipt_symlink_target_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / 'original.txt'; target.write_text('unchanged')
            path = Path(td) / 'receipt.json'; path.symlink_to(target)
            with self.assertRaises(FileExistsError):
                audit_bridge._write_exclusive(path, self.result, environ={})
            self.assertEqual(target.read_text(), 'unchanged')

    def test_offline_provider_fixture_to_local_validator_to_receipt(self):
        # Synthetic response only. No external call is made or claimed.
        response_result = json.loads(json.dumps(self.result))
        del response_result['findings'][0]['official_source_urls']
        response = {'id': 'msg_offline_fixture', 'stop_reason': 'end_turn',
                    'content': [{'type': 'text', 'text': json.dumps(response_result)}]}
        env = {'ANTHROPIC_API_KEY': 'fixture-only', 'TARIFF_ANTHROPIC_MODEL': 'fixture-model'}
        with patch.object(audit, 'validate_packet', return_value=self.packet), \
                patch.object(audit, 'request_json', return_value=response) as transport:
            result = audit.run_audit('.', self.packet, environ=env)
        transport.assert_called_once()
        self.assertEqual(result['status'], 'NEEDS_A0_VALIDATION')
        self.assertEqual(result['findings'][0]['official_source_urls'], [])
        context = {'repository': 'owner/example', 'workflow_run_id': '1',
                   'workflow_sha': 'd' * 40}
        receipt = audit_bridge._receipt(context, 'offline-only', self.packet, result, 'LIVE_VERIFIED')
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'receipt.json'
            audit_bridge._write_exclusive(path, receipt, environ=env)
            written = json.loads(path.read_text())
        self.assertEqual(written['findings'], self.result['findings'])
        self.assertEqual(written['a0_validation'], 'PENDING')
        # The fixture passing does not make any live project state verified.

    def test_binding_tampering_still_rejected(self):
        self.result['head_sha'] = 'e' * 40
        with self.assertRaisesRegex(audit.FindingsValidationBlocked, 'FINDINGS_BINDING'):
            audit.validate_findings(self.result, self.packet, environ={})

    def test_injected_source_still_rejected(self):
        self.result['findings'][0]['official_source_urls'] = ['https://untrusted.test/']
        with self.assertRaisesRegex(audit.FindingsValidationBlocked, 'FINDING_SOURCE_SCOPE'):
            audit.validate_findings(self.result, self.packet, environ={})


if __name__ == '__main__':
    unittest.main()
