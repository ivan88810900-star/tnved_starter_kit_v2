# TASK: Payment admission, arithmetic consistency and source-evidence safeguards

Status: Implementation complete and independently approved, 2026-09-12.
Publication requires successful CI on the integrated commit. PR #187, issue #188 Option A.
This closes the bounded technical task below; full legal rates/NTM coverage is partial.

## Completed scope

- A shared no-positive-grant interface separates parsing and evidence from permission to write legal rates. Six legacy apply services, generic JSON/CSV/XML/XLSX/feed writers, TWS, AI extraction, Tamdoc approval, backfill and identified rate-maintenance CLIs reject unreviewed rate writes before database/provider/destructive work.
- Rate-bearing mixed catalog bundles and rates/rows/data aliases are rejected atomically. Catalog-only preparation and explicit isolated structural fixtures remain. Strict JSON rejects duplicate, non-finite, extreme and recursive inputs without recording false freshness.
- Failed apply operations preserve genuine parsing failures and do not mutate SourceStatus or invalidate the application preview-cache revision. Normalization/coverage retain technical counts without promoting URL, revision or legacy row markers into legal review.
- AI extraction retains unreviewed evidence; optional diagnostic SQLite snapshots use bounded descriptor reads and in-memory deserialization, reject unsafe paths/sidecars, and never open the source through SQLite.
- Legacy NTM candidates retain unresolved code, date, direction, country, exclusion and malformed-field context. Unknown countries cannot mean all countries; code-only and legacy definite markers do not authorize mandatory-document checks.
- A6 reconciliation fixes nonneutral/invalid preference coefficients, unresolved cross-store antidumping overlap and displayed-cent reconciliation. Regression tests cover every confirmed defect; legal/review guards remain.
- Observed-source capture retains distinct original/quarantine receipts, validates SHA identities, inspects actual discovered links, and bounds optional native PDF extraction. Two named review-only plans contain nine and two disjoint targets; successful prior captures are reused.

## Independent acceptance evidence

A5 tested developers' code independently, including 107 admission/history cases,
20 additional A6 cases and 43 real HTTP requests to an isolated Uvicorn application.
Temporary database rows and cache state stayed unchanged on rejected operations.

- Combined A5 commit: `d300f92e697a448efe71a41ad1971f9884ed6b04`.
- [Focused QA 34716890248](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/34716890248): 1,968 passed, 1 known skipped, 2 warnings, 85 subtests.
- [A5 full CI 34716890270](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/34716890270): backend profile 5,113 passed, 2 known skipped, 2 warnings, 85 subtests; frontend 50, TypeScript, build, staging smoke and workflow contracts passed.
- A3's subsequent disjoint two-target/native-inspection change: `a1ce31b25c9dc03793804a98962b0804ecbf2158`; CI 34716832650 and focused 34716832672 (161 passed) passed.
- A6 defects were demonstrated against the unchanged payment engine: 16 failing author regressions in 34716429404, then all 1,273 focused cases passed in 34716718914. A5 independently supplied 20 additional cases.
- Final integration preserves the expanded CI profile and adds both A6 suites. Its own commit checks and PR #187 record the publication gate; component CI above is not a claim that the final assembly has already passed.

Exact scope, inputs and results: [independent evidence](evidence/payment-admission-independent-qa-20260912.json),
[A6 findings](A6_PAYMENT_AUDIT_RECONCILIATION.md), [A2 review](A2_NTM_ADMISSION_REVIEW.md),
[AI boundary](AI_NORMATIVE_ADMISSION.md), [recovery log](REMOTE_EXECUTOR_RECOVERY_20260912.md).

## Original-source result

Capture 34716176823 retained 2 original bodies and 7 quarantined bodies.
Capture 34717159548 retained the Decision 12 PDF and a quarantined card.
Both acquisition runs deliberately remain failed because original completeness
is false; their inspectors/uploads succeeded. Every response body and receipt is
retained and rehashed. Restorable backups do not attest legal retention.

A3 and A5 independently read retained Decisions 12 and 4 and the AD30 notice.
Literal products, producer names/addresses, printed rates and relative-date
clauses are recorded separately from quarantined card metadata. The chain
12 → 4 → 121 is source evidence, not an approved current interval or rate.
See [capture nine](evidence/eec-ad30-capture-34716176823.json),
[Decision 4 / notice](evidence/eec-ad30-decision4-notice-review-20260912.json) and
[Decision 12 / chain](evidence/eec-ad30-decision12-capture-review-20260912.json).

Current configuration has 49 registry entries, 49 policies and 72 default monitor
URLs. Eleven isolated review targets are outside that registry/policy coverage.
These are technical counts, not confirmed legal completeness.

## Remaining work outside this completed task

- Full ETT note/dependent-act interpretation and manifest-bound temporal rules; the saved 111C candidate covers four codes and only [2026-09-08, 2026-09-09).
- Complete VAT/excise/remedy/preference/origin applicability, source-bound specific-duty units and a complete public historical-payment contract. Unsupported public as_of remains rejected.
- Formal review candidate for the retained Decision 12 → 4 → 121 chain, verified amendment inventory, nomenclature and effective intervals. No numeric rule is admitted by a visual source reading.
- Full product-specific NTM applicability/exceptions, including quota sections 2.27/3.1/3.2 and legally applicable GOST/marking requirements; nine advisory families do not establish full legal coverage.
- Legacy diagnostic invoice_analyzer VAT override/Excel output remains outside the canonical grounded-payment guarantee; the bounded read-only call-graph audit is documented in AI_NORMATIVE_ADMISSION.md.
- Versioned durable object storage with attested retention/legal hold, manifest-bound human review and separate approval before any positive grant. DM-0014 concerns that future authorization, not a hold on technical preparation.
- Existing Python rounding convention is unchanged; cent reconciliation does not establish a new legal declaration-rounding policy.

No merge/deployment, production/application DB mutation, rollout or flag activation
is part of this task. Main remains `9712c7b`; PR #189 stays separate and inactive.
