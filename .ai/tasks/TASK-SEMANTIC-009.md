# TASK-SEMANTIC-009 — Exact retained «прочие» boundaries for heading 2204

## Status

Completed on the feature branch — 2026-08-18.

## Goal

Remove every `2204` user step above 30 choices using only exact uncoded
boundaries retained by the supplied official source projection, while preserving
all 211 source codes, 170 leaves and the existing 33-leaf PDO universe.

## Scope

### In scope

- the retained depth-7 «прочие» boundary inside the existing `220421` PDO group;
- the independent retained depth-7 «прочие» boundary under `2204220000`;
- exact ordered `(code, Canonical parent, leaf role, official description)`
  signatures, packed-header topology and stop carriers;
- independent Extractor and Builder validation with atomic fail-flat behavior;
- strengthened aggregate-only `2204` golden diagnostics and adversarial tests;
- heading, full-catalog and Gate-2 read-only verification.

### Out of scope

- synthesizing the PDF page-break label «белые» or any other missing header;
- generic acceptance of «прочие», numeric range rules or product-name clustering;
- code/leaf/parent/snapshot changes or fake/virtual customs codes;
- NTM exactness, API, frontend, CI, database, ingestion or serving flags;
- an eighth golden heading, merge, commit, push, rollout or deployment.

## Exact contract

The existing PDO wrapper remains the sole parent of its exact 33 ordered leaves.
Its first 17 leaves remain direct choices.  The retained «прочие:» header on
`2204213800` opens one nested codeless subgroup whose exact scope is the following
16 sibling leaves through `2204217800`.

The independent «прочие:» header on `2204221800` opens one codeless top-level
semantic group under Canonical parent `2204220000`.  Its exact scope is seven
sibling leaves through `2204225800`.

Neither rule assigns a missing colour/PDO label to `220422`, and neither exposes
an unretained «белые» question.  Endpoints and counts alone are insufficient:
the entire ordered source and topology signature must match.

## Fail-closed behavior

Missing, extra, reordered or substituted codes; title, punctuation, depth or
description drift; changed leaf role or parent; hidden intervening boundary;
malformed verified metadata; incomplete assembly; or post-containment drift
suppresses the affected new wrapper.  Its real nodes are spliced back into the
prior complete route.  A malformed nested PDO wrapper returns all 33 PDO leaves
to direct order.  No empty or partial semantic promise is returned as valid.

## Acceptance targets

- PDO becomes exactly 18/17 with one exact 16/16 nested subgroup;
- `2204220000` becomes exactly 27/25 with one exact 7/7 group;
- `2204` and catalog maximum become materially below 30, exactly 29/27;
- 211/211 `2204` source nodes and 170/170 leaves remain reachable exactly once;
- zero fake, duplicate, critical, degraded, role, parent or snapshot mismatch;
- full catalog remains 1,263/1,263, 16,708/16,708 code nodes and
  13,254/13,254 leaves;
- semantic coverage becomes 6,949/13,254;
- existing golden headings remain 7/7;
- strict Gate-2 remains green on all 18,246 checked paths;
- source database remains read-only and serving flags remain off.

## Changed files

```text
customs-clear/backend/app/services/semantic_navigation/bounded_slices.py
customs-clear/backend/app/services/semantic_navigation/extractor.py
customs-clear/backend/app/services/semantic_navigation/builder.py
customs-clear/backend/scripts/diagnose_guided_tnved_navigation.py
customs-clear/backend/tests/test_semantic_navigation_2204_pdo.py
customs-clear/backend/tests/test_diagnose_guided_tnved_navigation_catalog.py
.ai/decisions/DM-0012-guided-2204-retained-other-boundaries.md
.ai/tasks/TASK-SEMANTIC-009.md
```

## Completion evidence

- [x] Exact official descriptions and ordered topology audited against
  `/tmp/tnved-next-slice.YvmfkL/full-catalog.db` and tracked source
  `data/raw/tnved_tree/2025-01-01/ru.22_2022_25.04.2022.pdf`, pages 8 and 11
  (one-based), SHA-256
  `d36ff91756bda80cf54895843e8c5fca75897b26d6e77596f29a885f06b375d7`;
  all 48 pinned Canonical description carriers matched byte-for-byte.
- [x] After the PDO-only bounded split, the full 1,263-heading census remained
  correct and exposed the adjacent residual `220422` maximum at 33/32.
- [x] After the independent `220422` group, the full census is green at 29/27;
  all correctness problem lists are empty and golden is 7/7.
- [x] Focused `2204` plus aggregate diagnostic selection: 46 passed.
- [x] Surrounding semantic/Guided/Canonical selection on an isolated writable
  copy of the supplied DB: 158 passed; one pre-existing Starlette warning.
- [x] Strict read-only Gate-2: 17,809 commodities, 96 chapter paths, 18,150 node
  paths, 18,246/18,246 matches, zero mismatch/unresolved, `gate2_ok=true`.
- [x] Read-only input inventory: 21 sections, 96 chapters, 17,809 commodities
  and 13,290 pinned `hs_rates` rows.
- [x] Read-only source DB final SHA-256:
  `bf7d7db352e588335b8c7b5f710a9c8f306aa0f5a0eee8d033e3abc496cfa0da`.
- [x] Python compilation and `git diff --check` pass.
- [x] No NTM/API/frontend/CI/DB/flag file was changed by this task.

## Residual limitation

`2204290000` remains the largest `2204` step at 29 choices / 27 direct codes.
No further split was added because the retained source projection does not
justify another safe user-visible boundary within this task.  Page-break labels
visible only in the PDF require a future source-ingestion decision, not a runtime
guess.
