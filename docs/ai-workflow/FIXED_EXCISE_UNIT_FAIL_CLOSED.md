# Fixed excise unit guard

Date: 2026-09-23. Scope: one fail-closed payment correction on PR #187.

## Defect and executed boundary

`HsRate` stores automatic excise as `excise_type`, `excise_value` and free-text
`excise_basis`. It has no structured rate unit or denominator. The payment
engine nevertheless treated every `fixed` scalar as RUB per generic invoice
`quantity`. For example, a stored value of 613 and request quantity 20 produced
12,260 RUB even when the source text described a rate per litre and the request
did not establish litres. Neither `net_weight_kg` nor `extra_quantity` repaired
that missing source binding.

## Correction

Automatic fixed excise now remains an unresolved candidate until a future
source/schema path supplies a structured unit and matching shipment quantity.
The raw compatibility surface keeps zero in its explicitly provisional subtotal,
adds `excise_applicability_unverified`, and exposes the missing-unit reason. The
product quote withholds the excise line, dependent VAT and final payable total.
Generic `quantity` is never multiplied by the fixed scalar.

An explicit caller-provided `excise` amount remains a manual override. Percentage
excise behavior is unchanged. This correction does not infer a unit from free
text, approve any excise rate, add historical support, mutate a database, or
change production flags.

## Verification

- Initial focused author profile: 153 passed, one dependency deprecation warning.
  It covers fixed values 0 and 613, conflicting generic quantities, manual
  override, special-duty/VAT dependency propagation, preference guards and all
  completed A6 stage-two regressions.
- Broad `tests/test_payment*.py` profile: 506 passed, 6 failed, 12 subtests.
  Five failures reproduce unchanged at exact base `5d3b0c1d`: four deeply nested
  admission-parser cases under this Python runtime and one date-sensitive legacy
  antidumping expectation. The sixth was the obsolete test that expected the
  unsafe fixed-value multiplication; it was updated to assert review and no
  amount.
- Final focused replay including the updated legacy engine contract: 190 passed,
  one dependency deprecation warning.

This is author evidence, not independent A5 approval or legal-rate admission.
