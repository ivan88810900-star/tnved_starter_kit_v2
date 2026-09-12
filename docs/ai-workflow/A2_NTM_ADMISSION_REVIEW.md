# A2: Tamdoc admission and NTM review

Date: 2026-09-12. Work branch: `agent/ntm-compliance`.
Recovery base: PR #187 `22a7df5590a7442d943d89af285feb1228e80938`,
plus A0 shared admission dependency `22473e172c042f08cd5b72aece5dd221c54bdc9d`.

## Recovery and verification status

The executor disconnected after local Tamdoc commits `d620fff` and `b3b117a`.
This remote checkpoint reconstructs their confirmed behavior from the actual
GitHub source blob `543d2973f06eeb40d53f640e673d1c80effc4fa3` and recorded
edits. It is a new tree; old local test counts and HTTP smoke do not validate it.
Fresh agent CI and independent A5 review are required before A0 integration.
The unfinished historical legacy-v2 reader changes are not included here.

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
Current CI results must be attached to the new remote SHA by A0/A5.

## Remaining limitations

Historical mirror/v2 rows need a separate read-path correction: persisted
code-only `definite` is not reviewed applicability, and the old reader can borrow
a sibling leaf and ignore dates, direction, country and exclusions. That
reproduction and unfinished code must not be described as fixed by this commit.
The legacy candidate table stores one HS prefix and bounded excerpts; it is not
an immutable official manifest or a complete representation of document rules.

The published nine-family official advisory contour and bounded exact services
remain separate under DM-0008/0009/0010/0011. Structural coverage is not legal
applicability or proof of absence. No full rates/NTM completion is claimed.

A3's retained Decision 121/2026 source references earlier Decisions 12/2021 and
4/2026 and a publication-dependent start condition, without supplying a complete
numeric/product scope. Positive remedy interpretation remains blocked pending
the dependent official originals and reviewed temporal/product applicability.
