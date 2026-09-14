# TASK-PAYMENT-A6-STAGE2-001

Status: IN_PROGRESS. Started 2026-09-14 under Ivan's explicit stage-2 audit request.

## Goal and current state

Independently reproduce the supplied A6 findings in actual execution, classify
their origin and meaning, repair confirmed technical payment defects through
A1, and obtain independent A5 regression/integration and exact published CI.
This is a user-prioritized correction of the existing payment path; the completed
AD30 candidate is preserved and is not being rebuilt.

GitHub recovery and clean root HEAD: `dab1f8aae5a114a51505763bf9ea0a0d8161ed38`.
PR #187 remains draft/open/unmerged, feature `feat/ntm-official-full-contours`
to `feat/canonical-read-path`, base `a5a811e618ffa001b39cb491bbbf7a9ceb93f9a7`.
The existing AD30 final push/PR CI passed at that HEAD. Those earlier results
are not evidence for any new stage-2 fix.

## Findings supplied by the user

IDs below are A6 audit IDs, not ownership-role names.

| A6 ID | Reported scenario to reproduce |
| --- | --- |
| A1 | Unapplied provisional special duty enters raw aggregate/VAT base/total |
| A2 | Pending order gives different status and review-reason interpretations |
| A3 | Legacy coefficient below one reviewed, above one silently applied |
| A6 | Legacy HsRate AD and SpecialDuty AD counted together |
| A9 | Geo override is not selected but suppresses preference review, including on base |
| A10 | Fixed legacy AD assumes a unit and multiplies generic quantity |
| A13 | Specific amount uses hardcoded EUR/USD fallback without date/provenance/review |
| A11 | Empty AD country scope treated as worldwide |
| A12 | Missing specific_amount yields zero with OK |
| Additional | HsRate dates ignored, as_of=None failure, cents mismatch, combined/specific status gaps |

Final categories: confirmed blocker, inherited blocker, intentional conservative
behavior, false positive at the current HEAD. Previously fixed A3/A6/cents and
previously documented provisional/date boundaries are executed again as scoped
regressions; their old conclusions are not accepted merely by authority.

## Actual agents, isolation and ownership

All new worktrees were created from the actual HEAD above. A read-only detached
base worktree at `a5a811e6` permits execution comparisons without changing base.
The older completed A1–A4 worktrees remain intact. No independent ongoing A2/A3
implementation was interrupted. Three active children at most; A3's bounded
source audit can finish while A1 and A5 continue execution.

| Agent | Branch / worktree basename | Owned files |
| --- | --- | --- |
| A0 | Current feature / tariff-sept14 | This task, state/focus/decisions, CI integration and publication evidence |
| A1 Rates | agent/rates-a6-stage2-20260914 / tariff-a6-stage2-a1 | app/services/payment_engine.py, payment_quote_service.py; app/schemas/payment_quote.py; minimal app/api/calculator.py FX propagation; new tests/test_payment_a6_stage2.py and docs/ai-workflow/A6_PAYMENT_STAGE2_RECONCILIATION.md |
| A3 Sources | agent/sources-a6-stage2-20260914 / tariff-a6-stage2-a3 | New docs/ai-workflow/A6_STAGE2_SOURCE_BOUNDARIES.md only; no source or feature mutations |
| A5 QA | agent/qa-a6-stage2-20260914 / tariff-a6-stage2-a5 | New tests/test_payment_a6_stage2_redteam.py and docs/ai-workflow/evidence/payment-a6-stage2-independent-qa-20260914.json only |

App/script/test paths are relative to `customs-clear/backend/`; docs are
repository-relative. Existing tests may change only through explicit A0 scope
agreement when an obsolete assertion conflicts with a documented correction;
no test or review guard is weakened to obtain green CI. Feature repairs belong
to A1, never A5. Small logical commits precede independent review/integration.

## Corrective contract and source boundaries

- Preserve the distinction between raw provisional arithmetic and a final quote.
  Neither an amount nor a source marker establishes legal approval. Verify
  applied/status/reason invariants in both raw and product-facing consumers.
- A geo candidate cannot silently authorize a replacement or suppress review
  of a legacy coefficient. Unknown replacement/cumulation remains explicit.
- Legacy fixed AD lacks currency/unit/denominator in its schema. Quantity or
  free text cannot fill that source gap. Empty countries do not mean worldwide.
- Missing/invalid required specific or combined operands never establish a
  zero duty or a final amount. Existing current money/display conventions remain;
  no new statutory rounding policy is selected here.
- A numeric FX map supplies no source/date authorization. CBR ingestion already
  normalizes Value/Nominal to RUB per one foreign unit. Global source metadata
  and matching timestamps do not bind mutable current rows to the original XML.
  Foreign conversion can remain an explicit provisional estimate, with review
  and unavailable final amounts; RUB-to-RUB one is a unit identity.
- Populated invalid/future/expired HsRate date bounds cannot be ignored when
  publishing confirmed dependent components. Checking a claimed interval is not
  approval of complete historical law or missing-date records.
- Null as_of can be treated as no historical-date request if implemented
  consistently; all non-null historical requests, including malformed values,
  must continue to fail closed. This does not add a historical payment API.
- No new FX ingestion, models/migrations, source acceptance, legal rule,
  enforcement, Canonical activation, production DB write, merge or deploy.
  The adjacent currency-display mirror label is documented separately and is
  not silently claimed as repaired by the payment correction.

## Required execution and acceptance

1. Author red reproductions and independent A5 execution on current/base code,
   using synthetic temporary databases and real compute/quote calls.
2. Regressions for at least applied/special-duty invariant, coefficient >1,
   AD overlap, geo override, geo plus preference, fixed AD unit, unverified FX,
   as_of=None, missing specific_amount and expired hs_rates.
3. Additional malformed/empty scopes, future/boundary dates, unknown units,
   combined-rate paths and final/partial/status consistency where implicated.
4. Owner fixes followed by independent A5 hostile regressions and real isolated
   HTTP integration. No production or existing application DB may be accessed.
5. Preserve existing CI suites and add new ones; backend profile, frontend,
   types/build, local staging and workflow contracts on exact published HEAD.
6. Record A6 classification, red/green evidence, remaining scope limitations,
   commit identities, independent approval and actual CI in docs and PR #187.

Local executor briefly disconnected during environment preparation, then
recovered with the same clean repository. Declared backend dependencies are now
installed in the shared isolated test venv. No unexecuted scenario is described
as reproduced, and no old CI result is reused as proof of new behavior.
