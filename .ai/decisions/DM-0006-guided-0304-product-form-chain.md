# DM-0006: Guided 0304 product-form chain

> **Status:** Accepted — Option A
> **Date:** 2026-08-06
> **Owner:** Ivan
> **Context:**
> [TASK-SEMANTIC-007](../tasks/TASK-SEMANTIC-007.md),
> [TASK-SEMANTIC-005](../tasks/TASK-SEMANTIC-005.md),
> [DM-0005](DM-0005-guided-2204-pdo-interval.md),
> [ADR-0003](ADR-0003-canonical-anchor-identity.md),
> [CURRENT_PROJECT_FOCUS.md](../../docs/ai-workflow/CURRENT_PROJECT_FOCUS.md)

## Context

Heading `0304` is structurally correct and complete on the supplied Gate-2
snapshot: 117/117 source-backed code nodes and 100/100 declarable leaves are
reachable and Canonical-bound. It is nevertheless the catalog's largest root-step
usability outlier: 19 choices, including 16 direct code choices.

The official source contains a coherent five-part sequence for fresh/chilled and
frozen fish fillets or other fish meat. The strict generic extractor currently
recognizes three packed titles and rejects the two titles beginning with «прочее».
That generic rejection is correct catalog-wide, but it leaves this audited heading
with a mixed semantic/flat presentation and a rejected span of 59 code nodes.

The technically verified TASK-SEMANTIC-007 candidate binds the five-part sequence
to exact source text, endpoints, ordered code tuples, leaf roles and Canonical
parent topology. Its measured `0304` shape is 13/8 at root and 13/9 at the largest
step, with semantic coverage increasing from 82 to 92 of 100 leaves. Technical
evidence does not decide whether the product should display these five official
titles as one curated question chain, so `AGENTS.md` requires Ivan's decision.

## Decision required

Choose whether Guided may expose the exact five-part `0304` product-form chain,
add only the two generically rejected boundaries, or defer the heading to a future
generic packed-header parser.

## Binding safety boundary for every option

- Canonical remains the sole source of truth for real codes, roles, parents and
  snapshot identity.
- Codeless groups are navigation guidance, not customs codes or legal conclusions.
- No option may invent, remove, duplicate or silently reclassify a code.
- Any curated projection must fail closed to the complete pre-task route when its
  exact source or topology evidence drifts.
- Critical integrity failure retains the existing `DEGRADED` response and ordinary
  `/children` fallback without a 500 response.
- No option authorizes a database/API/frontend change, feature activation, LLM use,
  merge, rollout or deployment.

## Option A — Exact five-chain

### Option A description

Add one atomic, heading-specific projection containing these five exact open/closed
source intervals:

1. `(0304390000, 0304498000]` — «филе прочей рыбы, свежее или охлажденное» —
   19 source nodes / 16 leaves;
2. `(0304498000, 0304598000]` — «прочее, свежее или охлажденное» —
   11 / 10;
3. `(0304690000, 0304799000]` — «филе мороженое рыбы семейств
   Bregmacerotidae, Euclichthyidae, Gadidae, Macrouridae, Melanonidae,
   Merlucciidae, Moridae и Muraenolepididae» — 17 / 14;
4. `(0304799000, 0304898000]` — «филе прочей рыбы, мороженое» — 29 / 25;
5. `(0304898000, 0304999800]` — «прочее, мороженое» — 33 / 27.

The intervals are not broad numeric rules. Each must equal its complete audited
ordered source-code tuple, including non-leaf nodes, exact leaf flags and exact
nearest Canonical parents. Extractor and Builder independently recheck the entire
five-slice signature. One mismatch suppresses the whole bounded projection; no
partial chain is published.

### Option A pros

- presents one coherent official product-form sequence instead of mixed heuristics;
- reduces the measured root outlier from 19/16 to 13/8 and maximum step to 13/9;
- raises semantic coverage from 82 to 92 of 100 declarable leaves;
- preserves all 117 source nodes and 100 leaves with exact Canonical topology;
- exact full-tuple and double-gate checks make source drift fail closed;
- leaves the generic acceptance policy, API, frontend, database and flags unchanged;
- replaces the current 59-code unsplit warning with a bounded maximum of 33 while
  retaining an honest noncritical warning above the global limit of 30.

### Option A cons

- introduces another maintained heading-specific rule;
- Ivan must accept five user-visible boundary interpretations, including titles
  beginning with the otherwise unsafe generic word «прочее»;
- the fifth group still contains 33 source nodes, so one noncritical oversized
  warning remains;
- exact official titles are fuller than the current generic-cleaned labels, which
  changes codeless guide IDs for affected groups;
- source revisions may intentionally disable the whole chain until it is audited
  and accepted again.

## Option B — Add only the two missing boundaries

### Option B description

Keep the three groups currently recognized by the generic extractor and add bounded
exceptions only for «прочее, свежее или охлажденное» and «прочее, мороженое».

### Option B pros

- has the smallest immediate implementation surface;
- restores the two visibly missing product-form questions;
- can approach the same local choice and coverage metrics on the current snapshot.

### Option B cons

- publishes one five-part official sequence through two different trust models:
  three generic boundaries and two exact exceptions;
- does not bind the five titles, ordered tuples and topology as one atomic source
  signature;
- drift in one of the generic groups can leave a misleading partial chain;
- retains shortened generic-cleaned titles rather than the exact audited wording;
- creates less explainable maintenance and rollback behavior than Option A.

## Option C — Design a generic packed-header parser

### Option C description

Do not add a `0304` rule. First design a catalog-wide parser for packed official
descriptions, including generic titles such as «прочее», and then reconsider this
heading under the generic policy.

### Option C pros

- may eventually replace heading-specific slices with a reusable model;
- could improve many other flat or high-branching headings;
- would establish one catalog-wide packed-header policy.

### Option C cons

- is substantially broader than the audited `0304` evidence;
- «прочее» is not a safe boundary without surrounding source/topology context;
- a false generic boundary could misgroup legally visible choices across the
  catalog;
- requires a new full-catalog evidence census, adversarial tests and likely another
  product/legal decision;
- delays a bounded, measurable improvement for the current root outlier.

## Codex recommendation

Choose **Option A — Exact five-chain**.

The five titles form one source sequence, so they should share one evidence and
failure model. Exact ordered tuples, exact leaf/parent topology, immutable snapshot
input and independent Extractor/Builder checks make the candidate safer and easier
to explain than mixing generic and special rules. It also delivers a measured UX
improvement without generalizing from one heading.

The recommendation does not hide the remaining limitation: the final group has 33
source nodes, above the unchanged safe limit of 30. That warning must remain visible.
Further subdivision requires its own official evidence and decision.

## Guide-ID consequence requiring acceptance

Guided IDs for codeless groups include normalized title and semantic path. Option
A uses the exact official titles rather than some current shortened generic labels.
Consequently the affected codeless guide IDs may change, while all real coded-node
Canonical `stable_id` values remain unchanged.

This task adds no guide-ID alias or migration. Future accepted title changes also
produce new guide IDs, as required by ADR-0003; source drift first suppresses the
bounded chain. Persistent bookmarks, logs or external references to guide IDs would
require a separate alias/history decision before such consumers are introduced.

## Current and measured candidate evidence

| Metric | Current | Option A measured |
|--------|---------|-----------------|
| Root choices / direct | 19 / 16 | 13 / 8 |
| Maximum step / direct | 19 / 17 | 13 / 9 |
| Semantic leaf coverage | 82 / 100 | 92 / 100 |
| Semantic groups | 6 | 8 |
| Reachable source nodes | 117 / 117 | 117 / 117 |
| Reachable leaves | 100 / 100 | 100 / 100 |
| Largest noncritical span warning | 59 | 33 |
| Catalog golden assertions | 5 / 5 | 6 / 6 |

The candidate passed the focused and broad regressions, the strict read-only
whole-catalog census and Gate-2 audit. Catalog correctness remained 1,228/1,228
headings, 16,708/16,708 source nodes and 13,254/13,254 leaves with zero critical
mismatch; golden assertions are 6/6 and semantic coverage is 6,934/13,254
(52.3163%). The pristine Gate-2 database hash was unchanged. These technical
results do not accept the product-visible Option A decision.

## Decision record

**Accepted by Ivan on 2026-08-06: Option A — Exact five-chain.**

Ivan explicitly accepted Option A for DM-0006 after reviewing the measured
candidate results. Option B (mixed exact/generic trust) and Option C (defer to a
future generic parser) were not selected. TASK-SEMANTIC-007 may therefore be
marked Completed after its already-green final QA is recorded.

## Merge and rollout gate

Whichever option is selected:

- this Decision Memo does not merge, roll out or deploy code;
- both Canonical serving flags remain default OFF;
- no database/schema/ingestion change is authorized;
- no public API or frontend contract change is authorized;
- no external LLM, embedding provider request or spend is authorized.
