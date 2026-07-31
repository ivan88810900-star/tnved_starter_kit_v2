# Current Project Focus

## Status

Active

## Last updated

2026-07-31

## Strategic direction

The current active workstream is the **CustomsClear MVP application**: end-to-end product slices for TN VED usage, normative requirements, payments, sanctions/risk, and an AI assistant grounded in internal modules.

Official SGR and NTM v2 normative datasets remain important **data contours**, but the top priority is shipping user-facing MVP blocks — starting with the normative requirements block.

The normative requirements, TN VED search/code-card, explainable Smart Payments,
evidence-first sanctions/risk and grounded assistant slices are complete. Full-data
end-to-end product acceptance is also complete; the current focus is post-acceptance
product hardening, intelligent TN VED navigation and interactive UI verification.
This does not authorize Canonical runtime flag rollout or automatic semantic-vector
ingestion.

## What has already been completed

- NTM v2 storage model and applicability semantics (`definite` / `possible` / `needs_clarification`)
- Safe enforcement policy: only `definite` in broker; official SGR advisory-only by default
- Advisory requirements UI/API foundation
- Official SGR contour: importer, diagnostics, seed dataset, validator
- Normative requirements block MVP (backend aggregation + frontend block on NonTariff/compliance)
- Canonical anchor identity plus additive TN VED search/code-card bridge
- Additive guided TN VED v1: semantic choices from official descriptions are bound
  to one Canonical snapshot, fail closed on incomplete code coverage and lead only
  to real declarable codes; the main `/children` flags remain OFF
- Product-facing hybrid TN VED search: code/name/domain ranking, safe synonym
  boundaries, conservative typo recovery and explainable match reasons
- Product-description entry into Guided TN VED: text results are grouped into
  ranked Canonical 4-digit heading candidates, curated semantic evidence outranks
  incidental full-text matches, and every candidate opens the existing
  integrity-checked questions; numeric code lookup remains unchanged
- Frontend acceptance foundation: the real Dictionary/search/Guided composition is
  covered for `смартфон` → `8517` → semantic question → real `8517130000` →
  product card, with accessible dialogs, initial focus and background scroll lock
- Explainable Smart Payments in the TN VED card: bases, statuses, sources, assumptions,
  uncertainty and optional Canonical grounding anchor
- Evidence-first sanctions/risk checks in the TN VED card: explicit scope, conservative
  coverage, matched entity/prefix/country, match method and registered source links
- Grounded declarant assistant: deterministic no-key answers over TN VED, calculator,
  definite/advisory requirements and risk coverage; optional validated LLM wording,
  citations, limitations and follow-up actions
- Authenticated **strict read-only** MVP acceptance harness: SQLite opens with
  `mode=ro` plus `PRAGMA query_only`; startup migrations, job recovery, schedulers
  and exchange refresh are skipped. Search/code card, payments, normative
  requirements, evidence-first risk and grounded assistant pass 4/4 on the sandbox
  dataset with all Canonical flags OFF and external LLM keys disabled. The harness
  emits a compact aggregate-only JSON report and can reject undersized datasets with
  `--require-full-data`.
- Full-data gate passed on the user's 6.78 GB `customs.db`: 21 sections, 96 chapters,
  17,809 commodities and 13,322 rates. Authentication and all four MVP scenarios
  passed; the main database file remained unchanged; Canonical flags and external LLM
  remained OFF. Evidence: `evidence/mvp-acceptance-20260721.json`.

## Current top priority

**CustomsClear MVP application workstream** — deliver integrated product slices in this order:

1. ~~Product readiness audit~~ (ongoing reference)
2. ~~Normative block foundation~~ — required / missing / advisory documents, source labels, applicability, evidence
3. ~~TN VED + preliminary decisions~~ — Canonical anchor identity/snapshot, search,
   code card, related decisions and evidence
4. ~~Smart payments~~ — duty/VAT/excise/fees with explanation and conservative uncertainty
5. ~~Sanctions/risk checks~~ — lists, matches, severity and evidence
6. ~~AI assistant~~ — answers grounded in internal modules, cites sources
7. **Intelligent TN VED structure** — Canonical-backed semantic routes and
   understandable product questions without virtual/fake customs codes

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
  SQLite-enforced read-only, unchanged database file, no external LLM, Canonical
  flags OFF)
- ✅ Full-data end-to-end acceptance on the user's current DB (4/4, full-data
  thresholds passed, strict read-only confirmed). Evidence:
  `evidence/mvp-acceptance-20260721.json`
- ✅ Guided TN VED v1 backend + frontend: a heading exposes a separate smart route;
  semantic group IDs are deterministic, all real codes are bound to the current
  Canonical snapshot, and any integrity failure returns a safe ordinary-tree fallback
- ✅ TASK-SEMANTIC-003 controlled subgroup nesting passed the full-data read-only
  gate:
  explicit dash-depth or strict parent-title hints only, bounded unsplit spans,
  fail-flat diagnostics, validator checks and a nested Guided UI question. The
  aggregate-only gate verifies `0302`, `0303`, `5208` and `8517`: 328/328
  codes reachable, 100% Canonical coverage and zero fake codes.
- ✅ TASK-SEMANTIC-004 product-description entry into Guided TN VED:
  deterministic hybrid candidates are grouped and ranked by Canonical heading,
  then the existing route asks only discriminating questions inside the selected
  heading. Compact Gate-2 schema compatibility and read-only search fallback are
  covered.
- ✅ First automated frontend acceptance segment:
  search → Canonical Guided candidate → real code → product card. This is a
  DOM-level gate because the available cloud browser cannot reach the local app;
  it does not replace visual/live-browser QA.
- Expand the acceptance journey from the product card through payments,
  requirements/risk and the grounded assistant, then perform visual/live-browser
  verification when a reachable application URL is available, without broad UI
  redesign
- Separate readiness decision for semantic embeddings (vectors/API cost/provider), without
  weakening the deterministic hybrid-search fallback
- ✅ Optional-AI contract verification (no external request): citation grounding,
  unknown-citation rejection and deterministic fallback pass. The legacy
  `tnved_entries` vector contour remains default OFF for search and ingestion, reports
  aggregate readiness, ranks in
  bounded memory, and has a secret-safe optional LLM contract/live verifier. The
  product index decision is documented in `DECISION_MEMO_SEMANTIC_SEARCH.md`; no
  automatic ingestion or provider spend is authorized.

Full-data gate (run from `customs-clear/backend`):

```bash
python3 scripts/run_e2e_scenarios.py \
  --require-full-data \
  --report "mvp-acceptance-$(date +%Y%m%d-%H%M%S).json"
```

The report contains only aggregate counts and scenario metrics; it does not contain
passwords, absolute database paths, product descriptions, or assistant answer text.

Guided TN VED full-data gate (also aggregate-only and strict read-only):

```bash
python3 scripts/diagnose_guided_tnved_navigation.py \
  --require-complete \
  --output "guided-tnved-$(date +%Y%m%d-%H%M%S).json"
```

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
- Virtual TN VED levels or synthetic/fake customs codes for semantic groups
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
