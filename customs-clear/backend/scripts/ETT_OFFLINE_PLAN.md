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

The retained manifest is JSON that binds source ID/revision/byte digest to the
retained extraction digest. Its existing envelope may be preserved. The retained
extraction may be either a row array or an object containing `rows`; every row is
matched to RAW and page/line provenance. Raw-byte SHA-256 and size are always
checked before JSON parsing. Run `--print-package-schema` for exact package fields.

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

