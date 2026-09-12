# Retained originals for rate-source monitoring

The monitor previously discarded downloaded response bodies after deriving a
revision digest. For HTML, that digest describes selected links and document
identities, not the complete source bytes. A checksum-only report cannot supply
the missing original when a rate or legal change is reviewed later.

An explicit optional capture now stores each validated response body and a
separate immutable receipt in the existing local content-addressed store.
The receipt binds source IDs, the requested/final URLs and redirect chain,
observation time, content type, byte size and original-body SHA. The revision
digest retains its existing meaning. Different HTML responses can therefore
have the same revision identity and different original-body hashes.

## Local operation

From `customs-clear/backend`:

```bash
python scripts/monitor_official_ntm_sources.py \
  --capture-originals --store-root /path/to/private-source-store \
  --source-id trade_remedies_official \
  --source-id rf_excise_tax_code \
  --source-id eec_odata_vat_preferences \
  --state /path/to/observed-state.json --output /path/to/report.json
```

These IDs identify existing monitor targets. They are not proof that those
landing pages contain the required Russian VAT/excise rules or all trade-remedy
acts. The three remedy registry entries currently share one target; its receipt
preserves all associated registry identities without repeating the request.

`--source-id` is repeatable and accepts exact monitor IDs only. Unknown or empty
IDs fail before download. A selected run explicitly reports its limited scope
and cannot claim that the full registry was checked. Unselected baseline records
remain unchanged. Omitting selection keeps the existing complete target list.

Capture forces complete responses rather than reusing conditional `304`
observations. The guarded transport preserves its HTTPS/redirect, body-size,
Content-Length, encoding and content-validation checks. Failed object or receipt
writes do not accept or advance the affected baseline; an incomplete requested
capture has a nonzero exit even without `--strict`. No `--accept-changes` is
needed or authorized by source capture.

Signed query parameters and URL fragments are omitted from new receipts/reports;
hashes bind the exact observed URL strings. Receipt verification rechecks both
receipt and original-object bytes and rejects contradictory integrity claims.
It cannot independently prove that a network request occurred. All legal,
authenticity, retention, promotion and production assertions remain false.
Unselected historical state entries are preserved as supplied, including any
old URL parameters; this is not a sanitizer for an arbitrary pre-existing state
file. The isolated acquisition workflow starts with a new empty state.

## Isolated acquisition workflow

`official-rate-source-capture.yml` runs only on an explicit push to
`ops/official-rate-source-capture`. Its current selection is the two unresolved
remedy navigation pages described below; it uses
read-only repository permissions and private temporary evidence paths, and
never supplies acceptance arguments. A database sentinel verifies that source
capture did not create an application database. Even an incomplete attempt
packages its reports and retained objects for inspection.

This workflow does not run on the feature branch, on `main` or on a schedule.
It follows the existing isolated source-acquisition pattern; it does not deploy
application code. Temporary Actions artifacts are not permanent legal retention
and must be restored and saved before expiration.

## Verification and unfinished work

52 focused monitor/capture/selection tests passed. Cases cover original versus
revision SHA, deduplicated identities, no-object default behavior, missing or
corrupt objects, forged positive receipt claims, partial selection, unsolicited
304 and failure before baseline acceptance. The workflow uses pinned actions;
its shell and Python blocks pass static syntax checks.

The current ETT core, legal amendment OCR and twelve relief/origin PDFs are
already retained separately. The selected new acquisition avoids repeating
those completed stages. Capturing a landing page still leaves document
discovery, article/page/row binding, semantic interpretation, full applicability
audit, manifest-bound human approval and permanent retention as separate work.
# Observed capture and navigation repair, 11 September 2026

Implementation commit `a5ef7f3` passed PR CI `34598906017` (4,434 backend
tests, 2 skipped, 2 warnings, 73 subtests; frontend/types/build, workflow and
staging checks passed). Acquisition run `34598954173` was incomplete: only
the FNS excise original was retained. The obsolete EEC remedy URL failed and
OpenData changed its requested path. The archived failures remain evidence;
they are not silently relabelled successful.

The FNS original contains links to rates and a tobacco retail-price registry,
but no numerical excise table or combined tobacco formula. The exact body and
receipt identities are recorded in
[capture evidence](evidence/official-rate-originals-20260911.json).

The next selected acquisition uses separately corroborated navigation URLs;
see [observed links](evidence/eec-remedy-link-discovery-20260911.json).
No redirect exception is added. The FNS VAT page is an official reference
with links to legislation, not a per-code import-VAT dataset. The EEC department
index includes investigation notices and draft reports as well as enacted
decisions. The separately observed Decision 121 PDF is collected for review;
publication does not establish its effective date or approve a duty. The new
six-target capture does not repeat the already retained excise response and
does not constitute a complete trade-remedy, VAT or OpenData inventory.

## Quarantined rejected originals, 12 September 2026

Run `34600642623` retained four of six requested originals. The department and
document-index responses were HTTP 200 but failed content validation with
`block_or_error_page_detected`. Their bodies were discarded by the previous
`if ok` capture branch, so the report alone cannot establish why they matched.
The four successful originals are already retained and are not requested again
by the next isolated capture.

The new explicit `--capture-rejected-originals` option requires both
`--capture-originals` and `--store-root`. It keeps a nonempty HTTP 200 response
only after the existing guarded transport succeeds and a listed content check
rejects it. HTTPS, allowed redirect identity, encoding, bounded stream reads and
Content-Length checks remain in force. Transport failures, oversize bodies,
non-200 responses and empty responses have no quarantine capture. Missing MIME
metadata may be retained as an empty receipt field, with failed validation.

Rejected bodies and receipts use the same immutable content-addressed object
store, but the receipt is explicitly `official_monitor_rejected_original` with
`quarantine_status=content_rejected`. Only `verify_rejected_original_capture`
can replay this receipt. `verify_original_capture` rejects it. Receipt integrity
does not turn rejected content into a verified official artifact or candidate.

The report exposes `rejected_original_capture` separately. It cannot change
`ok`, `approval_allowed`, baseline or pending state, successful original count,
or original/revision completeness. Capture still exits nonzero for any rejected
source, even when its quarantine objects were successfully saved. All legal,
retention, review and promotion assertions remain false. The tests also exposed
and fixed a pre-existing diagnostic defect: a rejected PDF could still report
verified artifact/revision identity solely from its URL shape.

The workflow now selects only `trade_remedies_official` and
`trade_remedies_official__artifact_2`, without acceptance arguments. No new live
capture is claimed by this implementation checkpoint. Diagnosis of the resulting
bytes is separate from changing the content validator or approving a source.

Validation: 125 focused monitor/capture/integrity tests passed on an explicitly
isolated database sentinel; the monitor did not create it. Cases cover both
receipt verifiers, tampering, wrong/missing MIME, block responses, signed URL
redaction, shared URLs, mixed successful/rejected counts, preserved pending
baselines, transport failures, stream/declared size limits and CLI requirements.
The older Decision 121 and FNS VAT source identity checks remain separate tests
after narrowing the workflow selection. Independent QA, integration and remote
CI are required before this checkpoint is integrated.

## Explicit observed sources after the navigation capture

Run `34714034422` retained both rejected navigation bodies, with zero successful
originals and no accepted source IDs. Both rejected receipts and bodies replayed
successfully before the executor disconnected; the ordinary original verifier
rejected both receipts. Their header scripts contain the literal `captcha` token
inside `window['recaptchaFreeOptions']`: byte 5,363 on line 50 of the department
body, and byte 3,376 on line 22 of the document-index body. These observations
explain the validator match, but do not approve the content or relax validation.

The exact index original exposes pagination hrefs for pages 2, 3, 4 and 5.
The next explicit acquisition selects those four observed URLs and five observed
act references: Decision 4 page/PDF, Decision 121 page, the AD30 completion notice
and final investigation report. The already retained Decision 121 PDF and first
navigation pages are excluded. The exact request and source provenance are in
[evidence/eec-ad30-acquisition-plan-20260912.json](evidence/eec-ad30-acquisition-plan-20260912.json).

`REVIEW_ONLY_SOURCES` is separate from the 72 registered monitor targets and
does not add a policy or scheduled target. These IDs require explicit selection,
original capture and a store. Any acceptance request containing one of these IDs
is rejected before network or CLI store initialization, including mixed selections.
Review-only observations never create or replace accepted or pending baseline
records. Reports distinguish registered and review-only selection, and every legal,
retention, production and promotion assertion remains false. Standard content and
transport validators remain unchanged.

The implementation was reconstructed from immutable remote files after the local
execution server disconnected. No local test result is claimed for this new
nine-target checkpoint. Its focused tests, independent A5 review and fresh GitHub
Actions must pass before integration and the next acquisition.
