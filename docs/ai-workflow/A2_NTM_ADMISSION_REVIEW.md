# A2: Tamdoc admission and NTM review

Date: 2026-09-12. Work branch: `agent/ntm-compliance`.
Recovery base: PR #187 `22a7df5590a7442d943d89af285feb1228e80938`,
plus A0 shared admission dependency `22473e172c042f08cd5b72aece5dd221c54bdc9d`.

## Recovery and verification status

The executor disconnected after local Tamdoc commits `d620fff` and `b3b117a`.
Recovery commit `bfc70cb621c9267ab3945f0e79c2a1cccb720000` reconstructs their
confirmed behavior from actual GitHub source blob
`543d2973f06eeb40d53f640e673d1c80effc4fa3` and recorded edits. Historical legacy-v2
reader changes were excluded from that first recovery checkpoint and are added
in `3335f808cff072e12ea4120cef72c9d1595cf86d`, described below. These are new remote
trees; old local test counts and HTTP smoke are not their validation evidence.
Independent A5 review and A0 integration remain required.

## Root causes and corrected behavior

Tamdoc previously wrote VAT preferences and special duties directly or following
candidate status approval. No retained official artifact, manifest-bound legal
review or separate approval existed. An administrator request and extracted
percentage cannot supply the missing legal authority.

A separate isolated reproduction showed archive sync with `staging_only=True`
expanding a code prefix into an active legacy NTM row. A nonpayment veterinary
candidate with conditional/exclusion text could be approved and imported into
v2 as `definite`, `requires_manual_review=False`. The pure shadow gate allowed
the permit without evaluating the product exception. No runtime flag was enabled
in that reproduction; it does not imply production enforcement was active.

The reconstructed correction preserves extraction, candidate listing and rejection:

- Payment and nonpayment approvals return `manual_review_required` without
  changing stored candidate status, active rows, source observations or logs.
  This includes historically approved payment candidates, disguised/malformed
  extraction and forged approval text.
- `include_non_tariff=False` cannot label a normative candidate approved merely
  because no active row would be written. Mixed batches report actual blockers.
- Document, targeted and archive sync retain pending hints and excerpts; explicit
  apply/automatic approval options cannot write active payment, NTM or TR records.
- Four private legacy writer functions reject before opening the DB.
- Technical extraction success is separate from legal freshness. Source observations
  stay stale/unreviewed; summaries report no active rates/NTM written.
- A0 owns the shared admission contract and API cache integration. This branch
  changes no DB model, migration, production flag or external source baseline.

## Verification scope

`tests/test_tamdoc_payment_admission.py` reconstructs the prior 69-case suite,
with synthetic parser/transport fixtures and isolated per-test SQLAlchemy sessions.
It checks payment payload/status combinations, both NTM approval options, batch
nonmutation, archive staging/automatic approval combinations, prefix expansion,
TR catalog protection, source freshness and preserved rejection/listing.
The agent workflow supplies an explicit temporary `DATABASE_URL` before imports.
No external mirror, AI request or application DB is used for these fixtures.
Fresh GitHub checks on the exact remote trees:

- `bfc70cb`: agent QA [34715094064](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/34715094064)
  passed, 177 tests passed and 1 skipped; full CI
  [34715094035](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/34715094035) passed.
- `3335f808`: agent QA [34715397545](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/34715397545)
  passed, 205 tests passed and 1 skipped, including 28 historical boundary cases;
  full CI [34715397563](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/34715397563) passed.
  The full CI includes backend NTM safety, frontend tests/types/build, scheduled
  workflow contracts and disposable local staging smoke. Official evidence
  acquisition was skipped on the agent branch; no deployment occurred.

These checks do not replace independent A5 hostile-case review or the final
integration checks on the combined PR tree.

## Remaining limitations

The historical legacy-v2 reader defect described below is corrected in
`3335f808`. This is a safe interpretation boundary for that reader, not an audit
or cleanup of all historical mirror records or every other legacy read path.
The legacy candidate table stores one HS prefix and bounded excerpts; it is not
an immutable official manifest or a complete representation of document rules.

The published nine-family official advisory contour and bounded exact services
remain separate under DM-0008/0009/0010/0011. Structural coverage is not legal
applicability or proof of absence. No full rates/NTM completion is claimed.

A3's retained Decision 121/2026 source references earlier Decisions 12/2021 and
4/2026 and a publication-dependent start condition, without supplying a complete
numeric/product scope. Positive remedy interpretation remains blocked pending
the dependent official originals and reviewed temporal/product applicability.

## Historical legacy-v2 reader correction (`3335f808`)

The separate local reproduction found a persisted exact-code legacy row with
expired validity, export direction, country restriction and exclusion text being
returned for both its own code and a sibling leaf as definite. The shadow gate
allowed its permit without product verification. This checkpoint corrects that
read path without changing historical rows during reads.

- Runtime candidates always expose needs_clarification, manual review and
  used_for_missing_check=false; stored applicability remains separately visible.
  Newly imported legacy metadata is also unreviewed. A forged positive field
  cannot bypass the legacy merge or suitability gate.
- Exact leaf rules do not attach to sibling/parent queries. Broader distinct
  candidates remain visible instead of being hidden by the first exact hit.
- Additive keyword-only as_of, country and direction context reaches the legacy
  reader and existing adapter. Explicit invalid as_of fails before opening the
  DB. Existing non-tariff callsite forwards its country/direction. No historical
  API endpoint or complete historical legal coverage is claimed.
- Known stored date/direction/country/code exclusions constrain technical matches.
  Missing, malformed or unavailable metadata remains a clarification diagnostic,
  never a positive legal absence statement. Existing stored valid_to convention
  is inclusive. This is not legal approval of the stored dates.
- Diagnostic counts remain available separately from legal authority. No legacy
  item is labeled an enforcement candidate from a code/text marker alone.
- The separate official exact/curated services remain the authority for their
  bounded reviewed contracts. This change does not copy their business rules.

Nine tests asserting the retired code-only positive contract were updated to
assert explicit nonpromotion, preserved metadata and unchanged missing/status
results. Existing mapping, source payload, idempotency, catalog permit hints and
unknown-TR regressions remain checked. The new
tests/test_ntm_legacy_review_boundary.py covers persisted/forged approval,
sibling leakage, broader family retention, both row/measure historical boundaries,
direction/country/exclusion constraints, malformed metadata, no-write reads and
context propagation. Fresh CI results are recorded above. Independent A5 review
is still required; the disconnected local pre-adaptation run is not completion
proof.

## Independent country-marker finding and corrective checkpoint

A5 independently confirmed that the first historical-reader checkpoint accepted
any two ASCII letters as a known country: stored `ZZ` and requested `CN` silently
dropped a candidate, while `ZZ`/`ZZ` omitted the country uncertainty reason.
The correction recognizes only the existing project's 161 country dictionary
keys in `scripts/seed_tariff_preferences.py` (at `3335f808`) plus `RU` already
listed in `frontend/src/pages/Calculator.tsx`. Only identities are copied;
preference groups, coefficients, legal references and seed execution are not
imported. No new legal rule or country table is introduced.

This set is deliberately incomplete. An unlisted valid country, unknown marker,
aggregate such as `EU`, or malformed stored/requested value remains a candidate
with `country_unverified`, never an exclusion inferred from an unknown token.
Known normalized identities still permit a technical mismatch filter; all retained
legacy candidates remain unreviewed. Agent fixtures add both unknown and known
country cases; independent A5 fixtures cover `ZZ`/`CN`, `CN`/`ZZ`, `ZZ`/`ZZ`
and `EU`/`CN`. Fresh corrective-checkpoint CI is required.

The one skip in the earlier agent profile is the unchanged
`test_ntm_v2_legacy_measures_import.py::test_smoke_real_db_sample`: it requires a
populated legacy catalog in the global test database. Agent CI uses a fresh
disposable DB; synthetic per-test regressions run independently. No application
database was used to satisfy that optional historical-data smoke.
