#!/usr/bin/env bash
# Thin wrapper around run_cursor_task_from_issue.py (used by GitHub Actions).
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "${REPO_ROOT}"
export ISSUE_CONTEXT_PATH="${ISSUE_CONTEXT_PATH:-issue-context.json}"
exec python3 scripts/automation/run_cursor_task_from_issue.py
