# ETT review package: contract and present input gaps

Status: bounded readiness assessment and implemented source-binding prerequisite,
2026-09-08. No package builder, review decision, endpoint, database migration or
production behavior is added. Continues accepted Decision #188 Option A and the next sequence in
[ETT versioned candidates](ETT_VERSIONED_CANDIDATES.md).

## Present decision

A manifest-bound package needs the bytes of one specific candidate manifest.
The current source work has not produced that normative candidate: the checked-in
[complete-capture evidence](evidence/ett-complete-capture-20260908.json) still
reports `legal_rates_resolved=0`. Its complete technical receipt is
`ab67a2d3055a3fcd8416c874b9bc388ce0b0919e4b964e5de7c1f18c08a6f72e`.
It binds the supported observed download plan, including 100 core PDFs and two
linked legal PDFs. It does not establish the completeness of applicable acts or
the interpretation of their conditions and effective dates.

The former source-role gap is resolved by an optional schema-v2
`derived_amendment_inventory` descriptor. A manifest requires exactly one inventory
mode: either the existing `amendment_inventory` artifact with its own official URL,
or this descriptor bound to the sole original HTML index artifact's ID and SHA256.
Official artifact URLs remain unique. The current named amendment inventory is
derived JSON from the original ETT index. Its digest in that capture is
`1af4b8cd63c6c0e190477db5848869a5afb6a4866139fa5abce10e980e7e02a8`;
it is not a separately downloaded official inventory URL. The descriptor binds its
report SHA256, byte size, derivation kind and supported parser identity without
assigning JSON a fabricated official URL. Derived mode needs 99 official artifacts
(96 chapters, index and both note documents); the legacy mode still needs at least
100. Existing manifests omit the absent descriptor from serialization, preserving
their exact schema-v2 canonical bytes and digests.

`ett_derived_inventory.verify_derived_amendment_inventory` reads and verifies both
retained objects, re-runs `parse_amendment_inventory` on the original index bytes,
and compares the entire canonical report. Parser identity binds the amendment,
index and replay/encoding modules; unsupported or changed identities fail replay.
`ett_repository` performs this check before staging writes and on every stored
candidate load/preview. The descriptor lives in canonical manifest JSON and needs
no new database projection or migration. Semantic diffs expose descriptor changes.

This closes the technical provenance prerequisite; it does not produce a normative
candidate or solve the remaining legal-date and applicability interpretation.
Existing acquisition and analysis reports retain that distinction. A package
builder remains deferred until a specific candidate has meaningful source-backed
conditions and effective intervals.

## Input and identity contract for the next implementation

The source-bound manifest descriptor supplies the derived inventory mode directly.
Its source artifact must be the sole HTML index at the actual official ETT index
URL. Verification re-runs the matching supported parser on the original index
bytes and compares the whole canonical result. Missing objects, a rehashed edited
report, altered source bytes, wrong source URL or parser drift prevent staging or
stored preview. Missing links and all unverified legal flags remain in the report;
successful replay does not establish legal completeness.

A future complete package requires these immutable inputs:

| Input | Required verification |
|---|---|
| Candidate manifest | Canonical schema-v2 bytes and their SHA256; revalidate the complete model, including every source and quote reference. |
| Complete acquisition receipt | Require `ExpandedAcquisitionReceipt` v2 and replay `load_acquisition`; verify all original objects, exact index discovery, attachment plan, source sizes and capture intervals. |
| Candidate source bindings | Match exact final URL, SHA256, size, media type and retrieval timestamp to a captured download. Bind chapter numbers and labeled note roles through discovery references and their requested URLs. |
| Derived amendment inventory | Replay the optional manifest descriptor against the exact original HTML index and retained canonical report; retain missing links and all unverified legal flags. |
| Derived tariff-note evidence | Recompute from the exact labeled tariff-note PDF, retaining conditions, unresolved interpretation and every source locator. |
| Referenced PDF quotation verification | Run `verify_manifest_source_rows` on original bytes; retain the complete canonical verification result and its digest. |
| Optional earlier candidate and semantic diff | Verify the earlier canonical manifest digest and recompute the diff against the exact new manifest. A supplied report's hash alone does not verify its content. |

An artifact's hash membership alone cannot establish its role. The same bytes may
be served under different requested URLs, and a redirect's final URL can differ
from the URL in the discovered plan. Both associations must remain attributable.
The package must also preserve source requirements that are missing or unbound;
it cannot omit them to obtain a positive result.

`load_acquisition` currently accepts v1 and v2 receipts. A package requiring linked
attachment coverage must explicitly require v2; a replayable v1 receipt does not
provide that coverage. An incomplete-capture report is never a complete receipt.

## Existing verifiers and their limits

- `validate_manifest`, `canonical_manifest_bytes` and `manifest_sha256` provide
  deterministic candidate identity and structural validation.
- `verify_derived_amendment_inventory` verifies the optional source-bound inventory
  descriptor and complete parser output, without legal-completeness assertions.
- `load_acquisition` checks the complete supported discovery plan and retained
  originals, including v2 attachment bindings. It makes no legal-completeness or
  cryptographic origin-attestation claim.
- `verify_manifest_source_rows` re-extracts each referenced PDF and checks all
  code, rate, effective-date and footnote quotations against exact page, physical
  row locator, extracted text and text hash. It verifies referenced rows only.
- `verify_pdf_evidence` re-extracts original bytes and compares every retained
  extraction-report field, including parser and engine identity.

The quotation tests already demonstrate why semantic flags must remain separate:
a real source row quoting zero can accompany a structurally valid candidate
claiming five percent, and a quoted 2030 date can accompany a 2026 interval.
Quotation existence passes; the differing legal interpretation remains unverified.
The two currently retained amendment PDFs are scans with no extracted text, so
their conditions cannot pass a text-row verifier without an additional verified
visual/OCR evidence path.

The package itself should be a frozen, deterministic value with canonical
serialization and no mutable nested containers. A full validator must replay its
byte and derivation checks and compare the complete canonical package. Parsing a
package schema or accepting a client-provided `verified=true` is insufficient.
No client actor, reviewer identity, approval or activation flag belongs in this
construction step.

PDF replay uses the existing bounded worker and temporary files. Separate that
read-only verification operation from the pure value-construction step; do not
claim that PDF re-extraction is a filesystem-free pure function. Likewise,
`ett_repository.semantic_diff` currently imports ORM models and `app.db`.
A pure package module should not import that repository merely to reuse the diff;
a later bounded implementation must isolate the pure comparison or verify it
through an explicit replay boundary.

Until supported semantic checks exist, keep amendment completeness, effective-date
verification, footnote interpretation, duty interpretation, legal approval,
retention attestation, promotion and production readiness false. Empty issue lists,
matching note IDs, captured search pages and complete source-plan acquisition do
not supply these checks.

## Required tests when the builder becomes actionable

1. Changing any manifest, source, receipt, parser or derived-report byte invalidates
   the previous package identity and its full replay validation.
2. Wrong source URL/role, swapped chapters or notes, mismatched retrieval metadata,
   missing originals and an unbound inventory role remain explicit failures.
3. Rehashed fabricated PDF quotations fail actual row verification, including
   effective-date and footnote references; correct quotations do not approve
   contradictory normalized rates or dates.
4. Incomplete receipts and v1 receipts cannot satisfy the complete v2 source gate;
   unsupported attachments and unresolved named amendments stay visible.
5. Recomputed derived inventory and note evidence reject altered reports and
   changed parser identities. Derived JSON never gains a fabricated official URL.
6. Semantic-diff changes are bound to both exact manifests; fabricated or stale
   diff reports fail replay.
7. Nested mutation, unknown fields, duplicate JSON keys and caller-supplied legal
   flags are rejected; canonical serialization is stable.
8. Imports and execution make no DB/network calls, write no source objects and
   expose no approval, promotion or application behavior change. Temporary PDF
   worker files remain within the existing extraction boundary.

The next useful prerequisite is to complete the source-backed conditions and
effective-interval interpretation and identify one specific candidate for review,
while retaining the verified derived-inventory binding and remaining unresolved
legal interpretation explicitly. The optional descriptor preserves existing
schema-v2 identities and does not claim that a current legally valid candidate
exists.
