# TASK-CANONICAL-005: Freeze Canonical anchor identity and snapshot

> **Status:** Completed (ADR-0003 Accepted; implementation QA passed)
> **Owner:** Backend Engineer (+ Architect review)
> **Created:** 2026-07-14
> **Depends on:** ADR-0003 acceptance, TASK-CANONICAL-004 completion

## Goal

Implement the accepted ADR-0003 identity contract so Canonical nodes expose a stable,
versioned anchor suitable for the next TN VED search/code-card task without changing
current API behavior or enabling runtime flags.

## Scope

- version and freeze the `stable_id` formula;
- compute `snapshot_id` from deterministic Canonical output rather than `db_codes`;
- stamp one snapshot consistently on model and all nodes;
- define an internal additive `CanonicalAnchor` DTO;
- add determinism, mutation, ordering, collision, and serialization tests;
- update Canonical documentation and debt tables.

## Required behavior

1. `stable_id` does not include snapshot, database PK, time, randomness, or process state.
2. Content-only changes preserve coded-node identity and change output snapshot.
3. Structural identity changes affect the relevant stable IDs and snapshot.
4. Snapshot canonicalization is independent of DB row order and engine-specific values.
5. Provider source revision remains the cache rebuild trigger; model snapshot identifies
   the produced artifact.
6. Legacy serialization and `/children` JSON remain byte-compatible.
7. Validator gate and legacy fallback remain mandatory.

## Files / areas to inspect

- `app/services/tree_engine/models.py`
- `app/services/tree_engine/builder.py`
- `app/services/tree_engine/canonical_model.py`
- `app/services/tree_engine/provider.py`
- `app/services/tree_engine/serializer.py`
- `tests/test_canonical_tnved_model.py`
- `tests/test_canonical_read_path.py`

## Tests

- identical builds → identical stable IDs and snapshot;
- input order permutation → identical result;
- title/duty/notes/flags mutation → expected identity/snapshot behavior;
- wrapper/leaf same-code collision remains uniquely addressable;
- codeless title mutation follows ADR behavior;
- model/node snapshot consistency;
- legacy serializer excludes anchor fields;
- existing TASK-CANONICAL-004 focused regression remains green.

## Do not do

- do not enable `CANONICAL_TREE_ENABLED` or `CANONICAL_TREE_SHADOW`;
- do not merge or roll out TASK-CANONICAL-004;
- do not change `/children` or any public JSON contract;
- do not add DB/Alembic changes or persist anchors;
- do not migrate Semantic/Notes/Search/AI/RAG/NTM/Duty in this task;
- do not remove or modify legacy behavior;
- do not broaden root legacy `backend/`.

## Acceptance criteria

- [x] ADR-0003 accepted and implementation matches it exactly.
- [x] All new identity/snapshot tests pass.
- [x] TASK-CANONICAL-004 focused suite remains green.
- [x] Ruff/compileall pass for changed Python files.
- [x] Documentation reflects the final formula and remaining rollout boundary.
- [x] Feature flags remain default OFF.

## Completion report (2026-07-14)

### Implementation

- `stable-id-v1`: SHA-1 (24 hex) over the version prefix and compact JSON path of
  `(node_type, local_key)` segments; NFC + outer trim normalization; no snapshot,
  storage ID, timestamp, or random input.
- `canonical-snapshot-v2`: SHA-256 (32 hex) over deterministic Canonical output,
  including structure, names, flags, duty and notes, excluding IDs and request-time
  overlays.
- one computed `snapshot_id` is stamped on the model and every node;
- frozen internal `CanonicalAnchor(stable_id, snapshot_id, code, node_type)` added;
- legacy serializer and public `/children` response remain unchanged.

### Verification

- Ruff and `compileall`: passed.
- TASK-CANONICAL-004 focused regression: **40 passed**.
- Identity/snapshot selection: **15 passed**.
- Data-dependent model/tree suites: **36 passed, 7 failed**; the same seven missing-data
  failures occur at parent `af5dd7b`, therefore **zero new failures**.
- Synthetic 18,090-node timing: stable IDs 64.09 ms, snapshot 102.26 ms, stamping
  1.87 ms in the QA container.
- Broad backend run (excluding the unavailable `py7zr` collector): 1,233 passed,
  2 skipped; remaining failures/errors are pre-existing environment/full-dataset
  dependencies and are not used as this task's acceptance gate.

### Boundary / next task

No flag was enabled, no DB/Alembic/frontend/NTM/Duty behavior changed, and no anchors
were persisted. The recommended next bounded task is an additive TN VED code-card
anchor bridge; aliases/history must be designed before durable cross-snapshot links.

## Report format

1. changed files grouped by implementation/tests/docs;
2. exact stable-id and snapshot algorithms;
3. before/after behavior matrix;
4. commands and test counts;
5. risks/limitations and migration boundary;
6. recommended next task: additive TN VED code-card anchor bridge.
