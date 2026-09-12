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
        evidence={'holder':'session-one','terminal_status':'completed','source':'native_work',
                  'evidence_ref':'test-only-observation','observed_at':now.isoformat()}
        new=json.loads(propose(record,self.sha,'takeover','session-two',now=now,
                              ended_evidence=evidence)['content'])
        self.assertEqual(new['generation'],2)
        with self.assertRaises(LeaseError):
            propose(new,self.sha,'renew','session-one',token=record['token'],now=now)
        for bad in ({**evidence,'terminal_status':'running'}, {**evidence,'holder':'wrong'},
                    {**evidence,'observed_at':self.now.isoformat()}):
            with self.assertRaises(LeaseError):
                propose(record,self.sha,'takeover','session-two',now=now,ended_evidence=bad)
