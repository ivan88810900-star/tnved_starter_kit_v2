# A6 payment audit reconciliation

Date: 2026-09-12. A1 implementation; scoped A5 independent review completed.
No rate, legal rule, manifest, production data, deployment or enforcement is approved.

## Observed GitHub state

The audit was reconciled against actual PR #187 HEAD
`22a7df5590a7442d943d89af285feb1228e80938`, integration candidate
`68530dce424d5c16ea56fa1344715312c546d108`, and A1 maintenance checkpoint
`d66606f83ba3294ccae4752dd61bae44e4800680`. All three had the identical
`payment_engine.py` blob `8d56a3fc33038fa18555420e6c8e56dd3bd156af`.
Thus these findings were checked against code, not assumed true from the external review.

The maintenance checkpoint separately passed Actions 34715919970 (4438 passed,
2 existing skips, 73 subtests) and 34715920010 (1105 passed, 85 subtests).
Those runs do not validate the later A6 corrections.

## Finding classification

| A6 | Classification | Evidence and interpretation |
| --- | --- | --- |
| 1. Unapplied remedy has a provisional amount in totals | Intentional behavior | `_resolve_special_duties` separates computable arithmetic from legal approval; a provisional row has `applied=false`, `legal_review_verified=false`. `compute_payments` marks the raw estimate `REVIEW_REQUIRED`. The quote removes the final payable total and unresolved remedy/dependent VAT amounts. |
| 2. Pending is evaluated before the legal-review reason | Intentional behavior | Applicability/representation issues mean `needs_clarification`; legal review alone means `provisional` with available arithmetic. These are two different axes. Appending `legal_review_unverified` does not make an otherwise computable candidate an approved measure. |
| 3. Upward legacy coefficient is applied automatically | Confirmed inherited admission gap | The earlier discount-only correction deliberately left this path outside its scope; it explicitly did not certify those records. A country-only legacy record lacks shipment/product/date eligibility for an increase as well. Invalid coefficients also crashed or produced an unreviewed `OK`. |
| 4. Invalid origin scope applies to every country | False positive as an application claim | Unknown scope remains visible as an unresolved candidate; `origin_country_scope_unverified` sets `needs_clarification`, `amount=null`, `applied=false`. A known different country is excluded. Visibility of an uncertain code match is not a mandatory measure. |
| 5. Specific remedies are excluded from arithmetic | Intentional fail-closed behavior | The legacy schema lacks a source-bound unit/denominator. Invoice quantity, weight or FX cannot supply that legal basis. The candidate amount is unknown, not a confirmed zero; dependent VAT/final quote remain unavailable. |
| 6. Legacy AD and SpecialDuty AD can be counted twice | Confirmed arithmetic/applicability defect | `_resolve_antidumping` and `_resolve_special_duties` were aggregated without a common source-bound measure identity. Different amounts or act text cannot establish that the two representations are cumulative. |
| 7. Public as_of is rejected while private resolver uses a date | Intentional fail-closed boundary | Public legacy payment APIs do not have historical versions for every rate/fee family and reject explicit dates. The private remedy resolver accepts and validates an explicit date, with today only for callers that supplied none. Full historical payment support remains unfinished. |
| 8. Shown components do not sum to shown total | Confirmed presentation-arithmetic defect | Raw fractions were summed before independently rounding displayed components; a similar mismatch existed between remedy detail amounts and their aggregate. |

Contracts for findings 1, 2, 4, 5 and 7 are already described in
[RATE_SOURCE_FAIL_CLOSED_CORRECTIONS.md](RATE_SOURCE_FAIL_CLOSED_CORRECTIONS.md).
New explicit regressions are in `tests/test_payment_a6_reconciliation.py`:
`test_provisional_arithmetic_is_not_an_applied_or_final_legal_grant`,
`test_unknown_origin_scope_remains_candidate_without_applied_money`,
`test_missing_specific_unit_is_review_and_never_confirmed_zero`, and
`test_date_aware_private_resolver_does_not_enable_unsupported_whole_quote_date`.
The existing `test_payment_special_duty_applicability.py` retains the source,
date, producer/product, overlap, quote, dependent VAT and final-total checks.

## Reproduced failures before changing the engine

Diagnostic commit `d04e964e4158925d043b37157c1b50087b84d39a` changed tests and
the A5-owned workflow only. Actions run
[34716429404](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/34716429404),
job 103614397918, completed with **16 failed, 1257 passed, 85 subtests passed**:

- Nine coefficient cases: increases, specific-duty scaling, malformed values,
  boolean, NaN and infinity. None/string produced TypeError; others could appear final.
- Three cross-store AD cases: the engine added both legacy and structured AD,
  including a scenario with a separate countervailing candidate.
- Four displayed-money cases. At customs value 100.02, duty 10%, VAT 22% and
  synthetic fee 1000, displayed duty 10.00 + VAT 24.20 + fee 1000 was 1034.20
  while total was 1034.21. Two remedy details displayed 5.00 + 3.00 while the
  aggregate displayed 8.01.

All new confirming tests for findings 1, 2, 4, 5 and 7 passed on that unchanged engine.
All fixtures are synthetic, memory-only or dependency-isolated; they are not legal data.

## Corrections

1. Every non-neutral or invalid country coefficient now requires review.
   The original candidate remains visible; invalid numeric fields are represented
   safely with bounded text and a null numeric candidate. Duty stays at its unscaled
   provisional amount, and the quote does not expose final duty/VAT/payable amounts.
   This supersedes the upward-coefficient scope exception in
   [PAYMENT_PREFERENCE_REVIEW_GUARD.md](PAYMENT_PREFERENCE_REVIEW_GUARD.md).
   Neutral, explicit manual and the separate geographic paths retain their existing
   behavior; this does not certify those sources or complete their legal coverage.
2. When both legacy and structured AD candidates may apply, neither is selected
   or treated as cumulative. Both preserve their evidence and unknown amounts.
   `legacy_antidumping_overlap_unverified` marks the ambiguity, legacy AD and
   structured AD are excluded from the explicitly incomplete provisional subtotal,
   and dependent VAT/final quote remain unconfirmed. A distinct remedy family can
   retain its separate provisional estimate.
3. Existing `_round2` component behavior is preserved. Already displayed
   two-decimal monetary amounts are summed using decimal addition for the remedy
   aggregate, VAT base and total. VAT is computed from the reconciled provisional
   base. This is a deterministic display invariant, **not** an approved customs
   declaration rounding rule or a new legal calculation scheme.

## Acceptance and limitations

The red evidence establishes the original defects. Correction commits
`f34c6cca88dfc99f83f1ba69b988ef787af539b5`,
`7babea85d581371a15b16e6d35ad66387c959168` and
`15d5dfc0ec87a37b222113f71fd255a2de65a641` form one sequential chain.

At exact code HEAD `15d5dfc0ec87a37b222113f71fd255a2de65a641`:

- [Focused Actions 34716718914](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/34716718914):
  **1273 passed, 85 subtests passed**, two existing dependency warnings.
  All sixteen pre-fix failures now pass; the documented intentional behavior remains checked.
- [Normal CI 34716718892](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/34716718892):
  **4438 passed, 2 skipped, 73 subtests passed**, two existing dependency warnings;
  frontend tests/types/build, local staging smoke and scheduled-workflow contracts passed.
  The existing skips require live FSA or a separate full integration dataset.
- Independent A5 scoped approval for these A6 corrections: combined QA code
  `d300f92e`, run
  [34716890248](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/34716890248),
  job 103615640155: **1968 passed, 1 known skip, 85 subtests passed**.
  Twenty additional independent cases cover upward/invalid coefficients, cross-store
  AD ambiguity and distinct families, nonmatching origins, exact cents/VAT bases,
  and provisional cents with final quotes unavailable.
- Final combined-tree CI and the PR publication decision belong to A0. These
  scoped approvals do not establish complete legal rate or source coverage.

No new legal source interpretation was needed to remove unsafe admission,
ambiguous double counting or inconsistent display arithmetic. Official rate
coverage, origin/regime eligibility, approved measure identity/cumulation,
specific remedy units, complete historical payment versions and legally reviewed
declaration rounding remain separate unfinished source/architecture work.
The DB-derived ETT remains quarantined, and no positive legal grant was introduced.
