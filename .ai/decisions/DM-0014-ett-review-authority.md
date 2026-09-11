# DM-0014: Authority for manifest-bound legal review

> **Status:** Proposed — requires Ivan's decision
> **Date:** 2026-09-11
> **Owner:** Ivan
> **Scope:** trusted human review and separate approval; no activation

## Context

[Issue #188](https://github.com/ivan88810900-star/tnved_starter_kit_v2/issues/188#issuecomment-5584102215)
already accepts Option A. This memo does not reopen the official-source,
versioned-snapshot, quarantine, `as_of` or immutable-storage decisions.
Development without purchasing cloud storage remains authorized.

[PR #187](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/187)
now contains the recovered `177da64` source capture and `dc1cd389` Council
monitor supplement. CI run `34589072638` passed for `dc1cd389`; these changes
neither approve rates nor deploy the monitor to the default branch.

Recovery also restored the already completed full-catalog dependency worklist,
not a newly rebuilt one: 13,293 codes, 124 notes, 1,222 code-to-note edges and
63,237 retained source rows. All eight files matched the saved backup manifest.
The inventory SHA is
`e1935e7c0ae07fd9e10c591b7635e532cc0da55144e596fd0f8d9fc4e8ea64db`.
Six files of the earlier legal-interpretation backup were also restored and
hash-verified, including the literal-clause inventory
`95a48d4f5c0f33a608b9fa7dfaaf968eda82aeb543bbd89e0233dc4e232fa07f`
and the bounded 111C interpretation proposal. This reuses completed technical
work; it does not repeat OCR or certify the interpretations.

These are technical worklists, not a legally approved full rate manifest.
All 124 notes still require legal interpretation. Full applicability, subsequent
amendments, VAT/excise/trade-defence/origin coverage and retention remain separate
unfinished gates. The exact later 111C candidate/review-package bytes that failed
to upload in the prior session are still not recovered; their recorded hashes
alone cannot be reviewed or accepted as substitute inputs.

The accepted architecture requires a trusted human decision bound to an exact
manifest and separate approval before application. It does not define who has
that authority, whether both decisions may be made by the same person, or how
authority and previous decisions are revoked. There is no assigned legal
reviewer or manifest approval in the current PR/issue history. Existing source
checksum acceptance and generic administrator access do not grant legal authority.

`AGENTS.md` requires a Decision Memo for legal/compliance interpretation and
API/data-model choices. A positive legal-review authorization path must not
silently turn an existing admin token or a payload's reviewer name into authority.

## Decision required

Choose who may legally review a rate manifest and separately approve its use,
including whether these must be different people.

## Option A — separate reviewer and owner approval (recommended)

Ivan appoints a human legal reviewer. That reviewer records the evidence-backed
legal decision for the exact manifest and review-package hashes. Ivan records
the separate approval. The system requires different authenticated identities.

Pros: clear separation of source preparation, legal review and owner approval;
an administrator or AI cannot approve its own extraction by default.

Cons: requires an appointed second person and two human actions. Naming a person
does not itself establish qualifications or approve any rates.

## Option B — Ivan performs both separate actions

Ivan is explicitly authorized to perform both legal review and the subsequent
approval, with two distinct immutable records bound to the same complete package.

Pros: no second operator is required; the two-step decision remains explicit.

Cons: no separation of duties; Ivan must undertake or obtain the substantive
legal review. A second click is not an independent legal check.

## Common boundaries

- Authority comes from owner-approved grants and authenticated identity, never
  a caller-supplied reviewer label, model output or possession of a shared token.
- Review and approval bind exact manifest, prior snapshot, package and evidence
  hashes. Changes invalidate previous decisions; approval cannot outlive an
  applicable revocation or satisfy missing completeness/retention gates.
- A review can reject or request clarification. Unresolved legal conditions
  cannot become approved merely because technical assembly succeeds.
- Authority removal and decision withdrawal are append-only, attributable events;
  they cannot silently rewrite an earlier decision. Subsequent serving behavior
  requires its own tested, explicitly authorized transition.
- This memo approves no candidate, reviewer grant, cloud resource, migration,
  merge, deploy, DB write, active pointer or enforcement flag.
- Storage-provider/retention configuration is a later real-storage gate, not a
  reason to stop source acquisition or offline development now.

## Proposed next task after the decision

Implement and test the chosen manifest-bound review/approval authorization
contract in an isolated, non-activating contour, including negative identity,
self-approval (if prohibited), changed-hash, incomplete-evidence and revocation
cases. Continue full source-to-rule/date/condition interpretation from the
restored worklists without relabeling historical evidence or losing unresolved
items. Reconstruct any missing candidate as a new explicitly identified package
unless its original bytes are recovered. Keep runtime and production untouched.

The decision blocks the positive legal-authorization design, not all possible
offline preparatory work. The complete rates-and-sources block is not finished.
