# TASK-MVP-FRONTEND-ACCEPTANCE-001 — Search → Guided TN VED → product card

## Status

Completed — 2026-07-31

## Goal

Protect the first integrated non-specialist journey with a reproducible frontend
acceptance test: describe a product, choose a ranked Canonical heading, answer a
Guided TN VED question, and open the card for a real 10-digit code.

## Context

The backend/full-data gates verify the API and Canonical integrity, but the frontend
had no automated test harness. The available cloud browser cannot connect to the
local application address, so this task adds a deterministic DOM-level acceptance
gate without claiming visual or live-network browser coverage.

## Scope

- Add Vitest, jsdom and Testing Library to the frontend.
- Exercise the real `Dictionary`, `TnvedAccordionTree` and
  `GuidedTnvedNavigator` composition.
- Cover `смартфон` → heading `8517` → semantic choice → real code
  `8517130000` → product card.
- Make the search field and both full-screen dialogs accessible by name.
- Move initial focus to the dialog close action and lock background scrolling while
  a dialog is open.

## Out of scope

- Visual regression or a claim of live-browser acceptance.
- Product-card payments, requirements/risk and assistant panels; those are the next
  acceptance expansion.
- Search-ranking or Guided backend changes.
- Canonical feature-flag rollout, embedding ingestion or external LLM calls.

## Acceptance

- `npm test -- --reporter=verbose`: 1 passed.
- `npm run typecheck`: passed.
- `npm run build`: passed.
- The test asserts that the final selection is a real 10-digit code and that the
  Guided dialog is replaced by the product-card dialog.
- `CANONICAL_TREE_ENABLED` and `CANONICAL_TREE_SHADOW` remain unchanged/default OFF.

## Safety

- No database access or writes.
- No production API contract change.
- No external AI request or provider spend.
- No merge or feature-flag enablement.
