# Current Project Focus

## Status

Active

## Last updated

2026-07-14

## Strategic direction

The current active workstream is the **CustomsClear MVP application**: end-to-end product slices for TN VED usage, normative requirements, payments, sanctions/risk, and an AI assistant grounded in internal modules.

Official SGR and NTM v2 normative datasets remain important **data contours**, but the top priority is shipping user-facing MVP blocks — starting with the normative requirements block.

The normative requirements foundation is complete enough to advance to the TN VED
search/code-card slice. Per DM-0003, that slice is also the first planned consumer of
the Canonical anchor contract. This does not authorize Canonical runtime flag rollout.

## What has already been completed

- NTM v2 storage model and applicability semantics (`definite` / `possible` / `needs_clarification`)
- Safe enforcement policy: only `definite` in broker; official SGR advisory-only by default
- Advisory requirements UI/API foundation
- Official SGR contour: importer, diagnostics, seed dataset, validator
- Normative requirements block MVP (backend aggregation + frontend block on NonTariff/compliance)

## Current top priority

**CustomsClear MVP application workstream** — deliver integrated product slices in this order:

1. ~~Product readiness audit~~ (ongoing reference)
2. ~~Normative block foundation~~ — required / missing / advisory documents, source labels, applicability, evidence
3. **TN VED + preliminary decisions** — first freeze Canonical anchor identity/snapshot,
   then deliver search, code card, related decisions and evidence
4. Smart payments — duty/VAT/excise/fees with explanation
5. Sanctions/risk checks — lists, matches, severity
6. AI assistant — answers grounded in internal modules, cites sources

Parallel (not blocking MVP UI): continue curating `official_sgr_rules.seed.json` and validation — **without** enabling official SGR broker enforcement until a separate approved workstream.

## Next recommended implementation tasks

Current next tasks:

- ADR-0003 / TASK-CANONICAL-005: freeze `stable_id` + `snapshot_id` lifecycle
- TN VED search + code card with related preliminary decisions and evidence, using the
  additive Canonical anchor DTO
- Smart payment explanation block (reuse calculator/compliance surfaces)
- Sanctions/risk check slice
- Assistant grounding on normative + payments modules

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
