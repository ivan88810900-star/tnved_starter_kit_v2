# DM-0007: Guided 0406 fat and moisture chain

> **Status:** Accepted — Option A
> **Date:** 2026-08-07
> **Owner:** Ivan
> **Context:**
> [TASK-SEMANTIC-008](../tasks/TASK-SEMANTIC-008.md),
> [TASK-SEMANTIC-005](../tasks/TASK-SEMANTIC-005.md),
> [DM-0006](DM-0006-guided-0304-product-form-chain.md),
> [ADR-0003](ADR-0003-canonical-anchor-identity.md),
> [CURRENT_PROJECT_FOCUS.md](../../docs/ai-workflow/CURRENT_PROJECT_FOCUS.md)

## Context

The strict whole-catalog census on the supplied Gate-2 snapshot remains green:
1,228/1,228 headings, 16,708/16,708 source-backed code nodes and 13,254/13,254
declarable leaves. Heading `0406` nevertheless had the largest remaining
non-`2204` later-step usability outlier: one step under code branch `0406900000`
contained 27 choices, including 26 direct code choices. Only 10 of the heading's
47 declarable leaves were below semantic questions.

The official source text retained on `0406905000` contains an exact packed chain:
«прочие» → «с содержанием жира не более 40 мас.% и содержанием влаги в
обезжиренном веществе» → «не более 47 мас.%». Record `0406906900` closes the first
moisture interval and opens «более 47 мас.%, но не более 72 мас.%»; coded record
`0406909300` is the following «более 72 мас.%» choice.

A read-only prototype, using the unchanged real-code payload, showed that a
bounded three-question overlay reduces the largest `0406` step from 27/26 to
16/15 and raises semantic coverage from 10/47 to 21/47 leaves. All 54
source-backed code nodes and 47 leaves remain present exactly once.

## Binding safety boundary

- Canonical remains the sole source of truth for codes, leaf roles, parents and
  snapshot identity.
- Codeless choices are navigation guidance, not customs codes or a classification
  decision.
- The overlay may not invent, remove, duplicate or reclassify a real code.
- It must fail closed to the complete pre-task route on any source, ordering,
  leaf-role or Canonical-parent drift.
- It does not change the database, public API, frontend contract, generic
  extractor, LLM/vector contour or serving flags.
- This memo does not authorize merge, rollout, deployment or feature activation.

## Option A — Exact bounded moisture chain

Add one heading-specific top question sourced from `0406905000`:

> «с содержанием жира не более 40 мас.% и содержанием влаги в обезжиренном
> веществе»

Its exact ordered scope is `(0406905000, 0406909300]`: 17 declarable sibling
leaves, all with nearest Canonical parent `0406900000`. Inside it expose:

1. «не более 47 мас.%» — `(0406905000, 0406906900]`, exactly 3 leaves;
2. «более 47 мас.%, но не более 72 мас.%» — `(0406906900, 0406909200]`,
   exactly 13 leaves;
3. the existing coded leaf `0406909300` («более 72 мас.%») as a direct choice.

The scopes are exact ordered allowlists, not numeric range rules. Extractor and
Builder independently verify full `(code, parent, is_leaf)` tuples, packed-header
order/depth/text and activation boundaries. Any mismatch suppresses all bounded
questions atomically.

### Benefits

- reduces the measured `0406` maximum from 27/26 to 16/15 choices/direct codes;
- raises heading semantic coverage from 10/47 to 21/47 leaves;
- uses explicit official percentage boundaries instead of invented labels;
- stays within the accepted maximum semantic depth of two;
- preserves generic rejection of ambiguous «прочие» headers;
- keeps all 54 source nodes, 47 leaves, Canonical anchors and API fields unchanged.

### Costs and residual risks

- adds another maintained heading-specific exact-source rule;
- leaves 16/15 as a residual large step;
- does not expose the deeper rejected «прочие сыры...» header;
- any legitimate source revision disables the bounded route until another audit;
- codeless titles have deterministic guide IDs but no alias/history layer.

## Rejected alternatives

### Option B — Broader repeated-«прочие» chain

This could reduce the residual step further, but presents indistinguishable
«прочие» questions and needs either semantic depth above two or artificial
flattening. It is not authorized by this decision.

### Option C — Keep the current route

This avoids maintenance cost, but leaves the correct yet unwieldy 27/26 step and
uses only 10/47 leaves despite exact source evidence.

## Measured result

| Metric | Before | Option A |
| --- | ---: | ---: |
| `0406` root choices / direct | 5 / 5 | 5 / 5 |
| `0406` maximum step / direct | 27 / 26 | 16 / 15 |
| Semantic leaf coverage | 10 / 47 | 21 / 47 |
| Semantic groups | 3 | 5 |
| Reachable source nodes | 54 / 54 | 54 / 54 |
| Reachable declarable leaves | 47 / 47 | 47 / 47 |
| Maximum semantic depth | 1 | 2 |
| Catalog golden assertions | 6 / 6 | 7 / 7 |

The verified implementation reached 6,945/13,254 declarable leaves (52.3993%).
Whole-catalog correctness remained 1,228/1,228 and strict Canonical/legacy Gate-2
remained 18,211/18,211 with zero mismatch/unresolved on the supplied snapshot.

## Decision record

Ivan accepted **Option A — Exact bounded moisture chain** on 2026-08-07.
Implementation, verification and documentation are authorized on
`feat/canonical-read-path`. Commit and push were separately authorized on
2026-08-10. Acceptance does not authorize merge, rollout, deployment or feature
activation.
