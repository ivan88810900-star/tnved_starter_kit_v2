# Payment stage-two consumer review

A4 review, 2026-09-14. Starting product commit:
`dab1f8aae5a114a51505763bf9ea0a0d8161ed38`. This records a bounded consumer
inspection for A6 stage two; it is not independent A5 acceptance or proof of
complete legal rates coverage. A1 owns payment, FX and quote corrections. A4
checked their final consumer fields and comparison/quote changes at
`fa74edddda135fe736228b0a8784da3bc21724c3`; the inspected existing profile,
history and assistant projections are unchanged by that correction.

## Preserved public review contract

The existing top-level `status="REVIEW_REQUIRED"`, `amounts_provisional=true`,
`payment_review_reason` and `payment_review_reasons` remain the primary consumer
contract. New reason codes are carried as strings, without a fixed allowlist in
the inspected projections. They must travel with any compatible numeric subtotal.
An amount retained for a preliminary calculation is not an admitted final amount.

Paths in the table are relative to `customs-clear/`.

| Consumer | Observed propagation and presentation |
| --- | --- |
| `backend/app/api/calculator.py` → `frontend/src/pages/Calculator.tsx` | The raw calculation retains review fields. `hasProvisionalPayments` changes both total labels to “Предварительная сумма” and displays the review message. The assistant bridge copies status, flag, reason text and reason codes. |
| `backend/app/services/payment_profile_builder.py` | Profiles preserve status, flag, reason text/codes and `data_quality`. Comparisons reuse each exact raw scenario result rather than recomputing it; incomplete/review scenarios suppress deltas. |
| Calculator two-code and extended comparison UI | Review scenarios show a warning and preliminary headings. Incomplete comparison suppresses best-option/savings claims. Extended CSV retains status, provisional flag, reason text/codes. These guards require upstream review state to survive currency conversion. |
| `backend/app/services/calculation_history_service.py` | Full records save the output payload. List and CSV projections use `payment_result_metadata`; aggregate paths preserve review messages/codes. Old records without the flag keep an unknown status rather than inventing finality. No history DB was opened during this audit. |
| `backend/app/services/assistant_orchestrator.py::bundle_for_llm` | The compact payment summary preserves review status, flag, reasons and quality metadata. It does not determine legal applicability or recalculate payments. |
| `backend/app/services/grounded_assistant.py` | Snapshot and copilot paths retain review state and render preliminary totals with a warning. `assistant_chat.py` prevents external rewriting when its payment review guard is true. |
| `frontend/src/components/payments/SmartPaymentsBlock.tsx` | Quote lines with `unknown`, `manual_review_required` or `not_configured` show no amount. Null `total_payable_rub` shows an undefined final total and a separately labelled partial sum. |

The profile schema and raw Calculator preserve numeric subtotals for compatibility;
they do not yet provide the quote's null amount/status on every individual line.
Their review flags and visible warning remain essential. Null amounts in the
structured quote must not be copied into a legacy numeric profile and silently
coerced to zero.

## Additive component and FX evidence

A1's additive `payment_component_review` maps component codes to reason-code
lists; it does not replace the top-level review guard. The structured quote uses
the affected-component list to suppress its amount and mark it for review, with
VAT and the final total remaining unavailable when their basis is uncertain.
The raw compatibility breakdown continues to carry provisional numeric subtotals.

`fx_observations` records `usage`, `currency`, `rub_per_unit`, `source_kind`,
`source_date`, `source_evidence_verified` and `legal_review_verified`. An
unverified map, fallback constant or unavailable factor is labelled as such;
the date remains null and verification flags false. Neither the currency label
nor an observed number supplies official date/source authority. These two
structures are also retained under `data_quality`, which the inspected profile
and assistant projections preserve without adding their own FX interpretation.

When present, `duty_candidate` describes an incomplete structured expression
with null `amount`, `calculation_available=false` and the original rule's
code/type/specific amount/currency/unit fields. `hs_rate_period_candidate`
retains an unverified legacy validity period and its recorded source revision/URL.
These are candidate diagnostics, not new admitted rates. They are not projected
as dedicated UI fields in this task; the shared reasons remain visible.

## Concrete consumer findings and ownership

1. **Extended comparison dropped original FX context.** At the starting commit,
   `scenario_compare_service.py::compare_scenarios_extended` converts the foreign
   base amount with `get_rates_map`, defaults a missing rate to `1.0`, and forwards
   `invoice_currency="RUB"` to the engine without the original conversion evidence.
   The route is `POST /api/calculator/compare-scenarios`. This can hide the need
   for FX review before the comparison's otherwise valid ranking guard. A4
   reproduced the propagation loss and returned the feature defect to A1/A0;
   A5 independently confirmed it with the actual engine. A1's `fa74eddd` now
   preserves the original invoice currency and FX map and uses the shared
   `observed_fx_rate` validator; missing/invalid foreign factors are rejected.
   Engine review status then reaches the existing comparison/ranking guard.
2. **Partial arithmetic was labelled as confirmed.** The quote UI used
   “Подтверждённая часть” for every null final total, including a zero partial sum.
   A0 authorized the single copy change to “Частичная сумма”. Amounts, statuses,
   formulas, totals and API contracts are unchanged by that presentation fix.

A5 separately identified recycling fees included in the engine total but omitted
from quote lines; A1 owns that correction. Its additive `recycling_fee` line is
compatible with the existing frontend: line `code` is a string, and the quote UI
maps every line rather than selecting a fixed list of six codes. The existing
status-to-label mapping needs no new status. AI snapshot consumers do not consume
quote line arrays and therefore do not inherit this detailed new line automatically.

## Boundaries of this review

The existing assistant and profile projections must not be described as a complete
per-component source/FX evidence interface. Their overall review state survives;
that is narrower than displaying every engine evidence field. The existing chat
snapshot also does not include a separate recycling-fee component, although its
total/review state is retained. This task introduces no duplicate arithmetic,
source interpretation, producer selection, AI authority or live AD30 integration.

No comparison result or copied source URL proves current legal applicability.
Public `as_of=null` has the same meaning as an omitted value; a non-null requested
historical date remains rejected. Manifest-bound human review and separate legal
approval remain as recorded by A1/A3. Previously documented legacy diagnostic
invoice/Excel paths remain outside this bounded consumer review.

## Evidence and remaining verification

A4 inspected the actual routes, projections, schemas and rendering conditions.
In a database/network-free diagnostic, the actual extended-comparison function
body forwarded USD 1,000 with a rate of 90 as RUB 90,000 without FX provenance;
an unknown `ZZZ` currency became RUB 1,000 through the fallback. With an explicitly
stubbed OK engine result, both comparisons produced `comparison_complete=true`
and a best scenario. This initial diagnostic proves propagation loss; it is not
misrepresented as a full-engine test.

Replaying the actual corrected comparison and shared factor-validator bodies at
`fa74eddd`, still with explicitly stubbed DB/rate-map/engine dependencies, forwards
USD and its observed factor. A review response now leaves comparison incomplete
with null best scenario and savings; unknown `ZZZ` fails before the engine call.

A second diagnostic executed actual projection function bodies without importing
the application: two opaque reason codes and their message survived the copilot
summary, history list/CSV and grounded chat snapshot. Each output retained
`REVIEW_REQUIRED` and the grounded review guard remained true. These are bounded
projection probes, not browser, live API or production database tests.

After the authorized copy correction, the three existing SmartPaymentsBlock,
Calculator and extended-comparison payment-review suites passed: **10 tests**.
`npm run typecheck` and `npm run build` also passed. `npm ci` used the unchanged
lockfile. Only two existing text expectations changed; no scenarios or safety
assertions were removed. Build tooling emitted its existing SWC/esbuild and
Browserslist notices, without a test, type or build failure.

The owner record above preceded independent acceptance. A5 subsequently accepted
the exact A4 copy/test/doc blob after replaying the same 10 tests. Combined
candidate `599c3af0` passed full CI 34829794572 and admission 34829794668; see
[publication evidence](evidence/payment-a6-stage2-publication-20260914.json).
Final feature HEAD and documentation-child push/PR checks are recorded in PR #187.
