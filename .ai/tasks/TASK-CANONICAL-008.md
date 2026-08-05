# TASK-CANONICAL-008 — Snapshot-bound Guided semantic overlay

## Status

Completed — 2026-08-05

## Goal

Keep one Guided TN VED response inside one accepted Canonical model boundary: the
semantic overlay must use the official source records captured by the same
`TreeParseResult` that produced the loaded `CanonicalModel`.

## Context / root cause

The Canonical provider correctly published a build-once model and its `snapshot_id`,
but Guided navigation crossed that boundary after loading the model. It called
`SemanticNavigationBuilder.build_heading(db, ...)`, which queried `Commodity` again
through the request session. A database commit between the provider build and the
Guided request could therefore combine:

- Canonical structure and anchors from model snapshot A; and
- semantic titles and grouping inputs from database state B.

The successful response still reported snapshot A. This made the response
internally inconsistent even though both individual reads were valid. The defect
was not in the semantic extractor: it was the second database read after the
atomic model had already been selected.

## In scope

- Add a minimal frozen source-record projection containing `code`, official
  `description`, `import_duty`, Canonical-derived `is_leaf` and the nearest
  distinct real-code `parent_code`.
- Copy and index that projection inside `CanonicalModel` by four-digit heading,
  using immutable tuples behind a `MappingProxyType` view.
- Populate the projection from `TreeParseResult.commodities` in `TreeBuilder.build_model`.
- Keep `tree_engine` independent of `semantic_navigation`; map between their small
  record DTOs only in the Guided orchestration service.
- Add a pure `SemanticNavigationBuilder.build_heading_from_records(...)` entrypoint.
- Make runtime Guided navigation use only records owned by the loaded model.
- Return a safe `DEGRADED` response when the selected model has no retained source
  records for the requested heading.
- Add a regression that builds a model, mutates the database, and proves that Guided
  still uses the old model's records and snapshot.
- Freeze declarability and containment evidence at materialization time so later
  mutation of shared `TreeNode.metadata` cannot change a response under the same
  model snapshot.

## Out of scope

- Changes to the Canonical `snapshot_id` formula or `stable_id` semantics.
- Deep immutability of `TreeNode.children`, node metadata or other Canonical objects.
- PostgreSQL transaction-isolation or source-revision changes.
- Database schema, Alembic migrations or persisted source-record tables.
- API success-payload changes.
- Canonical feature-flag activation, merge or deploy.
- LLM, embeddings, semantic-vector ingestion or extractor-policy changes.
- Nomenclature aliases/history decisions.

## Contracts and invariants

- One `TreeBuilder.build_model(parse_result)` call retains records from that exact
  `parse_result`; later database state cannot alter the model projection.
- Source text and duty are copied from the Parser input. `is_leaf` and
  `parent_code` are derived once from the accepted Canonical output, so the
  projection binds both semantic content and structural role to one model build.
- `CanonicalModel.source_records_by_heading` is a read-only mapping, each value
  is a tuple, and each `CanonicalSourceRecord` is frozen.
- The projection is intentionally independent of the mutable `TreeParseResult` lists:
  values are copied while the model is materialized.
- `SemanticNavigationBuilder.build_heading_from_records(...)` performs no database
  access and deterministically filters and orders the supplied records.
- The legacy `build_heading(db, heading)` entrypoint remains available for
  offline and isolated semantic tooling, but delegates its loaded records to the
  pure entrypoint.
- `GuidedTnvedNavigationService.build(db, heading)` retains its stable signature
  but does not read `Commodity`; the loaded `CanonicalModel` is its only runtime
  data source for semantic descriptions, declarability and code containment.
- A model created manually without source records fails closed with
  `status=DEGRADED` and `reason=canonical_source_records_unavailable`.
- Existing successful Guided JSON fields, Canonical anchors and reported model
  snapshot remain unchanged.
- Canonical serving flags remain default OFF.

## Regression scenario

The self-contained SQLite regression performs the full boundary sequence:

1. Parse commodities and build a real `CanonicalModel`.
2. Record the model `snapshot_id` and retained description for code `0302110000`.
3. Commit a database update replacing that description with
   `MUTATED AFTER SNAPSHOT`.
4. Run the real Guided service and real semantic builder with the old model.
5. Verify the database contains the mutation while the Guided response remains `OK`,
   reports the original model snapshot, and returns the original title `Форель`.
6. Mutate `is_leaf` on the shared Canonical nodes and verify the frozen source DTOs
   and Guided leaf/branch roles remain unchanged.

## QA report

- Final focused Canonical/Guided/semantic/Parser selection: **48 passed**.
- Independent broad Canonical/semantic/API regression on an isolated full-schema
  database copy: **137 passed**.
- Compact Gate-2 direct read smoke: 17,774 parsed records and 1,228 retained headings;
  Guided headings `0302`, `0303`, `5208` and `8517` all returned `OK` from the same
  model snapshot.
- Whole-catalog Guided census on that snapshot: **1,228 / 1,228** headings,
  **16,708 / 16,708** source-code nodes and **13,254 / 13,254** declarable leaves,
  with zero leaf-role, childless-nonleaf or Canonical-parent mismatch.
- `compileall` and `git diff --check` passed.
- The compact Gate-2 database was read only. The mutation regression used an isolated
  in-memory database.

The compact Gate-2 schema intentionally contains only the audit columns and is not
an Alembic/runtime fixture. Broad data-backed tests therefore ran on a separate
full-schema copy; no migration or production database was changed to accommodate
the test harness.

## Residual risks and follow-ups

- The `snapshot_id` formula intentionally remains a hash of Canonical output. Two
  builds can therefore share a `snapshot_id` when only raw semantic punctuation
  or formatting changes and the normalized Canonical output stays identical,
  even though their retained semantic records differ. Each individual model
  remains internally atomic; versioning raw semantic inputs is a separate
  contract decision.
- Canonical nodes and metadata are not deeply immutable. Hardening shared model
  object graphs remains a separate corrective task before broader mutable
  consumers are added.
- PostgreSQL multi-query snapshot isolation and revision-token portability
  remain a separate database-boundary task.
- Retaining the projection adds one small in-memory copy of the active commodity
  inputs (17,774 records in the supplied Gate-2 data).
- Direct `CanonicalModel.from_roots(...)` callers that do not provide Parser records
  cannot serve Guided navigation and deliberately receive the safe fallback.

## Safety

No production database, schema, migration, public success contract, feature-flag
value, LLM setting or external service changed. Delivery is limited to the existing
feature branch; no merge or deployment is part of this task.
