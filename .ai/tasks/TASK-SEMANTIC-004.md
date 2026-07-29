# TASK-SEMANTIC-004 — Product description entry into Guided TN VED

## Status

Completed — 2026-07-29

## Goal

Let a non-specialist start with a product description, see a small ranked set of
real Canonical four-digit headings, and continue through the existing
integrity-checked Guided questions. Do not classify the product automatically and
do not create virtual customs codes.

## Scope

- Add an additive `guided_routes` field to the existing TN VED search response.
- Group lexical/hybrid results by Canonical four-digit heading.
- Rank direct-name and curated semantic evidence above incidental full-text hits.
- Preserve numeric/code-only search behaviour.
- Render the candidates above ordinary search results and label them as hypotheses,
  not a final classification decision.
- Keep `CANONICAL_TREE_ENABLED` and `CANONICAL_TREE_SHADOW` default OFF.
- Do not call an external LLM or ingest embeddings.

## Acceptance

- Targeted backend regression suite: 30 passed.
- Frontend TypeScript check and production build: passed.
- Optional-AI contract: passed without external requests; deterministic fallback
  and citation validation remain active.
- Read-only full Gate-2 API check:
  - `смартфон` → `8517` first;
  - `портативный компьютер` → `8471` first;
  - `8517130000` → no generated Guided hypothesis.
- Compact `hs_rates(id, hs_code)` Gate-2 schema builds the Canonical model without
  requiring production-only rate columns.

## Safety

- Additive API only; old frontend/backend deployment order is tolerated.
- Canonical failure is a soft miss and ordinary search remains available.
- No database writes, feature-flag rollout, merge, force-push or provider spend.
