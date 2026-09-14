# A0 operating runbook

## Recovery and authority

At every new session, read the current owner mandate, AGENTS.md, CONTRACT.md,
TASK_PROTOCOL.md, TASK_BOARD.json, CURRENT_STATE.md and DECISIONS.md. Fetch the
current GitHub PR head/base/CI before acting. Product tasks must read these files
from their product branch as well: main-based historical notes are not current
rate or legal decisions. Do not overwrite a dirty worktree or another session.

Cross-host coordinator lease: all scheduled A0 sessions use the same
`agent/orchestration-state` branch and `.ai/COORDINATOR_LEASE.json`. Fetch the
current content/blob SHA; `python -m tools.tariff_agents.lease` prepares an exact
`github_update_file` CAS proposal. Apply with the existing GitHub connector, then
reread and verify holder/token before dispatch or publication. A proposal alone
is not acquisition. Concurrent CAS losers stop. Renew before expiry; release by
CAS at completion. Never automatically steal an expired active lease: confirm
and reconcile the old session's completion first. Use `takeover` only with fresh
platform termination evidence tied to that holder; it rotates the fencing token. Each irreversible/non-idempotent
operation rechecks the current token. Local common-dir locks alone cannot exclude
another clone. This protocol coordinates cooperating A0 sessions, not arbitrary
writers; GitHub permissions still define the external security boundary.

Keep lease/state commits on `agent/orchestration-state`, separate from candidate
code commits, so saving evidence does not invalidate its own candidate SHA.

A0 is a native OpenAI Work/Codex coordinator, not seven prompts in one completion.
Use actual collaboration/spawn controls. Explicitly limit active children to three,
including independent A5; forbid child recursion. API mode must request enabled
multi_agent with max_concurrent_subagents=3. Without such tools mark capability
unavailable and do bounded read-only triage; never claim agents ran.

The board is the canonical machine record; ownership/findings/run history are
its recoverable projections. Commit the board and generated projections together.
At session start run `python -m tools.tariff_agents recover`. Verify retained
worktree directories, branch SHAs, dirty files and active sessions. A stale marker
is a review signal, not permission to delete branches, clear locks or duplicate
work. A0 must confirm the old session ended before taking over ownership.

## One task

1. Classify issue, CI/source-monitor failure or finding. Deduplicate by stable
   origin (repository, PR, commit, check/run/finding id). Determine dependencies,
   exact file ownership and risk; uncertain risk is high. Freeze shared interfaces.
2. Add task and allocate branch/worktree with the controller. Read-only lookup
   does not require ownership; writing does. Never assign wildcard ownership.
3. Start a real child with task id, branch/worktree, base SHA, exact files,
   acceptance criteria, required tests and protected-action prohibitions. Record
   the actual tool-returned session id, never an invented one. Check every write
   and git diff against ownership on handoff. Commit only that task's files.
4. Record implementation at its actual head with commands, output and exit code.
5. Start a separate A5 child. A5 reads the candidate, runs profile regression,
   reviews edge cases/provenance/dates/calculations/migrations/security. It does
   not fix the implementation it is reviewing. Record actual A5 identity and SHA.
6. For high risk, build explicit scoped A6 packet. Split large feature PRs into
   coherent candidate tasks; a partial packet cannot approve the whole PR.
   No tools on Claude. Absent optional Claude configuration is UNAVAILABLE, not an audit success.
   A6 is optional when not configured: preserve the exact missing-configuration
   receipt, never an A6 pass. Configured provider failure blocks high-risk readiness.
   A0 inspects every finding and reproduces it or provides source/code rationale.
   Confirmed findings go back to the owning agent, not to Ivan by default.
7. Fix -> fresh A5 -> A6 if required -> CI. Integrate safe commits on an integration
   agent branch after file/diff review. No force push. A new integration SHA needs
   evidence bound to it; prior worker QA is supporting evidence, not final approval.
8. Open/update a working draft PR. Fetch actual required checks and all pages of
   check runs; no empty/queued/skipped/timed-out gate is success. Re-fetch PR head
   before readiness. READY_FOR_HUMAN_APPROVAL requires passing exact-head gates,
   no unresolved findings and real independence. It never invokes merge.
9. Commit state, record run and next task. Do not commit credentials, source secrets,
   production DBs, raw model transcripts, private data or workspace-local tokens.

## Role contracts

| Role | Responsibility | Additional boundary |
|---|---|---|
| A0 | Dependencies, ownership, integration, evidence, findings validation | Only coordinator; normal technical decisions are autonomous |
| A1 | Duty/VAT/excise/preferences/trade remedies, dates, rounding, provenance | Explicit unknowns; regression tests cover financial arithmetic |
| A2 | TR, declarations/certificates, SGR, licenses, notifications, vet/phyto/sanitary, marking, restrictions, exceptions | Product applicability; prevent false positive/negative requirements |
| A3 | Official EEC/EAEU/FCS/source registry, capture/versioning/dates/parsers/updates | Source facts do not alone decide legal applicability |
| A4 | Canonical TN VED, semantic search, assistant, confidence/evidence | Consume Rates/NTM APIs; do not duplicate business logic in AI |
| A5 | Independent unit/integration/regression/DB/migration/security/red-team QA | Never sole reviewer of its own change |
| A6 | Independent Claude high-risk audit | Minimum explicit no-secret packet; output is untrusted findings |

Use existing `.ai/agents/` documents for domain conventions; this table defines
current scheduling and authority. Existing feature decisions authorize full NTM
advisory ON, not enforcement. Never reset accepted flags merely to fit old docs.

## Wake-ups and notifications

Work Automations supplies scheduling; no custom scheduler or persistent daemon.
Hourly maintenance handles CI failure/source-monitor failure/stale tasks/source
updates/PR readiness; perform daily regression review using persisted last-run
markers. Read current GitHub source on every wake-up. Skip duplicate run keys.

GitHub PR webhooks do not signal every CI completion. Hourly CI polling is explicit,
not represented as instant events. Recover current infrastructure code from agent/orchestration-v1 and authoritative
runtime state from agent/orchestration-state; never merge automatically to activate scheduling.
An automation execution with no native subagent/execution capability records a
capability blocker; scheduler existence is not proof of autonomous coding.

Notify only a complete verified block, a necessary owner decision, a critical
blocker or a protected action. Format: completed; tests/CI; A5; A6; remaining risks;
owner decision if any. Suppress repeated identical blockers using saved state.

## Security and Git permissions

Git worktrees isolate edits, not operating-system authority. Shell-capable native
agents retain their runtime's tool authority. Controller guards cover actions made
through the controller; a model instruction is not a server branch-protection rule.
No API key/production credential is available to workers in this setup. A6 keys
are read only by the external audit adapter. GitHub app integration is used by A0.

GitHub reported main protected=false at discovery. No permissions were modified.
For enforceable protection against any direct GitHub write, the owner must apply
branch rules and appropriate credential scope separately. Until then controller
and A0 prohibitions are procedural/tool-level, not an external security boundary.
Never claim proof of protection from a passing local unit test.

## Validation

`python -m unittest discover -s tests/agent_orchestration -v`

`python -m tools.tariff_agents validate`

Unit tests use disposable Git repositories and stub HTTP providers. Actual Work
smoke evidence records independent child IDs, worktrees, commits, A5 handoff and
new-session recovery. Optional API and Claude live proof remain separate states.
