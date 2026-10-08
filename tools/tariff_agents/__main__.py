"""Small operator CLI; native Work/Agents API provides the agent execution loop."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _validate_committed_snapshot(repo: Path) -> dict:
    """Validate the board committed at HEAD without selecting state authority.

    This path is intentionally read-only and is suitable for untrusted/offline
    CI checkouts.  Controller commands continue to require the separately
    bootstrapped state-authority pointer.
    """
    from .control import PolicyError, git, need, validate_board

    size_text = git(repo, 'cat-file', '-s', 'HEAD:.ai/TASK_BOARD.json')
    try:
        size = int(size_text)
    except (TypeError, ValueError):
        raise PolicyError('invalid_snapshot_size') from None
    need(0 <= size <= 8_000_000, 'state_too_large')
    content = git(repo, 'show', 'HEAD:.ai/TASK_BOARD.json')
    try:
        board = json.loads(content)
    except (TypeError, ValueError):
        raise PolicyError('invalid_json_state') from None
    validate_board(board)
    return {
        'valid': True,
        'source': 'HEAD:.ai/TASK_BOARD.json',
        'head_sha': git(repo, 'rev-parse', 'HEAD'),
        'revision': board['revision'],
        'task_count': len(board['tasks']),
    }



def _recovery_status(repo, state_root, code_sha, state_sha, publication_policy):
    """Read committed snapshots without invoking mutable controller recovery."""
    from datetime import datetime, timezone
    from . import control, lease, operations, preflight

    repo, state_root = Path(repo).resolve(), Path(state_root).resolve()
    code_sha, state_sha = preflight._sha(code_sha), preflight._sha(state_sha)
    def check_heads():
        if preflight._git(repo, "rev-parse", "HEAD").decode().strip() != code_sha:
            raise preflight.PreflightBlocked("TRUSTED_CHECKOUT_MOVED")
        if preflight._git(state_root, "rev-parse", "HEAD").decode().strip() != state_sha:
            raise preflight.PreflightBlocked("STATE_CHECKOUT_MOVED")
    check_heads()
    modules = {"__main__.py": Path(__file__), "operations.py": Path(operations.__file__),
               "preflight.py": Path(preflight.__file__), "lease.py": Path(lease.__file__),
               "control.py": Path(control.__file__)}
    code = {}
    for name, loaded in modules.items():
        relative = "tools/tariff_agents/" + name
        raw = preflight._committed(repo, code_sha, relative)
        if raw != loaded.read_bytes():
            raise preflight.PreflightBlocked("EXECUTING_HELPER_VERSION_SKEW")
        code[relative] = raw
    status_raw = preflight._committed(state_root, state_sha, preflight.STATUS_PATH)
    lease_raw = preflight._committed(state_root, state_sha, preflight.LEASE_PATH)
    board_raw = preflight._committed(state_root, state_sha, ".ai/TASK_BOARD.json")
    if len(board_raw) > 8_000_000:
        raise preflight.PreflightBlocked("STATE_FILE_TOO_LARGE")
    board = control.validate_board(json.loads(board_raw))
    result = operations.recovery_status(
        preflight._json(status_raw), preflight._json(lease_raw),
        now=datetime.now(timezone.utc), publication_policy=publication_policy)
    check_heads()
    snapshots = {preflight.STATUS_PATH: status_raw, preflight.LEASE_PATH: lease_raw,
                 ".ai/TASK_BOARD.json": board_raw}
    for relative, original in snapshots.items():
        if original != preflight._committed(state_root, state_sha, relative):
            raise preflight.PreflightBlocked("STATE_SNAPSHOT_CHANGED")
    for relative, original in code.items():
        if original != preflight._committed(repo, code_sha, relative):
            raise preflight.PreflightBlocked("TRUSTED_SNAPSHOT_CHANGED")
    result.update(code_sha=code_sha, state_sha=state_sha,
                  board_revision=board["revision"], task_count=len(board["tasks"]))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='.')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('init', 'validate', 'validate-snapshot', 'recover', 'status'):
        sub.add_parser(name)
    recovery = sub.add_parser('recovery-status')
    recovery.add_argument('--state-root', required=True)
    recovery.add_argument('--code-sha', required=True)
    recovery.add_argument('--state-sha', required=True)
    recovery.add_argument('--publication-policy', choices=['blocked', 'unknown'],
                          default='unknown')
    add = sub.add_parser('add')
    add.add_argument('task_id')
    add.add_argument(
        '--owner',
        choices=['A-CORE', 'A-PRODUCT', 'A1', 'A2', 'A3', 'A4', 'A5'],
        required=True,
    )
    add.add_argument('--file', action='append', required=True)
    add.add_argument('--dependency', action='append', default=[])
    add.add_argument('--risk', choices=['low', 'high'], default='high')
    add.add_argument('--goal', required=True)
    add.add_argument('--required-check', action='append', required=True)
    alloc = sub.add_parser('allocate')
    alloc.add_argument('task_id')
    alloc.add_argument('--base-sha', required=True)
    args = parser.parse_args()
    if args.command == 'recovery-status':
        from .control import PolicyError
        from .preflight import PreflightBlocked
        try:
            result = _recovery_status(args.repo, args.state_root, args.code_sha,
                                      args.state_sha, args.publication_policy)
        except (PolicyError, PreflightBlocked, ValueError, TypeError, OSError, KeyError):
            # Never echo untrusted JSON, tokens or exception messages.
            print(json.dumps({'status': 'RECOVERY_INPUT_INVALID',
                              'remote_write_authorized': False,
                              'external_export_authorized': False}))
            return 2
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    if args.command == 'validate-snapshot':
        result = _validate_committed_snapshot(Path(args.repo).resolve())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    from .control import StateStore
    store = StateStore(Path(args.repo).resolve())
    if args.command == 'init':
        result = store.initialize()
    elif args.command == 'recover':
        result = store.recover()
    elif args.command in ('validate', 'status'):
        result = store.load()
        if args.command == 'validate':
            result = {'valid': True, 'revision': result['revision'], 'task_count': len(result['tasks'])}
    elif args.command == 'add':
        result = store.add_task(args.task_id, args.owner, args.file,
                                dependencies=args.dependency, risk=args.risk,
                                goal=args.goal, required_checks=args.required_check)
    else:
        result = store.allocate(args.task_id, args.base_sha)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
