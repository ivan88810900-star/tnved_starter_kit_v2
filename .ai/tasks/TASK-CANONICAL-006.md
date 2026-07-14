# TASK-CANONICAL-006: TN VED search/code-card anchor bridge

> **Status:** Completed (implementation QA passed)
> **Owner:** Backend + Frontend
> **Created:** 2026-07-14
> **Depends on:** ADR-0003, TASK-CANONICAL-005

## Goal

Make TN VED search results and the professional code-card the first additive consumers
of the accepted Canonical anchor contract, preparing stable grounding for AI/RAG and
later product modules without enabling Canonical tree serving flags.

## Scope

- resolve exact 4/6/8/10-digit search/card codes against one cached Canonical model;
- expose optional `(stable_id, snapshot_id, code, node_type)` metadata additively;
- keep legacy/FTS/DB search and card responses available when Canonical is unavailable;
- update frontend types without showing raw technical identifiers to the user;
- add isolated resolver, batch, fallback, and schema tests.

## Invariants

- no feature-flag activation or merge;
- no DB/Alembic change and no persisted anchor;
- no NTM/Duty enforcement change;
- Canonical failure never turns an otherwise valid search/card request into 500;
- one search batch uses one model snapshot.

## Acceptance criteria

- [x] exact code resolves the accepted ADR-0003 anchor DTO;
- [x] search results and code-card accept optional anchor metadata;
- [x] provider failure is a soft miss;
- [x] existing API fields and UI behavior remain compatible;
- [x] focused backend tests, Ruff, compileall and frontend production build pass;
- [x] flags remain default OFF.

## Completion report (2026-07-14)

- Added one soft-fail resolver for exact Canonical anchors and a batch resolver that
  holds one shared snapshot across all search hits.
- Added optional `canonical_anchor` metadata to `/api/v1/tnved/search` results and the
  professional `/api/v1/tnved/{code}` card response.
- Updated frontend types only; raw technical IDs are intentionally not rendered.
- Ruff and compileall passed; **48 focused backend tests passed**.
- Frontend production build passed. Typecheck has the same four pre-existing errors in
  `PermitDocumentsBlock.tsx` on both parent and task code (`tr_ts_full_name`, `note`),
  so this task introduces zero new TypeScript errors.
- Existing data-suite selection: 5 passed, one pre-existing `test_detail_404` mismatch
  caused by the legacy 10-digit virtual-card fallback, outside this task.
- No DB, migration, NTM/Duty enforcement, serving flag, or visible UI behavior changed.
