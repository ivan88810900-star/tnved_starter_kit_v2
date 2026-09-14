# DM-0012: Guided 2204 retained «прочие» boundaries

> **Status:** Accepted — Option A
> **Date:** 2026-08-18
> **Owner:** Ivan
> **Context:**
> [TASK-SEMANTIC-009](../tasks/TASK-SEMANTIC-009.md),
> [TASK-SEMANTIC-006](../tasks/TASK-SEMANTIC-006.md),
> [DM-0005](DM-0005-guided-2204-pdo-interval.md),
> [ADR-0003](ADR-0003-canonical-anchor-identity.md),
> [CURRENT_PROJECT_FOCUS.md](../../docs/ai-workflow/CURRENT_PROJECT_FOCUS.md)

## Context

The existing bounded PDO question in heading `2204` was correct and complete,
but still exposed 33 direct declarable choices.  A strict read-only audit of the
supplied full catalog found two adjacent boundaries whose exact uncoded title,
ordered leaf tuple and Canonical topology are retained in the source records:

- `2204213800` retains the final depth-7 header «прочие:» inside the 33-leaf
  PDO scope.  Its exact open/closed interval contains the following 16 sibling
  leaves through `2204217800`;
- `2204221800` independently retains the same depth-7 title.  Its exact interval
  contains seven sibling leaves through `2204225800`.

The official PDF also shows page-break headers including «белые:», but those
headers are not retained in the immutable Canonical source projection.  They are
therefore not exposed or synthesized by this decision.

The tracked official source audited for these boundaries is
`data/raw/tnved_tree/2025-01-01/ru.22_2022_25.04.2022.pdf`, pages 8 and 11
(one-based PDF pages), SHA-256
`d36ff91756bda80cf54895843e8c5fca75897b26d6e77596f29a885f06b375d7`.

## Binding safety boundary

- Canonical remains the sole source of truth for every code, parent, leaf role
  and snapshot identity.
- Both questions are codeless navigation guidance, never customs codes or legal
  classification decisions.
- Runtime acceptance requires the full ordered `(code, parent, is_leaf,
  description)` signatures and the exact packed header text, depth, punctuation
  and stop carrier.
- Any source, ordering, role, parent, metadata or assembly drift suppresses only
  the unproven wrapper and restores the complete prior route; no partial promise
  is published.
- No numeric range inference, missing page-break label, fake code, alias or
  product title is invented.
- Database/schema, ingestion, NTM exactness, public API, frontend, CI, LLM/vector
  work and serving flags are outside this decision.
- This memo does not authorize merge, rollout, deployment or feature activation.

## Option A — Two exact retained «прочие» questions

Within the existing PDO question, retain the first 17 leaves as direct choices
and add one nested codeless «прочие» question containing the exact following 16
leaves.  The user-visible PDO step becomes 18 choices / 17 direct codes, and the
nested step is 16 / 16.  The original 33-leaf PDO universe remains ordered and
reachable.

Under Canonical parent `2204220000`, add a separate codeless «прочие» question
for the exact seven-leaf interval after `2204221800` through `2204225800`.  That
parent step becomes 27 choices / 25 direct codes; the new question is 7 / 7.

The two rules are deliberately independent.  The `220422` question does not
claim a PDO, colour or other missing parent label, and the PDO split does not
label its 17 direct choices as «белые».

### Benefits

- removes every step above 30 choices in heading `2204`;
- reduces the catalog maximum from 33/33 to 29/27 without changing the code or
  leaf universe;
- uses only exact official descriptions retained by the source projection;
- preserves the accepted two-level semantic-depth limit;
- strengthens the existing `2204` golden assertion without adding a redundant
  eighth golden heading.

### Costs and residual risks

- adds two maintained heading-specific exact-source rules;
- a legitimate source-text revision disables the corresponding question until
  a fresh audit;
- the residual largest `2204` step is `2204290000` at 29/27;
- absent page-break headings cannot be used until the source pipeline retains
  and validates them.

## Rejected alternatives

### Option B — PDO boundary only

This safely produces 18/17 plus 16/16 inside PDO, but reveals the adjacent
`2204220000` step as 33/32 and therefore does not remove all steps above 30.

### Option C — Reconstruct missing page-break labels

Restoring explicit PDF hierarchy may enable more natural colour questions, but
requires an ingestion/Canonical-source decision and snapshot migration.  Runtime
invention of those labels is forbidden.

### Option D — Numeric or product-name clustering

Grouping by code prefixes, counts or repeated regional names would be easier to
maintain but is not proof of an official semantic boundary.

## Measured result

| Metric | Before | Option A |
| --- | ---: | ---: |
| PDO step / direct | 33 / 33 | 18 / 17 |
| Nested PDO «прочие» | — | 16 / 16 |
| `2204220000` step / direct | 33 / 32 after PDO-only slice | 27 / 25 |
| `220422` «прочие» | — | 7 / 7 |
| Heading/catalog maximum step / direct | 33 / 33 | 29 / 27 |
| `2204` semantic groups / subgroups | 8 / 0 | 10 / 1 |
| `2204` maximum semantic depth | 1 | 2 |
| Reachable `2204` source nodes | 211 / 211 | 211 / 211 |
| Reachable `2204` leaves | 170 / 170 | 170 / 170 |
| Catalog semantic leaf coverage | 6,942 / 13,254 | 6,949 / 13,254 |
| Catalog golden assertions | 7 / 7 | 7 / 7 |

On the supplied immutable snapshot the full census remained 1,263/1,263
headings, 16,708/16,708 source code nodes and 13,254/13,254 declarable leaves.
Strict Canonical/legacy Gate-2 remained 18,246/18,246 with zero mismatch or
unresolved path.

## Decision record

Ivan authorized continuation of all source-backed plan items, and the exact
`220422` sibling was explicitly included in the accepted conservative scope.
Option A is implemented and verified on the feature branch. Acceptance does
not authorize merge, rollout, deployment or feature activation.
