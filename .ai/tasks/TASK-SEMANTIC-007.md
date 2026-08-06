# TASK-SEMANTIC-007 — Exact product-form chain for heading 0304

## Status

Completed — 2026-08-06.

[DM-0006](../decisions/DM-0006-guided-0304-product-form-chain.md) is
**Accepted — Option A** by Ivan on 2026-08-06. The implementation and strict
read-only evidence are complete. This status does not authorize merge, rollout,
deployment or feature-flag activation.

## Goal

Replace the mixed generic/flat presentation of five audited product-form spans in
heading `0304` with one exact, source-backed and fail-closed five-question chain,
without changing the Canonical code structure or the generic semantic parser.

## Context

TASK-SEMANTIC-005 identified `0304` as the catalog's largest first-step Guided
outlier. On the current Gate-2 snapshot the heading is correct and complete, but
its root exposes 19 choices, including 16 direct code choices. The existing strict
extractor recognizes three useful packed headers and rejects two titles beginning
with «прочее» under its generic safety policy. As a result, one official sequence
is presented through a mixture of generic groups and a large flat span.

The candidate does not weaken that generic policy. It describes one named `0304`
source/topology signature, analogous in safety intent to the accepted bounded
`2204` slice, while preserving the different Canonical parents and non-leaf nodes
inside each source interval.

## Decision status

This is a user-visible interpretation of legally meaningful nomenclature text.
Per `AGENTS.md`, implementation evidence may be prepared on the feature branch,
but Option A requires an explicit Ivan decision before the task can be accepted.

No part of this task authorizes merge, rollout, deployment or activation of
`CANONICAL_TREE_ENABLED` / `CANONICAL_TREE_SHADOW`.

## Exact candidate chain

Every span is open at its source anchor and closed at its stop. The stop remains
a real code inside the preceding group; when it also carries the next packed
title, that next title becomes active only for the following source record.

- **A:** «филе прочей рыбы, свежее или охлажденное»;
  `(0304390000, 0304498000]`; 19 source-code nodes (`03044*`), 16 leaves.
- **B:** «прочее, свежее или охлажденное»;
  `(0304498000, 0304598000]`; 11 source-code nodes (`03045*`), 10 leaves.
- **C:** «филе мороженое рыбы семейств Bregmacerotidae, Euclichthyidae,
  Gadidae, Macrouridae, Melanonidae, Merlucciidae, Moridae и
  Muraenolepididae»; `(0304690000, 0304799000]`; 17 source-code nodes
  (`03047*`), 14 leaves.
- **D:** «филе прочей рыбы, мороженое»; `(0304799000, 0304898000]`;
  29 source-code nodes (`03048*`), 25 leaves.
- **E:** «прочее, мороженое»; `(0304898000, 0304999800]`;
  33 source-code nodes (`03049*`), 27 leaves.

The prefixes above are review aids, not numeric range rules. Each
slice must match its complete ordered tuple of source-backed Canonical code nodes,
including intermediate non-leaves, exact leaf flags and the exact nearest
Canonical parent of every node. Numeric values absent from the audited tuple must
not be invented or inferred.

The five exact ordered tuples are versioned implementation constants in
`semantic_navigation/bounded_slices.py`. Extractor and Builder must both compare
the entire signature; matching only endpoints, prefixes or counts is forbidden.

## Exact source contract

Option A may emit the five bounded questions only when one immutable Canonical
source projection for heading `0304` proves all of the following:

- the pad/root record is `0304000000`, and all five anchors and stops exist in the
  same source order;
- the complete 117-node non-pad heading projection exactly matches its audited
  ordered `(code, Canonical parent, leaf role)` signature, including the eight
  intentionally flat `03043*` / `03046*` leaves;
- each anchor contains the exact final packed title shown above; normalization may
  remove only the already-defined dash separators and outer whitespace;
- each title activates after its anchor, never on the anchor itself;
- every `(anchor, stop]` source scope equals its exact ordered tuple;
- no unaccounted packed boundary at the relevant or shallower semantic depth
  intervenes inside a scope;
- all source nodes bind to the selected Canonical snapshot with their exact
  code, leaf role and nearest Canonical-parent topology;
- the five scopes are emitted as one audited chain, rather than five independent
  prefix guesses;
- records outside the five exact scopes retain their existing safe placement.

The existing generic extraction acceptance policy remains unchanged. This
signature is not evidence that every packed description, every `0304*` prefix or
every title beginning with «прочее» is a safe semantic boundary.

## Required behavior

1. Add five codeless navigation choices with the exact titles and scopes above.
2. Keep every one of the 117 source-backed code nodes and all 100 Canonical
   declarable leaves reachable exactly once.
3. Preserve every Canonical anchor, leaf role, parent relationship, snapshot and
   source order; semantic groups may guide navigation but may not rewrite legal
   code structure.
4. Keep the public Guided endpoint, response schema and frontend contract
   unchanged.
5. Keep `MAX_UNSPLIT_GROUP_CODES=30`. Slice E therefore retains one honest
   noncritical 33-code warning; no heading-specific threshold exemption is allowed.
6. Replace the current 59-code unsplit warning caused by the missing final boundary
   with the exact chain rather than suppressing the warning or pretending the
   large span is semantically verified.
7. Add `0304` as the sixth permanent aggregate-only golden hierarchy assertion.

## Fail-closed contract

Any missing, reordered or substituted code; marker/title drift; wrong anchor or
stop; extra/intervening packed boundary; changed leaf role; changed Canonical
parent; incomplete source projection; snapshot mismatch; or tuple/count mismatch
suppresses the entire bounded five-chain projection.

On suppression, Guided must preserve the complete pre-task ordinary/generic route.
No partial bounded chain may be published. If a malformed or incomplete verified
group reaches Builder assembly, all affected real nodes spill back to their safe
placement and every empty semantic group is pruned. Independent critical integrity
errors retain the existing `DEGRADED` result and ordinary `/children` fallback,
without a 500 response.

## Guide-ID title caveat

Guided IDs for codeless groups are derived from their normalized title and semantic
path. The exact official titles in Option A are intentionally fuller than some
currently generic-cleaned titles, so existing feature-branch guide IDs for the
three already recognized groups may change; the two new groups receive new IDs.

Real coded-node `stable_id` values do not change. No persistent guide-ID consumer,
alias or migration is added here. A later accepted official-title revision would
produce a new codeless guide ID after the exact signature is reviewed; silently
reusing an old ID for a changed title is forbidden by ADR-0003. If persistent
guide references are introduced, they require a separate alias/history decision.

## Current baseline and candidate targets

All target values are acceptance criteria for the candidate, not completed QA
claims.

| Metric | Current baseline | Option A target |
|--------|------------------|-----------------|
| `0304` root choices / direct code choices | 19 / 16 | 13 / 8 |
| `0304` maximum step choices / direct code choices | 19 / 17 | 13 / 9 |
| Declarable leaves under semantic choices | 82 / 100 | 92 / 100 |
| Semantic groups | 6 | 8 |
| Reachable source nodes | 117 / 117 | 117 / 117 |
| Reachable declarable leaves | 100 / 100 | 100 / 100 |
| Largest retained noncritical span warning | 59 | 33 |
| Golden hierarchy assertions | 5 / 5 | 6 / 6 |

Whole-catalog correctness must remain 1,228/1,228 headings, 16,708/16,708
source-backed code nodes and 13,254/13,254 declarable leaves, with zero fake,
duplicate, critical, degraded, empty-root, leaf-role, Canonical-parent and snapshot
mismatches. If only this bounded slice changes coverage, the expected catalog
semantic-leaf coverage is 6,934/13,254 (52.3163%); QA must report the measured
value rather than copying this projection.

## Files / areas to inspect

```text
customs-clear/backend/app/services/semantic_navigation/bounded_slices.py
customs-clear/backend/app/services/semantic_navigation/extractor.py
customs-clear/backend/app/services/semantic_navigation/builder.py
customs-clear/backend/scripts/diagnose_guided_tnved_navigation.py
customs-clear/backend/tests/test_semantic_navigation_0304_state.py
customs-clear/backend/tests/test_diagnose_guided_tnved_navigation_catalog.py
```

## Required regression coverage

- exact five-chain acceptance, titles, activation boundaries and ordered tuples;
- all intermediate Canonical non-leaves, leaf roles and nearest parents preserved;
- shuffled input remains deterministic;
- each anchor/stop missing, changed or reordered fails closed;
- same-count interior substitution and prefix-valid extra code fail closed;
- title, punctuation, packed-header depth and intervening-boundary drift fail closed;
- partial/malformed Builder scope spills every code back and prunes empty groups;
- complete `0304` service output remains 117/117 nodes and 100/100 leaves;
- exact 13/8 root and 13/9 maximum-step shape;
- coverage 92/100, semantic groups 8 and exactly one noncritical 33 warning;
- sixth aggregate-only golden assertion and report privacy;
- deterministic guide IDs for unchanged titles and explicit title-change behavior;
- existing `2204`, generic extraction, API and Canonical regressions remain green.

## QA gates before completion

```bash
pytest -q \
  tests/test_semantic_navigation_0304_state.py \
  tests/test_semantic_navigation_2204_pdo.py \
  tests/test_diagnose_guided_tnved_navigation_catalog.py \
  tests/test_guided_tnved_navigation.py \
  tests/test_guided_canonical_leaf_roles.py

python3 scripts/diagnose_guided_tnved_navigation.py \
  --headings 0304 \
  --require-complete

python3 scripts/diagnose_guided_tnved_navigation.py \
  --all-headings \
  --require-complete \
  --output guided-tnved-semantic-007.json
```

Rerun the strict read-only Gate-2 Canonical/legacy audit and Python compilation.
Reports must remain aggregate-only and must not export product descriptions,
ten-digit code allowlists, credentials or absolute database paths.

## Measured QA evidence

The accepted Option A implementation was verified on 2026-08-06:

- final focused acceptance suite: 71 passed;
- broader Canonical, Guided, API and terminal-L4 suites: 152 passed and 57
  data-dependent skips; one pre-existing Starlette/httpx deprecation warning;
- targeted read-only `0304`: status OK, root 13/8, maximum step 13/9,
  117/117 source nodes, 100/100 leaves, 92/100 semantic coverage and 8 groups;
- whole catalog: 1,228/1,228 complete headings, 16,708/16,708 source nodes,
  13,254/13,254 leaves, 6/6 golden assertions, zero critical/degraded/fake/
  duplicate/role/parent/snapshot problems;
- catalog semantic coverage: 6,934/13,254 (52.3163%);
- strict Canonical/legacy Gate-2: 18,211/18,211 matches, zero mismatch/unresolved;
- exactly one expected noncritical `oversized_unsplit_group` warning remains for
  the 33-node final state; the global limit remains 30;
- aggregate reports contain no ten-digit allowlist or product titles, and the
  pristine Gate-2 SHA-256 remained
  `b3ece86c68b5010486ec64cce102759673ddc585e634e5698be596d22a8d8d2b`.

The legacy `test_semantic_navigation_v1.py` harness calls `init_db()`/Alembic and
is not safe against the intentionally compact Gate-2 schema. It was not used as
Gate-2 evidence; equivalent current Guided/Canonical/API paths ran on an isolated
full-schema QA copy instead.

A repository-wide collection discovered 978 tests but the temporary sandbox
could not import 59 unrelated modules because optional project dependencies such
as pandas, the Google SDK and BeautifulSoup were not installed. Installing the
full requirements set was blocked by the sandbox's network policy. This does not
replace or weaken the green task-focused, broad Canonical/Guided/API and full-data
gates recorded above.

## Out of scope and safety

- No generic packed-header parser or global confidence-policy change.
- No other heading, fake/virtual customs level or change to Canonical code identity.
- No database/schema mutation, migration, seed, ingestion or write path.
- No public API/schema or frontend change.
- No feature-flag activation; both Canonical serving flags remain default OFF.
- No merge, rollout or deployment.
- No LLM, embedding, vector index, external provider request or spend.
- No guide-ID alias/history layer and no nomenclature-transition implementation.

Rollback is one task-code revert. It requires no database or data rollback and
returns `0304` to the complete pre-task route.

## Acceptance criteria

- [x] Ivan selects Option A in DM-0006.
- [x] Exact five-chain and complete heading source/topology signatures are
  enforced independently by Extractor and Builder.
- [x] All focused regressions pass.
- [x] `0304` reaches the measured target without correctness loss.
- [x] Whole-catalog census and Gate-2 remain green on one read-only snapshot.
- [x] Golden hierarchy assertions pass 6/6.
- [x] Flags remain OFF and no API/frontend/DB/LLM surface changes.
- [x] QA report records actual commands, results, warning and limitations.
- [x] `git diff --check` and documentation lint pass.
