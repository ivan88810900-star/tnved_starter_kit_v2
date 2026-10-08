"""Rehearse the existing A6 resolve/prepare/writer path BEFORE creating an event.

Offline only: no Git fetch, provider call, credential read, GitHub comment, state
write or authorization grant. Use a fresh connector-read main SHA and state SHA.
The synthetic event lives only in a temporary directory and is never exported.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


class PreflightBlocked(ValueError):
    """Only bounded reason codes, never raw code, credentials or exceptions."""


SHA = re.compile(r"[0-9a-f]{40}")
HASH = re.compile(r"[0-9a-f]{64}")
CODE_FILES = ("audit.py", "audit_bridge.py", "lease.py", "runtime.py", "preflight.py")
STATUS_PATH = ".ai/orchestration/A6_LIVE_STATUS.json"
LEASE_PATH = ".ai/COORDINATOR_LEASE.json"


def _git(root, *args):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_NO_REPLACE_OBJECTS="1", GIT_TERMINAL_PROMPT="0")
    try:
        return subprocess.check_output(
            ["git", "--no-pager", "-c", "core.hooksPath=" + os.devnull,
             "-c", "core.fsmonitor=false", *args], cwd=root, env=env,
            stderr=subprocess.DEVNULL, timeout=20)
    except (OSError, subprocess.SubprocessError):
        raise PreflightBlocked("GIT_SNAPSHOT_UNAVAILABLE") from None


def _sha(value):
    if not isinstance(value, str) or SHA.fullmatch(value) is None:
        raise PreflightBlocked("EXACT_SHA_REQUIRED")
    return value


def _plain_file(root, relative):
    target = Path(root)
    for part in Path(relative).parts:
        target = target / part
        if target.is_symlink():
            raise PreflightBlocked("SYMLINK_NOT_ALLOWED")
    try:
        return target.read_bytes()
    except OSError:
        raise PreflightBlocked("SNAPSHOT_FILE_UNAVAILABLE") from None


def _committed(root, sha, relative):
    current = _plain_file(root, relative)
    if current != _git(root, "show", f"{sha}:{relative}"):
        raise PreflightBlocked("UNCOMMITTED_SNAPSHOT_CHANGE")
    return current


def _json(raw):
    if len(raw) > 20_000:
        raise PreflightBlocked("STATE_FILE_TOO_LARGE")
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        raise PreflightBlocked("STATE_JSON_INVALID") from None
    if not isinstance(value, dict):
        raise PreflightBlocked("STATE_JSON_INVALID")
    return value


def _utc(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PreflightBlocked("NON_CANONICAL_UTC_TIMESTAMP")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
        if parsed.utcoffset().total_seconds() != 0:
            raise ValueError()
        return parsed
    except (ValueError, TypeError, AttributeError):
        raise PreflightBlocked("INVALID_UTC_TIMESTAMP") from None


def check(repo, state_root, *, trusted_sha, state_sha, request_id, packet_sha256,
          minimum_lease_seconds=600, request_contract_sha=None):
    """Return an operational preflight receipt, explicitly NOT export authority.

    The source of the executing helper must match the trusted commit, even when
    a copy was accidentally imported from the state branch. Pending identity is
    independent of a new lawful coordinator lease; no request is regenerated here.
    """
    from . import audit, audit_bridge, lease, runtime

    repo, state_root = Path(repo).resolve(), Path(state_root).resolve()
    trusted_sha, state_sha = _sha(trusted_sha), _sha(state_sha)
    # Code upgrades must not silently rebind an already prepared packet. The
    # caller pins its original contract commit explicitly; old callers remain
    # strict and default to the executing code commit.
    contract_sha = trusted_sha if request_contract_sha is None else _sha(request_contract_sha)
    if (not isinstance(request_id, str) or audit_bridge.REQUEST_RE.fullmatch(request_id) is None or
            not isinstance(packet_sha256, str) or HASH.fullmatch(packet_sha256) is None):
        raise PreflightBlocked("EXACT_REQUEST_BINDING_REQUIRED")
    if type(minimum_lease_seconds) is not int or not 300 <= minimum_lease_seconds <= 1800:
        raise PreflightBlocked("LEASE_MARGIN_MUST_BE_300_TO_1800_SECONDS")
    if _git(repo, "rev-parse", "HEAD").decode().strip() != trusted_sha:
        raise PreflightBlocked("TRUSTED_CHECKOUT_MOVED")
    if _git(state_root, "rev-parse", "HEAD").decode().strip() != state_sha:
        raise PreflightBlocked("STATE_CHECKOUT_MOVED")
    loaded = {"audit.py": Path(audit.__file__), "audit_bridge.py": Path(audit_bridge.__file__),
              "lease.py": Path(lease.__file__), "runtime.py": Path(runtime.__file__),
              "preflight.py": Path(__file__)}
    fingerprints = {}
    for filename in CODE_FILES:
        relative = "tools/tariff_agents/" + filename
        expected = _committed(repo, trusted_sha, relative)
        try:
            actual = loaded[filename].read_bytes()
        except OSError:
            raise PreflightBlocked("EXECUTING_HELPER_UNAVAILABLE") from None
        if actual != expected:
            raise PreflightBlocked("EXECUTING_HELPER_VERSION_SKEW")
        fingerprints[filename] = hashlib.sha256(expected).hexdigest()
    state_raw = _committed(state_root, state_sha, STATUS_PATH)
    lease_raw = _committed(state_root, state_sha, LEASE_PATH)
    status, record = _json(state_raw), _json(lease_raw)
    pending = status.get("pending_live_smoke")
    if not isinstance(pending, dict):
        raise PreflightBlocked("NO_PENDING_REQUEST")
    if (pending.get("request_id") != request_id or
            pending.get("packet_sha256") != packet_sha256 or
            pending.get("contract_sha") != contract_sha):
        raise PreflightBlocked("PENDING_BINDING_CHANGED")
    if pending.get("dispatched") is not False or pending.get("consumed") is not False:
        raise PreflightBlocked("PENDING_ALREADY_USED")
    # Distinct commits are allowed only when their committed contract text is
    # byte-identical. The immutable request, packet hash and contract SHA are
    # retained, not regenerated or replaced. A real contract change fails closed.
    contract_current = _committed(repo, trusted_sha, audit.CONTRACT_PATH)
    if _git(repo, "show", f"{contract_sha}:{audit.CONTRACT_PATH}") != contract_current:
        raise PreflightBlocked("REQUEST_CONTRACT_VERSION_SKEW")
    now = datetime.now(timezone.utc)
    prepared_at = _utc(pending.get("prepared_at"))
    # GitHub timestamps are second-resolution; wait locally rather than burning
    # the sole immutable delivery on a same-second/future timestamp mismatch.
    if (now - prepared_at).total_seconds() < 1:
        raise PreflightBlocked("PREPARATION_BOUNDARY_NOT_SETTLED")
    try:
        lease.validate(record)
    except (ValueError, TypeError):
        raise PreflightBlocked("LEASE_SCHEMA_INVALID") from None
    if record.get("state") != "active":
        raise PreflightBlocked("LEASE_NOT_ACTIVE")
    updated_at, expiry = _utc(record.get("updated_at")), _utc(record.get("expires_at"))
    if updated_at > now:
        raise PreflightBlocked("LEASE_TIMESTAMP_IN_FUTURE")
    if (expiry - now).total_seconds() < minimum_lease_seconds:
        raise PreflightBlocked("LEASE_RENEWAL_REQUIRED")
    if not record.get("holder", "").startswith("/root/a0_"):
        raise PreflightBlocked("LEASE_HOLDER_NOT_A0")

    # Run the SAME reader and writer, not a similar schema-only approximation.
    # This synthetic context has no authority outside this offline rehearsal.
    with tempfile.TemporaryDirectory(prefix="tariff-a6-preflight-") as temp:
        root = Path(temp)
        owner = lease.REPOSITORY.split("/", 1)[0]
        event = {"action": "created", "repository": {"owner": {"login": owner},
                 "default_branch": "main"}, "sender": {"login": owner},
                 "issue": {"number": audit_bridge.COMMENT_ISSUE},
                 "comment": {"id": 1, "body": audit_bridge.COMMENT_COMMAND,
                             "author_association": "OWNER", "user": {"login": owner}}}
        event_path = root / "offline-event.json"
        event_path.write_text(json.dumps(event), encoding="utf-8")
        env = {"GITHUB_EVENT_NAME": "issue_comment", "GITHUB_EVENT_PATH": str(event_path),
               "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": trusted_sha,
               "GITHUB_RUN_ID": "1", "GITHUB_REPOSITORY": lease.REPOSITORY,
               "A6_STATE_ROOT": str(state_root), "A6_STATUS_PATH": str(state_root / STATUS_PATH),
               "A6_LEASE_PATH": str(state_root / LEASE_PATH)}
        try:
            resolved = audit_bridge.resolve(repo, output=root / "resolved.json", environ=env)
            audit_bridge.prepare(
                repo, request_id=request_id, base=resolved["base_sha"], head=resolved["head_sha"],
                contract=resolved["contract_sha"], paths_json=resolved["paths_json"],
                sources_json=resolved["official_sources_json"], output=root / "packet.json",
                environ=env, fetch=False)
            written = (root / "packet.json").read_bytes()
            packet = json.loads(written)
            audit.validate_packet(repo, packet, environ=env)
        except (OSError, ValueError, KeyError, TypeError, runtime.RuntimeBlocked):
            raise PreflightBlocked("BRIDGE_REHEARSAL_FAILED") from None
        canonical = audit_bridge._canonical(packet)
        canonical_hash = hashlib.sha256(canonical).hexdigest()
        recorded_canonical = pending.get("serialized_canonical_sha256")
        if recorded_canonical is not None and recorded_canonical != canonical_hash:
            raise PreflightBlocked("SERIALIZED_PACKET_BINDING_CHANGED")
        if (_committed(state_root, state_sha, STATUS_PATH) != state_raw or
                _committed(state_root, state_sha, LEASE_PATH) != lease_raw or
                _git(state_root, "rev-parse", "HEAD").decode().strip() != state_sha):
            raise PreflightBlocked("STATE_CHANGED_DURING_PREFLIGHT")
        if _git(repo, "rev-parse", "HEAD").decode().strip() != trusted_sha:
            raise PreflightBlocked("TRUSTED_CHECKOUT_MOVED")
        for filename in CODE_FILES:
            _committed(repo, trusted_sha, "tools/tariff_agents/" + filename)
        if _committed(repo, trusted_sha, audit.CONTRACT_PATH) != contract_current:
            raise PreflightBlocked("REQUEST_CONTRACT_VERSION_SKEW")
        if (expiry - datetime.now(timezone.utc)).total_seconds() < minimum_lease_seconds:
            raise PreflightBlocked("LEASE_RENEWAL_REQUIRED")
        result = {"status": "PREFLIGHT_PASSED_NOT_AUTHORIZATION", "request_id": request_id,
                  "packet_sha256": packet_sha256, "contract_sha": contract_sha,
                  "trusted_code_sha": trusted_sha,
                  "state_sha": state_sha, "delivery_generation": resolved["delivery_generation"],
                  "lease_generation": resolved["lease_generation"], "lease_expires_at": record["expires_at"],
                  "canonical_packet_sha256": canonical_hash, "canonical_packet_bytes": len(canonical),
                  "written_packet_bytes": len(written), "trusted_helper_sha256": fingerprints,
                  "synthetic_context": True, "provider_called": False, "credentials_read": False,
                  "export_authorized": False, "dispatch_created": False,
                  "delivery_ledger_check": "REQUIRED_FROM_LIVE_GITHUB_IMMEDIATELY_BEFORE_DISPATCH"}
        result["preflight_sha256"] = hashlib.sha256(audit_bridge._canonical(result)).hexdigest()
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--trusted-sha", required=True)
    parser.add_argument("--state-sha", required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--packet-sha256", required=True)
    parser.add_argument("--request-contract-sha")
    args = parser.parse_args(argv)
    try:
        result = check(args.repo, args.state_root, trusted_sha=args.trusted_sha,
                       state_sha=args.state_sha, request_id=args.request_id,
                       packet_sha256=args.packet_sha256,
                       request_contract_sha=args.request_contract_sha)
    except PreflightBlocked as exc:
        print(json.dumps({"status": "PREFLIGHT_BLOCKED", "reason_code": str(exc),
                          "provider_called": False, "dispatch_created": False}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
