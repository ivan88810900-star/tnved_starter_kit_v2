# DM-0003: What follows TASK-CANONICAL-004

> **Status:** Accepted — Option C (Ivan, 2026-07-14)
> **Date:** 2026-07-14
> **Owner:** Ivan
> **Context:** ADR-0001, ADR-0002, TASK-CANONICAL-004, `CURRENT_PROJECT_FOCUS.md`

## Context

TASK-CANONICAL-004 is technically complete on `feat/canonical-read-path`:

- `CANONICAL_TREE_ENABLED` and `CANONICAL_TREE_SHADOW` remain default OFF;
- Gate-1 cache invalidation covers structural inputs;
- Gate-2 checked 18,049 `/children` paths: 18,049 match, 0 mismatch,
  0 unresolved, `gate2_ok=true`;
- legacy remains the production path, oracle, and fail-safe fallback;
- no API contract, database schema, frontend, NTM, or Duty behavior changed.

The next step is not mechanically determined:

1. ADR-0001 Stage 4 proposes moving Semantic Navigation, Notes, Search, AI/RAG,
   and later NTM/Duty to Canonical anchors.
2. `docs/ai-workflow/CURRENT_PROJECT_FOCUS.md` is Active and prioritizes the
   CustomsClear MVP sequence: normative block, TN VED search/code card, payments,
   risk, then grounded assistant.
3. `stable_id` formula and model `snapshot_id` inputs are still open decisions.
   Persisting anchors before those contracts are fixed can create migration debt.
4. Enabling the serving flag is an operational rollout decision and was explicitly
   excluded from TASK-CANONICAL-004.

Per `AGENTS.md`, this conflict must not be resolved by silently starting a new
implementation task.

## Decision required

Choose the sequence after TASK-CANONICAL-004 and confirm whether the Active MVP
focus still takes precedence over Canonical Stage 4.

## Decision

Ivan selected **Option C** on 2026-07-14. The next step is the MVP-aligned anchor
bridge: first freeze the Canonical anchor identity/snapshot contract, then use it in
the TN VED search/code-card slice. TASK-CANONICAL-004 remains unmerged and both runtime
flags remain default OFF until separate review/rollout decisions.

Execution follows the autonomous engineering model agreed with Ivan: the agent may
inspect, edit, test, correct, commit, and push isolated branches without stopping for
routine confirmations. Ivan retains strategic choices, production rollout, feature-flag
activation, and final merge authority.

## Option A — Roll out `/children` first

### Description

After Ivan reviews/merges TASK-CANONICAL-004, run a controlled shadow/canary rollout
and explicitly enable `CANONICAL_TREE_ENABLED` in a selected environment. Do not start
new anchor consumers until the read path is operationally stable.

### Pros

- validates real runtime latency, cache rebuild, fallback, and observability;
- completes the value loop for the already-built read path;
- keeps the blast radius limited to `/children`.

### Cons

- requires deployment ownership, monitoring thresholds, and a rollback window;
- does not advance the active MVP product slices directly;
- Gate-2 proves parity, not production capacity or multi-worker cache behavior.

## Option B — Continue Canonical Stage 4 immediately

### Description

Keep serving flags OFF and start migrating Semantic Navigation and Notes to
`anchor_node_id` / `stable_id`, followed by Search/embeddings.

### Pros

- follows ADR-0001's architectural sequence directly;
- reduces independent database structure reads;
- prepares AI/RAG and later NTM/Duty for one structural truth.

### Cons

- conflicts with the currently Active MVP priority unless Ivan reprioritizes it;
- persistent anchor consumers would depend on unresolved `stable_id` and
  `snapshot_id` contracts;
- scope is broader than one safe implementation task and needs its own ADR/tasks.

## Option C — MVP-aligned anchor bridge (recommended)

### Description

Finish governance for TASK-CANONICAL-004 first (review/merge by Ivan; flags remain
OFF). Then explicitly confirm/update `CURRENT_PROJECT_FOCUS.md` and make the TN VED
search/code-card slice the first additive Canonical anchor consumer. Before storing
anchors, close the `stable_id` formula and `snapshot_id` input decisions in a small ADR.
Do not migrate NTM/Duty or change enforcement semantics in this step.

### Pros

- reconciles the Canonical architecture with the approved user-facing MVP sequence;
- produces visible product value while establishing the anchor contract;
- avoids persisting identifiers before their lifecycle is defined;
- preserves source-kind isolation and keeps NTM/Duty out of scope;
- can remain additive/default OFF and reversible.

### Cons

- requires one short identity/snapshot design step before implementation;
- delays serving rollout of the completed `/children` path;
- needs a precise boundary between code-card data and later overlays.

## Codex recommendation

Choose **Option C**.

TASK-CANONICAL-004 has removed structural parity risk, but the next irreversible risk
is identifier lifecycle: Search, AI journals, RAG chunks, and graph edges must not store
anchors whose identity changes under an underspecified formula. A small identity/snapshot
ADR followed by a TN VED search/code-card task gives the MVP a user-facing result and
advances ADR-0001 without prematurely touching NTM/Duty or enabling production flags.

## What requires strategic review

Ivan / Strategic ChatGPT should answer:

1. Is the normative-block MVP complete enough to advance to TN VED search/code card?
2. Does `CURRENT_PROJECT_FOCUS.md` remain binding as written, or is Canonical Stage 4
   now the explicit primary workstream?
3. Should `stable_id` survive source snapshot revisions for the same real TN VED code,
   or intentionally include `snapshot_id` and change every revision?
4. Is `/children` rollout required before any new Canonical consumer, or may it remain
   default OFF while the next additive slice is built?

## Proposed next task if Option C is accepted

### TASK-CANONICAL-005 — Anchor identity and snapshot contract

**Goal:** approve and test one stable identity/lifecycle contract for real and synthetic
Canonical nodes before any persistent overlay, Search, RAG, or AI-journal reference.

**In scope:**

- exact `stable_id` inputs for real-code and codeless/synthetic nodes;
- exact `snapshot_id` structural/content inputs;
- alias/history behavior when a code is superseded;
- deterministic rebuild and revision-change tests;
- additive anchor DTO for the future TN VED code card.

**Out of scope:**

- enabling either Canonical feature flag;
- changing `/children` JSON;
- NTM or Duty migration/enforcement;
- database/Alembic changes before the identity ADR is accepted;
- Semantic/Notes/Search migration in the same task;
- legacy removal.

**Exit:** accepted identity ADR and a bounded implementation task for the TN VED
search/code-card anchor bridge.
