# AD30 offline review consumer contract

Reviewed by A4 on 2026-09-14 against integration `182af82b` plus A1's
row-provenance correction `9aafade5` (local cherry-pick `1263c3f`). This is a
description of the existing isolated interface, not a live AI/API integration
or legal approval. Independent A5 acceptance belongs to the combined task.

## Entry points and input authority

Paths below are relative to `customs-clear/backend/`.

| Entry point | Existing responsibility |
| --- | --- |
| `app/services/ad30_source_facts.py` | Load and revalidate the pinned immutable dossier and its tracked evidence records. |
| `app/services/ad30_applicability.py::assess_ad30_candidate` | Assess caller-supplied product facts against the bounded literal source candidate. |
| `app/services/ad30_duty_preview.py::preview_ad30_duty` | Recompute assessment and, when possible, evaluate one explicitly selected hypothetical source row through the existing `ETTDuty` / `preview_duty` arithmetic. |
| `scripts/preview_ad30_candidate.py` | Read one bounded JSON scenario and print the review result to stdout. |

Both assessment and preview require an explicit calendar `date` as `as_of`.
The date is retained; neither service selects an effective legal interval or
uses today's date as a fallback. The preview accepts no precomputed assessment,
producer inference or approval marker. A supplied source DTO is revalidated,
including its values; a claimed digest or boolean is not authority.

The CLI requires `as_of` in strict `YYYY-MM-DD` form, a `facts` object and
`currency` (`EUR`, `USD` or `RUB`). `source_row_id` and `customs_value` may be
omitted for clarification output. Its only source row IDs are `foshan_vinmay`,
`guangdong_sumwin` and `other_producers`; choosing one declares a hypothetical
operand, not verified producer identity. No unknown producer defaults to
`other_producers`. No exchange-rate conversion is performed.

The authoritative product input schema and interpretation are in
[AD30_APPLICABILITY_REVIEW.md](AD30_APPLICABILITY_REVIEW.md). Codes and structured
facts are supplied, not inferred by classification, description search or AI.
Measurements are explicit positive millimetres. Monetary and measurement
fractions use bounded plain decimal strings in JSON, not JSON floats. Unknown
top-level fields, duplicate keys, nonfinite numbers and oversized input are
rejected. File/stdin input is limited to 64 KiB; a named file must be a regular
file and cannot be a symlink. No database, network or application startup is
part of this path.

## Interpret the complete result

| Field or outcome | Meaning for a consumer |
| --- | --- |
| `assessment.candidate_scope="matches_source_candidate"` | All bounded product predicates match the supplied facts. No final classification, mandatory document or legally applicable duty is established. |
| `assessment.candidate_scope="outside_source_candidate"` | A known predicate excludes this particular literal candidate. This is not a legal exemption or proof that no other duty applies. |
| `assessment.candidate_scope="needs_clarification"` | Facts are missing, invalid or contradictory; inspect the assessment diagnostics. |
| `status="calculated"` | Exact hypothetical arithmetic is available in `amount` and `calculation`; legal applicability is still unavailable. |
| `status="needs_clarification"` | The product candidate or scenario operands are unresolved; `amount` and `calculation` are null. |
| `status="unavailable"` | This preview cannot supply an amount; never convert null to a zero liability. |
| `legal_applicability`, `temporal_applicability` | Both remain `"unavailable"` for every valid preview. |
| `review_required`, `assessment.requires_manual_review` | Both remain true, including after successful arithmetic. |
| `applied`, `legal_review_verified`, `legal_approval`, `final_payable`, `can_promote` | All remain false. `final_payable_amount` remains null. |

Keep `assessment.criteria`, `missing_facts`, `invalid_facts`,
`contradictory_facts` and `review_blockers` together. Invalid or contradictory
facts take precedence over a known mismatch; a known mismatch can otherwise
exclude this candidate despite unrelated missing facts. Top-level
`missing_inputs` describes missing arithmetic operands only after the product
candidate matches; an empty list does not mean that all product facts are known.

`selected_source_row` may be present even when assessment is unresolved or
outside the candidate. Its presence is evidence of the caller's row selection,
not permission to calculate, apply a rate, or disregard `status`.

## Preserve evidence and decimal values

Every valid result carries `source_dossier_sha256`. Assessment criteria link
`source_fact_ids` to `assessment.source_evidence`, which includes the tracked
evidence path/SHA, JSON pointer, original-body SHA, source URL, page, locator and
`observation_kind`. Those assessment evidence entries do not contain
`value_json`; resolve their pinned records if displaying the observed content.

`selected_source_row.source_evidence` contains the complete bound facts for
both the selected producer row and the percent-of-customs-value unit, including
`value_json`. Preserve this unit and the row's `rate_percent_literal`; a bare
number or unresolved evidence ID is insufficient provenance. `observation_kind`
distinguishes prior visual observations from literal source excerpts. Do not
represent an English source-reading summary as native Russian PDF extraction.

`source_record_integrity_verified=true` verifies the tracked dossier/record
bindings. It does not mean the current invocation replayed the original PDF,
verified its transcription, established effective dates or obtained human legal
approval. `original_artifacts_verified` and `source_text_verified` remain false;
producer identity, amendment history and durable legal retention also remain
unverified. See [AD30_SOURCE_FACT_DOSSIER.md](AD30_SOURCE_FACT_DOSSIER.md).

Python monetary output uses `Decimal`; the CLI serializes it as a decimal
string. Retain exact strings/decimal arithmetic and the `calculation.trace`.
`rounding_applied=false`: this preview supplies no declaration rounding policy
and must not be merged into `vat_base`, payment components or `total_payable`.
For example, an explicitly selected hypothetical row can produce
`"0.001462"` RUB from `"0.01"` RUB; rounding that to display zero must not turn
it into a zero-duty conclusion.

## CLI completion is not admission

| Exit | Output | Meaning |
| --- | --- | --- |
| 0 | `status="calculated"` | Hypothetical arithmetic completed, with review and legal limits intact. |
| 3 | `needs_clarification` or `unavailable` | Valid review scenario has no usable amount. |
| 2 | `status="invalid_input"` | Representation, input-read or source-record validation failed. |

The exit-2 JSON is deliberately smaller: it retains null `amount`, unavailable
legal applicability, review required and false admission/write flags, but has
no assessment, selected row or complete success schema. Read `status` before
accessing optional evidence. None of these exits authorizes application.

## Current assistant and classification boundary

A read-only reference search across product/legacy Python and frontend
TypeScript found the AD30 modules/functions only in the three new services,
their CLI and author tests. No live router, application startup, assistant,
classification or frontend module imports this candidate. The product diff
also leaves those existing consumers unchanged.

The existing `assistant_orchestrator.py` calls the shared payment compatibility
service and NTM service; `grounded_assistant.py` consumes canonical anchors,
search and NTM facts plus the existing payment snapshot schema.
`assistant_chat.py` uses that grounding and its existing payment review guard.
`app/api/classify.py` retains the existing classifier services. No AD30
threshold, producer selection or money formula was copied into these modules.

This review DTO is **not** a drop-in payment snapshot or NTM obligation.
For example, the existing `payment_requires_review` helper recognizes payment
fields such as `amounts_provisional` and `REVIEW_REQUIRED`, not this preview's
`review_required` field. Any future consumer needs an explicit reviewed adapter
that preserves the above states and evidence; renaming `amount` to
`total_payable` or `matches_source_candidate` to `definite` is not supported.
This inspection proves the bounded code/reference state, not runtime acceptance
of a future AI integration or complete correctness of every existing AI path.

## Verification of this document

A4 executed four real CLI subprocesses on the reviewed code: complete literal
scenario → exit 0 / `calculated` / `"0.001462"`; missing product facts → exit 3 /
`needs_clarification`; declared `welded=false` → exit 3 / `unavailable`; forged
top-level `legal_approval=true` → exit 2 / `invalid_input`. All four outputs
retained unavailable legal applicability and `final_payable=false`; stderr was
empty. Selected-row cases exposed both the row and unit evidence. No feature
code or runtime consumer changed in this documentation task; A5 independently
verifies the combined implementation before integration.
