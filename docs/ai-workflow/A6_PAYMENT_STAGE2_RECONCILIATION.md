# A6 payment audit, stage 2

Date: 2026-09-14. Status: owner corrections independently accepted by A5;
exact published candidate CI/admission passed. The historical owner execution
record below is preserved. This document grants no legal applicability or admission.

## Actual execution boundary

A1 ran the same self-contained `tests/test_payment_a6_stage2.py` against actual
PR #187 HEAD `dab1f8aae5a114a51505763bf9ea0a0d8161ed38` and the read-only base
checkout `a5a811e6`. Imports in the diagnostic output identify each checkout's
real `payment_engine.py`. Both call real `compute_payments` and
`build_payment_quote`, with three fresh in-memory ORM tables (`HsRate`,
`HsDutyRule`, `SpecialDuty`). External providers, classification, fees and
unrelated enrichment use explicit synthetic fixtures; no application DB or
network source is accessed. The fee is a synthetic constant 4,924 RUB, not a
verified statutory fee. The usual scenario is code 8501100000, CN, customs
value 1,000,000 RUB, duty 10%, VAT 22%, quantity 20 and insurance 0.

At the unchanged actual HEAD, proposed safety regressions produced **19 failed,
4 passed**. At the base, the identical file produced **22 failed, 1 passed**.
These are intentionally red diagnostic runs, not a claim that existing CI fails.

## Classification and observed results

| Finding | Classification at actual HEAD | Executed observation |
| --- | --- | --- |
| A1/A2: provisional special arithmetic, pending order | Intentional separation, current guards verified | Special amount 50,000 remains provisional; applied/legal flags false, raw REVIEW_REQUIRED, quote remedy/VAT/final unavailable. Base exposed final 407,924/OK. |
| A3: upward coefficient | False positive at actual HEAD; previously fixed | Coefficient 2 retains ordinary duty 100,000 and review. Base doubled duty to 200,000 and final 468,924/OK. |
| A6: cross-store AD overlap | False positive at actual HEAD; previously fixed | Both unresolved AD amounts withheld; quote final unavailable. Base summed 50,000 twice and returned 468,924/OK. |
| A9: geo override/preference interaction | Confirmed inherited defect | Geo 35% plus structured 10% produces duty 100,000 and final 346,924/OK on both checkouts. Coefficients 1, 0.75 and 2 all have the same result; geo presence suppresses preference review despite not replacing the structured duty. |
| A10: fixed legacy AD unit | Confirmed inherited unsupported unit inference | Fixed 100 multiplies universal quantity 20 to 2,000, status applied and final 349,364/OK. With an independently unresolved countervailing row, final is withheld but the AD line still exposes the unsupported amount. |
| A13: foreign specific FX | Confirmed inherited source-confidence defect | Missing EUR uses 100 and computes duty 20,000/OK; missing USD uses 92 and computes 18,400/OK. Explicit map factor 123.45 computes 24,690/OK without source/date proof. |
| A12: missing specific amount | Confirmed inherited incomplete-expression defect | `specific` with missing amount produces duty 0 and final 224,924/OK. Combined max/min with missing specific operand silently use 100,000 and final 346,924/OK. |
| HsRate validity | Confirmed inherited temporal defect | Expired, future and malformed populated bounds all produce final 346,924/OK. No claim is made that a within-window or unbounded legacy row is legally approved. |
| A11: AD origin scope | Confirmed inherited uncertainty defect | Empty scope applies 50,000 globally and returns final 407,924/OK. `ALL` is silently treated as a mismatch; `CN,unknown` applies to CN. Neither establishes a verified scope. |
| Explicit `as_of: null` | Confirmed representation regression under A0's null-is-omitted contract | Actual HEAD raises the unsupported-date error; base equals omission. Every non-null date value remains unsupported. This correction does not enable historical payments. |
| Display rounding | Previously fixed, current regression passes | At value 100.02, displayed duty/VAT/fee sum to 4,958.20, equal to current final. Base returned 4,958.21. Existing rounding policy is unchanged. |

## Corrective boundary

Geo is a review candidate, not permission to replace a rate or suppress a
preference. An unbound fixed-AD unit has no calculable amount. Foreign FX can
only supply a provisional observation until its row/date provenance is proved;
RUB-to-RUB at one is a unit identity. SourceStatus or caller flags alone cannot
grant approval. Stored CBR rows already represent Value/Nominal and must not be
divided by nominal again. Missing expression operands or invalid populated
dates cannot produce confirmed components or final quotes.

Implementation must preserve the already passing A1/A2/A3/A6/rounding guards,
existing non-null historical-date rejection, unavailable dependent VAT and
evidence for all unresolved candidates. Owner corrections, stronger regressions,
independent A5 review and final GitHub CI are required before completion.

## Implemented owner corrections

The test-only diagnostic commit is `290d72a7`. Null handling is separately
corrected by `9698dfc`: null equals omission in the engine, comparison and
`CurrentPaymentRequest`; every non-null value, including false/zero/empty string,
remains rejected. The old test case was retained with its corrected assertion.

The remaining owner change adds `payment_component_review` and `fx_observations`
without treating these metadata as authorization. It retains the existing raw
provisional subtotals for compatibility. An incomplete expression additionally
has `duty_candidate.amount=null` and `calculation_available=false`; invalid
populated HsRate dates retain a separate source/interval review candidate. The
quote withholds each affected component, dependent VAT/base, and final amount.
Foreign invoice conversion also withholds the dependent customs-fee amount/base.
Neither supplied maps nor global source-status markers certify a currency rate;
invalid used factors fail validation instead of becoming one. RUB-to-RUB uses
the unit identity, independent of mutable map values.

Geo metadata stays an unapplied review candidate. It neither substitutes a rate
nor hides a nonneutral coefficient. Two obsolete automatic-geo test expectations
were strengthened with review, ordinary-or-missing duty, false application and
unavailable quote assertions, with A0's approval. Fixed AD no longer assumes RUB
per universal unit. Empty/malformed source-country scope cannot mean worldwide
application or known non-applicability. These checks do not certify the complete
ISO country registry or all historical country identities.

Two additional independently reproduced inherited consumer defects were repaired:

- Extended scenario comparison previously converted foreign value and replaced
  its currency with RUB, losing the review context. It now preserves the original
  currency and observed map, and validates the factor through the shared helper.
  Existing comparison guards suppress best-option/savings claims for unresolved
  results; unknown or invalid factors cannot default to one.
- The quote omitted a nonzero existing recycling fee from its visible lines.
  It now exposes that same amount, base, coefficient and existing legal-reference
  text as `recycling_fee`, without calculating a new fee. Its existing basis is
  independent of customs value; foreign invoice FX does not suppress this
  independent amount merely because other components require review.

Owner's expanded new stage-2 suite: **49 passed**. The combined targeted profile
with earlier A6, preference and special-duty guards: **198 passed**, two dependency
warnings. Unchanged independent A5 regressions, after A5 repaired its isolated
profile-session/table setup: **48 passed**, two dependency warnings. This replay
by A1 is not a substitute for A5's own final verification.

The combined owner, independent red-team, earlier A6 and consumer/history/assistant
profile passed **289 tests**, with two dependency warnings. Independent QA source
commits are `fd25287`, `1af168c`, `f4095ae` and the strengthened assertions in
`3d8531a`; local cherry-picks preserve their separate A5 ownership. The final
owner replay of the strengthened A5 file plus the owner suite passed **97 tests**,
with the same two dependency warnings, using an explicit temporary application
database path.

A standalone legacy engine/quote subset needs its pre-existing shared CI database
initialization: run alone it reported 46 missing-`hs_rates` setup errors, while the
isolated consumer/history/assistant cases passed. The application's existing URL
resolver maps `sqlite:///:memory:` to a literal file named `:memory:` inside this
new isolated checkout; direct SQLAlchemy fixture engines still use real in-memory
databases. The broad attempt created only that test file and its WAL/SHM sidecars
(the inspected main file contained `declaration_documents`). Those three new test
artifacts were removed explicitly; no existing application database was touched.
Later replay uses an explicit temporary application database path. The resolver
is outside this correction's scope. These setup errors were not treated as feature
defects or fixed by weakening tests. The final ordered CI profile remains a
required gate.

## Independent completion record

A5 independently accepted the unchanged owner/test blobs: 97 new cases, a
335-case combined profile, 12 fresh-process HTTP cases and 10 consumer frontend
tests passed. Exact published candidate `599c3af0` passed full CI 34829794572
(5,615 backend / 50 frontend plus types/build/staging/workflows) and admission
34829794668 (2,422). Known skips/warnings and exact identities are recorded in
[evidence](evidence/payment-a6-stage2-publication-20260914.json). Final feature
HEAD and documentation-child push/PR checks are recorded in PR #187.
