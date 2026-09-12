# TASK: Restore and finish payment admission safety

Status: In progress, 2026-09-12. PR #187, Option A of issue #188.

## Goal

Close every identified public rate-write path that accepts a legacy bundle or
commercial extraction without original evidence and manifest-bound review.
Keep technical parsing, offline versioned ETT previews and isolated fixtures.

## Verified recovery boundary

Remote `5f715ae` contains the numeric, payment applicability and NTM guards,
exact provisional ETT arithmetic, original-body capture and corrected official
navigation. The later uncommitted admission changes and their reported local
tests were lost with the workspace. They are not part of this commit or proof
that the remaining paths are fixed.

## Remaining implementation and acceptance

- Six dedicated legacy apply services: preserve parse errors; reject otherwise
  valid legacy rates before DB planning, rate writes or provenance stamps.
- Generic file/bundle/feed writers: reject rate-bearing payloads atomically,
  including mixed catalog/rate payloads, before any DB write. Catalog-only
  preparation and explicit isolated structural fixtures remain available.
- Tamdoc payment writers and candidate approval/batch: commercial review must
  not approve legal rates. Preserve pending staging and rejection/listing.
- Normalization, source plans, coverage and backfill: URL/revision/SourceStatus
  and row markers must not imply legal provenance, `present`, ready-to-ingest
  or recommend applying unreviewed rates. Preserve technical counts.
- Rejected public applies must not bump application preview-cache revision.
- Test genuine zero, invalid numeric inputs, forged approval fields, alternate
  imports, atomic no-write behavior and existing parser/private fixture behavior.
- Run the relevant CI profile on an explicit fresh test DB, then real HTTP
  smoke after Uvicorn restart; publish commits and verify remote CI.

## Source work still open

The four-original archive from run 34600642623 is retained independently of CI.
The two rejected navigation responses need a separate quarantined capture for
diagnosis. The already captured Decision 121 PDF and FNS pages need source-bound
interpretation and dependent original acts, not automatic acceptance. The full
ETT note worklist, VAT/excise/remedies/preferences/origin legal coverage, trusted
review and durable retention remain unfinished gates.

## Boundaries

No positive grant is inferred from administrator access or payload fields.
No production/application DB writes, merge, deploy, rollout or enforcement
activation. Draft PR #189 remains separate. The full rates-and-sources block
must not be reported complete from test counts or this recovery task alone.
