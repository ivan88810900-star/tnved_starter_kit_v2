# Current Project Focus

## Status

Active

## Last updated

2026-09-08

## Strategic direction

The current active workstream is the **CustomsClear MVP application**: end-to-end product slices for TN VED usage, normative requirements, payments, sanctions/risk, and an AI assistant grounded in internal modules.

Official SGR and NTM v2 normative datasets remain important **data contours**, but the top priority is shipping user-facing MVP blocks — starting with the normative requirements block.

The normative requirements, TN VED search/code-card, explainable Smart Payments,
evidence-first sanctions/risk and grounded assistant slices are complete. Full-data
end-to-end product-flow acceptance is also complete, but it does not establish the
current legal correctness of every duty rate. The current focus is post-acceptance
product and data-source hardening, intelligent TN VED navigation and interactive UI
verification.
This does not authorize Canonical runtime flag rollout or automatic semantic-vector
ingestion.

## What has already been completed

- NTM v2 storage model and applicability semantics (`definite` / `possible` / `needs_clarification`)
- Safe enforcement policy: only separately authorized `definite` sources may enter
  broker; the official full NTM contour is advisory-only
- Official full NTM advisory rollout accepted by Ivan on 2026-08-15: default ON
  with `NTM_V2_OFFICIAL_FULL_ADVISORY_ENABLED=false` as kill switch, 9 measure
  families and 30 base Decision-30 sections; enforcement is not approved
- Structured NTM applicability (DM-0011): the API/UI accepts optional transaction
  and product facts, bounded source-backed exact rules expose explainable
  `definite`/`excluded` advisory results, and requests without facts retain the
  broad-only contract. The versioned curated broker bridge is implemented for
  shadow audit but remains default OFF; caller-supplied evidence is rejected by
  the broker trust gate even if the flag is enabled, and production activation
  is not approved. Export/transit requests do not reuse import broker/payment
  semantics and expose catch-all transaction risk separately.
- The NTM catalog topology gate independently verifies the tracked 96-PDF corpus:
  exact 21 sections, 96 chapters, 17,809 unique commodities, 0 duplicate/invalid
  catalog rows and 17,774 nonempty descriptions. The earlier tariff-rate portion
  of the full staging claim is withdrawn: the DB-derived `ett:2026-06-18` bundle
  has 13,319 raw rows, 2 invalid rows and 27 duplicate rows across 23 codes,
  including 18 material rate conflicts, and it does not represent current EEC
  amendments or temporary/as-of footnotes. It is now explicitly quarantined and
  cannot produce a positive staging snapshot. Existing aggregate evidence remains
  useful only for catalog/NTM structure; it is not evidence of current duty-rate
  correctness. No production/application DB was mutated.
- Advisory requirements UI/API foundation
- Official SGR contour: importer, diagnostics, seed dataset, validator
- Automatic source lifecycle (DM-0013): 36/36 registry entries have an explicit
  policy; this is policy coverage, not proof that all 36 sources are refreshed
  automatically or legally current. Seven trusted structured sources update daily/weekly through strict,
  table-scoped adapters and atomic full-snapshot replacement where applicable;
  OFAC and EU feeds run validation-only and cannot mutate blocking tables;
  the expanded official monitor currently covers exactly 50 URLs: 15 direct
  PDF/machine-readable artifacts have revision-digest coverage, 27 legal HTML
  pages are explicit revision gaps checked for availability/identity only, and
  eight additional landing URLs are availability-only. HTML gaps are reported
  without masquerading as revision coverage or making the operational workflow
  permanently fail, while the notifier keeps them visible in an issue; covered
  artifact failures remain fail-closed. Of the 15 covered artifacts, six legal
  PDFs require digest-bound review; nine structured artifacts advance technical
  freshness automatically after validation. Five curated layers
  raise a monthly review, four commercial mirrors remain disabled and one AI layer
  remains manual. Revision-covered legal checksum changes stay pending until an explicit referenced
  approval and never change enforcement automatically. FTS/FSA open-data adapters
  now pin official identities, TLS, redirect paths and artifact schemas. The five
  curated monthly sources use a durable evidence-bound review queue whose resolve
  and refresh operations are compare-and-set safe. Scheduler overlap is blocked
  across processes/replicas and every run persists an observable status.
- Source ingestion hardening: bounded identity-encoded streaming, exact NSI
  dictionary pins, original-byte sanctions evidence, strict OOXML fallback
  validation, private streamed FSA downloads and patched `py7zr==1.1.3` with
  allowlisted CSV extraction. CBR rates and digest-bound provenance are atomic,
  first-run/concurrent writers serialize, and stale workers cannot downgrade a
  newer success. This does not enable enforcement or deploy the scheduler.
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
- Integrated product-card acceptance: real frontend components cover explainable
  payments → normative documents → risk check → grounded-assistant prefill, with
  a separate unavailable-evidence path that cannot report a false clean state or
  an unverified VAT rate
- Grounded-assistant frontend acceptance: the real application bridge preserves
  the product question while routing to `/assistant`; the chat focuses the prefill
  and renders deterministic or guarded-LLM answers with truthful provenance,
  citations and limitations
- Frontend production hardening: every existing page is an on-demand route bundle;
  the initial JavaScript set fell from 1,277,432 to 231,325 bytes (`-81.9%`), with
  accessible loading and recoverable route-error states and no URL/API changes
- Canonical pipeline boundary hardening: `TreeParser` is now the sole DB-reading
  stage for commodities, chapter metadata and L4/L6 leaf evidence; `TreeBuilder`
  consumes explicit inputs without opening a second session. An explicit SQLite
  read transaction also keeps those inputs on one snapshot under concurrent commits.
  Full Gate-2 remained 18,049/18,049 with all serving flags OFF.
- Canonical snapshot-bound Guided input: the semantic overlay now uses immutable
  source records captured by the exact `TreeParseResult` that built its
  `CanonicalModel`; it no longer re-reads commodity descriptions from a request
  session after selecting a model snapshot.
- Canonical publication hardening: the shared model now deep-freezes every
  published node, parent link, tuple children and recursive standard metadata
  container. A retained pre-publication list/dict alias cannot mutate the model,
  while `TreeBuilder.build(...)` remains mutable before validator/stamping/
  publication. Identity formulas, API behavior and default-OFF flags are unchanged;
  Gate-2 remains 18,211/18,211 and the census remains 1,228/1,228.
- Terminal L4 correctness: 162 exact-rate `XXXX000000` records without deeper
  descendants are now real declarable leaves under their stable four-digit heading
  wrappers in both legacy and Canonical projections. Gate-2 now independently
  requires these source-backed leaves and passes 18,211/18,211 paths.
- Whole-catalog Guided census: on the supplied Gate-2 snapshot, all 1,263 Canonical
  headings and 16,708 source-backed code nodes pass reachability, binding and nearest
  Canonical-parent integrity. The model contains 13,254 actual declarable leaves;
  leaf roles are checked against Canonical rather than inferred from the absence of
  semantic children. On the current feature branch, semantic questions cover 6,949
  leaves; these are measured product-quality baselines, not a claim that every
  heading is already semantically optimized.
- TASK-SEMANTIC-006 plus DM-0012/TASK-SEMANTIC-009 provide a bounded official
  `2204` slice. Exact retained «прочие» boundaries split the 33-leaf PDO scope into
  18/17 plus 16/16 and the neighboring `220422` step into 27/25 plus 7/7. Source
  drift fails closed to the complete prior route. Whole-catalog correctness remains
  1,263/1,263, golden 7/7 and Gate-2 18,246/18,246; catalog maximum is 29/27 and
  no step above 30 remains. Serving flags remain OFF.
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
  remained OFF. This is product-flow/read-only evidence only; the rate rows require
  the separate official ETT manifest/as-of gate described above. Evidence:
  `evidence/mvp-acceptance-20260721.json`.

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

Parallel (not blocking MVP UI): maintain the official NTM datasets and the DM-0013
automatic source lifecycle. Ivan accepted Decision #188 Option A for a versioned
official ETT manifest, temporal/as-of rate model and reviewed atomic promotion.
TASK-ETT-001 now implements isolated local candidates, schema-v2 validation,
versioned tables and date-specific previews without a cloud purchase. The next
data task is completing a current official capture and PDF continuation/footnote/date
interpretation. TASK-ETT-002 implements the transport, actual-index discovery,
original-byte receipts, reproducible PDF rows and referenced-quote verification;
TASK-ETT-003 now assembles and lexically parses all 13,289 commodity rows in the
96 pinned PDFs, preserving typography, note clauses and source diagnostics. The
old padded heading 0406900000 is not inserted. This is historical evidence; current
index raw bytes are now captured and their specific layout is supported. Complete
current-PDF acquisition and note/amendment interpretation remain unverified. An isolated ops/ett-source-capture push can request read-only
GitHub acquisition without merging application changes. Positive production staging remains closed until
legal review and promotion are implemented.
Keep the curated official bridge OFF before proposing any exact-rule production
enforcement.

## Next recommended implementation tasks

Current next tasks:

- [ETT source-of-truth Decision Memo #188](https://github.com/ivan88810900-star/tnved_starter_kit_v2/issues/188): Option A accepted and [TASK-ETT-001 implemented](ETT_VERSIONED_CANDIDATES.md).
  Local candidate history and temporal previews are tested. Real official
  acquisition and reproducible row verification are implemented in
  [TASK-ETT-002](ETT_SOURCE_EVIDENCE.md). [TASK-ETT-003](ETT_TABLE_INTERPRETATION.md)
  adds full cells, source-proven superscript separation, note clauses and actual
  legal attachment capture, with explicit dispatch/isolated-branch CI acquisition.
  Current-source acquisition and legal footnote/date interpretation,
  durable retention, manifest-bound legal review and production
  promotion remain unfinished. An exact quote match alone does not approve a rate.
  The DB-derived bundle remains quarantined; old direct PDF/OData/index-hash
  paths now return REVIEW_REQUIRED and cannot publish rates or false freshness.

- ✅ ADR-0003 / TASK-CANONICAL-005: `stable_id` + `snapshot_id` lifecycle frozen
- ✅ TASK-CANONICAL-006: TN VED search + code-card consume the additive Canonical
  anchor DTO with soft fallback; preliminary decisions/evidence remain visible
- ✅ TASK-CANONICAL-007: all Canonical Builder inputs are collected by Parser from
  one DB session; Builder is DB-independent and compact Gate-2 parity remains green
- ✅ TASK-CANONICAL-008: Guided semantic inputs are retained inside the selected
  Canonical model snapshot; a later database update cannot mix description state B
  with structure/anchors from snapshot A
- ✅ TASK-CANONICAL-009: exact terminal L4 codes are reachable in both tree
  projections and in Guided navigation; hardened Gate-2 passes 18,211/18,211
- ✅ TASK-CANONICAL-010: published Canonical nodes and recursive metadata are
  physically immutable for standard containers; snapshot content and navigation
  indexes cannot split through a retained node/container reference. Arbitrary custom
  mutable metadata objects remain a documented limitation, with none in production
- ✅ TASK-SEMANTIC-005: strict read-only census covers all 1,228 headings and
  16,708 source-backed code nodes / 13,254 declarable leaves; quality distributions
  and four-digit outlier lists are reported separately from correctness
- ✅ TASK-SEMANTIC-006: exact official `2204` PDO interval is completed and accepted
  via DM-0005 Option A, with implementation + verification on the feature branch.
  It fails closed and covers 33/33 Canonical leaves; `220421` is 18/14 before the
  PDO step, the whole census is 1,228/1,228 and the fifth golden assertion is green.
  Flags remain OFF; this docs-only update performs no merge, rollout or deployment.
- ✅ TASK-SEMANTIC-007 is implemented, verified and accepted through DM-0006
  Option A: an atomic exact five-question product-form chain for
  `0304`, verified against exact source titles, `(anchor, stop]` ordered tuples,
  leaf roles and Canonical-parent topology. Measured results are root 13/8,
  maximum step 13/9 and semantic coverage 92/100 while preserving 117/117 source
  nodes and 100/100 leaves; census is 1,228/1,228, golden 6/6 and Gate-2
  18,211/18,211. Acceptance does not constitute merge, rollout or flag activation.
- ✅ TASK-SEMANTIC-008 is implemented, verified and accepted through DM-0007
  Option A. The exact official `0406` fat/moisture chain reduces the maximum step
  from 27/26 to 16/15 and raises semantic coverage from 10/47 to 21/47 while
  preserving all 54 source nodes and 47 leaves. Census is 1,228/1,228, golden
  7/7 and Gate-2 18,211/18,211. Acceptance does not merge, roll out or activate
  flags.
- ✅ TASK-SEMANTIC-009 is implemented and accepted through DM-0012 Option A.
  Exact retained `2204` «прочие» boundaries preserve 211/211 source codes and
  170/170 leaves, reduce the catalog maximum to 29/27, and pass the current
  1,263/1,263 census plus 18,246/18,246 Gate-2. Missing page-break labels are not
  synthesized; runtime flags remain OFF.
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
- ✅ TASK-NTM-EXACT-001 / DM-0011: additive structured facts contract, bounded
  exact health/device/trade evaluators, explicit exclusions and transaction-level
  export catch-all note are integrated into the normative block. Exact rows remain
  advisory; the two-rule versioned enforcement bridge is default OFF and audited.
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
- ✅ Second automated frontend acceptance segment:
  product card → payments → requirements/risk → grounded-assistant prefill,
  including fail-safe loading/error evidence states and accessible tabs.
- ✅ Third automated frontend acceptance segment:
  product-card question → real application route bridge → assistant input →
  cited grounded response. Deterministic and guarded optional-LLM presentation
  contracts are covered without an external provider call.
- ✅ TASK-MVP-FRONTEND-PERFORMANCE-001 route-level production bundles:
  all existing screens load on demand, the Vite 500 kB warning is eliminated, and
  loading/failure behavior is protected by regression tests.
- Perform visual/live-browser verification when a reachable application URL is
  available, without broad UI redesign
- Improve semantic question coverage and reduce measured high-branching outliers
  in bounded, evidence-backed slices. Do not set arbitrary global usability
  thresholds until a reviewed baseline policy exists; preserve whole-catalog
  integrity and the seven golden hierarchy assertions. The source-backed `2204`
  follow-up is accepted via DM-0012 and leaves a bounded 29/27 residual at `220429`;
  any further split requires new retained source evidence.
- Preserve the DM-0006 Option A boundary for `0304`. Exact official titles change
  codeless guide IDs while real Canonical coded-node IDs remain stable; no guide-ID
  alias/history layer is included. Any source/topology drift must fail closed.
- Preserve the DM-0007 Option A boundary for `0406`. Do not silently select the
  broader repeated-«прочие» route or raise semantic depth; source/topology drift
  must fail closed to the complete route.
- Review proposed DM-0004 before adding Canonical aliases/history or changing
  persistent identity semantics. No schema/runtime implementation is authorized
  until an official transition-source feasibility audit and Ivan decision.
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
  --all-headings \
  --require-complete \
  --output "guided-tnved-$(date +%Y%m%d-%H%M%S).json"
```

Official SGR dataset tasks (when not conflicting with MVP slices):

- Expand `data/official_sgr_rules.seed.json` (Решение КТС №299 and related contours)
- Extend `validate_official_sgr_dataset(...)` and dataset report coverage
- Regression: toys `9503`, adult cosmetics `3304`, child/special SGR cases
- ✅ Rebuilt the exact 21/96/17,809 catalog from 96 tracked official PDFs into a
  temp audit-only artifact and verified the catalog/NTM topology without production
  DB mutation. Do not reuse the retired positive rate-snapshot conclusion: the
  current ETT bundle is quarantined until a reviewed schema-v2 official manifest
  and temporal-rate model exist.

## What is not the next priority

- Official NTM/SGR **enforcement** in broker / missing-check (not approved; a new
  Ivan decision is required)
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
