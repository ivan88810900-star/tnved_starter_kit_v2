# DM-0005: Guided 2204 PDO interval

> **Status:** Accepted — Option A (Ivan, 2026-08-05)
> **Date:** 2026-08-05
> **Owner:** Ivan
> **Context:**
> [TASK-SEMANTIC-006](../tasks/TASK-SEMANTIC-006.md),
> [TASK-SEMANTIC-005](../tasks/TASK-SEMANTIC-005.md),
> [ADR-0001](ADR-0001-canonical-tnved-model.md),
> [CURRENT_PROJECT_FOCUS.md](../../docs/ai-workflow/CURRENT_PROJECT_FOCUS.md)

## Context

TASK-SEMANTIC-005 proved whole-catalog Guided integrity on the supplied Gate-2
snapshot and identified heading `2204` as the largest later-step usability
outlier. Under `220421`, the existing safe route presents 50 choices, including
47 direct code choices.

The official description retained on source record `2204210900` contains several
packed dash-prefixed headings. Its final depth-6 marker names wines with Protected
Designation of Origin (PDO). The first later matching depth-6 marker for Protected
Geographical Indication (PGI) is retained on `2204217800`.

TASK-SEMANTIC-006 is implemented and technically verified on the feature branch
as staged evidence for this decision. It adds one codeless PDO question only when
the official markers and an exact allowlist of 33 Canonical sibling leaves match.
The candidate reduces the `220421` step to 18 choices / 14 direct codes; selecting
PDO then presents 33/33 real Canonical codes. Whole-catalog integrity remains green.
Focused regressions reject an extra depth-6 anchor or stop header and hidden depth-5
or depth-6 boundaries inside the open interval, including text the generic extractor
would reject.

Technical correctness does not settle the product/legal choice. Showing the PDO
label changes what the user sees as an official-nomenclature question. The staged
interpretation also treats a packed header on one source record as a boundary for
the following siblings: PDO is `(2204210900, 2204217800]`, while the first code
choice under the following PGI question is `2204217900`. Per `AGENTS.md`, that
user-visible interpretation required an explicit Ivan decision.

## Decision

Ivan accepted **Option A — Exact bounded interval** on 2026-08-05. The accepted
product interpretation allows Guided to show the exact official PDO label as a
codeless navigation question under the bounded contract below. It also accepts the
boundary `(2204210900, 2204217800]`, with the next PGI code choices beginning at
`2204217900`, and retains one noncritical 33-choice oversized warning.

Options B and C were not selected. Acceptance records the product/legal direction;
this docs-only action does not merge, roll out or deploy the feature-branch code
and does not enable either Canonical serving flag.

## Binding safety boundary for every option

- Canonical remains the source of truth for real codes and identity.
- No option may invent, remove, duplicate or silently reclassify a customs code.
- A codeless semantic question is navigation guidance, not a declaration that the
  user's product legally qualifies as PDO or PGI.
- Any accepted semantic projection must fail closed to the complete flat Canonical
  route when its source or topology evidence drifts.
- Critical integrity failure continues to return the existing `DEGRADED` response
  and ordinary-tree fallback without a 500 response.
- This decision does not authorize database/API changes, LLM use, deployment,
  feature-flag activation or a broader legal-classification rule.

## Option A — Exact bounded interval (accepted)

### Option A description

Accept the staged TASK-SEMANTIC-006 behavior only for heading `2204`. Publish one
codeless PDO choice when all exact source and Canonical predicates match:

- parent `2204210000` is a Canonical non-leaf;
- anchor `2204210900` is the exclusive source boundary and contains the unique
  depth-6 packed header, which is final and is the exact bilingual PDO marker;
- no source record in the open interval `(2204210900, 2204217800)` contains a
  packed header at depth 6 or shallower (`dash_depth <= 6`), even when generic
  extraction would reject its text;
- `2204217800` contains exactly one depth-6 packed header, which is final and is
  the exact bilingual PGI marker, and is the inclusive boundary carrier;
- the official sibling scope is the exact ordered allowlist of 33 Canonical leaves
  already recorded in TASK-SEMANTIC-006;
- the first real code choice in the following PGI group is `2204217900`.

The rule remains a named bounded slice. It is not evidence for a generic packed-
header extraction policy.

### Option A pros

- exposes a meaningful question directly grounded in retained official wording;
- reduces the affected first decision from 50/47 to 18/14;
- keeps all 211 heading codes and all 170 declarable leaves reachable and bound;
- exact evidence, allowlist and Builder recheck make source drift fail closed;
- requires no database, schema, public API, frontend or LLM change;
- is independently reversible as one task slice.

### Option A cons

- deliberately introduces one heading-specific semantic rule;
- Ivan must accept the boundary interpretation in which `2204217800` closes PDO
  and the next PGI code choice begins at `2204217900`;
- PDO still opens 33 direct choices, above the unchanged global safe-nesting limit
  of 30;
- validation therefore retains exactly one noncritical
  `oversized_unsplit_group` warning;
- future official-source revisions may disable the question until the allowlist
  and markers are reviewed again.

## Option B — Keep the flat route

### Option B description

Do not merge the staged TASK-SEMANTIC-006 semantic behavior. Keep the existing
complete flat/canonical placement for heading `2204`, including the 50-choice /
47-direct-code step.

### Option B pros

- makes no new legal or user-visible interpretation of the packed source text;
- has no heading-specific maintenance rule;
- preserves the already-proven whole-catalog correctness baseline.

### Option B cons

- retains the catalog's measured worst later-step branching;
- does not expose the explicit official PDO/PGI distinction as a useful question;
- defers a high-value usability improvement despite exact source evidence and a
  verified fail-closed implementation.

## Option C — Design a generic packed-header parser

### Option C description

Do not merge the staged rule as product behavior. First design and validate a
catalog-wide parser for descriptions containing multiple dash-prefixed headings,
then decide which generic evidence and hierarchy rules may drive Guided questions.

### Option C pros

- could replace heading-specific slices with one reusable parsing model;
- could improve multiple currently flat or high-branching headings;
- creates an explicit long-term policy for packed official descriptions.

### Option C cons

- is substantially broader than the verified `2204` evidence;
- official descriptions vary in dash depth, boundary placement and text quality;
- a false generic boundary can misgroup many legally visible code choices;
- requires a new catalog-wide evidence census, adversarial regressions and likely
  another product/legal decision before implementation;
- delays the bounded verified improvement and risks conflating one known pattern
  with a universal nomenclature rule.

## Codex recommendation — accepted by Ivan

Choose **Option A**, exact bounded interval.

It produces measurable product value while keeping the risk surface explicit and
reversible. The staged rule requires exactly one final depth-6 PDO header at the
anchor, no header at depth 6 or shallower anywhere in the open interval, exactly
one final depth-6 PGI header at the stop, exact boundary codes, exact Canonical
parent/leaf roles and an exact ordered 33-code allowlist. A single mismatch
suppresses the projection and preserves the flat route. That is safer than
generalizing from one packed description, and more useful than retaining the known
50/47 outlier.

The recommendation also accepts one visible limitation: PDO opens 33/33 choices
and keeps one noncritical oversized warning. The global limit must not be relaxed
or the warning suppressed. Any further subdivision requires another bounded
official-evidence slice or a separately accepted generic design.

## Decision record

Ivan's acceptance resolves the strategic questions as follows:

1. Guided may show the exact official PDO label as a codeless navigation question;
   it remains guidance, not a legal product qualification.
2. The staged boundary is accepted: `2204210900` is exclusive, `2204217800` is
   inclusive and the following PGI code choices begin at `2204217900`.
3. One noncritical 33-choice oversized warning is accepted and must remain visible;
   the global limit of 30 is not relaxed.
4. The named heading-specific rule is accepted. A generic packed-header parser is
   not authorized by this decision and would require a separate design and gate.

## Merge and rollout gate

Option A is accepted, but merge and operational rollout remain separate actions:

- TASK-SEMANTIC-006 is completed and accepted in governance, while its code remains
  implemented and verified only on the feature branch;
- this docs-only update does not merge, roll out or deploy the user-visible behavior;
- `CANONICAL_TREE_ENABLED` and `CANONICAL_TREE_SHADOW` remain default OFF;
- no deployment, database/API change, external LLM call or provider spend is
  authorized.

Before any later merge action, rerun the focused and strict read-only whole-catalog
gates and review the complete branch diff. A future merge still does not itself
authorize production deployment or either Canonical serving flag.
