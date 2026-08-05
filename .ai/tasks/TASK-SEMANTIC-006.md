# TASK-SEMANTIC-006 — Bounded official PDO interval for heading 2204

## Status

Completed — Option A accepted by Ivan, 2026-08-05.

The implementation and verification remain on the feature branch.
[DM-0005](../decisions/DM-0005-guided-2204-pdo-interval.md) records the accepted
product direction. This docs-only update does not merge, roll out or deploy the
code, and both Canonical serving flags remain OFF.

## Goal

Reduce the measured high-branching Guided step in heading `2204` by restoring one
explainable, source-backed PDO question from the official nomenclature text, without
changing generic semantic extraction or weakening whole-catalog integrity.

## Context

TASK-SEMANTIC-005 proved correctness for the full supplied Gate-2 catalog and
identified `2204` as the largest later-step usability outlier: the affected
`220421` branch exposed 50 choices, including 47 direct code choices. The official
description stored on `2204210900` contains several packed dash-prefixed headers.
Its final depth-6 header is the PDO marker, while the first matching depth-6 PGI
marker is carried by `2204217800`.

The generic extractor intentionally accepts only its existing strict patterns. This
task adds one corrective, bounded projection for the verified official `2204` slice;
it does not introduce a catalog-wide packed-header heuristic.

## Decision status

DM-0005 was required under `AGENTS.md` because this technically bounded overlay
changes a user-visible question derived from legally meaningful nomenclature text.
Ivan accepted Option A on 2026-08-05, including the exact interval, user-visible
codeless PDO question and retained noncritical 33-choice warning.

The acceptance closes the product-semantic choice but does not perform or
authorize merge, rollout or deployment in this task. Canonical remains the source
of truth for real codes; the public API and enforcement semantics remain unchanged.

## Exact verified scope

The PDO group may be emitted only when all of the following evidence matches in
the same Canonical source snapshot:

- heading: `2204`;
- Canonical parent: `2204210000`, and that parent is not a leaf;
- source anchor: `2204210900`, exclusive, a Canonical leaf under that parent;
- the anchor contains exactly one depth-6 packed header; it is the final packed
  header and the exact bilingual official PDO marker;
- every source record in the open interval `(2204210900, 2204217800)` contains no
  packed header at depth 6 or shallower (`dash_depth <= 6`), even if generic
  extraction would reject its text;
- `2204217800` contains exactly one depth-6 packed header; it is the final packed
  header and the exact bilingual official PGI marker;
- the existing strict extractor independently accepts that PGI boundary;
- no accepted semantic boundary intervenes between the PDO anchor and PGI carrier;
- the open/closed source interval `(2204210900, 2204217800]` resolves to exactly
  the following ordered allowlist of 33 Canonical sibling leaves under
  `2204210000`:

```text
2204211100
2204211200
2204211300
2204211700
2204211800
2204211900
2204212200
2204212300
2204212400
2204212600
2204212700
2204212800
2204213200
2204213400
2204213600
2204213700
2204213800
2204214200
2204214300
2204214400
2204214600
2204214700
2204214800
2204216200
2204216600
2204216700
2204216800
2204216900
2204217100
2204217400
2204217600
2204217700
2204217800
```

The list is an exact ordered allowlist with intentional numeric gaps, not a generic
claim that every numeric value inside the interval is a valid customs code. The
first later PGI code choice begins at `2204217900` and must remain outside the PDO
group.

## Accepted bounded behavior

- Guided adds one codeless semantic choice titled from the verified PDO marker.
- Its children are exactly the 33 real Canonical declarable codes above, in source
  order, with their existing Canonical anchors and snapshot identity.
- The public endpoint, response fields, code roles and frontend contract are
  unchanged; this uses the existing `semantic_choice` representation.
- The generic extraction policy and `MAX_UNSPLIT_GROUP_CODES=30` remain unchanged.

## Fail-closed contract

Any missing code, changed marker, wrong dash depth, extra/non-final depth-6 header,
any depth-6-or-shallower header inside the open interval, shifted boundary, changed
leaf role, changed Canonical parent, intervening semantic boundary or allowlist
mismatch suppresses the PDO projection. Guided then preserves the complete ordinary
flat Canonical path; no code is hidden or invented.

The Builder rechecks the provenance-bound interval before publication. If a verified
group reaches assembly with malformed or incomplete scope, every child spills back
to the safe flat placement, the empty group is pruned and the response remains
complete. No partial PDO promise may be published. Independent critical integrity
errors continue to return the existing `DEGRADED` result and ordinary `/children`
fallback without a 500 response.

## Feature-branch verification

On the supplied strict read-only Gate-2 snapshot:

- heading `2204` remained `OK` and complete: 211/211 expected, reachable,
  Canonical-bound and source-backed code nodes, including 170/170 declarable leaves;
- the affected `220421` step changed from 50 choices / 47 direct code choices to
  18 / 14; choosing PDO opens exactly 33 / 33;
- the heading retained five root choices, while semantic groups increased from
  seven to eight and semantic-covered leaves increased from 24 to 57;
- the catalog-wide maximum later step is now 33 / 33, still in `2204`;
- the exact PDO slice and following PGI boundary are now the fifth golden hierarchy
  assertion.

The whole-catalog census remained fully correct:

- 1,228/1,228 headings are `OK` and complete;
- 16,708/16,708 source-backed code nodes are reachable and Canonical-bound;
- 13,254/13,254 Canonical declarable leaves are preserved;
- five of five golden headings pass;
- semantic questions remain present in 548 headings, while covered declarable
  leaves increased to 6,924/13,254 (52.2408%);
- fake, duplicate, critical, degraded, empty-root, leaf-role, Canonical-parent and
  snapshot mismatches remain zero.

## Known noncritical warning

The verified PDO group intentionally contains 33 direct code choices. Because the
global safe-nesting limit remains 30, validation reports exactly one
`oversized_unsplit_group` warning. It is noncritical, does not make the endpoint
`DEGRADED` and is retained as honest UX debt rather than hidden through a special
threshold exemption. Further subdivision requires a separate bounded slice backed
by official evidence.

## Out of scope and safety

- No generic packed-header extraction, global threshold change or unrelated heading.
- No database/schema mutation, migration, seed, ingestion or write path.
- No public API/schema or frontend change.
- No feature-flag rollout: `CANONICAL_TREE_ENABLED` and
  `CANONICAL_TREE_SHADOW` remain default OFF.
- No merge, rollout or deployment is performed or authorized by this documentation
  update.
- No LLM, embedding, vector-index or external provider call.
- No nomenclature aliases/history or identity-formula change.

Rollback is a single task-code revert. It requires no migration or data rollback;
the previous complete flat 50/47 branch returns, while Canonical correctness and
the ordinary fallback remain intact.

## Regression coverage

Focused regressions cover exact packed-header acceptance, the full ordered 33-leaf
scope, codeless/provenance metadata, shuffled input determinism, wrong heading or
missing Canonical evidence, source-marker drift, boundary drift, missing/non-leaf/
wrong-parent codes, same-count interior substitution, Builder spillback, empty-group
pruning, extra anchor/stop depth-6 headers, hidden depth-5 and depth-6 boundaries
inside the open interval even when generic extraction rejects them, complete
service output, the retained noncritical warning, exact 18/14 and 33/33 question
shapes, ordered PDO/PGI siblings, the fifth aggregate-only golden assertion and
report privacy.

## QA evidence

- Relevant Guided/Canonical/API regression suite on an isolated full-schema database
  copy: **79 passed**; one pre-existing Starlette/httpx deprecation warning.
- Strict read-only Gate-2 legacy/Canonical audit: **18,211 / 18,211**, zero mismatch
  and unresolved paths, `gate2_ok=true`.
- Strict read-only whole-catalog Guided census: **1,228 / 1,228**, 16,708 / 16,708
  source-backed nodes, 13,254 / 13,254 leaves, golden **5 / 5**, zero correctness
  problems and one consistent snapshot.
- Aggregate report privacy check found no ten-digit code or PDO/PGI source text.
- Python compilation and `git diff --check` passed.
