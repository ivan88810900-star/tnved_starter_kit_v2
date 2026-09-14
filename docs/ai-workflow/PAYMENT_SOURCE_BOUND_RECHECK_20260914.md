# Payment source-bound recheck — 2026-09-14

Scope: read-only A1 recheck at exact PR #187 HEAD
`5d3b0c1dc7dd8e396c4f812db2bf6f1fa6d293f9`, input tree
`59fe9ed9d1a27175a96749cc85422ba34f36b12c`. All examples used newly
created in-memory SQLite tables and synthetic rows. No provider, network source,
application database, flag or legal policy was used.

## Local execution

- A temporary `/tmp` virtual environment was created from
  `customs-clear/backend/requirements.txt` because the base runtime had no
  `pytest`. Command:
  `uv venv /tmp/tariff-payment-recheck-venv && uv pip install --python /tmp/tariff-payment-recheck-venv/bin/python -r requirements.txt`.
- With a fresh temporary `DATABASE_URL`, executed
  `pytest -q tests/test_payment_a6_stage2.py tests/test_payment_a6_stage2_redteam.py tests/test_payment_consumer_review.py tests/test_payment_history_uncertainty.py tests/test_assistant_payment_review.py`:
  **138 passed, 2 dependency deprecation warnings in 7.67 s**.
- A direct in-memory engine/quote probe reused the fixture setup and actual
  `payment_engine.compute_payments` / `payment_quote_service.build_payment_quote`.
  A direct legacy-consumer probe executed actual
  `invoice_analyzer.enrich_with_customs_data`, with DB, geo, FX and profile-bridge
  boundaries replaced by deterministic local fixtures. The profile bridge was
  deliberately made to fail closed; no AI/provider function ran.

## Confirmed residual gaps

| Area | Actual current behavior | Residual dependency |
| --- | --- | --- |
| Dates and editions | A synthetic `HsRate` with `valid_from=""`, `valid_to=""`, empty `source_url` and unbound `source_revision` returned raw/quote `OK`, `amounts_provisional=false`, no period candidate and final `346924.0`. A non-null `as_of="2026-09-01"` was correctly rejected. `HsDutyRule` has no effective interval, edition or source fields. | A3 must supply an immutable rate-row/edition/amendment binding and effective interval. A2 must define shipment-date applicability and precedence from reviewed facts. Until then public historical calculation remains unsupported. |
| Source-bound specific-duty unit | A synthetic `HsDutyRule(type="specific", specific_amount=2, specific_currency="RUB", specific_uom="kg")` returned raw/quote `OK`, duty `200.0` and final `225168.0`. The table records the literal unit but has no source/edition binding, so a populated unit is currently enough for final admission. | A3 must bind amount, currency, unit and denominator to an exact source row/edition. A2 must validate the unit against the product/manifest quantity basis. |
| FX provenance | A supplied EUR factor `123.45` produced only provisional arithmetic: raw `REVIEW_REQUIRED`, `fx_observations.source_kind="unverified_rate_map"`, null source date/verification flags, and null quote duty/final. `get_rates_map()` still erases `ExchangeRate`/CBR revision and date identity and fills constants, so there is no path from a genuine stored row to verified payment FX. | A3 must expose row-bound CBR source date/revision/artifact identity without treating timestamps or global `SourceStatus` as proof. A2 must establish the applicable valuation-date rule. |
| Final amount admission | The two synthetic probes above show that blank/unbound `HsRate` dates/source and an unbound specific RUB/kg rule can still produce `status="OK"` and a non-null final quote. This is not a legal-rate claim; it is a confirmed missing technical admission gate. | A1 can withhold final components only after A3/A2 provide a typed reviewed-admission result. DM-0014 human authority and separate approval remain outside this implementation. |
| Current consumer inconsistency | On the same synthetic 10% duty / DB VAT 22% row, direct legacy enrichment returned `duty=100`, `vat=242`, `total_tax_pay=342`; passing `vat_import_override=10` changed it to `vat=110`, `total_tax_pay=210`. Current diagnostic scripts feed model `vat_rate_final` into this argument. The legacy Excel path exports these legacy VAT/total fields and explanation, while its separately attached `payment_profile` does not replace them or supply their review/admission state. Mounted invoice/calculator APIs were not shown to reach this override. | A4/A1 need a separately scoped consumer correction after A2 defines the admissible VAT applicability result; legacy diagnostic output must not present model-derived VAT as final. |

## Already fixed and reproduced green

- Invalid/future/expired/reversed populated `HsRate` dates withhold dependent
  components and final quote; `as_of=null` equals omission and every non-null
  public historical value remains rejected.
- Missing/invalid structured specific operands, currency or unit are unavailable,
  not zero; legacy fixed antidumping no longer invents a universal unit.
- Foreign invoice/specific-duty maps and constants remain unverified observations;
  invalid factors are rejected, RUB `1` is only unit identity, and comparison
  cannot rank unresolved FX scenarios.
- Geo/preference, cross-store remedy overlap, provisional special-duty arithmetic,
  recycling-fee visibility and displayed-cent reconciliation remain guarded.
- Raw/profile/history/assistant numeric compatibility subtotals preserve
  `REVIEW_REQUIRED` and reason metadata; structured quote lines and final total
  are null when affected. This intentional compatibility split passed the
  consumer suites and is not the legacy VAT override above.

## Proposed next ownership (no implementation in this branch)

1. **A3 Sources** — own new immutable source DTO/evidence and ingestion/read
   contract in `app/services/exchange_rates.py`,
   `app/services/payment_source_ingestion.py`,
   `app/services/payment_source_registry.py`, plus source-only tests/evidence.
   Any persisted edition/unit/FX binding requires a separately reviewed Alembic
   migration; do not retrofit trust from existing timestamps, URLs or constants.
2. **A2 NTM/legal applicability** — own a new bounded payment applicability
   service and tests (proposed
   `app/services/payment_rate_applicability.py` and
   `tests/test_payment_rate_applicability.py`) for effective interval,
   amendment/edition precedence, product/origin/producer conditions and quantity
   basis. It consumes A3 facts and emits no amount.
3. **A1 Rates/Payments** — after A3/A2 contracts are reviewed, own integration in
   `app/services/payment_engine.py`, `app/services/payment_quote_service.py`,
   `app/services/scenario_compare_service.py` and dedicated payment tests. A1
   must require the reviewed token for a non-null final amount while retaining
   current fail-closed behavior.
4. **A4 Consumers** — own the legacy boundary in
   `app/services/invoice_analyzer.py`, `scripts/test_invoice_parsing.py`,
   `scripts/vat_22_stress_validate.py` and focused consumer/export tests. Do not
   change mounted API semantics or duplicate payment arithmetic.

No product code, schema, database, workflow, flags or tests were changed by this
recheck.
