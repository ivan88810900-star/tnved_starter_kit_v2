# Rate-source and applicability corrections, 11 September 2026

This corrective continuation of issue #188 and PR #187 implements Ivan's
existing requirements: invalid extraction is not a zero rate, ambiguity requires
review, and code-only candidates cannot establish mandatory documents. It does
not approve new legal rules, import production data or activate enforcement.

## Invalid source values

Official VAT and excise bundle ingestion previously delegated to a permissive
legacy normalizer: missing or malformed VAT could become the default rate,
malformed excise could become zero, and non-finite numbers could survive.
The three trade-remedy ingestors also converted missing or unsupported rate
forms into zero and discarded a valid generic specific-rate value.

The official ingestors now validate explicit source values before normalization.
True zero remains representable. Missing, invalid, negative, boolean, non-finite,
overflowing or positive-underflowing values block the bundle before database
planning, provenance updates or application. Original row numbers and bounded
source-cell diagnostics remain visible. JSON decimal magnitude survives parsing
until validation. This corrects ingestion, not the underlying legal dataset.

Trade-remedy ingestion shares a supported-form validator across antidumping,
safeguard and countervailing measures. Conflicting source aliases and unsupported
combined formulas require review. A supported specific amount keeps its explicit
currency; source unit fields that this legacy schema cannot preserve block
ingestion, and a missing calculation basis cannot authorize arithmetic. The
existing float-backed storage schema is unchanged;
the separate ETT candidate arithmetic uses exact decimals.

The retained excise bundle contains two tobacco rows (`2402201000` and
`2402209000`) with `combined` expressions that this legacy schema cannot
represent. The bundle now fails parsing with those source diagnostics; its
original bytes and SHA
`e1d008097f5d16366364b19e1a0bd9c915bdf7dafaea8ce0fb444236414d849e`
remain unchanged. Neither a guessed simple rate nor new legal terms were
substituted to make that input pass.

## Unresolved trade-remedy applicability

The legacy payment engine previously selected remedy rows without checking
their start date, producer/product conditions or whether several matches were
alternative rates. It also multiplied specific rates by generic quantity and
fallback currency factors despite lacking a source-bound unit.

The corrected resolver excludes temporally inactive rows and keeps malformed
dates, unknown origin scope, producer/product conditions, verification flags,
missing provenance, unsupported specific units and overlapping alternatives
unresolved. It retains their source details without an applied amount. An
otherwise computable source-marked row can supply only provisional arithmetic:
existing source markers are not a manifest-bound legal approval. Remedy
uncertainty remains visible in the dependent VAT and final-payment status.
An unresolved zero is never labeled `not_applicable`.

The existing legacy quote/calculator/compare APIs do not have verified temporal
versions of all their rate and fee families. They explicitly reject supplied
`as_of`, including nested scenario inputs, instead of silently replacing it
with today's calculation. The isolated ETT candidate preview supports explicit
dates within its actual finite coverage. Full temporal product integration
remains unfinished; this guard does not claim to implement it.

## Technical requirements with unresolved scope

The legacy positive TR catalog does not contain all product codes. Absence from
that catalog cannot prove legal exclusion. Retaining an unknown row also cannot
make its documentary wording an enforceable requirement.

Unresolved legacy TR rows therefore retain explicit review metadata. Imported
v2 applicability, legacy reads and broker merging preserve that uncertainty;
the user receives an advisory item without a mandatory permit or missing-check
effect. Existing imported classifications are checked on reads, so safety does
not depend on running a mass database rewrite. This change does not establish
the legal applicability of any particular technical regulation.

## Other regressions found while restoring verification

The authenticated permit-job detail route now precedes the public catch-all
verification route. Alembic keeps existing application loggers enabled. A
commodity card requires an exact catalog identity; a neighboring code or a rate
row alone cannot create a card with a borrowed description. Exact existing cards,
their rate fallback and optional Canonical-provider failure remain supported.

The diagnostic full-suite comparison against the transfer HEAD had the same
130 failed test IDs on both commits, including 120 assumptions requiring a
separate full integration dataset. The corrections above address demonstrable
implementation defects. Tests were not supplied invented legal data or weakened
to turn missing integration fixtures into successful acceptance.

## Unchanged release boundary

These corrections and the [ETT duty preview](ETT_DUTY_PREVIEW.md) do not complete
the legally approved full tariff manifest. All 124 tariff notes still require
substantive source-to-rule/date/condition review; the saved four-code candidate
is not full current coverage. Complete official VAT/excise/trade-defence/origin
applicability, durable legal-retention attestation and manifest-bound human
approval remain unfinished. The DB-derived ETT stays quarantined.

## Verification before publication

- Official scalar/JSON and five-ingestor regression set: 849 passed, 73 subtests,
  two existing dependency warnings. Duplicate keys cannot hide a later zero,
  country, type or revision; retained SHA identifies the exact bytes parsed.
- Payment applicability/consumer and existing-engine regressions: 179 passed,
  with two existing deprecation warnings in the focused run.
- Unknown-TR and adjacent legacy/v2 tests: 104 passed, one existing data smoke
  skipped; the original smartphone assertions remain intact.
- Catalog identity regression set: 15 passed. Authentication/routing/logging
  regression set: 32 passed, one opt-in live-FSA test skipped.
- Restarted Uvicorn HTTP smoke: health and authenticated source registry/plan
  passed; both contain 48 sources. Anonymous permit-job detail is 401; an
  authenticated missing job and unknown commodity card are 404. Quote and both
  calculator routes reject unsupported dates with 422. The isolated read-only
  database SHA remained
  `399b8f1eca8f44ed5a3d8aadad19b5e2fa172dbfa8e12994643eb1be57e3e8b0`.

These sets overlap and must not be added into a claimed total. The CI selection
now includes the changed source, payment, TR, routing and identity contracts.
An initial local integrated run ended without a pytest summary at 64%; it is
not recorded as successful and its cause is unknown. A subsequent run with
JUnit and process-completion evidence finished successfully: **4,403 passed,
2 skipped, 2 warnings, 73 subtests passed**, zero failures/errors and exit 0.
The skipped tests require live FSA or the separate full integration dataset.

Published correction commit: `819226f181b9624822216cc04298b06b520750d6`.
Both [PR CI](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/34598161580)
and [push CI](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/34598153219)
completed successfully. No merge or deployment followed those checks.
