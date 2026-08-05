# TASK-CANONICAL-010 — Deep-freeze published Canonical graph

## Status

Completed — 2026-08-05

## Goal

Make the in-memory `CanonicalModel` physically immutable after publication so
its content-addressed `snapshot_id`, object graph and navigation indexes cannot
diverge through a retained `TreeNode` reference.

## Context

ADR-0001 already defines the Canonical model as immutable. Materialization had
only frozen the model facade: roots/navigation returned tuples and indexes used
`MappingProxyType`, while each returned `TreeNode` still exposed mutable scalar
attributes, `parent`, `children` and `metadata`.

The gap was directly reproducible: changing a published node's `is_leaf` made
`compute_snapshot_id(model.roots)` differ from `model.snapshot_id`; removing a
child changed `node.children` while the model's precomputed children index still
returned the old topology. TASK-CANONICAL-008 protected retained Guided source
records from that mutation, but did not repair the shared graph itself.

This is a corrective implementation of the accepted ADR invariant, not a new
architecture/product decision; no Decision Memo is required.

## Contract

- `TreeBuilder.build(...)`, recovery and identity stamping remain mutable.
- `CanonicalModel.from_roots(...)` runs the validator and stamps the snapshot
  version before the publication freeze.
- Every published node rejects assignment or deletion of scalar attributes,
  including attempts to clear its own frozen marker; the production node hierarchy
  is slotted and exposes no `__dict__` mutation bypass.
- Publication is available only through validator-gated
  `CanonicalModel.from_roots(...)`; direct constructor use is rejected, and every
  supplied root must have `parent is None`.
- Published `children` are tuples; `parent` cannot be reassigned.
- Metadata mappings, lists/tuples, sets and byte arrays are recursively detached
  and converted to `MappingProxyType`, tuple, frozenset and `bytes` respectively.
- Mutable container aliases retained before publication cannot mutate the model.
- Standard-container metadata cycles are rejected before the freeze commit point;
  the complete input graph remains mutable and retryable after that failure.
- Roots already belonging to a published model cannot be silently republished
  without their retained Parser inputs. The same recursive preflight rejects a
  published descendant before validator/stamping can mutate a new root.
- Stable-ID and snapshot formulas, node classes, serializers, API JSON and legacy
  tree behavior remain unchanged.

## Implementation scope

- `app/services/tree_engine/models.py`: mutable-build/frozen-publication guard,
  recursive container freeze and thaw protection.
- `app/services/tree_engine/canonical_model.py`: freeze at the model publication
  boundary after source projection/index construction.
- `app/services/tree_engine/serializer.py`: accept any root iterable, including
  the tuple returned by `CanonicalModel.roots`.
- Focused regressions for scalar/container mutation, alias detachment,
  topology/index/snapshot invariants and serializer compatibility.

## Out of scope

- PostgreSQL transaction isolation or provider revision changes.
- Semantic extraction, grouping policy or outlier thresholds.
- API/schema changes, migrations, database writes or materialized snapshots.
- Feature-flag rollout, aliases/history, LLM calls or embeddings.

## QA

- Focused deep-freeze and Guided leaf-role regressions: **17 passed**.
- Canonical/Guided/serializer compatibility on an isolated full-schema DB:
  **130 passed** (one unrelated Starlette/httpx deprecation warning).
- Compact full-data Gate-2: **18,211 / 18,211**, zero mismatch/unresolved,
  `gate2_ok=true`.
- Whole-catalog Guided census: **1,228 / 1,228** headings, one consistent
  snapshot, 16,708 source-backed nodes and 13,254 declarable leaves, all four
  golden assertions green.

Gate-2 and whole-catalog census opened the compact database in strict read-only
mode. The broad suite used an isolated database copy; source databases remained
unchanged. Canonical serving flags remained OFF and no external provider was
called.

## Known limitation

The publication freezer recursively handles the standard containers used by
production Canonical metadata. An arbitrary custom mutable object stored as a
metadata value is retained as that object: freezing unknown classes safely would
require a separate cloning/serialization protocol. No current production Canonical
metadata contains such objects.

## Safety

This is publication-boundary hardening only. `stable-id-v1` and
`canonical-snapshot-v2` formulas, API behavior, legacy behavior and feature-flag
values are unchanged; no flag was enabled and no database/schema was modified.
