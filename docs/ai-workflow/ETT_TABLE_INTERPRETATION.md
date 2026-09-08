# ETT complete cells and note evidence — TASK-ETT-003

Status: implementation and historical-corpus verification, 2026-09-08. This continues approved Decision #188 Option A. The **complete current legal rates block is not ready**: current original documents have not been captured in this environment, and no legally reviewed manifest has been produced.

## Source-preserving interpretation

`ett_table_assembly.py` re-extracts the original PDF bytes before assembling commodity rows. It distinguishes 4/6/8/9-digit headings, exact 10-digit commodity rows, uncoded headings and narrative code mentions. It retains description, supplementary unit and complete duty cells across supported line/page continuations. Hierarchical descriptions are display paths assembled from retained labels, not newly authored legal descriptions. Missing or ambiguous boundaries remain diagnostic results.

The PDF evidence format now retains text spans with font, size, baseline and coordinates in addition to physical word rows. `ett_duty_typography.py` requires mutually consistent word/span evidence before separating a superscript note from a duty. For example, the retained string `563С)` is separated into `5 63С)` only when the original glyph geometry proves that distinction. Merely recognizing digits or a font flag is insufficient. Source row text and hashes are preserved unchanged.

`ett_duty_cells.py` consumes complete isolated cells, requires a proven percentage header for a bare number, and parses the whole expression using exact decimals. It does not select the final number, silently drop unfamiliar suffixes or convert failures into zero. A parsed expression is a lexical result; footnotes and legal applicability remain unresolved until interpreted against the relevant edition.

`ett_notes.py` retains every note's source rows, exact labels, repeal references, country clauses and temporal candidates. Inclusive end dates receive arithmetic conversion only when inclusiveness is explicit. Dates relative to entry into force remain unresolved. Gaps in note numbering do not establish missing documents; duplicate identifiers are never treated as valid bindings. Neither note-ID matching nor a recognizable date clause proves that a rate applies.

## Legal document capture

Acquisition receipt v2 retains an immutable inventory of actual attachment links found on captured official document pages and downloads discovered PDF attachments. Original and resolved hrefs, visible document identity and source HTML hashes are retained. Unsupported DOCX and other attachments are listed explicitly; their contents are not assumed to be captured. Receipt v1 remains verifiable with its original narrower meaning.

Receipt verification re-derives the attachment plan from retained HTML, checks the inventory object and requires every planned PDF with its original hash and size. It cannot certify undiscovered amendments, an atomic legal edition or the contents of unsupported attachments. Live portal/index DOM compatibility has not been established from current original bytes; synthetic layout fixtures are labeled accordingly.

## Operation

From `customs-clear/backend`, using an explicit private development store:

```bash
python3 scripts/ett_candidates.py acquire --store-root /path/to/private-objects
python3 scripts/ett_candidates.py extract RECEIPT_SHA256 --store-root /path/to/private-objects
python3 scripts/ett_candidates.py analyze RECEIPT_SHA256 --store-root /path/to/private-objects
```

`analyze` verifies the receipt and original objects, extracts tariff notes, assembles all 96 chapters, checks typography, parses cells and reports unresolved note references. It retains the individual reports and publishes their digest-bound index only after completing the set. Empty chapters, duplicates, assembly diagnostics and unassigned note rows remain visible. JSON serialization has per-object, aggregate and elapsed-time limits. No command opens a production database or activates rates.

The explicit CI input `ett_acquire=true`, or a deliberate push to the isolated `ops/ett-source-capture` branch, performs capture, extraction and analysis, then archives the store and reports. Ordinary feature/PR pushes do not enable acquisition. The dedicated branch provides a capture trigger without merging the application into `main`. The job has an 80-minute limit covering the three bounded stages plus installation and packaging. It does not add a scheduled production job; the normal scheduled source lifecycle is unchanged. Temporary GitHub artifact retention is not immutable legal retention.

## Historical verification

The pinned corpus contains **96 chapter PDFs, 1,537 pages and 13,289 exact commodity table rows**. All these rows have assembled duty cells and hierarchical description paths; 29 narrative code mentions are excluded. There are no duplicate table codes or orphan continuations in this retained corpus. These counts do not certify the current legal catalog.

The old quarantined bundle's additional `0406900000` is not printed as a commodity in the retained chapter 04 PDF. That PDF contains the heading `0406 90` and real ten-digit descendants. The new parser does not pad the heading to force agreement with the former 13,290 count. This finding concerns the retained sources and does not independently determine current legal status.

The [reproducible census](evidence/ett-complete-cells-20260908.json) records original source and final parser hashes: all **13,289** complete duty cells parse, including **11,560 ad-valorem, 1,072 maximum, 617 specific, 34 sum and 6 capped-maximum expressions**. It proves 1,219 superscript markers geometrically. Engine displacement uses its own explicit unit; the capped formula preserves `min(cap, max(percent, specific))`. Existing schema-v2 manifest bytes and digests remain unchanged for prior expression types.

The explicitly selected historical notes contain 105 identifiers. Chapter references to IDs 106C–117C remain unbound: the audit does not mix this older notes file with a claim of current completeness. All 264 source rows are accounted for, including two unassigned title rows; 42 act-dependent timing clauses and 18 repeal statements remain visible. No rate interval is approved.

The configured backend suite passed 1,726 tests before the final audit-script and workflow-context additions; their focused verification also passed. Frontend passed 37 tests, TypeScript and production build. Isolated SQLite migration and five authenticated/read-only HTTP checks passed. The prior remote Run #15 failed workflow validation before creating jobs: `runner.temp` was invalid at job-level `env`. Paths now come from `$RUNNER_TEMP` in the Prepare step and are passed through `$GITHUB_ENV`; a regression covers this context restriction. New-head remote CI must be checked directly across push and PR events, because the connector's PR-only workflow helper omitted that failed push run.

## Remaining gates

1. Obtain a current raw capture on a host that can retrieve the official documents, and verify the actual index and portal layouts.
2. Bind each applicable rate interval, destination and product condition to the current notes and complete amendment evidence. Scan-only or unsupported documents require an explicit verified interpretation path.
3. Produce and review one specific manifest, then implement retention attestation and reviewed atomic promotion before connecting active product rates.

All current reports keep `legal_rates_resolved=0`, `current_rates_verified=false` and production readiness closed. Existing calculator rates, VAT and NTM enforcement are not rewritten by this pipeline. No cloud resource, merge or deployment was created.
