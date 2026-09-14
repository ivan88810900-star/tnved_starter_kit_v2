# TASK-AD30-EXECUTABLE-REVIEW-001

Status: IN_PROGRESS. Started 2026-09-14 under Ivan's current PR #187 mandate.

## Goal and factual starting point

Produce an executable, isolated review of the retained AD30 Decision 12 → 4 → 121
source candidate: exact source-record integrity, explicit product conditions,
and exact hypothetical arithmetic for an explicitly selected printed source row.
This prepares review; it cannot determine current legal liability or admit rates.

GitHub PR #187 remains at `a9d15c74699c8cd7842404580ff6fd7bd957e9eb`,
base `a5a811e618ffa001b39cb491bbbf7a9ceb93f9a7`; main remains `9712c7b`.
The repeated eight A6 findings are already reconciled there. The engine and both
regression suites match their approved blobs; do not repeat those fixes.

Later work is reused, not restarted: PR #191 has the independently checked
dynamic agent-branch CI matcher and current admission report; PR #192 has the
bounded source-fact document at `5bff4523ec20f7a29fe6f7b997ffccfc479c9bff`.
This task does not recreate either report or recapture preserved source originals.

The separate coordination candidates #190/#193 and their runtime-state branch
are inspected read-only. Their old lease and incomplete session record are not
cleared or presented as completed. Their owned files are outside this task.
Existing local product/source/infrastructure worktrees were inspected without
modification; the five inspected worktrees were clean.

## Actual native agents and exclusive ownership

All new worktrees start at the actual PR #187 HEAD above. At most three children
work simultaneously; A5 starts independently after a developer hands off.

| Agent | Branch / worktree basename | Exclusive new files |
| --- | --- | --- |
| A0 | agent/ad30-integration-20260914 / tariff-sept14 | This task, current state/focus/decisions, integration evidence and CI selection |
| A1 /root/a1_rates | agent/rates-ad30-20260914 / tariff-sept14-a1 | app/services/ad30_duty_preview.py; scripts/preview_ad30_candidate.py; tests/test_ad30_duty_preview.py; tests/test_ad30_candidate_cli.py |
| A2 /root/a2_ntm | agent/ntm-ad30-20260914 / tariff-sept14-a2 | app/services/ad30_applicability.py; tests/test_ad30_applicability.py; docs/ai-workflow/AD30_APPLICABILITY_REVIEW.md |
| A3 /root/a3_sources | agent/sources-ad30-20260914 / tariff-sept14-a3 | app/services/ad30_source_facts.py; app/data/official_sources/ad30_source_facts_v1.json; tests/test_ad30_source_facts.py; docs/ai-workflow/AD30_SOURCE_FACT_DOSSIER.md |
| A5 | Assigned after handoff | Independent tests and review evidence only; never feature repairs |
| A4 | Waits for stable interfaces | No feature implementation assigned |

Application/script/test paths in this table are relative to `customs-clear/backend/`.
Documentation paths are repository-relative. Worktrees live under the current
task workspace, separate from earlier sessions. A0 owns CI changes and may reuse
the already reviewed PR #191 matcher; original PR/state/ownership records stay intact.

## Frozen interfaces

1. A3: `load_ad30_source_facts(repository_root=None)` returns an immutable
   `AD30SourceFacts` dossier. `validate_ad30_source_facts(bundle)` rejects forged
   or replaced values by checking pinned source-record identities, exact JSON
   pointers and values. Source-record integrity is distinct from original PDF
   replay, native-text verification, legal interpretation and retention.
2. A2: `assess_ad30_candidate(as_of, facts, source_facts=None)` returns
   `matches_source_candidate`, `outside_source_candidate` or `needs_clarification`,
   with each criterion's source basis. It validates a supplied source DTO again.
   All results keep legal applicability unavailable. An outside result concerns
   only the printed source candidate; it is never a global no-duty finding.
3. A1: `preview_ad30_duty(as_of, facts, source_row_id, customs_value, currency,
   source_facts=None)` recomputes A2 assessment, accepts no supplied approval or
   applicability result, and calculates only for a fully matched literal product
   candidate and an explicitly selected source row. It reuses `ETTDuty` and
   `ett_duty_preview.preview_duty`; no new money/rounding engine is introduced.

Callable inputs are keyword-only. Public dates are explicit `date` objects;
the CLI accepts strict ISO date text. Exact dimensions are explicitly in mm.
Money is bounded exact decimal/integer input; no float/bool coercion. The CLI
uses bounded strict JSON, produces review output, and never starts the application,
fetches sources, opens a database, writes rates or changes runtime configuration.

## Safety and source interpretation

- A3 records literal text or explicitly labelled prior visual observations.
  English observations are not represented as native Russian PDF extraction.
- A2 formalizes a review candidate using code AND description, origin/import
  direction, welded/stainless/tubular facts and explicitly declared shape/dimensions.
  No unit conversion, inferred perimeter, shape-to-code mapping or free-text
  producer identification is permitted.
- Missing, malformed, unknown-country and contradictory facts remain explicit.
  A bounded country-identity set is a technical limitation, not a legal exclusion.
- A1 row IDs `foshan_vinmay`, `guangdong_sumwin`, `other_producers` identify
  hypothetical operands. Unknown producer never automatically selects “прочие”.
- Explicit `as_of` is retained but never supplies missing amendment/history or
  authoritative effective intervals. Printed date clauses are not approved law.
- Legal review, producer identity/succession, nomenclature history, complete
  amendment inventory, retention, final payable, promotion and active-rate writes
  remain unverified/false. Successful arithmetic does not remove these limitations.
- No live payment API, DB model, NTM enforcement, source baseline or AI consumer
  is changed by the isolated candidate. No merge/deploy/production DB/flag action.

## Acceptance

- Author tests cover source corruption/forgery, every dimensional boundary,
  missing/invalid/contradictory facts, explicit dates, unknown origin/row, exact
  arithmetic and fixed review-only status.
- A5 independently reconstructs source bindings and attacks the complete CLI
  path, including tampering, numeric edge cases and absence of database/network
  side effects. Feature defects go back to their owners.
- Integration preserves the existing CI suites and adds explicit new tests.
  Backend CI, frontend/tests/types/build, workflow contracts and local staging
  smoke must pass on the exact published candidate.
- A4 may review the stable output contract for grounded consumption; no duplicate
  domain logic or live feature activation is introduced.
- Current state, decisions, PR description and exact commit/QA/CI evidence are
  updated. Completing this task does not claim complete legal rates/NTM coverage.

## Evidence

Pending implementation and independent QA. Historical passing CI for `a9d15c74`
is not evidence for the new candidate. Optional external A6 is not claimed to
have audited this task; user-supplied A6 findings remain independently evaluated.
