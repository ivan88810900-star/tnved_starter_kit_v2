# A6 payment audit, stage 2

Date: 2026-09-14. Status: execution-backed findings; corrections and independent
A5 acceptance pending. This document grants no legal applicability or admission.

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
| A3: upward coefficient | Previously fixed, current regression passes | Coefficient 2 retains ordinary duty 100,000 and review. Base doubled duty to 200,000 and final 468,924/OK. |
| A6: cross-store AD overlap | Previously fixed, current regression passes | Both unresolved AD amounts withheld; quote final unavailable. Base summed 50,000 twice and returned 468,924/OK. |
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
