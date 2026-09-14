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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='.')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('init', 'validate', 'validate-snapshot', 'recover', 'status'):
        sub.add_parser(name)
    add = sub.add_parser('add')
    add.add_argument('task_id')
    add.add_argument('--owner', choices=['A1', 'A2', 'A3', 'A4', 'A5'], required=True)
    add.add_argument('--file', action='append', required=True)
    add.add_argument('--dependency', action='append', default=[])
    add.add_argument('--risk', choices=['low', 'high'], default='high')
    add.add_argument('--goal', required=True)
    add.add_argument('--required-check', action='append', required=True)
    alloc = sub.add_parser('allocate')
    alloc.add_argument('task_id')
    alloc.add_argument('--base-sha', required=True)
    args = parser.parse_args()
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
