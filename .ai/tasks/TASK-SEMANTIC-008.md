# TASK-SEMANTIC-008 — Exact fat/moisture chain for heading 0406

## Status

Completed — 2026-08-10.

## Goal

Replace the 27/26-choice outlier under `0406900000` with one exact,
source-backed and fail-closed fat/moisture route while preserving every
Canonical code, role, parent and snapshot.

## Scope

### In scope

- one bounded `0406` projection with the exact three-step contract in DM-0007;
- full ordered `(code, Canonical parent, leaf role)` signatures for all 17 leaves;
- independent Extractor and Builder verification;
- atomic suppression/spillback on any mismatch;
- a seventh aggregate-only golden hierarchy assertion;
- focused, Gate-2 and whole-catalog read-only QA.

### Out of scope

- generic acceptance of «прочие» or a catalog-wide packed-header parser;
- semantic depth above two;
- regrouping other parts of `0406` or another heading;
- fake/virtual customs codes or Canonical identity changes;
- database/schema/ingestion, public API or frontend changes;
- feature activation, LLM/vector work, merge, rollout or deployment.

## Exact Option A contract

The top codeless group uses the exact official title:

> «с содержанием жира не более 40 мас.% и содержанием влаги в обезжиренном
> веществе»

Its ordered scope is:

```text
0406906100 0406906300 0406906900 0406907300 0406907400
0406907500 0406907600 0406907800 0406907900 0406908100
0406908200 0406908400 0406908500 0406908600 0406908900
0406909200 0406909300
```

Every code is a Canonical declarable leaf whose nearest distinct coded parent is
`0406900000`. The nested exact scopes are:

- «не более 47 мас.%»: `0406906100`, `0406906300`, `0406906900`;
- «более 47 мас.%, но не более 72 мас.%»: exact ordered allowlist ending at
  `0406909200` (13 leaves);
- `0406909300` remains the direct coded «более 72 мас.%» choice.

The implementation verifies exact packed source chains on `0406905000` and
`0406906900`, the following coded boundary, ordering, title text, dash depth,
finality, parent and leaf evidence. Prefixes, endpoints or counts alone are not
evidence.

## Fail-closed behavior

Any missing, extra, reordered or substituted code; title/depth/punctuation drift;
hidden boundary at the same or shallower depth; changed leaf role or parent;
malformed verified metadata; partial assembly; or post-containment scope drift
suppresses the complete bounded chain. All real codes spill back to the safe
pre-task route and empty wrappers are pruned. No partial percentage hierarchy may
be returned as `OK`.

## Acceptance targets

- `0406`: 54/54 source nodes and 47/47 declarable leaves reachable and bound;
- root remains 5/5 choices/direct codes;
- maximum step becomes exactly 16/15;
- semantic coverage becomes exactly 21/47;
- semantic groups become 5 and maximum semantic depth remains 2;
- zero fake, duplicate, critical, degraded, leaf-role or parent mismatch;
- whole catalog remains 1,228/1,228 with 16,708/16,708 source nodes and
  13,254/13,254 leaves;
- catalog semantic coverage becomes 6,945/13,254;
- golden assertions become 7/7;
- strict Canonical/legacy Gate-2 remains 18,211/18,211;
- pristine Gate-2 database hash remains unchanged.

## Required regressions

- exact source/header/topology acceptance and deterministic shuffled input;
- exact ordered top and nested scopes;
- activation is after the source anchor, never on it;
- missing/extra/substituted/reordered code fails closed;
- parent and leaf-role drift fail closed;
- title, punctuation, marker-depth, finality and hidden-boundary drift fail closed;
- malformed/tampered Builder metadata and post-containment drift spill all codes;
- existing deeper rejected «прочие сыры...» candidate remains rejected;
- existing `0304`, `2204`, generic extraction and public Guided/API tests stay green;
- diagnostic report remains aggregate-only and contains no ten-digit allowlist or
  product titles.

## Changed files

```text
customs-clear/backend/app/services/semantic_navigation/bounded_slices.py
customs-clear/backend/app/services/semantic_navigation/extractor.py
customs-clear/backend/app/services/semantic_navigation/builder.py
customs-clear/backend/scripts/diagnose_guided_tnved_navigation.py
customs-clear/backend/tests/test_semantic_navigation_0406_moisture.py
customs-clear/backend/tests/test_diagnose_guided_tnved_navigation_catalog.py
```

## Completion evidence

- [x] Ivan accepted DM-0007 Option A.
- [x] Exact bounded chain is implemented and adversarially tested.
- [x] Current self-contained focused semantic selection: 85 passed.
- [x] Current surrounding Guided/Canonical runtime selection: 41 passed.
- [x] Earlier strict supplied Gate-2 run met all exact acceptance targets:
  1,228/1,228, 16,708/16,708, 13,254/13,254, golden 7/7 and
  Canonical/legacy 18,211/18,211.
- [x] Flags remain OFF and no API/frontend/DB/LLM scope is added.
- [x] Separate commit/push authorization recorded on 2026-08-10.

The original compact Gate-2 attachment was no longer materializable during the
2026-08-10 publication preflight. The full-data numbers above are retained from
the completed immutable read-only run; current publication QA reran all 85
self-contained semantic regressions plus 41 surrounding runtime regressions and
did not substitute a partial database as full-data evidence.
