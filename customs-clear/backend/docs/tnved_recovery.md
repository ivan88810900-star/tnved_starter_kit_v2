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

## Local HTTP/UI read profile (2026-11-06)

The explicit `app.recovery_main:create_app` factory serves the **existing**
recovery store through the existing React dictionary/tree. It does not import
`app.main`, `app.db`, dotenv, migrations, seeds, schedulers, rate/NTM services,
or providers. This is a local structural read profile, not a production cutover.
No ORM catalog or second materialized catalog is created.

Use a dedicated copy of the already accepted SQLite, not the backup itself.
The caller must supply its explicit SHA-256; startup rejects missing/changed
files, sidecars, and mismatched pins. Requests fail with 503 if the bound file
identity changes or sidecars appear. All store connections use SQLite `mode=ro`.

From the repository root, after building `customs-clear/frontend`:

```bash
TARIFF_PY=/absolute/path/to/isolated/venv/bin/python
env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 \
  TNVED_RECOVERY_DB=/absolute/path/to/working-copy/tnved-structure.sqlite \
  TNVED_RECOVERY_SQLITE_SHA256=c5959912f7c1a3e8c0329130d511243c9ead4e5ae5501dc7ce7facff2d6bdff4 \
  TNVED_RECOVERY_FRONTEND="$PWD/customs-clear/frontend/dist" \
  "$TARIFF_PY" -m uvicorn app.recovery_main:create_app --factory \
  --app-dir customs-clear/backend --host 127.0.0.1 --port 18001
```

Open `http://127.0.0.1:18001/tnved`. The API exposes search, structural detail,
breadcrumb and direct children using the same snapshot. Health and catalog
responses identify the pinned SQLite SHA-256. The existing dictionary page
selects its structural card from the explicit `recovered_catalog` capability.
The card displays source/edition/page and the full original `path`, including
uncoded labels. Parent/child navigation follows saved edges; no fake codes or
new intermediate nodes are synthesized. Rates remain null, dates unknown and
source status unverified. Other application workflows are outside this profile.

Run regression in `customs-clear/backend`:

```bash
"$TARIFF_PY" -m unittest -v tests.test_tnved_recovery_http \
  tests.test_tnved_catalog_api.HermeticTnvedCatalogApiTests
"$TARIFF_PY" scripts/run_tnved_recovery_ci.py
```

`frontend/scripts/recovery-browser-check.cjs` drives a real browser against the
built application without substituting responses. It takes the local base URL,
a JSON expectation derived read-only from the pinned working SQLite, and an
output directory. Fields: `snapshot_sha256`, `code`, `name`, `path`, `parent`,
`parent_name`, `child_codes`. It requires Playwright in `NODE_PATH`; optionally
set `PLAYWRIGHT_CHROMIUM_EXECUTABLE` to an installed Chrome binary. The desktop
bundled Playwright runtime was used for the recorded local acceptance.

## Official tree fidelity candidate (2026-11-06)

The historical acceptance above remains scoped to its original bytes. The next
local candidate is built from all actual chapter links on the saved official EEC
index, with separate accepted/current source hashes. See
`docs/operations/TARIFF_TREE_FIDELITY_20261106.md` and its per-chapter ledger.
The accepted builder entry point and its immutable pins are unchanged.

`app.services.tnved_fidelity` extracts header-gated PDF table cells with Poppler
word coordinates. `audit_tnved_official.py` independently checks layout code-cell
occurrences and the pinned retained physical-cell inventory, then compares every
source row/edge/name/path/order/page with HTTP. It exits nonzero on proof failures.
Rates columns and prose references cannot introduce codes. Reserved bracketed
positions are recorded separately and do not become active tariff codes.

From `customs-clear/backend`, with read-only source directories and NEW outputs:

```bash
"$TARIFF_PY" scripts/audit_tnved_official.py \
  --accepted-root "$ACCEPTED" --current-root "$OFFICIAL" \
  --baseline "$ACCEPTED_SQLITE_COPY" --output "$AUDIT" --pdftotext "$PDFTOTEXT"
"$TARIFF_PY" scripts/build_tnved_fidelity.py \
  --source-root "$OFFICIAL" --rows-root "$AUDIT/source-rows" \
  --accepted-catalog "$ACCEPTED/data/tnved/catalog.json" \
  --accepted-catalog-sha256 c7e4e5bb52b103d8b13554b4e25bf12ea0d09b4d67494e236a55cc276a173d41 \
  --manifest-sha256 baa2708f444176a493c2553972b20516bc6473d6e83348db4f9929e27dd2faa2 \
  --output "$NEW_SQLITE"
```

The candidate reuses the recovery schema and validator. Its navigation tables
are a source-derived projection in that SAME SQLite, not a second live catalog.
Use the resulting manifest's SQLite SHA in the existing local factory command.
The recorded candidate hash is
`725b784d8185c2f9a6a0378886199e01e19df9501688e1dbdbc3fe803a153591`.
No application/persistent database is opened. Existing outputs are never replaced.

Navigation identifies actual printed codes by their exact strings and uncoded
rows by stable `u-` IDs bound to source PDF hash/page/baseline. Uncoded rows have
no HS code. Equal labels remain distinct. `source_order` determines children;
all breadcrumbs include uncoded source ancestors. A unique depth-zero combined
printed row can have an explicit four-digit heading alias; detail returns the
actual code and `navigation_alias`, never a substituted normative identity.

Numeric search matches code prefixes only. Text search matches labels/paths.
Search returns `total`, `offset`, `limit`, `mode`, and snapshot/query-bound
next/previous/last cursors; invalid cursors return 422. Children either return
the complete direct list or fail explicitly. The UI separates loading, loaded,
empty and failed states, with a retry that calls the real endpoint.

```bash
"$TARIFF_PY" -m unittest -v tests.test_tnved_fidelity \
  tests.test_tnved_recovery_http \
  tests.test_tnved_catalog_api.HermeticTnvedCatalogApiTests
"$TARIFF_PY" scripts/run_tnved_recovery_ci.py
"$TARIFF_PY" scripts/audit_tnved_official.py \
  --accepted-root "$ACCEPTED" --current-root "$OFFICIAL" \
  --baseline "$ACCEPTED_SQLITE_COPY" --output "$AUDIT" --pdftotext "$PDFTOTEXT" \
  --candidate "$NEW_SQLITE" --url http://127.0.0.1:18001
```

`frontend/scripts/fidelity-browser-check.cjs BASE_URL SOURCE_EXPECTATIONS OUT`
drives real Chrome against the built app. Expectations come from independently
extracted source rows/index, not candidate HTTP responses or SQLite. It checks
all 96 titles, expanded 01/30/84/85/94/95, source paths/cards, clipboard leading
zeroes, complete numeric pagination and a separate failed-request/retry case.
Successful responses are never replaced. The 125% case uses a 1024 CSS-pixel
viewport with DPR 1.25 to represent a physical 1280-pixel desktop viewport.
The earlier `recovery-browser-check.cjs` is the limited historical c595 profile
check; it is not the all-chapter acceptance.

Historical notes/provenance remain stored, but the UI does not admit them as
current law. Legal applicability, completeness, dates and rates remain unverified.
The official index/PDF Latin-H versus Cyrillic-Н title discrepancy in chapter 41
is retained in the report; the chapter navigation takes the index title.

## Claude findings: source text projection (2026-11-09)

The audited `725b784d...` snapshot and audit packet remain unchanged. A NEW local
candidate has SHA-256
`99f70ee34caa30637663c4c1a4e847958bfcfe663f4f5136e3d0b02725e0ef1f`.
See `docs/operations/TARIFF_CLAUDE_ADJUDICATION_20261109.md` for adjudication,
source coverage limits, commands and the requirement for targeted Claude recheck.

The source build now also requires `requirements-tnved-source.txt` (pdfplumber
and pdfminer pins). Use a separate source-build Python environment for
`audit_tnved_official.py`; HTTP and synthetic CI do not import these libraries.
The prepared source runtime was used without installing anything in the HTTP venv.

Wrapped lexical hyphens keep their glyph without an inserted space. Suspended
forms such as `газо- или` retain their separator. Unhyphenated split words join
only with matching PDF character evidence that no separator was encoded. A space
just beyond the final word's ink is included even beyond the nominal text-column
cutoff. Unknown character boundaries prevent building a candidate.

`recovery_source_text` is a provenance/display projection inside the SAME new
SQLite, with raw label, original lines/page/baseline/character evidence and dash
depth. API detail exposes `raw_name`, `source_lines`, `dash_depth`, `kind`; children
expose depth/kind. Captions have no dash, and the tree renders the source depth
instead of a fixed one/two-dash placeholder. Node identity/edges/order/aliases do
not change. Reserved positions and footnote/index typography remain separate
open presentation questions; no active code or legal meaning is invented.
