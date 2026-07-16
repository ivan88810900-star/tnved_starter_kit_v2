# Current Project Focus

## Status

Active

## Last updated

2026-07-16

## Strategic direction

The current active workstream is the **CustomsClear MVP application**: end-to-end product slices for TN VED usage, normative requirements, payments, sanctions/risk, and an AI assistant grounded in internal modules.

Official SGR and NTM v2 normative datasets remain important **data contours**, but the top priority is shipping user-facing MVP blocks — starting with the normative requirements block.

The normative requirements, TN VED search/code-card, explainable Smart Payments,
evidence-first sanctions/risk and grounded assistant slices are complete. The current
focus is full-data end-to-end product acceptance and hardening; this does not authorize
Canonical runtime flag rollout or automatic semantic-vector ingestion.

## What has already been completed

- NTM v2 storage model and applicability semantics (`definite` / `possible` / `needs_clarification`)
- Safe enforcement policy: only `definite` in broker; official SGR advisory-only by default
- Advisory requirements UI/API foundation
- Official SGR contour: importer, diagnostics, seed dataset, validator
- Normative requirements block MVP (backend aggregation + frontend block on NonTariff/compliance)
- Canonical anchor identity plus additive TN VED search/code-card bridge
- Product-facing hybrid TN VED search: code/name/domain ranking, safe synonym
  boundaries, conservative typo recovery and explainable match reasons
- Explainable Smart Payments in the TN VED card: bases, statuses, sources, assumptions,
  uncertainty and optional Canonical grounding anchor
- Evidence-first sanctions/risk checks in the TN VED card: explicit scope, conservative
  coverage, matched entity/prefix/country, match method and registered source links
- Grounded declarant assistant: deterministic no-key answers over TN VED, calculator,
  definite/advisory requirements and risk coverage; optional validated LLM wording,
  citations, limitations and follow-up actions
- Authenticated read-only MVP acceptance harness: search/code card, payments,
  normative requirements, evidence-first risk and grounded assistant pass 4/4 on
  the sandbox dataset with all Canonical flags OFF. The obsolete scenario that
  treated US origin as an automatic embargo was removed.

## Current top priority

**CustomsClear MVP application workstream** — deliver integrated product slices in this order:

1. ~~Product readiness audit~~ (ongoing reference)
2. ~~Normative block foundation~~ — required / missing / advisory documents, source labels, applicability, evidence
3. ~~TN VED + preliminary decisions~~ — Canonical anchor identity/snapshot, search,
   code card, related decisions and evidence
4. ~~Smart payments~~ — duty/VAT/excise/fees with explanation and conservative uncertainty
5. ~~Sanctions/risk checks~~ — lists, matches, severity and evidence
6. ~~AI assistant~~ — answers grounded in internal modules, cites sources

Parallel (not blocking MVP UI): continue curating `official_sgr_rules.seed.json` and validation — **without** enabling official SGR broker enforcement until a separate approved workstream.

## Next recommended implementation tasks

Current next tasks:

- ✅ ADR-0003 / TASK-CANONICAL-005: `stable_id` + `snapshot_id` lifecycle frozen
- ✅ TASK-CANONICAL-006: TN VED search + code-card consume the additive Canonical
  anchor DTO with soft fallback; preliminary decisions/evidence remain visible
- ✅ TASK-MVP-SEARCH-QUALITY-001: hybrid search ranking, typo recovery and
  explainable main-UI results
- ✅ TASK-MVP-PAYMENTS-001: Smart payment explanation block in the TN VED card
- ✅ TASK-MVP-RISK-001: sanctions/risk check slice with source evidence and
  conservative match semantics
- ✅ TASK-MVP-ASSISTANT-001: deterministic grounded assistant + optional guarded LLM
  wording over normative, payments and risk modules
- ✅ Local end-to-end acceptance of the completed MVP slices (4/4, authenticated,
  no external LLM, no writes, Canonical flags OFF)
- Full-data end-to-end acceptance on the user's current DB remains pending; use
  `E2E_SEARCH_QUERY` / `E2E_PAYMENT_HS_CODE` only to select representative data,
  without changing product semantics
- Separate readiness decision for semantic embeddings (vectors/API cost/provider), without
  weakening the deterministic hybrid-search fallback

Official SGR dataset tasks (when not conflicting with MVP slices):

- Expand `data/official_sgr_rules.seed.json` (ЕЭК №299 and related contours)
- Extend `validate_official_sgr_dataset(...)` and dataset report coverage
- Regression: toys `9503`, adult cosmetics `3304`, child/special SGR cases

## What is not the next priority

- Official SGR **enforcement** in broker / missing-check (separate Decision Memo required)
- Broad legacy SGR heuristics promoted to broker as “official”
- Unrelated refactors or legacy root `backend/` expansion
- Broad UI redesign outside MVP slices
- Canonical `/children` flag rollout without a separate Ivan decision
- NTM/Duty anchor migration in TASK-CANONICAL-005

## When to create a Decision Memo

Create a Decision Memo instead of a Cursor Task if:

- product wording or legal interpretation is ambiguous (e.g. advisory vs blocking UI);
- expanding SGR requires legal/product interpretation not encoded in seed;
- API contract changes break backward compatibility;
- roadmap should switch away from CustomsClear MVP (e.g. to enforcement-only workstream).

## How agents use this file

- **Codex** reads this file **before** proposing the next task; if `Status: Active`, this overrides backlog-style AGENT-01…05 priorities unless an issue explicitly says otherwise.
- **Cursor** implements only tasks aligned with the active focus or an explicit issue scope.
- **Ivan** updates `Last updated` and sections when reprioritizing.
