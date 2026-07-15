# TASK-MVP-ASSISTANT-001: Grounded declarant assistant

> **Status:** Completed
> **Owner:** Backend + Frontend
> **Created:** 2026-07-15
> **Depends on:** TASK-CANONICAL-006, TASK-MVP-SEARCH-QUALITY-001,
> TASK-MVP-PAYMENTS-001, TASK-MVP-RISK-001

## Goal

Make the declarant assistant useful and auditable with or without an external LLM:
answers must be assembled from the same TN VED, payment, normative and risk contracts
that the product UI uses, disclose missing coverage, and cite their data sources.

## Scope

- build a bounded evidence bundle from TN VED/Canonical, calculator, definite/advisory
  requirements and sanctions/risk coverage;
- render a deterministic server answer when no LLM key is configured;
- allow Anthropic/Gemini only as an optional wording layer over the server draft;
- reject malformed model output and unknown/non-inline citation IDs;
- return typed grounding metadata, citations, limitations and follow-up suggestions;
- show evidence mode, source links and remaining checks in the chat and copilot UI;
- keep the assistant navigation and calculator hand-off available without an LLM key;
- correct the erroneous demo label that represented `8509400000` as an electric kettle;
- extract the product part of conversational search queries before typo recovery.

## Invariants

- no AI-generated rate, amount, requirement, source status or clean-risk conclusion;
- `possible` / `needs_clarification` remain advisory-only;
- incomplete sanctions coverage is never represented as “no risk”;
- candidate search is not represented as final TN VED classification;
- an imported official TN VED revision is never overwritten by corrected seed data;
- no client-side AI key, database migration, feature-flag activation, merge or deploy.

## Acceptance criteria

- [x] assistant works in factual mode when no external LLM is configured;
- [x] chat answers contain inline source IDs and a structured citation list;
- [x] payment amounts come only from the passed calculator snapshot;
- [x] definite documents and advisory requirements are visibly separated;
- [x] risk answers expose incomplete coverage and unchecked scope;
- [x] configured model output is accepted only with valid JSON and known inline citations;
- [x] malformed/unknown-citation model output falls back without exposing raw text;
- [x] copilot and batch copilot return a full deterministic evidence summary without a key;
- [x] typo recovery works inside conversational queries (`код ... для смартфн`);
- [x] auth, live HTTP, backend tests, frontend typecheck and production build pass.

## Completion report (2026-07-15)

- Grounded assistant/route/provider focused matrix: **25 passed**.
- Broader relevant matrix: **106 passed, 7 failed**; the same seven tests fail on the
  untouched parent commit with the same sandbox DB/dependency set (empty data contours,
  old payment-fixture expectations and missing `apscheduler`), so there are **zero new
  regressions** in that matrix.
- Authenticated live HTTP with all LLM keys unset: health ready, chat and copilot all
  returned 200; the final chat smoke-test reported `deterministic/grounded`, eight
  sources and three follow-ups;
  copilot returned a deterministic evidence summary and no raw model output.
- Real-catalogue conversational search on **14,021 rows**: notebook → 8471, electric
  kettle → 8516, and `смартфн` → visible correction to `смартфон` with 851713 first.
- Frontend `npm run typecheck`: passed.
- Frontend production `npm run build`: passed; only the existing SWC deprecation and
  >500 kB bundle warnings remain.
- Changed-file Ruff, Python compile and diff checks: passed.
- No model key was available for a real paid-provider call; the configured-provider
  contract, citation validation and failure fallback are covered with mocked responses.
- No feature flag, migration, merge, deployment or production data mutation was performed.
