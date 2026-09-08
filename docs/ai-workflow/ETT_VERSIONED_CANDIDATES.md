# ETT versioned candidates — TASK-ETT-001

Status: Implemented and locally verified, 2026-09-08. Relates to [Decision #188](https://github.com/ivan88810900-star/tnved_starter_kit_v2/issues/188) and Draft PR #187.

Ivan approved Option A in chat; the approval was recorded in [the decision comment](https://github.com/ivan88810900-star/tnved_starter_kit_v2/issues/188#issuecomment-5584102215). He subsequently instructed development to continue without purchasing cloud storage. That authorizes the independent local implementation, not any legal dataset approval or production promotion. Yandex Object Storage has been recommended, but no provider account, paid resource, retention period or access credentials have been configured.

## Result and boundaries

The previous PDF importer could read the last number in a product description as a duty, default failed extraction to zero and fabricate VAT. PDF upsert, guessed ETT OData discovery, index-hash freshness and `load_full_tariff.py` now return `REVIEW_REQUIRED`. The old `/api/sources/sync/ett` endpoint also avoids cache-revision writes. Generic explicitly configured JSON/CSV feeds remain a separate legacy contour.

The new isolated path is:

1. Retain supplied source bytes in an explicit local SHA-256 store.
2. Validate a schema-v2 candidate and bind its complete normalized content to one digest.
3. Atomically stage five versioned tables: `ett_snapshots`, `ett_artifacts`, `ett_code_versions`, `ett_footnotes`, `ett_rate_rules`.
4. Compare candidate revisions and preview a rate for an explicit date, destination and product facts.

The schema requires exactly 96 chapter artifacts (01–76, 78–97), an index, nomenclature notes, tariff notes and an amendment inventory. A structurally present inventory is **not proof** that all current amendments are captured. Evidence binds an artifact hash, page/row locator and exact retained text hash; staging alone does **not** verify extraction of that quote from its PDF. TASK-ETT-002 adds a separate `verify-rows` check, which still does not approve legal interpretation. URL allowlisting is not download provenance.

Dates use explicit half-open intervals `[valid_from, valid_to)` and a finite snapshot coverage window. No dates are inferred from filenames, retrieval time, or HTTP metadata. Multiple nonoverlapping versions of one code are retained. Duty expressions support ad-valorem, specific, sum and maximum of components with exact decimals. TASK-ETT-003 adds explicit engine-displacement units and a bounded capped maximum; existing serialized candidates retain their exact hashes. Unknown formulas, unresolved footnotes and overlapping rules fail validation; missing product facts return `needs_clarification`. Out-of-window/no-match queries return `unavailable`, never an invented zero.

All results permanently say `mode=candidate_preview`. Candidate tables accept only `status=candidate` and `storage_kind=local_development`. There is no approve, promote, active-pointer or compatibility-materialization command/API in this slice. The existing calculator, VAT, `hs_rates`, official NTM enforcement and runtime flags remain unchanged. Quarantined schema-v1 staging data remains quarantined.

## Local operation

Run from `customs-clear/backend`. Use an explicit **isolated** SQLite database already migrated with Alembic, not an application/production database. Example placeholders below are operator-chosen paths, not existing artifacts:

```bash
python3 scripts/ett_candidates.py validate /path/to/candidate.json
python3 scripts/ett_candidates.py diff /path/to/previous.json /path/to/candidate.json
python3 scripts/ett_candidates.py stage /path/to/candidate.json \
  --database /path/to/isolated-candidates.db --store-root /path/to/objects
python3 scripts/ett_candidates.py preview MANIFEST_SHA256 \
  --database /path/to/isolated-candidates.db --store-root /path/to/objects \
  --code 0101210000 --as-of 2026-09-01 --destination RU
```

Every artifact declared by the manifest must already exist in the supplied local store, populated through `LocalArtifactStore.put(original_bytes)`. Staging verifies all source objects and retains canonical manifest bytes. The separate `acquire` and `extract` commands introduced in [TASK-ETT-002](ETT_SOURCE_EVIDENCE.md) prepare technical source evidence without staging a legal candidate. JSON manifests and individual source artifacts are bounded to 64 MiB. Numeric product facts use lossless plain decimal strings or integers; binary floating-point values are rejected. `--facts` accepts a JSON file.

Local publication is atomic and does not overwrite an existing digest. Reads verify hashes, sizes, file identity and private ownership/permissions. Symlinks, hardlinks and unsafe paths are rejected. This POSIX development store is not Object Lock and is not durable archival proof. On systems without POSIX locking, only this optional store fails; importing the application remains possible.

For authenticated admin preview, configure `ETT_CANDIDATE_STORE` to an existing local store and migrate the candidate database. Read-only routes:

- `GET /api/sources/ett/candidates`
- `GET /api/sources/ett/candidates/{sha256}/readiness`
- `POST /api/sources/ett/candidates/{sha256}/preview` with `code`, `as_of`, `destination`, optional `facts`.

The listing is metadata only and explicitly says `integrity_checked=false`. Preview/readiness revalidate the complete candidate and all retained source objects. This intentionally expensive development check is not a production serving-performance claim. SQLite reads explicitly pin a transaction; CLI preview additionally uses `mode=ro` and `query_only`. Staging uses a separate fresh session, SQLite `BEGIN IMMEDIATE` or a PostgreSQL transaction-scoped advisory lock, plus foreign-key checks. PostgreSQL DDL was generated offline; no live PostgreSQL instance was exercised.

## Verification

- 304 new ETT tests; complete configured backend CI suite: **1,056 passed**.
- SQLite full upgrade, downgrade to `r1s2t3u4v5w6`, and upgrade to `e1t2t3s4n5p6` succeeded on an isolated database.
- PostgreSQL new-revision offline DDL succeeded.
- Authenticated uvicorn/curl checks passed for health, candidate listing, readiness, date-specific preview and the existing NTM check, with read-only startup and no scheduler.
- Synthetic fixtures are explicitly labeled. Their 100 placeholder artifacts test schema shape, not official-document authenticity, a complete commodity catalog or current duty accuracy.

## Next implementation sequence

1. [TASK-ETT-002](ETT_SOURCE_EVIDENCE.md) implements bounded official index acquisition, source-body retention, reproducible PDF rows and a candidate quote verifier. The explicit CI acquisition path has retained the current index and all 100 core PDFs. The current corpus audit covers all 13,293 rows from 96 chapter PDFs. Complete amendment capture and legal interval interpretation remain unfinished; see [TASK-ETT-003](ETT_TABLE_INTERPRETATION.md). No downloaded set directly updates `hs_rates`.
2. [TASK-ETT-003](ETT_TABLE_INTERPRETATION.md) assembles full code descriptions, complete rate cells and source-backed note clauses. Complete a current capture, then bind footnote interpretation and effective dates to verified PDF rows; report all unresolved cases and semantic differences. Quote existence alone does not verify interpretation. Reconstructing historical 2022–2026 law is a separate project.
3. Implement manifest-bound review records, retention-capable storage attestation and atomic reviewed promotion, then a compatibility materialization and product `as_of` integration. Architecture approval alone cannot satisfy these gates.
4. Continue the NTM workstream: exact source-row and registry evidence for SGR, cryptography/notifications, radio equipment, licenses, sanitary/veterinary/phytosanitary conditions, technical conformity and export control. Improve trusted registry checks without changing broad candidates into mandatory documents.
5. Connect the already implemented source lifecycle to the chosen deployment, verify live behavior and alerts, and keep legal changes review-bound. Merge, deployment and enforcement require their separately agreed authorization.
