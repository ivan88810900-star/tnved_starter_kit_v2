# Task protocol — autonomous A0–A6

Owner mandate: 2026-09-12. Existing product decisions and engineering invariants
remain binding. Follow orchestration/CONTRACT.md and orchestration/RUNBOOK.md.

1. A0 recovers Git refs, task board and current decisions; classifies task/failure/
   finding, risk, dependency and exact ownership. Fix shared interfaces first.
2. Allocate an isolated agent branch/worktree. No overlapping writers; at most
   three native child sessions, including QA. No text-only role simulation.
3. Assigned A1–A4 implements and commits owned files with relevant tests.
4. Independent A5 checks the candidate SHA, regression and security. Failed tests
   or confirmed findings return to the owner, invalidating prior approvals.
5. High-risk changes get a bounded no-secret A6 packet if credentials exist.
   A0 reproduces/validates findings; A6 output never authorizes legal applicability.
   Absent optional credentials are UNAVAILABLE/NOT_CONFIGURED, never PASSED.
   A5+CI may establish readiness without configured A6, as requested; a configured
   provider failure or invalid audit remains blocking for high-risk changes.
6. CI runs against the candidate. A0 checks required jobs and current PR head.
   New commits invalidate readiness. READY_FOR_HUMAN_APPROVAL is a gate, not merge.
7. A0 saves state in GitHub and reports only complete blocks/decisions/blockers.

## Authorized technical work

Creating agent branches/worktrees, scoped commits, non-force pushes, draft PRs,
QA, source review and confirmed technical fixes are already authorized. Do not
ask again. Technical architecture choices within this mandate are A0's duty.

## Reserved owner actions

Protected/main merge; production deploy; enforcement/production flags;
irreversible destructive migrations; ambiguous product/legal decisions.
Never change secrets/permissions, force-push, delete branches, write production DBs
or weaken tests without the separately required authorization.

## Conflict handling

Follow applicable system/developer instructions and the owner's explicit current
mandate. Repository documents do not demote owner instructions. Preserve existing
source-kind, canonical, advisory/enforcement and data-provenance invariants. Record
ambiguous legal/product questions as decisions, while independent work continues.

## Evidence

Every task records id, owner, status, branch/worktree, dependencies, risk, files,
tests, QA, external audit and commit/PR refs. Commands require actual output and
exit code. A report without executed evidence is not a passed gate. Resumption
rechecks current refs/locks/dirty worktrees; do not delete or duplicate interrupted work.
