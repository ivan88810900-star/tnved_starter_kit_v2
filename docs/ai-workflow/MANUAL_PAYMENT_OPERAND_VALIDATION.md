# Manual payment operand validation

Date: 2026-09-24. Bounded A1 correction stacked on PR #216 exact HEAD
`eb702ef05735cec12afd03278edbf23c93cbe51b`.

## Defect

The payment engine treated caller-supplied `duty_rate`, `vat_rate` and `excise`
as explicit manual overrides but did not validate their numeric domain. Negative,
boolean, malformed or non-finite operands could therefore enter payment arithmetic,
reduce the provisional total or produce a non-serializable result. A very large
but finite operand could also overflow only during duty, VAT-base/VAT, or final-total
arithmetic and reach the response as infinity.

## Correction

Manual override semantics are unchanged for finite non-negative values, including
an explicit zero. Invalid operands are rejected before source reads and arithmetic
with a stable `ValueError`; mounted calculator endpoints already map that error to
HTTP 400. Every dependent monetary aggregation is additionally checked for finite
output, so finite inputs that overflow cannot reach JSON. No automatic rate, source
admission, rounding rule or legal applicability decision is added.

Focused regressions cover negative, boolean, malformed, NaN and infinity inputs,
all three finite-input overflow paths, plus the explicit-zero compatibility path.

## Boundaries

This change does not validate or approve automatic source rows, create a statutory
rate ceiling, implement historical payments, establish fixed-excise units, alter
the database/schema, activate flags, deploy, or change production data.
