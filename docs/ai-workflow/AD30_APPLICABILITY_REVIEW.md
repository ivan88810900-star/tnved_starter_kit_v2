# AD30 product assessment for an offline review candidate

Status: implementation complete and independently approved by A5, 2026-09-14.
Exact integrated/publication CI is recorded by the integration task.

This adds an executable interpretation of the retained Decision 12 product
wording to the source-fact preparation already recorded in PR #192. It does not
replace that document, admit a rate or establish current/historical law.
Accepted issue #188 Option A and DM-0011/DM-0014 permit this non-activating
preparation; human manifest review and separate admission remain outstanding.

## Boundary and interface

`app.services.ad30_applicability.assess_ad30_candidate` is a pure function:

```python
assess_ad30_candidate(*, as_of: date, facts: Mapping[str, object],
                     source_facts: AD30SourceFacts | None = None) -> dict
```

The function revalidates even a caller-supplied frozen source DTO against A3's
pinned dossier. It binds the result and every product criterion to the dossier,
the original source-record SHA, JSON pointer, original-body SHA and page/locator.
That verifies the tracked source records. It does not re-read PDF bytes or
independently verify their contents. The result labels both limitations.

`candidate_scope` is one of `matches_source_candidate`,
`outside_source_candidate`, `needs_clarification`. A match means that the supplied
facts satisfy the bounded interpretation below. An outside result means that a
known conjunct of this literal candidate does not match; it is **not** a finding
of legal exemption or absence of any duty. Malformed or contradictory supplied
facts take precedence over a known mismatch. Otherwise a known false conjunct
can exclude this candidate even when unrelated facts are missing.

Every result has `legal_applicability="unavailable"`, `requires_manual_review=true`
and `legal_review_verified=false`, `effective_dates_verified=false`,
`can_promote=false`, `final_payable=false`, `db_mutated=false`.
No producer row is selected. There are no DB calls, live API routes, NTM broker
changes, rate writes, network calls, clocks, feature flags or payment components.

## Source fact versus interpretation

The source DTO binds these IDs to the tracked
[Decision 12 evidence](evidence/eec-ad30-decision12-capture-review-20260912.json).
Its full product observation is an English source-reading summary; it is not
misrepresented as an exact Russian transcription. The dimensional fragments and
joint-code/name phrase are literal source excerpts.

| Input predicate | Source fact ID / locator | A2 interpretation tested |
|---|---|---|
| `direction`, `destination` | `d12.product`, clause 1, pages 1–2 | Explicit import into one of AM/BY/KG/KZ/RU |
| `origin_country` | `d12.origin`, clause 1 | Explicit CN origin, independent of destination or producer name |
| `tubular_product`, `welded`, `corrosion_resistant_steel` | `d12.product`, clause 1 | All three exact boolean facts must be true |
| `commodity_code` | `d12.codes`, clause 1 continued; `d12.joint_code_description`, clause 2, page 2 | Exact ten-digit input matches one of the four printed codes **and** product conditions match |
| `wall_thickness_mm` | `d12.wall`, clause 1, page 1 | 0.4 through 6 mm, inclusive |
| `cross_section="round"`, `outer_diameter_mm` | `d12.round_diameter`, clause 1, page 1 | Explicit round section, outer diameter 6 through 115 mm, inclusive |
| `cross_section="square"`, `perimeter_mm` | `d12.square_perimeter`, clause 1, page 1 | Explicit square section, perimeter at most 400 mm |
| `cross_section="rectangular"`, `perimeter_mm`, `max_side_mm` | `d12.rectangle_dimensions`, clause 1 continued, page 2 | Both perimeter at most 400 mm and maximum side at most 120 mm |

The source names three alternatives: round, square or rectangular. The function
does not invent a mapping between shapes and individual codes or a taxonomy
that assigns an unlabeled shape from equal-side dimensions. Explicit `other`
means the caller declares that none of those three named alternatives describes
the section; an unrecognized shape string remains unresolved.

The source prints four historical code strings: `7306 40 200 9`,
`7306 40 800 1`, `7306 40 800 8`, `7306 61 100 9`. Removing their printed spaces
for literal comparison is not a nomenclature transition. Prefixes, non-ASCII
digits, integer inputs, code padding and inferred current-code substitutions are
not accepted. Even an exact printed-code match retains the unresolved historical
mapping blocker for every requested date.

All measurements must be positive, exact millimetres supplied as bounded plain
decimal strings, integers or `Decimal`. Floats, bools, NaN/infinity, excessive
precision/exponents, signed/space-padded/unit-bearing strings, zero and negative
measurements are invalid. Positive dimensions are an input-validity requirement,
not an extra regulatory minimum. Missing dimensions are not calculated from
other dimensions. Every supplied measurement is validated, including one not
needed by the declared shape, before any exclusion can be returned.

For an explicitly rectangular section with both supplied perimeter and maximum
side, contradictory values `perimeter <= 2 * max_side` or
`perimeter > 4 * max_side` require clarification. This exact rational comparison
checks consistency of the supplied measurements and does not fill a missing
regulatory field. No assumption about corner radius or wall uniformity is used
to derive an inner hole, missing side, shape or legal exception.

Country identity recognition is deliberately partial: the five EAEU destination
identities plus CN, US, DE, GB, JP, KR, IN and TR. This is not an origin registry
or tariff preference list. Unlisted identities, including valid countries outside
that bounded set, remain `country_identity_unverified`; ZZ, EU and EAEU cannot
become a known country mismatch. Names/aliases and lowercase values are not
silently normalized. Expanding this technical set requires a separate explicit
change and tests, without implying legal origin verification.

## What remains unresolved for Decision 12 → 4 → 121

The supplied `as_of` is mandatory and must be a calendar `date`, not a timestamp
or implicit current day. It is recorded without selecting legal intervals.
The Decision 4 preliminary-collection procedure, Decision 121 crediting/repeal,
publication authority, relative 30-day clauses and inclusive end dates have not
been translated into admitted temporal rules. Quarantined portal card dates
cannot satisfy that gap.

The complete amendment/repeal inventory, historical nomenclature, producer
identity/succession, actual transaction/product evidence, independent original
text verification, human manifest review, separate approval and attested object
versioning/retention/legal hold remain blockers even for a literal product
match. A missing or unrecognized producer is never treated as `прочие`; an exact
name is never sufficient to select either named producer. A1's separate explicit
source-row scenario can display hypothetical arithmetic only and must carry all
these limitations.

## Validation and handoff

Author tests cover all four printed codes and three declared shapes without a
shape-code mapping; inclusive bounds and just-outside values; rectangular
conjunction; missing facts; known and unknown countries; wrong direction;
non-tubular/seamless/non-stainless declarations; malformed measurements and
unsupported fields; contradictory dimensions; explicit historical dates;
source-DTO tampering; unchanged input data; and Decimal-context independence.
Every relevant branch asserts unavailable legal applicability and no final amount
or admission grant. Author verification against A3 source commit
`2bfa1799e11eefb371b548ace46aca9feee47fd2`:

```text
python -m pytest -q tests/test_ad30_source_facts.py tests/test_ad30_applicability.py
200 passed in 0.64s
```

This historical author run is 44 source tests and 156 product-assessment tests.
A5 subsequently completed independent source interpretation and hostile-case
verification: 43 independent cases and a 449-case combined profile passed.
See [A5 evidence](evidence/ad30-independent-qa-20260914.json); the original author
run alone is not independent acceptance. No runtime API
was added or changed; runtime HTTP and full CI checks belong to the combined
integration gate and are not claimed by this isolated pure-function test run.
