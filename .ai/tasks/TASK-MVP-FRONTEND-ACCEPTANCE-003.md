# TASK-MVP-FRONTEND-ACCEPTANCE-003 — Product card → grounded assistant

## Status

Completed — 2026-07-31

## Goal

Protect the real frontend handoff from a selected TN VED product card to the
declarant assistant, including a cited deterministic response and the validated
optional-LLM presentation contract.

## Context

The product-card test verified that a question was queued, but application routing
still lived inside the browser bootstrap file and could not be exercised in
isolation. The assistant accepted a prefilled question, but did not focus its input.
There was also no frontend acceptance proving how deterministic and guarded
LLM-grounded responses are distinguished for the user.

## Scope

- Extract the application/router composition from `main.tsx` into testable
  `App.tsx` without changing route contracts.
- Exercise the real assistant navigation bridge and verify navigation from
  `/tnved` to `/assistant` with the exact product-card question.
- Focus the chat input when a prefill job is consumed.
- Exercise the real `Assistant` and `DeclarantChatThread` against mocked API
  boundaries.
- Verify deterministic server-fact labels, limitations, citations and follow-up
  suggestions.
- Verify the guarded `llm_grounded` presentation label without making an external
  provider request.

## Out of scope

- A real Anthropic/Gemini/OpenAI provider call or provider spend.
- Visual/live-network browser acceptance.
- Assistant backend or prompt-contract changes.
- Canonical feature-flag rollout, embedding ingestion or database writes.

## Acceptance

- `npm test -- --reporter=verbose`: 7 tests passed across 4 files.
- `npm run typecheck`: passed.
- `npm run build`: passed.
- Route acceptance proves the real bridge carries the product question intact to
  `/assistant`.
- Assistant acceptance proves the question is focused, sent to
  `/v1/assistant/chat`, and rendered with its grounding provenance.
- Deterministic and `llm_grounded` modes receive distinct, truthful UI labels.

## Safety

- Backend diff is empty.
- No database access or writes.
- No external AI request, API key use or provider spend.
- No merge or feature-flag enablement.
