# DM-0013: Automatic regulatory-source updates

> **Status:** Accepted
> **Date:** 2026-08-23
> **Owner:** Ivan
> **Scope:** regulatory source registry, structured ingestion, source-change monitoring

## Decision

Every entry in `REGULATORY_SOURCE_REGISTRY` must have exactly one explicit update
policy. Automatic application is allowed only for deterministic structured
official registries whose adapters update evidence data without changing NTM
enforcement:

- CBR exchange rates;
- EAEU SGR, FSB notification and REO/VChU registries;
- FSA certificates, FTS TROIS and FTS document dictionaries.

OFAC SDN and EU consolidated feeds are fetched, parsed and validated on the daily
schedule, but scheduled runs cannot mutate their blocking tables. Applying a
reviewed sanctions snapshot remains a separate explicit operation that requires
the affirmative `--apply` flag; omitting `--validate-only` does not authorize a
promotion. This preserves
DM-0008's advisory/enforcement boundary while still detecting stale or malformed
official feeds automatically.

Official legal pages, PDFs, annexes, technical-regulation catalogs, Decision 30,
Decision 299 lists, veterinary/phytosanitary lists, PP 2425 and Russian export-
control lists are monitored automatically by URL, ETag and SHA-256. A changed or
unavailable source opens one review issue. A legal checksum advances only after a
manual default-branch run by a trusted repository actor, an existing Issue/PR
reference, an exact pending source-ID set and an unchanged pending digest. It never
updates a code rule, changes `definite`, or enters broker/enforcement without a new
verified extraction and the existing full-catalog gates.

Curated and legacy datasets are reconciled only after review. Commercial mirrors
remain optional and disabled by default. AI extracts always require manual review.

## Runtime and CI contract

- FastAPI APScheduler runs daily structured adapters at 03:00, weekly open-data
  adapters on Sunday at 08:00 and the curated review queue on day 1 at 13:00 in
  `REGULATORY_SYNC_TZ`.
- A process file lock for SQLite, PostgreSQL advisory lock and `max_instances=1`
  prevent overlapping writes. PostgreSQL adapters require the separate
  least-privilege `REGULATORY_SYNC_DATABASE_URL` role.
- Every adapter has a strict machine-readable result contract and explicit write-
  table allowlist. Empty, partial, fallback, implausibly shrunken or nested-error
  snapshots fail closed; full replacements and their success log commit atomically
  where the upstream artifact is a complete snapshot.
- Scheduled GitHub CI verifies 100% policy coverage, validates live CBR and official
  source artifacts, reconstructs and audits the exact 21/96/17,809 catalog, uploads
  evidence, then persists reviewed or pending checksum state. Pending legal drift
  remains a red gate while retaining the state needed for a later approval.
- `CUSTOMSCLEAR_READ_ONLY` continues to suppress scheduler startup and all writes.
- `NTM_V2_OFFICIAL_CURATED_ENFORCEMENT_ENABLED=0` remains the mandatory default.

## Rationale

Registry rows and exchange rates are machine-readable evidence and can be updated
idempotently. Sanctions feeds are also structured, but they directly participate
in a blocking control, so validation and promotion are deliberately separated. A
new legal document revision is not equivalent to a verified HS mapping. Splitting
structured ingestion, enforcement-sensitive staging and legal-source monitoring
provides fresh evidence without silently changing customs requirements for every
product code.
