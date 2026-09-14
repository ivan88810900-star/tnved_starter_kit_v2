# A6 stage 2: FX and legacy duty source boundaries

Status: source/code audit completed by A3 and independently accepted by A5 on
2026-09-14 after checking the code and both primary CBR pages. This acceptance
concerns the documented source boundary, not rate admission or the pending
implementation/CI gates.
Observed 14 September 2026 against PR #187 feature commit
`dab1f8aae5a114a51505763bf9ea0a0d8161ed38`.
This is a read-only source-input audit, not A1's implementation report or a claim
that corrected payment behaviour has passed integration tests. Existing originals,
source records, rates and application databases were not changed or reacquired.

## Official CBR contract and the existing representation

The official [CBR XML documentation](https://www.cbr.ru/development/SXML/), checked
for this audit, specifies an optional `date_req` parameter in day/month/year form.
Omitting it returns the document for the latest registered date. It does not
promise that the response belongs to the caller's current calendar date. The
[official daily table](https://www.cbr.ru/currency_base/daily/) separately labels
the rate date, number of currency units and quoted ruble amount. These are source
format observations, not a decision about the customs valuation date to apply.
No current numeric CBR rate was copied into project data.

The web reader could open the official documentation and daily table. Its direct
XML reader reported unsupported `application/xml`; this does not establish a CBR
outage or absence of the XML artifact. No replacement mirror was used as evidence.

The existing `app/services/exchange_rates.py` implementation has useful source
metadata before the read layer:

- `fetch_cbr_rates()` requires the exact HTTPS CBR daily endpoint, validates the
  response and returns `CBRRateSnapshot(date_key, rows, sha256)`.
- `_parse_cbr_xml()` reads `ValCurs.Date`, `Nominal` and `Value`. It stores each
  selected rate as `Value / Nominal`: **RUB per one foreign currency unit**.
  The original nominal is retained separately. A consumer must not divide that
  already-normalized stored rate by nominal again.
- Successful ingestion writes all tracked rows and a `SourceStatus` / `SyncLog`
  revision `cbrf:YYYY-MM-DD:sha256:<artifact digest>` in one transaction.
  The status also has the source URL, sync timestamp and stale flag. Existing
  monotonicity and same-date digest guards preserve earlier accepted data when
  an inconsistent update is detected.
- The ingestion age check is an operational transport gate: it permits a
  tomorrow-dated response and uses a configurable maximum age. It is not an
  assertion that the XML date applies to a particular payment or historical
  declaration. `updated_at` and `synced_at` are observation/write times, not
  substitutes for the source's `Date`.

`ExchangeRate` has only currency, normalized rate, nominal and updated timestamp.
Its mutable rows have no per-row source revision or artifact digest. A successful
`SourceStatus` revision records ingestion evidence; **that marker alone does not
cryptographically bind currently stored row values to the original XML**.
Matching timestamps likewise do not prove this binding. `CBRRateSnapshot`'s
`rows` field is itself a mutable mapping, so construction of that Python type or
possession of its digest is not a standalone authenticity/approval mechanism.

## Confirmed baseline read boundaries

| Boundary at the observed commit | Code finding | Technical implication |
|---|---|---|
| `exchange_rates.get_rates_map()` | Returns stored values with no date, origin or revision, then fills missing currencies from `FALLBACK` (`USD=92`, `EUR=100`, etc.) | Stored official observations, old/legacy rows and constants become indistinguishable to a consumer |
| `exchange_rates.get_rates_payload()` | Returns `status="OK"`, row timestamps and a map; an empty table produces constants | This existing payload cannot attest current official FX; the timestamp is not the XML date |
| `payment_quote_service.build_payment_quote()` | Multiplies invoice value by `get_rates_map()` and inserts the map into `_fx_rates` | Baseline quote calculation has no source/date test for invoice conversion or foreign specific-duty conversion |
| `payment_engine._compute_structured_duty()` | Starts with `_FALLBACK_FX_RATES`, overlays the internal `_fx_rates` map and uses the selected value | A numeric value alone supplies no CBR provenance, date or legal valuation basis |
| `api/calculator.py` compute/compare | Uses the same provenance-free map; compute writes `fx_source="ЦБ РФ"` unconditionally | A fallback or legacy value can be labeled as CBR without supporting source evidence |

These are direct code-path findings. Whether an individual baseline quote
appears final also depends on its other duty/VAT/excise/review branches; A1 owns
executed reproductions and A5 independently checks the corrected behaviour.

The internal `_fx_rates` trust boundary must be described accurately. Raw
`compute_payments(dict)` accepts the field. Public calculator/payment-quote
request models use `extra="ignore"`, and `build_payment_quote()` overwrites it
with its own map. Therefore the reviewed code does **not** demonstrate that a
public client can inject an arbitrary FX map through those schemas. It does
show why a caller-supplied/internal dictionary must not serve as proof of source
validity or permission to publish a final amount.

An adjacent display path, `app/api/currency.py`, independently tries official CBR
and then `cbr-xml-daily.ru`. Both successful responses are labeled `source="cbr"`;
its local-cache response can also contain fallback constants. That route is not
used by the audited quote's `get_rates_map()` call. Its source-label weakness is
recorded separately and is not silently counted as an A1 payment repair.

## Fixed antidumping units and geopolitical candidates

`HsRate` stores `antidumping_type`, `antidumping_value`, countries and condition
text. It has no antidumping-specific currency, quantity unit or denominator.
At the observed commit, `_resolve_antidumping()` nevertheless describes `fixed`
as RUB per unit and multiplies the value by generic request quantity. The schema
and an empty condition string cannot establish that monetary/unit interpretation.
It cannot be repaired by assuming kilograms, pieces, currency or a denominator.

`SpecialDuty` is a distinct legacy schema: it has `rate_specific` and currency,
but no source-bound unit/denominator either. Its existing resolver already emits
`specific_unit_basis_unverified` and withholds a calculable amount when the
specific component is positive. This protective behaviour must be retained;
unavailable arithmetic is not a confirmed zero liability. Free-text regulatory
acts and product/manufacturer descriptions do not fill the missing unit fields.

`GeoSpecialDuty` stores prefix, country, rate string, measure type and document
basis/link. It lacks an effective interval, artifact/row binding, complete product
conditions and manifest-bound legal approval. The baseline matcher selects a
prefix/country candidate; the engine extracts an ad-valorem value and applies its
fallback priority condition. Neither matching that candidate nor deciding which
legacy storage path has priority establishes a legally applicable replacement
rate. A document link or fallback marker is evidence to investigate, not approval.
This source audit makes no decision about replacing or accumulating geopolitical
and ordinary rates; those interpretations require the domain review chain.

## Bounded corrective interface recommendation to A0/A1

Preserve the existing ingestion mechanism. Separate a numeric conversion
observation from its source/date confidence; do not create a new FX ingestion
system for this correction. A minimal consumer contract can carry the observed
currency, RUB-per-unit value, source category, source date/revision if known, and
an explicit review reason. It must never infer verified provenance from a caller
flag, timestamp, arbitrary map or global status marker.

Until row-bound/date applicability is actually proved, the conservative technical
choice is to keep foreign-FX amounts explicitly provisional, request review and
withhold the final payable total. This applies when either the invoice or a
specific-duty component uses foreign FX. RUB-to-RUB at one is a unit identity,
not an official rate observation. Missing/invalid FX must not become a zero rate
or an implicitly verified one. Any reusable existing metadata should remain
labeled as observed diagnostics, not a cryptographic or legal verification grant.

For legacy fixed antidumping, preserve raw evidence and report the missing
currency/unit/denominator basis without manufacturing an amount. For geopolitical
candidates, expose the unresolved replacement/applicability issue independently
of which legacy row wins the old priority. Keep all current source/review guards.
A1 implements the bounded technical behaviour; A5 checks concrete regressions.
A3 supplies these source boundaries without approving a product/legal rule.

## Validation and ownership

A3 read the functions, ORM fields and public request schemas identified above,
and checked the two linked primary CBR pages. Only this new document is owned
and modified by A3. There are no feature-code, model, migration, test, workflow,
flag or database changes in this commit. No runtime test is claimed for this
read-only documentation scope. A5 independent acceptance and final integrated
CI results belong to the separately recorded implementation evidence.
