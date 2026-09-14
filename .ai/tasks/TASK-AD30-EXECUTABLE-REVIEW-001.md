# TASK-AD30-EXECUTABLE-REVIEW-001

Status: IMPLEMENTED_AND_A5_APPROVED; exact publication CI gate remains.
Started 2026-09-14 under Ivan's current PR #187 mandate.

## Goal and factual starting point

Produce an executable, isolated review of the retained AD30 Decision 12 → 4 → 121
source candidate: exact source-record integrity, explicit product conditions,
and exact hypothetical arithmetic for an explicitly selected printed source row.
This prepares review; it cannot determine current legal liability or admit rates.

At recovery, GitHub PR #187 was at `a9d15c74699c8cd7842404580ff6fd7bd957e9eb`,
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
| A5 /root/a5_qa | agent/qa-ad30-20260914 / tariff-sept14-a5 | tests/test_ad30_review_redteam.py; docs/ai-workflow/evidence/ad30-independent-qa-20260914.json |
| A4 /root/a4_ai | agent/ai-ad30-contract-20260914 / tariff-sept14-a4 | docs/ai-workflow/AD30_REVIEW_CONSUMER_CONTRACT.md; documentation only after interfaces stabilized |

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

Implementation and independent A5 review are complete. The same red assertions
reproduced four failures before owner fixes and passed all 28 after them. A5's
final independent suite passed 43 cases, including 15 real CLI processes with
traps for attempted network/DB/write/application-startup side effects. Combined
new author/red-team plus existing ETT arithmetic profile: 449 passed.

A5 independently matched the integrated feature, data, tests and evidence blobs
to its reviewed tree. A4's consumer contract was also independently approved;
no live AI/API integration is claimed. A0 assumed documentation ownership after
A2/A3 handoff to record acceptance without rewriting their historical test runs.

| Work | Author/local commit | Local integration commit |
| --- | --- | --- |
| A3 dossier | 2bfa1799 | 96c771c8 |
| A2 product assessment | b0904fa1 | cd7404db |
| A1 hypothetical arithmetic | f27eae01 | bd151b6f |
| A1 strict CLI | 1c642b89 | 8d371a19 |
| A3 source-label correction | 5c18618c | 182af82b |
| A1 complete row/unit evidence | 9aafade5 | b9774b7f |
| A4 consumer contract | fbdc9397 | b548e27f |
| A5 independent regressions | 5882ce3 / 96141d2e | ab25f165 / 87c6d4ba |
| A5 evidence | 27304a4c | a7abc9a2 |

Author and local integration hashes identify the isolated worktrees. Direct
git push has no credentials in the recovered environment; publication uses the
authorized GitHub Git Data connection. Its commit metadata changes SHAs while
preserving every exact tree/blob and logical commit boundary. The publication
evidence records the local-to-GitHub mapping; local hashes alone are not claimed
as published ancestry.
The dynamic agent matcher from PR #191 is reused; generic agent QA retains all
44 existing files and adds five AD30 suites. Ordinary backend CI also retains
its existing selection and adds the same five suites. No test is weakened.

[Executable reviewer guide](../../docs/ai-workflow/AD30_EXECUTABLE_REVIEW.md),
[independent A5 evidence](../../docs/ai-workflow/evidence/ad30-independent-qa-20260914.json).
Exact assembled/published CI must still be recorded before final completion;
historical green CI for a9d15c74 is not evidence for this candidate. Optional
external A6 is not claimed to have audited this task. The same eight earlier
findings remain independently evaluated in the existing A6 reconciliation.
