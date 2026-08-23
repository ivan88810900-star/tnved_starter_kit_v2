# DM-0013: Automatic regulatory-source updates

> **Status:** Accepted
> **Date:** 2026-08-23
> **Owner:** Ivan
> **Scope:** regulatory source registry, structured ingestion, source-change monitoring

## Decision

Every entry in `REGULATORY_SOURCE_REGISTRY` must have exactly one explicit update
policy. Automatic application is allowed only for deterministic structured
official registries whose adapters upsert evidence data without changing NTM
enforcement:

- CBR exchange rates;
- EAEU SGR, FSB notification and REO/VChU registries;
- FSA certificates, FTS TROIS and FTS document dictionaries;
- OFAC SDN and the EU consolidated sanctions dataset.

Official legal pages, PDFs, annexes, technical-regulation catalogs, Decision 30,
Decision 299 lists, veterinary/phytosanitary lists, PP 2425 and Russian export-
control lists are monitored automatically by URL, ETag and SHA-256. A changed or
unavailable source opens one review issue. It never updates a code rule, changes
`definite`, or enters broker/enforcement without a new verified extraction and the
existing full-catalog gates.

Curated and legacy datasets are reconciled only after review. Commercial mirrors
remain optional and disabled by default. AI extracts always require manual review.

## Runtime and CI contract

- FastAPI APScheduler runs daily structured adapters at 03:00 and weekly open-data
  adapters on Sunday at 04:00 in `REGULATORY_SYNC_TZ`.
- A non-blocking file lock and `max_instances=1` prevent overlapping local writes;
  adapters run sequentially and report partial failure without hiding other results.
- Scheduled GitHub CI verifies 100% policy coverage, persists the source checksum
  baseline, runs the existing NTM/export-control/catalog audits, and queues source
  drift for review.
- `CUSTOMSCLEAR_READ_ONLY` continues to suppress scheduler startup and all writes.
- `NTM_V2_OFFICIAL_CURATED_ENFORCEMENT_ENABLED=0` remains the mandatory default.

## Rationale

Registry rows and exchange rates are machine-readable evidence and can be updated
idempotently. A new legal document revision is not equivalent to a verified HS
mapping. Splitting structured ingestion from legal-source monitoring provides
fresh data without silently changing customs requirements for every product code.
