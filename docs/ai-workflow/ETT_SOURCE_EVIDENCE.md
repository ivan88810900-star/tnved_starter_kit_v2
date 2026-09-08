# ETT source capture and PDF evidence — TASK-ETT-002

Status: implementation verified, 2026-09-08; acquisition of the current official source set has **not** completed. Continues approved [Decision #188 Option A](https://github.com/ivan88810900-star/tnved_starter_kit_v2/issues/188#issuecomment-5584102215) and [TASK-ETT-001](ETT_VERSIONED_CANDIDATES.md).

## Result

The candidate layer can now acquire the actual [EEC ETT index](https://eec.eaeunion.org/comission/department/catr/ett/), discover its 96 chapter links and labeled global notes, and retain linked supplemental PDFs and amendment pages. No filename pattern supplies a missing URL. A blank link to an older notes file is retained as supplemental evidence; it cannot replace the visibly labeled tariff notes. All original bytes are SHA-256 objects in the explicit local development store.

The transport enforces exact official HTTPS hosts, same-host bounded redirects, TLS verification, identity encoding, content length, MIME and PDF framing checks. HTML and individual PDF limits are 4 MiB and 64 MiB; the capture is bounded to 256 linked documents and 512 MiB. Elapsed time is checked during reads; synchronous in-flight I/O still has its own short timeout. The fixed index cannot redirect to a different base path. Authentication, ambient cookies and proxy credentials are not forwarded.

An acquisition publishes one canonical receipt only after every discovered document is retained and verified and a second index fetch reproduces the discovery plan. Failure leaves only unreferenced source objects, never a success receipt or rate update. The receipt is a **technical capture**, not a schema-v2 legal candidate, signed origin attestation or atomic legal edition. Stable start/end links cannot prove that every same-URL PDF stayed unchanged between individual downloads. Linked legal portal HTML is retained as a page, not assumed to contain the complete act. Many amendment declarations lack direct links; `legal_inventory_complete` remains false.

PDF extraction runs in a separate process with CPU, memory, output, descriptor and time limits. It retains original PDF hash, parser-module hash, PyMuPDF/MuPDF versions, page and word coordinates, deterministic physical rows, and raw cell fragments only where column headers are confirmed. The row locator is `p0001:r00001`. Row text is the extracted words joined by U+0020, with each original extracted word retained separately; it is not the original PDF whitespace. Resource limits are not an operating-system security sandbox.

`verify-rows` re-extracts the original source bytes and checks all code, rate-rule, footnote and effective-date **quotes** against the exact page, locator, text and hash. Rehashing a fabricated quotation does not pass. This checks only referenced PDF rows; it does not attest unreferenced artifacts. A correct quote can still have an incorrectly interpreted rate or date, so all semantic interpretation and approval flags remain false even when `rows_verified=true`.

There is no active-rate materialization, automatic date inference, VAT derivation, review approval or promotion. Candidate readiness remains closed. No application database, NTM behavior or runtime feature flag is changed.

## Reproducible operation

From `customs-clear/backend`, with an explicitly chosen private development store whose parent already exists:

```bash
python3 scripts/ett_candidates.py acquire --store-root /path/to/private-objects
python3 scripts/ett_candidates.py extract RECEIPT_SHA256 --store-root /path/to/private-objects
python3 scripts/ett_candidates.py verify-rows /path/to/candidate.json --store-root /path/to/private-objects
```

`acquire` returns `receipt_sha256`; `extract` returns `report_sha256` for the extraction-set index. Both retain their canonical JSON as immutable store objects. Extraction has its own aggregate byte/time limits. Partial failures never produce a complete extraction-set index. `verify-rows` is read-only and exits 2 for unverified quotes while returning the diagnostic report. These commands do not open a candidate database.

The existing CI workflow also has an optional **manual** `workflow_dispatch` input `ett_acquire=true`. It captures and extracts into a private runner directory and uploads the whole store plus compact reports as a temporary artifact for up to 90 days. Existing CI jobs run normally. The acquisition job does not run on ordinary push/PR events and adds no production schedule. Artifact retention is **not** Object Lock or durable legal retention. No cloud account or paid resource was created. The connected GitHub tool surface did not expose workflow dispatch in this session, so this optional acquisition job was not run.

## Verification and limits

- All 96 pinned chapter PDFs were extracted: **1,537 pages**, **13,318 candidate occurrences**. These are retained historical inputs, not a newly downloaded current edition.
- Diagnostics retain 252 candidates with unconfirmed table headers, eight ambiguous cell layouts and one cross-chapter reference in a note. Duplicates and note mentions are preserved. Counts are not proof of complete table coverage or legally valid rates.
- Every candidate still requires interpretation of footnotes, dates, hierarchy and multiline/page continuations. `legal_rates_resolved=0` in this extraction slice.
- The synthetic index fixtures test topology, URL handling and source drift. Search exposed the current official page, but raw HTML/PDF acquisition from this environment timed out; the raw current DOM has not passed the new parser. No search-rendered text was substituted for original source bytes.
- The configured backend CI suite passed **1,326 tests**, including **270 new tests**. Authenticated read-only HTTP checks passed for health, candidate listing/readiness/preview and the existing NTM endpoint. CLI row verification leaves source objects untouched and does not create the database named in its environment. Evidence is recorded in `evidence/ett-source-evidence-20260908.json`.

## Next task

Complete a real current capture on a host that can retrieve the official raw documents, validate the retained index layout, then assemble full table rows and descriptions across continuations. Bind footnote conditions and effective intervals to the current notes and amendment acts, explicitly resolving every missing or ambiguous case before constructing a legally reviewable manifest. The later manifest-bound legal review, durable retention and approved promotion gates remain separate.
