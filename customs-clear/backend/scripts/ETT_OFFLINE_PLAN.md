# Offline ETT normalization plan

This runner validates an explicitly supplied local package and generates a
reviewable plan plus PostgreSQL SQL. It never connects to a database, reads an
ambient database URL, uses the network, or executes the SQL.

## Command

```bash
python -S scripts/ett_offline_plan.py \
  --package /authorized/local/package \
  --output-dir /new/local/output-directory
```

Inspect the machine-readable package schema without optional dependencies:

```bash
python -S scripts/ett_offline_plan.py --print-package-schema
```

The output directory must not exist. It is published atomically only after the
whole package validates and contains exactly `plan.json` and `apply.sql`.

## Package

`package.json` is UTF-8 JSON with these top-level fields:

- `schema_version`: `1`.
- `normalizer_version`: the version implemented by this checkout.
- `source_object`: the complete staged source identity and immutable byte digest.
- `ingest_run`: deterministic run identity, complete `scope`, counts, and cursor.
- `raw_rows`: the complete staged RAW row set.
- `artifacts`: descriptors for `source_bytes`, `retained_manifest`, and
  `retained_extraction`; each descriptor has a package-relative `path`, `sha256`,
  and `size_bytes`.

The retained manifest must use one of two explicit schema-version-1 forms. The
flat form binds source ID/revision and source/extraction byte digests directly.
The retained legacy form has no scalar source ID; instead its source URL,
revision, authority, dataset, capture/status metadata, chapter, and exact
`objects.original` fields are bound to the already validated source/run
identity. Its `objects.extraction` bucket, sibling key, JSON media type, digest,
and size are bound to the validated extraction artifact. Values found only in
unrelated nested fields never satisfy a binding. The retained bytes are read and
validated in place and are not rewritten.

The legacy manifest `chapter` is bound to `ingest_run.scope.chapter`; an
invented or legacy `scope.group` value is not substituted. Its `captured_at`
and the staged source timestamp must both be valid timezone-aware ISO-8601 values
for the same instant, so equivalent `Z` and `+00:00` spellings are accepted
while naive, invalid, or different instants fail closed.

The legacy `admission` object has exactly `normalized`, `verified`, and
`admitted`, bound to the zero-valued staged run counters. Its extraction object
has exactly `raw_count`, `unique_count`, and `next_ordinal` alongside the
object identity fields; these values are bound to the validated run counts and
resume cursor. The runner does not rename or rewrite retained keys.

The retained extraction may be either a row array or an object containing
`rows`; every row is matched to RAW and page/line provenance. Raw-byte SHA-256
and size are always checked before JSON parsing. Run `--print-package-schema`
for exact package fields.

## Output contract

`plan.json` records the verified inputs, normalized rows, expected counts,
normalization digest, SQL digest, plan digest, and invariants. `apply.sql`:

- targets only `tariff_staging.tariff_ingest`;
- contains no connection or transaction-boundary command;
- validates source, run, RAW rows, target columns, nullability, PK, unique and FK
  contracts before inserting results;
- treats an exact same-version replay as zero mutations;
- rejects incomplete or conflicting same-version state;
- keeps a new parser version as separate history;
- never changes RAW or product tables.

The operator must execute the reviewed SQL inside one explicitly owned,
authorized transaction. Generation is not execution. All results remain
technical `UNVERIFIED` data with `verified=false` and `admitted=false`.

## Legacy 533-row preview

A separately recovered legacy chapter-29 envelope can be converted into a
deterministic JSON-only technical preview:

```bash
python -S scripts/ett_legacy_normalization_preview.py \
  --recovery-envelope /authorized/local/recovery-envelope.json \
  --original /authorized/local/original.pdf \
  --source-text /authorized/local/source.txt \
  --output /new/local/preview.json
```

The command requires the exact original and page-aware source-text bytes that
were used to reconstruct the recovery envelope. It rejects duplicate JSON keys,
non-finite JSON numbers, evidence drift, incomplete runs, and any existing
output path. The completed preview is linked into place atomically and is never
used to generate SQL or contact a database or network service.

Every preview row retains its legacy run ID, historical parser version, raw-line
SHA-256, original fields, and page/line provenance. Repeated HS codes remain
separate when their raw identities differ. All rows and summary counts remain
technical `UNVERIFIED` results with `verified=0` and `admitted=0`.

