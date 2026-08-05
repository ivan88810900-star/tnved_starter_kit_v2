# TASK-CANONICAL-009 — Preserve terminal L4 declarable codes

## Status

Completed — 2026-08-05

## Goal

Make every exact-rate `XXXX000000` record with no deeper commodity record reachable
as a real declarable leaf while preserving the separate four-digit heading wrapper.

## Root cause

Legacy `build_tree()` and Canonical `StructureNormalizer` both treated every
`XXXX000000` commodity as heading metadata and removed it before classification.
That convention is correct when the record only names a heading with descendants,
but wrong when the same record is itself the terminal declarable code and has exact
`hs_rates.hs_code` evidence.

The earlier parity gate compared only the union of nodes produced by the two engines.
It could therefore remain green when both projections omitted the same real source
code. The whole-catalog Guided census exposed the result: 162 valid headings had
an empty first step.

## Contract

- A pad record is materialized as a terminal L4 leaf only when both conditions hold:
  it has exact L4 leaf evidence and its heading has no deeper commodity record.
- `hs_prefix` alone does not make an L4 record declarable; L6 continues to accept
  exact or inherited rate evidence.
- A heading wrapper remains a distinct group node with its existing stable identity.
- Exact pad records that have descendants remain heading metadata and are not
  duplicated as leaves.
- Terminal titles are preserved in full. Numeric ranges such as `3901 – 3913` or
  `8202 – 8205` are ordinary legal text, not semantic pad-title separators.
- Guided navigation obtains terminal leaf status from the selected Canonical model,
  exposes one direct declarable choice and performs no second database read.
- The offline parity audit independently requires source-backed terminal L4 codes,
  so equal omission by both projections now fails Gate-2.

## Implementation scope

- Separate exact `hs_code` and inherited `hs_prefix` evidence in `TreeParser`.
- Preserve terminal L4 records in legacy and Canonical recovery under the contract
  above, with a build-scoped legacy leaf-predicate cache.
- Pass Canonical leaf evidence into the semantic source record; do not create a
  service-side synthetic code.
- Extend Gate-2 reachability requirements using Parser evidence.
- Add exact/non-exact/with-descendants, numeric-title, Canonical/legacy, Guided
  and audit regressions.

## Full-data result

On the strict read-only compact Gate-2 export:

- Canonical node paths increased from **17,953** to **18,115**;
- the audit increased from **18,049** to **18,211** checked paths;
- **18,211 / 18,211** paths match, with zero mismatch or unresolved paths;
- Guided source code-node coverage increased from **16,546** to **16,708**, while
  actual Canonical declarable leaves increased from **13,092** to **13,254**;
- all **162** previously empty terminal-L4 headings now have a real direct choice;
- the special exact-rate pad `2206000000` remains metadata because deeper records
  exist, preventing a false extra leaf.

## Out of scope

- New virtual levels or fake/custom semantic codes.
- API/schema changes, migrations or database writes.
- Canonical feature-flag activation or legacy removal.
- Duty-rate semantics, aliases/history, LLM or embeddings.

## Safety

Both projections were changed together and checked against an independent Parser
requirement. Existing golden Guided semantic assertions remain green. All serving
flags remain default OFF; no production data was modified.
