"""Trusted GitHub Actions bridge for the commit-bound Claude A6 adapter.

This module is intentionally small.  It never checks out or executes candidate
code: ``prepare`` fetches exact commit objects and asks :mod:`audit` to build the
packet, while ``run`` revalidates that packet from Git before the only provider
call.  Its receipt is advisory evidence for A0, never an audit approval.
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

from . import audit
from .runtime import RuntimeBlocked


class BridgeBlocked(RuntimeBlocked):
    pass


SHA_RE = re.compile(r"[0-9a-f]{40}")
REQUEST_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")
MAX_INPUT_JSON_BYTES = 20_000
DISPATCH_ACTION = "tariff-a6-live"
PAYLOAD_FIELDS = frozenset({"request_id", "base_sha", "head_sha", "contract_sha",
                            "paths_json", "official_sources_json"})


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha256(value):
    return hashlib.sha256(value).hexdigest()


def _exact_sha(value, label):
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise BridgeBlocked(f"{label} must be an exact 40-character commit SHA")
    return value


def _request_id(value):
    if not isinstance(value, str) or not REQUEST_RE.fullmatch(value):
        raise BridgeBlocked("Invalid A6 request id")
    return value


def _json_list(raw, label):
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_INPUT_JSON_BYTES:
        raise BridgeBlocked(f"Invalid {label}")
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        raise BridgeBlocked(f"Invalid {label}") from None
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise BridgeBlocked(f"Invalid {label}")
    return value


def validate_trusted_context(repo, *, environ=None):
    """Require the narrow dispatch running workflow code from the default branch."""
    env = os.environ if environ is None else environ
    if env.get("GITHUB_EVENT_NAME") != "repository_dispatch":
        raise BridgeBlocked("A6 live bridge only accepts repository_dispatch")
    event_path = env.get("GITHUB_EVENT_PATH", "")
    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
        default_branch = event["repository"]["default_branch"]
        action = event["action"]
        payload = event["client_payload"]
    except (OSError, ValueError, KeyError, TypeError):
        raise BridgeBlocked("Default branch evidence is unavailable") from None
    if (action != DISPATCH_ACTION or not isinstance(payload, dict) or
            set(payload) != PAYLOAD_FIELDS or
            any(not isinstance(value, str) for value in payload.values())):
        raise BridgeBlocked("Invalid A6 repository dispatch payload")
    if (not isinstance(default_branch, str) or not default_branch or
            env.get("GITHUB_REF") != f"refs/heads/{default_branch}"):
        raise BridgeBlocked("Workflow ref is not the repository default branch")
    workflow_sha = _exact_sha(env.get("GITHUB_SHA"), "workflow SHA")
    try:
        checked_out = audit._commit(repo, "HEAD")
    except RuntimeBlocked:
        raise BridgeBlocked("Trusted workflow checkout cannot be verified") from None
    if checked_out != workflow_sha:
        raise BridgeBlocked("Checkout differs from the trusted workflow SHA")
    run_id = env.get("GITHUB_RUN_ID", "")
    if not re.fullmatch(r"[1-9][0-9]{0,19}", run_id):
        raise BridgeBlocked("Invalid workflow run id")
    repository = env.get("GITHUB_REPOSITORY", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}", repository):
        raise BridgeBlocked("Invalid repository identity")
    return {"default_branch": default_branch, "workflow_sha": workflow_sha,
            "workflow_run_id": run_id, "repository": repository,
            "payload": payload}


def _validate_request_binding(context, *, request_id, base, head, contract,
                              paths_json=None, sources_json=None):
    expected = {"request_id": request_id, "base_sha": base, "head_sha": head,
                "contract_sha": contract}
    if paths_json is not None:
        expected["paths_json"] = paths_json
    if sources_json is not None:
        expected["official_sources_json"] = sources_json
    if any(context["payload"].get(key) != value for key, value in expected.items()):
        raise BridgeBlocked("Command arguments differ from repository dispatch payload")


def fetch_commit_objects(repo, commits):
    """Fetch only named same-repository commit objects, never a candidate ref checkout."""
    clean_env = {key: value for key, value in os.environ.items()
                 if not key.startswith("GIT_")}
    clean_env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                     GIT_NO_REPLACE_OBJECTS="1", GIT_TERMINAL_PROMPT="0")
    for commit in dict.fromkeys(commits):
        _exact_sha(commit, "candidate SHA")
        try:
            result = subprocess.run(
                ["git", "--no-pager", "-c", "core.hooksPath=" + os.devnull,
                 "fetch", "--no-tags", "--no-recurse-submodules", "--depth=1",
                 "origin", commit], cwd=repo, env=clean_env, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=90, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise BridgeBlocked("Exact candidate commit objects could not be fetched") from None
        if result.returncode:
            raise BridgeBlocked("Exact candidate commit objects could not be fetched")
        if audit._commit(repo, commit) != commit:
            raise BridgeBlocked("Fetched candidate commit identity mismatch")


def _write_exclusive(path, value, *, environ=None):
    raw = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True,
                     allow_nan=False) + "\n"
    audit.ensure_safe_text(raw, environ={} if environ is None else environ)
    target = Path(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(target, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(raw)
    except Exception:
        try:
            target.unlink()
        except OSError:
            pass
        raise


def prepare(repo, *, request_id, base, head, contract, paths_json,
            sources_json, output, environ=None, fetch=True):
    env = os.environ if environ is None else environ
    context = validate_trusted_context(repo, environ=env)
    _request_id(request_id)
    base, head, contract = (_exact_sha(base, "base SHA"),
                            _exact_sha(head, "head SHA"),
                            _exact_sha(contract, "contract SHA"))
    paths = _json_list(paths_json, "paths JSON")
    sources = _json_list(sources_json, "official sources JSON")
    _validate_request_binding(context, request_id=request_id, base=base, head=head,
                              contract=contract, paths_json=paths_json,
                              sources_json=sources_json)
    if fetch:
        fetch_commit_objects(repo, (base, head, contract))
    packet = audit.build_packet(repo, base, head, paths, contract_ref=contract,
                                official_sources=sources, environ=env)
    if (packet["base_sha"] != base or packet["head_sha"] != head or
            packet["contract"]["resolved_commit"] != contract):
        raise BridgeBlocked("Prepared packet has invalid commit binding")
    _write_exclusive(output, packet, environ=env)
    return {"status": "PACKET_BUILT", "request_id": request_id,
            "base_sha": base, "head_sha": head,
            "packet_sha256": packet["packet_sha256"]}


def _receipt(context, request_id, packet, result, bridge_status, reason_code=None):
    value = {
        "schema_version": 1,
        "bridge_status": bridge_status,
        "audit_status": result.get("status", "BLOCKED"),
        "live_verified": bridge_status == "LIVE_VERIFIED",
        "advisory_only": True,
        "a0_validation": "PENDING",
        "request_id": request_id,
        "repository": context["repository"],
        "workflow_run_id": context["workflow_run_id"],
        "trusted_workflow_sha": context["workflow_sha"],
        "base_sha": packet["base_sha"],
        "head_sha": packet["head_sha"],
        "contract_sha": packet["contract"]["resolved_commit"],
        "packet_sha256": packet["packet_sha256"],
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "provider_message_id": result.get("message_id"),
        "model": result.get("model"),
        "findings": result.get("findings", []),
        "limitations": result.get("limitations", []),
    }
    if reason_code:
        value["reason_code"] = reason_code
    value["receipt_sha256"] = _sha256(_canonical(value))
    return value


def run(repo, *, request_id, base, head, contract, packet_path, receipt_path,
        environ=None):
    env = os.environ if environ is None else environ
    context = validate_trusted_context(repo, environ=env)
    _request_id(request_id)
    base, head, contract = (_exact_sha(base, "base SHA"),
                            _exact_sha(head, "head SHA"),
                            _exact_sha(contract, "contract SHA"))
    _validate_request_binding(context, request_id=request_id, base=base, head=head,
                              contract=contract)
    try:
        raw = Path(packet_path).read_bytes()
        if len(raw) > audit.MAX_PACKET_BYTES * 2:
            raise BridgeBlocked("Packet input exceeds the hard bound")
        packet = json.loads(raw)
        packet = audit.validate_packet(repo, packet, environ=env)
        dispatched_paths = sorted(_json_list(context["payload"]["paths_json"],
                                             "paths JSON"))
        dispatched_sources = _json_list(context["payload"]["official_sources_json"],
                                        "official sources JSON")
        if (packet["base_sha"] != base or packet["head_sha"] != head or
                packet["contract"]["resolved_commit"] != contract or
                packet["paths"] != dispatched_paths or
                packet["official_sources"] != dispatched_sources):
            raise BridgeBlocked("Run request differs from packet binding")
        result = audit.run_audit(repo, packet, environ=env)
        valid_live = (
            result.get("status") == "NEEDS_A0_VALIDATION" and
            result.get("live_verified") is True and
            result.get("advisory_only") is True and
            result.get("a0_validation") == "PENDING" and
            result.get("base_sha") == base and result.get("head_sha") == head and
            result.get("packet_sha256") == packet["packet_sha256"] and
            isinstance(result.get("message_id"), str) and
            re.fullmatch(r"[A-Za-z0-9_-]{1,180}", result["message_id"]) is not None and
            isinstance(result.get("model"), str) and
            re.fullmatch(r"[A-Za-z0-9._-]{1,100}", result["model"]) is not None
        )
        if valid_live:
            # Keep the bridge fail-closed even if a future adapter refactor
            # accidentally returns unvalidated findings.
            audit.validate_findings({
                "packet_sha256": result["packet_sha256"],
                "head_sha": result["head_sha"],
                "findings": result.get("findings"),
                "limitations": result.get("limitations"),
            }, packet, environ=env)
            receipt = _receipt(context, request_id, packet, result, "LIVE_VERIFIED")
            exit_code = 0
        elif result.get("status") == "UNAVAILABLE" and result.get("live_verified") is False:
            receipt = _receipt(context, request_id, packet, result, "UNAVAILABLE",
                               "PROVIDER_OR_CONFIG_UNAVAILABLE")
            exit_code = 2
        else:
            receipt = _receipt(context, request_id, packet, {}, "BLOCKED",
                               "INVALID_ADAPTER_RESULT")
            exit_code = 2
        _write_exclusive(receipt_path, receipt, environ=env)
        return receipt, exit_code
    except (OSError, ValueError, KeyError, TypeError, RuntimeBlocked):
        # Do not copy exception text into a durable artifact: it may contain a
        # provider, environment or attacker-controlled value.
        minimal_packet = {
            "base_sha": base, "head_sha": head, "packet_sha256": "0" * 64,
            "contract": {"resolved_commit": contract},
        }
        receipt = _receipt(context, request_id, minimal_packet, {}, "BLOCKED",
                           "INVALID_OR_UNREADABLE_EVIDENCE")
        _write_exclusive(receipt_path, receipt, environ=env)
        return receipt, 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("prepare")
    for command in (build,):
        command.add_argument("--request-id", required=True)
        command.add_argument("--base", required=True)
        command.add_argument("--head", required=True)
        command.add_argument("--contract", required=True)
    build.add_argument("--paths-json", required=True)
    build.add_argument("--sources-json", required=True)
    build.add_argument("--output", required=True)
    live = commands.add_parser("run")
    live.add_argument("--request-id", required=True)
    live.add_argument("--base", required=True)
    live.add_argument("--head", required=True)
    live.add_argument("--contract", required=True)
    live.add_argument("--packet", required=True)
    live.add_argument("--receipt", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            summary = prepare(args.repo, request_id=args.request_id, base=args.base,
                              head=args.head, contract=args.contract,
                              paths_json=args.paths_json, sources_json=args.sources_json,
                              output=args.output)
            print(json.dumps(summary, sort_keys=True))
            return 0
        receipt, exit_code = run(args.repo, request_id=args.request_id, base=args.base,
                                 head=args.head, contract=args.contract,
                                 packet_path=args.packet, receipt_path=args.receipt)
        print(json.dumps({"bridge_status": receipt["bridge_status"],
                          "request_id": receipt["request_id"],
                          "receipt_sha256": receipt["receipt_sha256"]}, sort_keys=True))
        return exit_code
    except (OSError, ValueError, TypeError, RuntimeBlocked):
        print(json.dumps({"bridge_status": "BLOCKED"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
