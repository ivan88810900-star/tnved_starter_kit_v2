# TASK-MVP-FRONTEND-ACCEPTANCE-002 — Product evidence journey

## Status

Completed — 2026-07-31

## Goal

Protect the integrated product-card journey for a non-specialist: inspect an
explainable payment quote, confirm required documents, run a risk check and hand
the selected real TN VED code to the grounded assistant.

## Context

The product card assembled these modules, but it had no automated integration
gate. It could also render a green “nothing required” state before the preview or
normative evidence had loaded, and it displayed a fallback VAT rate as if it were
confirmed. In customs work, unavailable evidence must never look like a verified
clean result.

## Scope

- Exercise the real `ProductDetails`, summary, Smart Payments, normative
  requirements, risk and assistant bridge composition.
- Load preview and normative evidence eagerly for real code `8517130000`.
- Keep VAT, permit and special-measure states neutral while loading and explicit
  when the source is unavailable.
- Expose the product-card sections as an accessible tab set.
- Add a direct “Спросить помощника” action with a grounded code/name prompt.
- Cover both verified evidence and unavailable-source scenarios.

## Out of scope

- A claim of visual or live-network browser acceptance.
- External LLM invocation or validation of provider-generated wording.
- Changes to payment, normative or risk API contracts.
- Canonical feature-flag rollout, embedding ingestion or database writes.

## Acceptance

- `npm test -- --reporter=verbose`: 4 tests passed across 2 files.
- `npm run typecheck`: passed.
- `npm run build`: passed.
- The integrated card test verifies payments → documents → risk → assistant
  prefill using the real frontend components and mocked API boundaries.
- Failure and partial-evidence tests verify that unavailable preview/normative
  evidence never produces a confirmed-green “nothing required” state or an
  invented VAT rate, while a confirmed requirement remains visible if the other
  source fails.
- `CANONICAL_TREE_ENABLED` and `CANONICAL_TREE_SHADOW` remain unchanged/default
  OFF.

## Safety

- No database access or writes.
- No external AI request or provider spend.
- No merge or feature-flag enablement.
