# TASK-CANONICAL-007 — Single-snapshot Parser inputs and pure Builder

## Status

Completed — 2026-08-01

## Goal

Make `TreeParser` the only database-reading stage of the Canonical build pipeline so
every Builder input comes from one database session and `TreeBuilder` remains a pure,
deterministic transformation.

## Context / RCA

ADR-0001 defines `Parser → Recovery → Builder → Validator`, with Parser as the sole
database boundary. In practice, `TreeBuilder._compute_leaf_flags(...)` opened a second
session to query `hs_rates`. A concurrent ingestion could therefore make commodities
and leaf evidence come from different database snapshots, while direct Builder use had
an undocumented database dependency. A reproduction also confirmed that Python's
SQLite legacy transaction mode can report an active SQLAlchemy Session transaction
without issuing `BEGIN` for `SELECT`: two reads in one Session observed `before` and
then a concurrent committed `after` value.

## Scope

- Collect exact/inherited L4/L6 leaf evidence in `TreeParser` using its existing
  session.
- Start a real SQLite read transaction before the first Parser query so all Parser
  inputs share one snapshot; retain native transaction behavior elsewhere.
- Add `leaf_flags` to `TreeParseResult` as an explicit Builder input.
- Remove database/session-factory knowledge from `TreeBuilder`.
- Preserve compact Gate-2 compatibility when `hs_rates.hs_prefix` is absent.
- Keep provider revision inputs and prefix-audit behavior aligned.
- Add self-contained full-schema, compact-schema, pure-Builder and one-session tests.

## Out of scope

- API or JSON-contract changes.
- Database schema or migration changes.
- Canonical flag rollout, merge or deploy.
- Semantic-vector ingestion, external embeddings or LLM calls.
- Alias/history model decisions.

## Acceptance

- Builder imports no SQLAlchemy, `SessionLocal` or `HsRate` and opens no session.
- Provider build uses exactly one session for all Parser inputs.
- A concurrent SQLite commit after the commodity read is excluded from the active
  Parser snapshot.
- Full-schema and compact Gate-2 leaf semantics are identical to the legacy predicate.
- Full Canonical structure/content parity remains green.
- Full Gate-2 remains 18,049/18,049 with zero mismatch/unresolved.
- Canonical flags remain default OFF.

## QA report

- Self-contained Parser/Builder/provider/snapshot, audit and exporter tests:
  **10 passed**.
- Canonical model suite on a temporary full-schema database populated from the
  supplied Gate-2 export, plus Tree Engine and audit regressions: **53 passed**.
- Read-only full Gate-2: 17,774 active commodities; 18,049 checked/matched;
  0 mismatches; 0 unresolved; `gate2_ok=true`.
- Same-container baseline comparison showed no material Gate-2 runtime regression
  (15.09 s before, 15.38 s after in matched runs).
- `compileall`, `git diff --check` and scope inspection passed.
- The supplied database/archive was read only; all writable database work used
  temporary copies under `/tmp`.

## Safety

No production API, frontend, database schema, migration, feature-flag value or LLM
configuration changed. Legacy `build_tree()` remains untouched and remains the oracle.

## Architecture review

**Verdict: APPROVE.** The change closes the documented ADR-0001 boundary debt with a
bounded diff, preserves legacy parity and fallback behavior, introduces no secret or
data write, and keeps both Canonical serving flags default OFF. Canonical
aliases/history remain a separate decision because they change persistent identity
semantics and require an explicit Decision Memo.
