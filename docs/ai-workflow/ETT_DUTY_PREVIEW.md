# Source-bound candidate duty arithmetic

This continuation of [TASK-ETT-001](ETT_VERSIONED_CANDIDATES.md) implements
provisional monetary arithmetic on the already supported duty expressions.
It uses the accepted Option A boundary in issue #188. It adds no application
endpoint, legal authorization, rate application or production storage.

## Operation

Run from `customs-clear/backend`, against an explicitly selected isolated
candidate database and its existing source store:

```bash
python3 scripts/ett_candidates.py preview-duty MANIFEST_SHA256 \
  --database /path/to/isolated-candidates.db --store-root /path/to/objects \
  --code 0101210000 --as-of 2026-09-08 --destination RU \
  --calculation-inputs /path/to/calculation-inputs.json
```

The paths and code above illustrate the interface; they are not a supplied or
legally approved candidate. A minimal calculation input is:

```json
{"currency":"RUB","customs_value":"123.40"}
```

The CLI loads and verifies the complete staged manifest and retained artifacts,
resolves the exact code/date/destination/product facts, then replays all native
PDF and typed HTML quotations referenced by that manifest. An unresolved rate
or unverifiable quote produces no monetary amount. A quote match proves that
the supplied words occur in the retained source; it does not prove that a
proposed rule or date is legally correct.

For a specific component, supply `quantity` and `quantity_unit`. Quantity is the
**total calculation basis** in exactly the duty's declared unit. Product facts
do not automatically provide a quantity; there is no silent weight, volume,
item-count or engine-displacement conversion. Missing or zero quantity requires
clarification. A zero customs value is allowed, but even an explicit zero
ad-valorem rate requires a supplied value before monetary arithmetic.

Supported formulas preserve the existing model:

| Duty kind | Arithmetic |
| --- | --- |
| `ad_valorem` | customs value × percent / 100 |
| `specific` | specific amount × total quantity / per-quantity × currency factor |
| `combined_max` | maximum of ad-valorem and specific components |
| `combined_sum` | sum of both components |
| `capped_combined_max` | minimum of the cap and the maximum of both components |

Inputs accept bounded plain decimal strings or integers. Binary floating-point,
booleans, non-finite numbers, duplicate JSON keys and unknown fields are
rejected. Arithmetic does not depend on the process-wide Decimal context. A
non-terminating exact decimal result is `unavailable`; the preview never invents
a rounding rule. The response includes exact components and immutable operation
steps. This is a duty-only preview, not a duty/VAT/excise/final-payment total.

## Currency evidence boundary

When source and calculation currencies differ, `exchange_rate` must contain
`from_currency`, `to_currency`, an exact matching ISO `as_of`, a positive
`multiplier`, `source_url`, `source_artifact_sha256`, `source_locator`,
`source_text` and `source_text_sha256`. Only the explicitly directed pair is
accepted; no reciprocal or cross rate is inferred.

This validates the supplied reference's shape and text hash. It does **not**
retrieve the currency source, authenticate the quoted factor, or certify that
the factor is legally applicable. The arithmetic result permanently retains
`source_evidence_verified=false`, `legally_approved=false`,
`final_payable=false` and `rounding_applied=false`. The enclosing workflow's
separate `source_quote_verification` concerns the candidate's tariff quotations,
not exchange-rate authenticity. Its `legal_approval`, `production_ready`,
`can_promote` and `active_rates_written` remain false.

## Read-only and error contract

`preview-duty` opens the explicit SQLite file with `mode=ro` and `query_only`.
It never consults the application's `DATABASE_URL` or creates a database.
Calculation input is bounded to 1 MiB; other JSON files retain their existing
64 MiB limit. Non-regular input files are rejected without blocking on a FIFO.
The source verifier may use bounded temporary worker files, but does not acquire
new sources or mutate source objects.

Exit codes: `0` for calculated provisional duty, `3` for clarification or
unavailable results, `2` for sanitized malformed-input/integrity failures.
Existing `preview`, staging and manifest serialization remain compatible.

## Verification scope

102 arithmetic cases cover all five formulas, input validation, exact contexts,
date/unit/currency mismatch, missing inputs and immutable provisional flags.
14 subprocess CLI cases use isolated synthetic evidence and candidate tables;
they verify real quotation replay, fabricated-quote rejection, malformed files,
zero-versus-missing distinctions, unchanged database/store bytes and absence of
an application database. Synthetic fixtures do not establish legal coverage.

The replacement real 111C review package is separately described in
[reconstruction evidence](evidence/ett-111c-reconstruction-20260911.json).
Its four-code, one-day candidate must not be presented as the current or complete
ETT. Human review/approval, retained-object policy attestation, complete legal
applicability and product payment integration remain separate unfinished work.
