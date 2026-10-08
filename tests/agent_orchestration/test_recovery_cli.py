"""Exercise the principal CLI in separate processes against local Git fixtures.

No native sessions, external providers, GitHub writes or transport delivery are
performed or certified by these tests.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.tariff_agents import operations, verify

PROJECT = Path(__file__).resolve().parents[2]


def git(root, *args):
    return subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-C', str(root),
                           *args], check=True, text=True, capture_output=True).stdout.strip()


class RecoveryCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.code, self.state = self.root / 'code', self.root / 'state'
        for directory in (self.code, self.state):
            directory.mkdir()
            git(directory, 'init', '-b', 'fixture')
            git(directory, 'config', 'user.name', 'Offline fixture')
            git(directory, 'config', 'user.email', 'fixture@example.com')
        for source in (PROJECT / 'tools/tariff_agents').glob('*.py'):
            self.write(self.code, 'tools/tariff_agents/' + source.name, source.read_text())
        self.code_sha = self.commit(self.code)
        self.status = {
            'schema_version': 1, 'live_verified': False,
            'owner_gate': {'action': 'A6_EXTERNAL_PROVIDER_EXPORT',
                           'authorization': 'REQUIRED_EXACT_REQUEST_ONLY',
                           'request_id': 'offline-existing-request',
                           'packet_sha256': 'a' * 64},
            'pending_live_smoke': {'request_id': 'offline-existing-request',
                                   'packet_sha256': 'a' * 64,
                                   'dispatched': False, 'consumed': False},
        }
        self.lease = {'schema_version': 1, 'state': 'released', 'generation': 106,
                      'holder': None, 'token': None, 'expires_at': None}
        self.board = {'schema_version': 1, 'revision': 661,
                      'max_concurrent_subagents': 3, 'tasks': [],
                      'findings': [], 'runs': []}
        self.save_state()

    @staticmethod
    def write(root, path, value):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value, encoding='utf-8')

    @staticmethod
    def commit(root):
        git(root, 'add', '.')
        git(root, 'commit', '--allow-empty', '-m', 'Offline snapshot fixture')
        return git(root, 'rev-parse', 'HEAD')

    def save_state(self):
        for path, value in (
            ('.ai/orchestration/A6_LIVE_STATUS.json', self.status),
            ('.ai/COORDINATOR_LEASE.json', self.lease),
            ('.ai/TASK_BOARD.json', self.board),
        ):
            self.write(self.state, path, json.dumps(value))
        self.state_sha = self.commit(self.state)

    def invoke(self, *extra):
        env = dict(os.environ, PYTHONPATH=str(PROJECT), PYTHONDONTWRITEBYTECODE='1')
        return subprocess.run(
            [sys.executable, '-m', 'tools.tariff_agents', '--repo', str(self.code),
             'recovery-status', '--state-root', str(self.state),
             '--code-sha', self.code_sha, '--state-sha', self.state_sha, *extra],
            cwd=PROJECT, env=env, text=True, capture_output=True, timeout=30)

    def assert_blocked(self, result):
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'RECOVERY_INPUT_INVALID')
        self.assertNotIn('Traceback', result.stderr)

    def test_export_gate_does_not_block_local_work_or_regenerate_request(self):
        before = {p: p.read_bytes() for p in self.state.rglob('*')
                  if p.is_file() and '.git' not in p.parts}
        state_head = git(self.state, 'rev-parse', 'HEAD')
        result = self.invoke('--publication-policy', 'blocked')
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual(out['status'], 'READ_ONLY_WORK_AVAILABLE')
        self.assertEqual(out['publication'], 'PLATFORM_CLEARANCE_REQUIRED')
        self.assertEqual(out['export_gate_status'], 'OWNER_ACTION_REQUIRED')
        self.assertTrue(out['local_analysis_and_tests_allowed'])
        self.assertTrue(out['task_owner_action_required'])
        self.assertTrue(out['pending_unused'])
        for key in ('remote_write_authorized', 'external_export_authorized',
                    'request_regenerated', 'provider_called', 'notification_sent'):
            self.assertIs(out[key], False)
        self.assertEqual(out['request_id'], 'offline-existing-request')
        self.assertEqual(out['code_sha'], self.code_sha)
        self.assertEqual(out['state_sha'], self.state_sha)
        self.assertEqual(out['board_revision'], 661)
        self.assertEqual(out['notification_delivery'], 'UNCONFIRMED')
        self.assertEqual(out['native_session_status'], 'UNVERIFIED')
        self.assertEqual(git(self.state, 'rev-parse', 'HEAD'), state_head)
        self.assertFalse((self.state / '.git/tariff-agents').exists())
        self.assertEqual(git(self.state, 'status', '--porcelain'), '')
        for path, raw in before.items():
            self.assertEqual(path.read_bytes(), raw)

    def test_default_does_not_claim_safety_clearance(self):
        out = json.loads(self.invoke().stdout)
        self.assertEqual(out['publication'], 'PERMISSION_UNVERIFIED')
        self.assertIs(out['remote_write_authorized'], False)

    def test_no_cli_authorization_bypass_switch(self):
        result = self.invoke('--publication-policy', 'authorized')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')

    def test_consumed_request_is_reported_not_recreated(self):
        self.status['pending_live_smoke']['consumed'] = True
        self.save_state()
        out = json.loads(self.invoke().stdout)
        self.assertFalse(out['pending_unused'])
        self.assertFalse(out['request_regenerated'])
        self.assertTrue(out['local_analysis_and_tests_allowed'])

    def test_state_head_movement_is_rejected(self):
        self.commit(self.state)
        self.assert_blocked(self.invoke())

    def test_dirty_state_is_rejected(self):
        path = self.state / '.ai/COORDINATOR_LEASE.json'
        path.write_text(path.read_text() + '\n')
        self.assert_blocked(self.invoke())

    def test_executing_code_drift_is_rejected(self):
        path = self.code / 'tools/tariff_agents/operations.py'
        path.write_text(path.read_text() + '\n# drift\n')
        self.code_sha = self.commit(self.code)
        self.assert_blocked(self.invoke())

    def test_invalid_board_is_rejected_by_canonical_validator(self):
        self.board['max_concurrent_subagents'] = 4
        self.save_state()
        self.assert_blocked(self.invoke())

    def test_symlink_state_file_is_rejected(self):
        path = self.state / '.ai/COORDINATOR_LEASE.json'
        raw = path.read_text()
        backup = self.root / 'lease.json'
        backup.write_text(raw)
        path.unlink()
        path.symlink_to(backup)
        self.assert_blocked(self.invoke())

    def test_untrusted_diagnostic_text_is_not_echoed(self):
        marker = 'UNTRUSTED_INPUT_DO_NOT_ECHO'
        self.status['pending_live_smoke']['request_id'] = marker + '\n'
        self.save_state()
        result = self.invoke()
        self.assert_blocked(result)
        self.assertNotIn(marker, result.stdout + result.stderr)

    def test_pure_recovery_never_dispatches_or_notifies(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('network')) as net:
            out = operations.recovery_status(self.status, self.lease,
                    now=datetime.now(timezone.utc), publication_policy='blocked')
        net.assert_not_called()
        self.assertFalse(out['notification_sent'])

    def test_new_and_cli_suites_are_mandatory_nonempty_exact_files(self):
        names = ('test_cli_snapshot', 'test_preflight', 'test_operations',
                 'test_structured_safety', 'test_recovery_cli')
        directory = self.root / 'missing-required-suites'
        directory.mkdir()
        for name in names:
            self.assertIn(name, verify.REQUIRED)
            with self.assertRaisesRegex(RuntimeError, 'Required test module missing'):
                verify._load_required(directory, name, unittest.TestLoader())
            (directory / (name + '.py')).write_text('"""no tests"""\n')
            with self.assertRaisesRegex(RuntimeError, 'zero tests'):
                verify._load_required(directory, name, unittest.TestLoader())


if __name__ == '__main__':
    unittest.main()
