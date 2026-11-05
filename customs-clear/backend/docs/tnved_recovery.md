# TN VED structural recovery

This builder creates a new isolated SQLite from the pinned 96-chapter catalog.
It does not open or modify the application/staging database and does not import
duty rates, NTM data, validity dates, or a reviewed/legal status.

```bash
export TNVED_RECOVERY_SOURCE_DIR=/path/to/Declarant-full96-ingest
python scripts/build_tnved_recovery.py \
  --catalog "$TNVED_RECOVERY_SOURCE_DIR/data/tnved/catalog.json" \
  --ett-index "$TNVED_RECOVERY_SOURCE_DIR/data/tnved/raw/ett-index.html" \
  --output /new/recovery/tnved-structure.sqlite \
  --manifest /new/recovery/manifest.json
```

The command requires the approved catalog and saved EEC-index SHA-256 values,
validates the complete node/source/edition/note sets, duplicates, orphans and
parent cycles, builds with foreign keys enabled, and runs `integrity_check` and
`foreign_key_check`. Repeating it with the same bytes produces the same SQLite
and logical-content hashes. It refuses to overwrite an existing output path, so
each recovery is placed in a new dated directory.

The GitHub offline-safety workflow also exercises the same validation, schema,
deterministic build, immutable reopen, integrity/FK checks and read-only adapter
against a generated synthetic 96-chapter fixture.  The operational `build()` and
CLI remain bound to the approved source hashes; the synthetic fixture contains no
private snapshot bytes and cannot establish source completeness for the real data.
The mandatory runner fails if it discovers no recovery subject tests, does not
execute every discovered test, or skips every subject test; its final summary
records discovered, executed and skipped counts.

## 2026-10-20 builder compatibility assessment

The accepted bundle remains attributed to PR head
`bc8a24542549725aa7c73ad7160ba41c7a76cc4f` and reviewed tree
`4caf1d03f0d718cac7b8d462e66090c423ecb9ee`; later CI refactoring does not
relabel that historical artifact.  The refactored operational `build()` still
supplies the same immutable catalog/index hashes, counts, chapters and section
count to the shared implementation.  Running that operational entry point on
the pinned accepted inputs produced a byte-identical SQLite with SHA-256
`c5959912f7c1a3e8c0329130d511243c9ead4e5ae5501dc7ce7facff2d6bdff4` and
logical SHA-256
`be57fc61571bee51817e5a0915918d7f3baa86873c644ce148c613b1b20589e6`.
This establishes output equivalence for those exact accepted inputs; it is not
a new legal/source acceptance and does not replace the private dated Mac
verification receipt.

All 18,014 catalog nodes remain strings, including leading zeroes. Their full
`path_json` retains 3,172 uncoded intermediate labels. Source/page references,
note links, change symbols, source hashes and the 96 unverified editions are
retained. `valid_from`/`valid_to` remain NULL and `complete` remains false.

The 21 sections are parsed separately from the pinned `ett-index.html` and map
all 96 chapters. The source writes sections XII and XIV with Cyrillic `Х`; the
database preserves that in `raw_roman_number` and uses Latin `XII`/`XIV` only as
the normalized structural key.

`TnvedRecoveryStore` opens the database with SQLite `mode=ro` and exposes only
structural status, lookup, breadcrumb and search. Every lookup explicitly reports
`rates=None` and the snapshot status stays `unverified`. The `tnved_entries`
table is a compatibility projection for the existing TnvedEntry-shaped read
path; its `source_revision` is the unverified edition id, not legal admission.
