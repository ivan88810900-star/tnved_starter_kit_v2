"""Full offline bridge rehearsal, not mocked provider acceptance or live CI."""
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.tariff_agents import audit, audit_bridge, lease, preflight


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / 'trusted'
        self.repo.mkdir()
        self.state = self.repo / '.a6-state'
        self.init(self.repo)
        self.write(self.repo, audit.CONTRACT_PATH, 'Independent audit of declared code only.\n')
        for name in preflight.CODE_FILES:
            self.write(self.repo, 'tools/tariff_agents/' + name,
                       (Path(preflight.__file__).parent / name).read_text())
        self.write(self.repo, 'src/rates.py', 'RATE = 1\n')
        self.commit(self.repo)
        self.base = self.head(self.repo)
        # Decorators caused a real false-positive in the JSON writer; execute
        # that writer, not a lookalike packet schema test.
        self.write(self.repo, 'src/rates.py', 'import pytest\n\n@pytest.fixture\ndef rate():\n    return 2\n')
        self.commit(self.repo)
        self.trusted = self.head(self.repo)
        self.packet = audit.build_packet(self.repo, self.base, self.trusted,
                                         ['src/rates.py'], contract_ref=self.trusted,
                                         official_sources=[], environ={})
        self.state.mkdir()
        self.init(self.state)
        self.now = datetime.now(timezone.utc)
        self.pending = {
            'request_id': 'offline-rehearsal-001', 'base_sha': self.base,
            'head_sha': self.trusted, 'contract_sha': self.trusted,
            'paths_json': '["src/rates.py"]', 'official_sources_json': '[]',
            'packet_sha256': self.packet['packet_sha256'],
            'serialized_canonical_sha256': hashlib.sha256(audit_bridge._canonical(self.packet)).hexdigest(),
            'prepared_at': self.z(self.now - timedelta(seconds=5)),
            'packet_validation': 'PASSED_OFFLINE_WITHOUT_CREDENTIALS',
            'dispatched': False, 'consumed': False,
            'authorization_required': True,
        }
        proposal = lease.propose(lease.initial(), '1' * 40, 'acquire',
                                 '/root/a0_offline_test', now=self.now, ttl_seconds=1800)
        self.record = json.loads(proposal['content'])
        self.save_state()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.no_network = []
        for target in ('tools.tariff_agents.audit.run_audit',
                       'tools.tariff_agents.audit.request_json',
                       'tools.tariff_agents.audit_bridge.run',
                       'tools.tariff_agents.audit_bridge.fetch_commit_objects',
                       'urllib.request.urlopen'):
            self.no_network.append(self.stack.enter_context(patch(
                target, side_effect=AssertionError('Network/provider path forbidden in offline test'))))

    @staticmethod
    def z(value):
        return value.isoformat().replace('+00:00', 'Z')

    def git(self, root, *args):
        return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL)

    def init(self, root):
        self.git(root, 'init', '-q')
        self.git(root, 'config', 'user.email', 'offline@example.com')
        self.git(root, 'config', 'user.name', 'Offline regression')

    def write(self, root, relative, content):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')

    def commit(self, root):
        self.git(root, 'add', '.')
        self.git(root, 'commit', '--allow-empty', '-qm', 'offline fixture')

    def head(self, root):
        return self.git(root, 'rev-parse', 'HEAD').decode().strip()

    def save_state(self):
        self.write(self.state, preflight.STATUS_PATH, json.dumps({
            'schema_version': 1, 'live_verified': False, 'pending_live_smoke': self.pending}))
        self.write(self.state, preflight.LEASE_PATH, json.dumps(self.record))
        self.commit(self.state)
        self.state_sha = self.head(self.state)

    def check(self, **kwargs):
        args = dict(trusted_sha=self.trusted, state_sha=self.state_sha,
                    request_id='offline-rehearsal-001', packet_sha256=self.packet['packet_sha256'])
        args.update(kwargs)
        return preflight.check(self.repo, self.state, **args)

    def blocked(self, reason):
        with self.assertRaisesRegex(preflight.PreflightBlocked, '^' + reason + '$'):
            self.check()
        for mocked in self.no_network:
            mocked.assert_not_called()

    def test_exact_resolve_prepare_writer_pass_without_dispatch_or_authority(self):
        before = {p: (self.state / p).read_bytes() for p in (preflight.STATUS_PATH, preflight.LEASE_PATH)}
        result = self.check()
        self.assertEqual(result['status'], 'PREFLIGHT_PASSED_NOT_AUTHORIZATION')
        for field in ('provider_called', 'credentials_read', 'dispatch_created', 'export_authorized'):
            self.assertIs(result[field], False)
        self.assertIs(result['synthetic_context'], True)
        self.assertEqual(result['packet_sha256'], self.packet['packet_sha256'])
        self.assertEqual(result['canonical_packet_sha256'], self.pending['serialized_canonical_sha256'])
        self.assertEqual(result['state_sha'], self.state_sha)
        self.assertEqual(result['canonical_packet_bytes'], len(audit_bridge._canonical(self.packet)))
        self.assertEqual(set(result['trusted_helper_sha256']), set(preflight.CODE_FILES))
        for path, raw in before.items():
            self.assertEqual((self.state / path).read_bytes(), raw)
        for mocked in self.no_network:
            mocked.assert_not_called()

    def test_lease_change_does_not_regenerate_immutable_delivery(self):
        first = self.check()
        identity = audit_bridge._canonical(self.pending)
        self.record.update(generation=self.record['generation'] + 1,
                           holder='/root/a0_second_offline_test', token='a' * 32)
        self.save_state()
        second = self.check()
        self.assertEqual(first['delivery_generation'], second['delivery_generation'])
        self.assertEqual(first['request_id'], second['request_id'])
        self.assertEqual(identity, audit_bridge._canonical(self.pending))
        self.assertNotEqual(first['lease_generation'], second['lease_generation'])
        self.assertIs(second['export_authorized'], False)

    def test_offset_timestamp_rejected_before_event(self):
        self.record['expires_at'] = self.record['expires_at'].replace('Z', '+00:00')
        self.save_state()
        self.blocked('NON_CANONICAL_UTC_TIMESTAMP')

    def test_non_hex_token_rejected(self):
        self.record['token'] = 'not-hex-at-all'
        self.save_state()
        self.blocked('LEASE_SCHEMA_INVALID')

    def test_non_string_token_rejected_without_type_error(self):
        self.record['token'] = ['not-a-token']
        self.save_state()
        self.blocked('LEASE_SCHEMA_INVALID')

    def test_released_lease_rejected(self):
        self.record.update(state='released', token=None, holder=None, expires_at=None)
        self.save_state()
        self.blocked('LEASE_NOT_ACTIVE')

    def test_insufficient_lease_margin_rejected(self):
        self.record['expires_at'] = self.z(self.now + timedelta(seconds=100))
        self.save_state()
        self.blocked('LEASE_RENEWAL_REQUIRED')

    def test_future_lease_timestamp_rejected(self):
        self.record['updated_at'] = self.z(self.now + timedelta(minutes=1))
        self.save_state()
        self.blocked('LEASE_TIMESTAMP_IN_FUTURE')

    def test_future_preparation_blocked_before_dispatch(self):
        self.pending['prepared_at'] = self.z(self.now + timedelta(minutes=1))
        self.save_state()
        self.blocked('PREPARATION_BOUNDARY_NOT_SETTLED')

    def test_consumed_request_not_retried(self):
        self.pending['consumed'] = True
        self.save_state()
        self.blocked('PENDING_ALREADY_USED')

    def test_dispatched_request_not_retried(self):
        self.pending['dispatched'] = True
        self.save_state()
        self.blocked('PENDING_ALREADY_USED')

    def test_request_identity_change_rejected(self):
        self.pending['request_id'] = 'a-different-request'
        self.save_state()
        self.blocked('PENDING_BINDING_CHANGED')

    def test_stale_contract_rejected(self):
        self.pending['contract_sha'] = self.base
        self.save_state()
        self.blocked('PENDING_BINDING_CHANGED')

    def test_packet_hash_change_rejected(self):
        self.pending['packet_sha256'] = '0' * 64
        self.save_state()
        self.blocked('PENDING_BINDING_CHANGED')

    def test_omitted_path_rejected_by_actual_bridge(self):
        self.pending['paths_json'] = '[]'
        self.save_state()
        self.blocked('BRIDGE_REHEARSAL_FAILED')

    def test_serialized_hash_change_rejected(self):
        self.pending['serialized_canonical_sha256'] = '0' * 64
        self.save_state()
        self.blocked('SERIALIZED_PACKET_BINDING_CHANGED')

    def test_dirty_helper_rejected(self):
        path = self.repo / 'tools/tariff_agents/lease.py'
        path.write_text(path.read_text() + '\n# dirty copy\n')
        self.blocked('UNCOMMITTED_SNAPSHOT_CHANGE')

    def test_stale_loaded_helper_rejected(self):
        stale = self.repo / 'stale-helper.py'
        stale.write_text('# stale helper\n')
        with patch.object(lease, '__file__', str(stale)):
            self.blocked('EXECUTING_HELPER_VERSION_SKEW')

    def test_state_snapshot_moved_rejected(self):
        self.commit(self.state)
        self.blocked('STATE_CHECKOUT_MOVED')

    def test_uncommitted_state_rejected(self):
        path = self.state / preflight.STATUS_PATH
        path.write_text(path.read_text() + '\n')
        self.blocked('UNCOMMITTED_SNAPSHOT_CHANGE')

    def test_state_symlink_rejected(self):
        path = self.state / preflight.STATUS_PATH
        other = self.state / 'original.json'
        other.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(other)
        self.blocked('SYMLINK_NOT_ALLOWED')

    def test_state_change_during_rehearsal_rejected(self):
        original = audit_bridge.prepare
        def mutate(*args, **kwargs):
            result = original(*args, **kwargs)
            path = self.state / preflight.LEASE_PATH
            path.write_text(path.read_text() + '\n')
            return result
        with patch.object(audit_bridge, 'prepare', side_effect=mutate):
            self.blocked('UNCOMMITTED_SNAPSHOT_CHANGE')

    def test_cli_safe_diagnostic_not_raw_exception(self):
        from io import StringIO
        output = StringIO()
        args = ['--repo', str(self.repo), '--state-root', str(self.state),
                '--trusted-sha', self.trusted, '--state-sha', self.state_sha,
                '--request-id', 'WRONG', '--packet-sha256', self.packet['packet_sha256']]
        with patch('sys.stdout', output):
            self.assertEqual(preflight.main(args), 2)
        result = json.loads(output.getvalue())
        self.assertEqual(result['reason_code'], 'PENDING_BINDING_CHANGED')
        self.assertNotIn('token', output.getvalue())
        self.assertIs(result['provider_called'], False)



    def advance_code(self, relative='docs/code-maintenance.md', content='Code-only update.\n'):
        self.write(self.repo, relative, content)
        self.git(self.repo, 'add', relative)
        self.git(self.repo, 'commit', '-qm', 'code-only fixture update')
        self.trusted = self.head(self.repo)

    def test_explicit_original_contract_survives_code_only_upgrade(self):
        first = self.check()
        original_contract = self.pending['contract_sha']
        before = {p: (self.state / p).read_bytes() for p in (preflight.STATUS_PATH, preflight.LEASE_PATH)}
        self.advance_code()
        result = self.check(request_contract_sha=original_contract)
        self.assertEqual(result['contract_sha'], original_contract)
        self.assertEqual(result['trusted_code_sha'], self.trusted)
        self.assertNotEqual(result['contract_sha'], result['trusted_code_sha'])
        self.assertEqual(result['delivery_generation'], first['delivery_generation'])
        self.assertEqual(result['packet_sha256'], first['packet_sha256'])
        self.assertEqual(result['canonical_packet_sha256'], first['canonical_packet_sha256'])
        self.assertIs(result['export_authorized'], False)
        for path, raw in before.items():
            self.assertEqual((self.state / path).read_bytes(), raw)
        for mocked in self.no_network:
            mocked.assert_not_called()

    def test_code_upgrade_does_not_implicitly_choose_old_contract(self):
        self.advance_code()
        self.blocked('PENDING_BINDING_CHANGED')

    def test_real_contract_change_rejected_even_with_explicit_old_sha(self):
        original_contract = self.pending['contract_sha']
        self.advance_code(audit.CONTRACT_PATH, 'Different audit contract.\n')
        with self.assertRaisesRegex(preflight.PreflightBlocked, '^REQUEST_CONTRACT_VERSION_SKEW$'):
            self.check(request_contract_sha=original_contract)
        for mocked in self.no_network:
            mocked.assert_not_called()

    def test_wrong_explicit_contract_does_not_rebind_pending(self):
        with self.assertRaisesRegex(preflight.PreflightBlocked, '^PENDING_BINDING_CHANGED$'):
            self.check(request_contract_sha=self.base)

    def test_contract_worktree_drift_rejected(self):
        (self.repo / audit.CONTRACT_PATH).write_text('Dirty contract.\n')
        self.blocked('UNCOMMITTED_SNAPSHOT_CHANGE')

    def test_consumed_stays_blocked_after_code_upgrade(self):
        original_contract = self.pending['contract_sha']
        self.advance_code()
        self.pending['consumed'] = True
        self.save_state()
        with self.assertRaisesRegex(preflight.PreflightBlocked, '^PENDING_ALREADY_USED$'):
            self.check(request_contract_sha=original_contract)

    def test_lease_loss_stays_blocked_after_code_upgrade(self):
        original_contract = self.pending['contract_sha']
        self.advance_code()
        self.record.update(state='released', token=None, holder=None, expires_at=None)
        self.save_state()
        with self.assertRaisesRegex(preflight.PreflightBlocked, '^LEASE_NOT_ACTIVE$'):
            self.check(request_contract_sha=original_contract)


if __name__ == '__main__':
    unittest.main()
