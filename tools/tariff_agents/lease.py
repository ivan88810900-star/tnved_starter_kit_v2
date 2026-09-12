"""CAS proposals for A0's existing GitHub connector, without storing credentials.

A proposal is NOT acquisition. Apply using github_update_file(expected blob SHA),
then reread and verify before dispatch. Never clear an expired active holder merely
because its clock expired. This fences cooperating A0 sessions, not arbitrary GitHub
writers with repository permissions.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import re
import uuid
from pathlib import Path

REPOSITORY = 'ivan88810900-star/tnved_starter_kit_v2'
STATE_BRANCH = 'agent/orchestration-state'
LEASE_PATH = '.ai/COORDINATOR_LEASE.json'


class LeaseError(ValueError):
    pass


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def _time(value):
    try:
        result = dt.datetime.fromisoformat(value)
        if result.tzinfo is None:
            raise ValueError()
        return result
    except (TypeError, ValueError):
        raise LeaseError('Lease timestamp must include timezone') from None


def validate(record):
    if not isinstance(record, dict) or record.get('schema_version') != 1:
        raise LeaseError('Unknown lease schema')
    if record.get('state') not in {'active', 'released'}:
        raise LeaseError('Unknown lease state')
    if type(record.get('generation')) is not int or record['generation'] < 0:
        raise LeaseError('Invalid generation')
    if record['state'] == 'active':
        if not isinstance(record.get('holder'), str) or not record['holder']:
            raise LeaseError('Missing real A0 session identity')
        if not re.fullmatch(r'[a-f0-9]{32}', record.get('token', '')):
            raise LeaseError('Invalid fencing token')
        _time(record.get('expires_at'))
    return record


def initial():
    return {'schema_version': 1, 'state': 'released', 'generation': 0,
            'holder': None, 'token': None, 'expires_at': None}


def assert_holder(record, holder, token, *, now=None):
    validate(record)
    if record['state'] != 'active' or record['holder'] != holder or record['token'] != token:
        raise LeaseError('This session does not hold the current remote lease')
    if _time(record['expires_at']) <= (now or utcnow()):
        raise LeaseError('Lease expired; renew by CAS before any dispatch/publication')


def propose(record, blob_sha, action, holder, *, token=None, now=None, ttl_seconds=1800, ended_evidence=None):
    """Return exact GitHub update_file args. Caller MUST apply CAS and verify result."""
    validate(record)
    if not re.fullmatch(r'[a-f0-9]{40}', blob_sha):
        raise LeaseError('Expected remote blob SHA required')
    if not isinstance(holder, str) or not holder or len(holder) > 200:
        raise LeaseError('Real A0 session identity required')
    if type(ttl_seconds) is not int or not 60 <= ttl_seconds <= 3600:
        raise LeaseError('Lease duration must be 60..3600 seconds')
    now = now or utcnow()
    if now.tzinfo is None:
        raise LeaseError('Timezone required')
    new = dict(record)
    if action == 'acquire':
        if record['state'] != 'released':
            raise LeaseError('Another session is active; expiry is not proof it ended')
        new.update(state='active', generation=record['generation']+1,
                   holder=holder, token=uuid.uuid4().hex)
    elif action == 'takeover':
        if record['state'] != 'active' or _time(record['expires_at']) > now:
            raise LeaseError('Takeover requires an expired active lease')
        evidence = ended_evidence
        if (not isinstance(evidence, dict) or evidence.get('holder') != record['holder'] or
                evidence.get('terminal_status') not in {'completed', 'failed', 'cancelled', 'terminated'} or
                evidence.get('source') not in {'native_work', 'agents_api'} or
                not isinstance(evidence.get('evidence_ref'), str) or not evidence['evidence_ref'].strip()):
            raise LeaseError('Verified previous-session termination evidence required')
        observed = _time(evidence.get('observed_at'))
        if observed > now or (now-observed).total_seconds() > 3600:
            raise LeaseError('Termination evidence must be current')
        new.update(state='active', generation=record['generation']+1,
                   holder=holder, token=uuid.uuid4().hex, previous_holder_end=evidence)
    elif action in {'renew', 'release'}:
        # The holder may renew after interruption only while its token remains current.
        # An expired lease cannot be stolen automatically by a different session.
        if record['state'] != 'active' or record['holder'] != holder or record['token'] != token:
            raise LeaseError('Holder/token changed; old session is fenced')
        if action == 'release':
            new.update(state='released', holder=None, token=None, expires_at=None)
    else:
        raise LeaseError('Unknown lease action')
    if new['state'] == 'active':
        new['expires_at'] = (now + dt.timedelta(seconds=ttl_seconds)).isoformat()
    new['updated_at'] = now.isoformat()
    return {'repository_full_name': REPOSITORY, 'branch': STATE_BRANCH,
            'path': LEASE_PATH, 'sha': blob_sha,
            'message': 'chore(agents): '+action+' coordinator lease',
            'content': json.dumps(new, sort_keys=True, indent=2)+'\n'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['acquire', 'renew', 'release', 'takeover'])
    parser.add_argument('--record', type=Path, required=True)
    parser.add_argument('--blob-sha', required=True)
    parser.add_argument('--holder', required=True)
    parser.add_argument('--token')
    parser.add_argument('--ended-evidence', type=Path)
    args=parser.parse_args()
    print(json.dumps(propose(json.loads(args.record.read_text()), args.blob_sha,
                             args.action, args.holder, token=args.token,
                             ended_evidence=json.loads(args.ended_evidence.read_text())
                             if args.ended_evidence else None), indent=2))


if __name__ == '__main__':
    main()
