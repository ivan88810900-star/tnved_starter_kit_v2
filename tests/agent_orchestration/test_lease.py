import datetime as dt
import json
import unittest
from tools.tariff_agents.lease import LeaseError, initial, propose, assert_holder


class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.now=dt.datetime(2026,9,12,tzinfo=dt.timezone.utc)
        self.sha='a'*40

    def active(self):
        proposal=propose(initial(),self.sha,'acquire','session-one',now=self.now)
        self.assertEqual(proposal['branch'],'agent/orchestration-state')
        self.assertEqual(proposal['sha'],self.sha)
        self.assertEqual(proposal['path'],'.ai/COORDINATOR_LEASE.json')
        return json.loads(proposal['content'])

    def test_expiry_does_not_allow_second_writer(self):
        record=self.active()
        with self.assertRaises(LeaseError):
            propose(record,self.sha,'acquire','session-two',now=self.now+dt.timedelta(days=1))
        with self.assertRaises(LeaseError):
            assert_holder(record,'session-one',record['token'],now=self.now+dt.timedelta(days=1))

    def test_release_reacquire_fences_old_session(self):
        first=self.active()
        released=json.loads(propose(first,self.sha,'release','session-one',token=first['token'],now=self.now)['content'])
        second=json.loads(propose(released,'b'*40,'acquire','session-two',now=self.now)['content'])
        self.assertEqual(second['generation'],2)
        with self.assertRaises(LeaseError):
            propose(second,'c'*40,'renew','session-one',token=first['token'],now=self.now)
        assert_holder(second,'session-two',second['token'],now=self.now)

    def test_cas_required_and_proposal_is_not_local_acquisition(self):
        record=initial()
        with self.assertRaises(LeaseError):
            propose(record,'main','acquire','session-one',now=self.now)
        p1=propose(record,self.sha,'acquire','one',now=self.now)
        p2=propose(record,self.sha,'acquire','two',now=self.now)
        self.assertEqual(record['state'],'released')
        self.assertEqual(p1['sha'],p2['sha']) # GitHub accepts at most one CAS update.
        self.assertNotEqual(json.loads(p1['content'])['token'],json.loads(p2['content'])['token'])

    def test_invalid_holder_and_clock_are_rejected(self):
        with self.assertRaises(LeaseError):
            propose(initial(),self.sha,'acquire','',now=self.now)
        with self.assertRaises(LeaseError):
            propose(initial(),self.sha,'acquire','a',now=dt.datetime(2026,1,1))

    def test_takeover_requires_observed_termination_and_fences_previous(self):
        record=self.active()
        now=self.now+dt.timedelta(hours=2)
        with self.assertRaises(LeaseError):
            propose(record,self.sha,'takeover','session-two',now=now)
        evidence={'holder':'session-one','token':record['token'],'generation':record['generation'],
                  'terminal_status':'completed','source':'native_work',
                  'evidence_ref':'test-only-observation','observed_at':now.isoformat()}
        new=json.loads(propose(record,self.sha,'takeover','session-two',now=now,
                              ended_evidence=evidence)['content'])
        self.assertEqual(new['generation'],2)
        with self.assertRaises(LeaseError):
            propose(new,self.sha,'renew','session-one',token=record['token'],now=now)
        for bad in ({**evidence,'terminal_status':'running'}, {**evidence,'holder':'wrong'},
                    {**evidence,'token':'0'*32}, {**evidence,'generation':0},
                    {**evidence,'generation':True}, {**evidence,'generation':1.0},
                    {**evidence,'observed_at':self.now.isoformat()}):
            with self.assertRaises(LeaseError):
                propose(record,self.sha,'takeover','session-two',now=now,ended_evidence=bad)

    def test_lease_timestamps_are_well_formed_and_mutations_are_monotonic(self):
        record=self.active()
        renewed_at=self.now+dt.timedelta(seconds=40)
        renewed=json.loads(propose(record,'b'*40,'renew','session-one',token=record['token'],
                                   now=renewed_at,ttl_seconds=60)['content'])
        rollback=self.now+dt.timedelta(seconds=30)
        for action in ('renew','release'):
            with self.assertRaises(LeaseError):
                propose(renewed,'c'*40,action,'session-one',token=record['token'],now=rollback)

        released=json.loads(propose(renewed,'c'*40,'release','session-one',
                                    token=record['token'],now=renewed_at)['content'])
        with self.assertRaises(LeaseError):
            propose(released,'d'*40,'acquire','session-two',now=rollback)

        for malformed in ({**record,'updated_at':None},
                          {**record,'updated_at':'2026-09-12T00:00:00'},
                          {**record,'expires_at':record['updated_at']}):
            with self.assertRaises(LeaseError):
                propose(malformed,'d'*40,'renew','session-one',token=record['token'],
                        now=self.now)

    def test_takeover_rejects_terminal_evidence_from_before_current_renewal(self):
        record=self.active()
        observed=self.now+dt.timedelta(seconds=30)
        renewed_at=self.now+dt.timedelta(seconds=40)
        renewed=json.loads(propose(record,'b'*40,'renew','session-one',token=record['token'],
                                   now=renewed_at,ttl_seconds=60)['content'])
        takeover_at=self.now+dt.timedelta(seconds=101)
        stale_evidence={'holder':'session-one','token':renewed['token'],
                        'generation':renewed['generation'],'terminal_status':'completed',
                        'source':'native_work','evidence_ref':'pre-renewal-observation',
                        'observed_at':observed.isoformat()}
        with self.assertRaises(LeaseError):
            propose(renewed,'c'*40,'takeover','session-two',now=takeover_at,
                    ended_evidence=stale_evidence)

        current_evidence={**stale_evidence,'evidence_ref':'current-incarnation-observation',
                          'observed_at':takeover_at.isoformat()}
        taken=json.loads(propose(renewed,'c'*40,'takeover','session-two',now=takeover_at,
                                 ended_evidence=current_evidence)['content'])
        self.assertEqual(taken['holder'],'session-two')
        self.assertEqual(taken['generation'],renewed['generation']+1)

    def test_owner_release_requires_exact_fresh_connector_verified_receipt(self):
        record=self.active()
        now=self.now+dt.timedelta(hours=2)
        evidence={
            'source':'github_owner_receipt',
            'owner_login':'ivan88810900-star',
            'decision':'release_stale_holder',
            'holder':'session-one',
            'generation':record['generation'],
            'lease_blob_sha':self.sha,
            'verified_by_connector':True,
            'evidence_ref':(
                'https://github.com/ivan88810900-star/tnved_starter_kit_v2/'
                'issues/214#issuecomment-1'
            ),
            'confirmed_at':now.isoformat(),
        }
        released=json.loads(propose(
            record,self.sha,'owner-release','recovery-session',now=now,
            owner_release_evidence=evidence)['content'])
        self.assertEqual(released['state'],'released')
        self.assertIsNone(released['holder'])
        self.assertIsNone(released['token'])
        self.assertEqual(released['owner_recovery_release'],evidence)

        for bad in (
            None,
            {**evidence,'owner_login':'someone-else'},
            {**evidence,'holder':'wrong'},
            {**evidence,'generation':0},
            {**evidence,'lease_blob_sha':'b'*40},
            {**evidence,'verified_by_connector':False},
            {**evidence,'evidence_ref':'https://example.test/comment'},
            {**evidence,'confirmed_at':self.now.isoformat()},
        ):
            with self.assertRaises(LeaseError):
                propose(record,self.sha,'owner-release','recovery-session',now=now,
                        owner_release_evidence=bad)

    def test_owner_release_never_replaces_live_or_released_lease(self):
        active=self.active()
        evidence={
            'source':'github_owner_receipt','owner_login':'ivan88810900-star',
            'decision':'release_stale_holder','holder':'session-one',
            'generation':active['generation'],'lease_blob_sha':self.sha,
            'verified_by_connector':True,
            'evidence_ref':(
                'https://github.com/ivan88810900-star/tnved_starter_kit_v2/'
                'issues/214#issuecomment-1'
            ),
            'confirmed_at':self.now.isoformat(),
        }
        with self.assertRaises(LeaseError):
            propose(active,self.sha,'owner-release','recovery-session',now=self.now,
                    owner_release_evidence=evidence)
        with self.assertRaises(LeaseError):
            propose(initial(),self.sha,'owner-release','recovery-session',now=self.now,
                    owner_release_evidence=evidence)
