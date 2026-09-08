# ETT complete cells and note evidence — TASK-ETT-003

Status: implementation and current-source table verification, 2026-09-08. This continues approved Decision #188 Option A. The **complete current legal rates block is not ready**: the current index and all 100 core PDFs have been captured on GitHub, but the complete legal amendment set and a legally reviewed manifest have not yet been produced.

## Source-preserving interpretation

`ett_table_assembly.py` re-extracts the original PDF bytes before assembling commodity rows. It distinguishes 4/6/8/9-digit headings, exact 10-digit commodity rows, uncoded headings and narrative code mentions. It retains description, supplementary unit and complete duty cells across supported line/page continuations. Hierarchical descriptions are display paths assembled from retained labels, not newly authored legal descriptions. Missing or ambiguous boundaries remain diagnostic results.

The PDF evidence format now retains text spans with font, size, baseline and coordinates in addition to physical word rows. `ett_duty_typography.py` requires mutually consistent word/span evidence before separating a superscript note from a duty. For example, the retained string `563С)` is separated into `5 63С)` only when the original glyph geometry proves that distinction. Merely recognizing digits or a font flag is insufficient. Source row text and hashes are preserved unchanged.

`ett_duty_cells.py` consumes complete isolated cells, requires a proven percentage header for a bare number, and parses the whole expression using exact decimals. It does not select the final number, silently drop unfamiliar suffixes or convert failures into zero. A parsed expression is a lexical result; footnotes and legal applicability remain unresolved until interpreted against the relevant edition.

`ett_notes.py` retains every note's source rows, exact labels, repeal references, country clauses and temporal candidates. Inclusive end dates receive arithmetic conversion only when inclusiveness is explicit. Dates relative to entry into force remain unresolved. Gaps in note numbering do not establish missing documents; duplicate identifiers are never treated as valid bindings. Neither note-ID matching nor a recognizable date clause proves that a rate applies.

## Legal document capture

Acquisition receipt v2 retains an immutable inventory of actual attachment links found on captured official document pages and downloads discovered PDF attachments. Original and resolved hrefs, visible document identity and source HTML hashes are retained. Unsupported DOCX and other attachments are listed explicitly; their contents are not assumed to be captured. Receipt v1 remains verifiable with its original narrower meaning.

Receipt verification re-derives the attachment plan from retained HTML, checks the inventory object and requires every planned PDF with its original hash and size. It cannot certify undiscovered amendments, an atomic legal edition or the contents of unsupported attachments. The original 132,800-byte current index was captured by GitHub Run #34235767121 (SHA-256 `75991416897e2764afc58f20c72dcaff49753b564f8504c383414028a0633072`). Its empty same-target chapter-24 alias is now retained without duplicating or erasing that chapter. Conflicting aliases still fail. The raw fixture and source metadata are retained verbatim. It yields 96 chapters, 101 PDF references / 100 unique PDF URLs and two legal-document links. This validates that specific index layout; current portal HTML still requires a successful capture.

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

The published `18aba33` passed remote push and PR CI, including **1,750 backend tests**, frontend and staging smoke. The subsequent real-index compatibility and acquisition diagnostics corrections have additional focused tests. Frontend passed 37 tests, TypeScript and production build. Isolated SQLite migration and five authenticated/read-only HTTP checks passed. The prior remote Run #15 failed workflow validation before creating jobs: `runner.temp` was invalid at job-level `env`. Paths now come from `$RUNNER_TEMP` in the Prepare step and are passed through `$GITHUB_ENV`; a regression covers this context restriction. Remote CI is checked across both push and PR events, because the connector's PR-only workflow helper omitted that failed push run. The explicit capture branch ran successfully through checkout, setup and packaging, but acquisition stopped on the duplicate alias in the real index. The stored failed result is not a complete capture receipt. The next Run #34236950319 obtained 100 PDF objects plus the index, then failed on the first legacy legal-portal URL. Its ZIP was retained. A distinct incomplete-capture report now preserves each successful request URL, hash and timestamp on transport failure; it cannot load as a complete receipt.

## Incomplete captures and the named-act inventory

`analyze-incomplete INCOMPLETE_CAPTURE_SHA --store-root /path/to/private-objects` accepts only a hash-verified incomplete report whose completed records form the exact prefix of the original download plan. It requires every core PDF before analyzing the 96 chapters. Its result has a distinct kind, `acquisition_complete=false`, an explicit incomplete report hash and an `incomplete_acquisition` blocker. It never invents a successful final index fetch or a complete acquisition receipt. Failed requests carry only a public source identity and a static failure classification.

The [named-act inventory](evidence/ett-amendment-inventory-20260908.json) independently binds the retained index to **105 amendments (61 Collegium, 44 Council), of which 2 are linked and 103 have no source URL in the declaration**. The founding Council Decision №80 of 14.09.2021 is separate. Every act and inherited issuing body has an exact quote and character range. Adoption dates are not effective dates. Unsupported residue, ambiguous links and duplicate act identities fail enumeration; missing URLs are not synthesized.

The previous complete-cell census is retained as evidence of the earlier tested parser revision, not silently relabeled as an audit of every later revision or the new live source set.

## Current-source verification

[Run #34239100895](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/34239100895) retained the current index and **100 unique core PDFs** before the first legacy portal link failed. The distinct incomplete report is `5b4dda0926a9c4c17a009903bd7b685c092c072e5b53ed297cfd14c78140a873`; it records actual successful request URLs, hashes and timestamps. The original archive was preserved separately from GitHub's temporary retention.

The [current corpus audit](evidence/ett-current-cells-20260908.json) re-extracted **96 chapters / 1,537 pages / 13,293 exact unique table codes**. All 13,293 complete duty cells and hierarchical descriptions resolve; no duplicate codes, unresolved cells, empty/scanned chapters or unbound note IDs were found. Current notes contain **124 identifiers**. Independent extraction accounted for all **311/311** note rows; the two unassigned rows form the title. All 140 pages without table headers precede their chapter's table and contain introductory narrative. These checks establish extraction coverage, not current legal applicability.

Compared with the retained historical corpus, chapter 32 replaces `3215110000` and `3215190000` with six exact descendants ending in `0001`, `0002` and `0009`. Eight chapter PDFs changed. Twenty-seven shared duty cells changed their note references; their parsed numeric structures are unchanged. These are source differences, not approved catalog or rate migrations.

The [current-note census](evidence/ett-current-notes-20260908.json) preserves 24 absolute windows across 23 notes, 51 starts tied to an act entering into force, 34 repeal statements and 18 notes with unresolved Russian destination/conditional scope. Its 85 literal citations identify 61 distinct acts requiring primary-body review. Recognizing these clauses does not resolve their legal effect.

The current analysis report is `b98c7681f2aeca5c4c1188f76b12ff19b6d03a5387e3bbff1b3d9dd4e4d582ab`. It retains `acquisition_complete=false`, zero verified effective clauses, 103 unlinked named amendments and all legal/promotion blockers. Passing parser checks does not open the production gate.

## Portal discovery and rejected originals

Two original modern portal pages are retained verbatim with capture metadata and replay tests. Each exposes one distinct PDF and six unsupported attachments. Their shared clarification DOCX is preserved exactly as linked; its filename is not used to infer act identity.

The [observed list audit](evidence/ett-legal-list-discovery-20260908.json) parses 100 rows from each of two 2022 decision-year lists. The pages report totals of 205 Collegium and 170 Council decisions, so these first pages are explicitly partial. Exact issuing-body/number/adoption-date matching identifies eight of the 105 named amendments and one of the 61 current-note dependencies. Row text hashes, DOM locators, observed date fields and actual pagination links are retained; none is marked as a verified effective date or complete act body.

A separate discovery-only transport implements the GET search form actually present in those original pages: `/documents/search/` with one bounded `q`. The ordinary source/manifest URL contract remains query-free. The isolated CI probe captures three public queries and their exact original responses; empty search results cannot establish an act's absence.

The source-access diagnostics identified an explicit default HTTPS port in the legacy redirect. That same-origin `:443` spelling is now normalized only for observed redirects; initial source/manifest URLs, other origins and nondefault ports remain restricted. Inspection of both retained originals established the exact `%PDF-1.4 Sharp Scanned ImagePDF` header. This narrow producer variant now passes the header/EOF gate without modifying original bytes. Both PDFs open without repair or encryption: 12 and 17 scanned pages, with no text rows. They require a separate verified visual/OCR evidence path before legal interpretation. Rejected original document bytes can now be retained by digest while the request remains `failed`, with `document_validation_passed=false`; they never become successful receipts merely because the bytes exist. This permits inspecting the originals before adjusting a format rule. The open-data landing `/api/` returned non-200 in the observed capture; its availability is not assumed.

## Remaining gates

1. Complete the amendment-body capture, including the 103 named acts with no URL in the index declaration. The current index, all 100 core PDFs and two modern portal HTML pages have been retained; they do not establish complete amendment coverage.
2. Bind each applicable rate interval, destination and product condition to the current notes and complete amendment evidence. Scan-only or unsupported documents require an explicit verified interpretation path.
3. Produce and review one specific manifest, then implement retention attestation and reviewed atomic promotion before connecting active product rates.

All current reports keep `legal_rates_resolved=0`, `current_rates_verified=false` and production readiness closed. Existing calculator rates, VAT and NTM enforcement are not rewritten by this pipeline. No cloud resource, merge or deployment was created.
