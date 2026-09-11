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
`ops/official-rate-source-capture`. It selects the three targets above, uses
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
