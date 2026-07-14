# ADR-0003: Canonical anchor identity and snapshot lifecycle

> **Status:** Accepted — Ivan, 2026-07-14
> **Date:** 2026-07-14
> **Owner:** Ivan
> **Implements:** DM-0003 Option C
> **Predecessors:** ADR-0001, ADR-0002, TASK-CANONICAL-004

## 1. Context

The Canonical tree already has deterministic `stable_id` values and a model-level
`snapshot_id`, but only the former is suitable for early in-memory navigation:

- current `stable_id` is `node-<sha1(path)[:24]>`, independent of snapshot content;
- current `snapshot_id` hashes only `db_codes` and misses names, duties, notes, and
  leaf-relevant `hs_rates`;
- the runtime provider has a separate exact source revision for cache invalidation;
- no persistent Search/RAG/AI/overlay consumer stores Canonical anchors yet.

The TN VED search/code-card slice will be the first additive anchor consumer. The
identity contract must be frozen before references escape the model; otherwise a later
formula change requires migration of indexes, RAG chunks, AI journals, and graph edges.

## 2. Decision drivers

1. A real TN VED node keeps its identity across content-only source updates.
2. A Canonical output change always changes `snapshot_id`.
3. Identical Canonical output is reproducible across database engines, row order, and
   process restarts.
4. Synthetic/codeless identities are deterministic without random UUIDs.
5. Consumers can detect stale annotations by carrying the source `snapshot_id`.
6. Cache invalidation and model identity are related but not conflated:
   source revision answers “must we rebuild?”, snapshot answers “what did we build?”.
7. No API, schema, NTM/Duty, or serving-flag change is needed to freeze the contract.

## 3. Decision

### 3.1 `stable_id` — snapshot-independent anchor identity

Freeze the current path-based identity as **stable-id-v1**:

```text
segment = [node_type, local_key]
path    = parent_path_segments + [segment]
stable_id = "node-" + sha1("stable-id-v1\n" + canonical_json(path))[0:24]
```

All hash inputs are UTF-8. Text normalization is exactly Unicode NFC followed by
outer-whitespace trim; internal whitespace and case are preserved. No locale-dependent
normalization is allowed. `canonical_json(path)` is compact JSON; structured segments
avoid delimiter ambiguity when a codeless title contains `/`, `:`, or similar text.

`local_key` rules:

- coded node: normalized `display_code`, falling back to normalized `code`;
- codeless node: `grp:` + normalized title;
- path includes node type and all canonical ancestors;
- no `snapshot_id`, database row ID, timestamp, process state, or random input.

Consequences:

- content-only changes preserve `stable_id` for coded nodes;
- a hierarchy/type/display-code change changes identity;
- changing a codeless group's title changes its identity because it has no stronger
  intrinsic key;
- future supersession/history is expressed through aliases (`previous_stable_ids`,
  `superseded_by`) rather than silently reusing identity for a different structure.

The version prefix is part of the hash input, not the public ID shape. Existing IDs
will change once when v1 is formally introduced; this is safe because no persistent
consumer exists yet. After acceptance, changing the formula requires a new ADR and an
explicit alias/migration plan.

### 3.2 `snapshot_id` — hash of the produced Canonical model

Replace the `db_codes` skeleton with **canonical-snapshot-v2**, computed from a canonical
serialization of the built model, excluding volatile/reference fields:

```text
snapshot_id = "snap-v2-" + sha256(canonical_payload)[0:32]
```

`canonical_payload` is UTF-8 JSON with sorted object keys, compact separators, explicit
boolean values, and arrays kept in deterministic Canonical child order. The hash input
is prefixed with `canonical-snapshot-v2\n`.

The payload recursively includes, in deterministic child order:

- `node_type`, normalized `code`, `display_code`, `level`;
- title/name;
- structural flags: `is_leaf`, `is_codeless`, `is_group`, `is_synthetic`;
- Canonical content: `import_duty`, `notes`;
- child structure/order.

The payload excludes:

- `id`, `stable_id`, `snapshot_id`, object addresses, database PKs;
- runtime/cache counters and timestamps;
- overlay values that are deliberately request-time (`duty_rate`, VAT, measures,
  permits, AI/RAG annotations).

Because leaf-relevant `hs_rates` affects the produced flags/structure, it is reflected
in the snapshot output without embedding rate values that belong to overlays.

### 3.3 Build order

```text
Parser → Recovery → Builder roots
       → assign stable-id-v1
       → canonical snapshot serialization/hash
       → stamp snapshot_id on model/nodes
       → Validator gate → freeze
```

The provider's exact source revision remains the rebuild trigger. A successful stable
build publishes the output snapshot. If source revision changes during build, the
provider discards the model and retries exactly as in TASK-CANONICAL-004.

### 3.4 Anchor contract for consumers

The additive anchor DTO is:

```json
{
  "stable_id": "node-…",
  "snapshot_id": "snap-v2-…",
  "code": "8517…",
  "node_type": "commodity"
}
```

- `stable_id` is the identity/reference key.
- `snapshot_id` is the version guard for derived data.
- `code` is a human/debug/re-resolution key, not the primary identity.
- persistent derived data must retain the snapshot it was computed from and be rebuilt,
  revalidated, or marked stale when the current snapshot differs.
- TASK-CANONICAL-005 defines the DTO and tests only; it does not persist anchors.

## 4. Alternatives considered

### A. Include `snapshot_id` in every `stable_id`

Rejected: every content update would invalidate Search/RAG/AI/graph references even when
the real TN VED node identity is unchanged.

### B. Use only normalized TN VED code

Rejected: codeless/synthetic nodes exist, and code collisions occur between wrappers and
their real/synthetic leaf. Type and hierarchy are required discriminators.

### C. Use database primary keys

Rejected: DB PKs are storage/ingestion identifiers, not reproducible Canonical identity;
they are not portable across exports, environments, or PostgreSQL migration.

### D. Reuse provider source revision as `snapshot_id`

Rejected: source revision may change for an input update that produces identical
Canonical output. It is a rebuild key, not the identity of the built artifact.

## 5. Acceptance criteria

- [x] Ivan accepts stable-id-v1 and canonical-snapshot-v2.
- [x] Two identical builds produce identical IDs and snapshot on SQLite/PostgreSQL-safe
      canonical inputs.
- [x] Row-order changes do not affect either value.
- [x] Content-only coded-node changes preserve `stable_id` and change `snapshot_id`.
- [x] Structural/type/display-code changes change the affected `stable_id` and snapshot.
- [x] Leaf-marker changes change the snapshot when they change Canonical output.
- [x] Request-time overlay-only changes do not change the snapshot.
- [x] Existing legacy serializer/API contract remains unchanged.
- [x] No DB/Alembic/frontend/NTM/Duty/feature-flag change.

## 6. Rollback

Before persistent consumers exist, rollback is code-only: revert stable-id-v1/snapshot-v2
and rebuild the in-memory model. After anchors are persisted, formula rollback requires
the same explicit alias/migration plan as any future formula change.

## 7. Decision record

Ivan accepted all four contract points on 2026-07-14: snapshot-independent path
identity, codeless-title fallback, output-model snapshot hash, and the additive
`(stable_id, snapshot_id, code, node_type)` anchor DTO. Any future formula change now
requires a new ADR plus an explicit alias/migration plan.
