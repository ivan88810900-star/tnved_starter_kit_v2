# NTM completeness recheck — 2026-09-14

## Scope and evidence boundary

- Task: `TARIFF-NTM-COMPLETENESS-RECHECK-001` (A2 NTM/compliance review).
- Reviewed product candidate: PR #187 head `5d3b0c1dc7dd8e396c4f812db2bf6f1fa6d293f9`, tree `59fe9ed9d1a27175a96749cc85422ba34f36b12c`.
- This is a code, repository-evidence, and executable-test review. It is **not** a legal opinion and does not decide that any measure applies to a transaction.
- No fresh legal proposition is inferred from a web page. The source dates, revisions, hashes, and URLs below are the versions bound in the reviewed repository. The accepted NTM authority boundaries are DM-0008 (official contours remain advisory-only; enforcement not approved) and DM-0011 (bounded structured applicability in shadow; production activation deferred). DM-0014 is only a **proposed** future authority model for ETT rate-manifest legal review and must not be cited as an accepted NTM authority decision.
- No product code, database, feature flag, enforcement behavior, provider configuration, or secret was changed.

## Result

The reviewed implementation has a broad **structural** NTM contour: every code in the separately retained audit corpora can be evaluated against nine advisory families, and bounded exact rules are guarded by closed fact schemas and fail-closed enforcement checks. The repository evidence supports that structural claim, but it does **not** support a claim of complete current legal coverage.

Two technical defects are confirmed:

1. NTM API freshness is derived from the unrelated `EEC_ETT` source only and falls back to `LOCAL / is_stale=false` when the source is absent or the query fails. This can present unknown NTM freshness as fresh.
2. The primary product-details permit card can display a green “no special permits identified” message when there are no enforced broker documents, even when the same response contains official advisory requirements that require clarification.

Enforcement must remain off. Exact positive findings remain advisory unless they pass the deliberately narrow trusted-evidence gate; the reviewed repository contains no basis for broad automatic legal applicability.

## Implemented NTM family map

Primary implementation: `customs-clear/backend/app/services/official_ntm_contours.py`. The matrix always returns all nine families and distinguishes `definite`, `needs_clarification`, `excluded`, `legacy_signal`, and `not_detected`. Broad contour rows set `used_for_missing_check=false`, so they cannot independently create a broker-document failure.

| Family | Repository-bound source/rule layer | Product-characteristic predicates | Current completeness boundary |
|---|---|---|---|
| `technical_conformity` | EAEU/RF technical-regulation catalog plus RF Government Resolution No. 2425 | TN VED prefix, product description, material/use signals, bounded characteristic rules for TR 007/015/026/036/050/051/052 and tableware | Broad candidate detection; many “из”/description predicates need clarification. Four regulations in the full-gate evidence lack a primary filter: TR 047/2018, 048/2019, 049/2020, 053/2026. |
| `sanitary_registration` | Decision No. 299 contour; curated SGR seed; SGR registry evidence | TN VED, first import, food contact, drinking water, disinfectant, personal-hygiene use | Broad list is advisory. Exact health slice is small and bounded; registry evidence is not equivalent to full list extraction. |
| `veterinary_control` | Decision No. 317 | TN VED, animal origin, feed/veterinary use, processing and manufacturer evidence | Prefix/description coverage is advisory. Exact coverage is bounded, not exhaustive. |
| `phytosanitary_control` | Decisions No. 318 and No. 157 | Plant origin, processing, packaging, declared phytosanitary risk tier | High/low risk distinctions still require transaction and product facts. A low-risk prefix candidate is not a legal exemption decision. |
| `radio_frequency` | Decision No. 30 section 2.16 and bounded device rules | Embedded radio, radio technology, frequency, power, registry/exemption evidence | 2.16 contour has 93 unique 2.16/2.19 ranges together with cryptography; technical exemption allowlist is intentionally small. |
| `cryptography` | Decision No. 30 section 2.19 and bounded device rules | Presence/function of cryptography, mass-market characteristics, registry number, verification/exemption evidence | Code-only matches do not establish notification/licence applicability. |
| `licensing` | Decision No. 30 sections 1.2, 2.2, 2.3, 2.30 and related bounded trade rules | Waste/hazard/contamination, cultural-object facts, sealed/package properties, composition/CAS/name match | Only bounded exact slices can become `definite`; broad and “из” matches remain clarification candidates. |
| `prohibitions_restrictions` | Decision No. 30 section index | TN VED plus transaction/product facts | Quota contours 2.27, 3.1, and 3.2 are intentionally omitted because year, origin, and volume are required. This is a known source/model gap, not evidence of no restriction. |
| `export_control_dual_use` | Six RF export-control lists and catch-all signals | Direction, destination, end user/use, list item and technical parameters, military/WMD and sanctioned-end-user indicators | 1,087 raw HS candidates are stored; the repository reports 1,085 effective candidates after retirement handling. Code-only applicability is prohibited; catch-all is transaction-level. |

The family disclaimer in `official_ntm_contours.py` correctly states that `not_detected` is not proof that no legal measure applies.

## Source, version, and date bindings

| Evidence | Bound version/date in this candidate | What it proves | What it does not prove |
|---|---|---|---|
| `docs/ai-workflow/evidence/ntm-full-gate-20260815.json` | Audit dated 2026-08-15; 17,809 positions, 21 sections, 96 groups, nine families; 20,312 generated requirements; no invalid matrix row or enforcement leak | Structural evaluation and invariants for the audited catalog snapshot | Current legal applicability or freshness after 2026-08-15 |
| `docs/ai-workflow/evidence/ett-current-table-ntm-compatibility-20260908.json` | Evaluated 2026-09-08 against 13,293 exact codes/descriptions from the current official-table corpus; 15,695 advisory rows: 13,670 `official_ntm_contours` + 2,025 `official_export_control`; zero reported enforcement leaks | The advisory evaluator and enabled/default-off bridge rejection behavior were structurally compatible with that current-table input set | The legacy 17,809 catalog gate, a DB-backed broker runtime, exact transaction applicability, full legal completeness, or production approval/readiness |
| `official_ntm_exact_health.py` | Four official EEC URLs plus URL response ETag/date observations recorded on 2026-08-15 for Decisions 299, 317, 318, 157 | Observation metadata associated with eight code-declared shadow rule groups / 19 exact codes | The repository retains no official response bytes, official-content hashes, source-row locators, or quotes that prove extraction. Quote-bound validation against retained official-source content is still required; exhaustive health coverage is not established. |
| `official_ntm_exact_trade.py` | Decision No. 30 slice checked 2026-08-15; PP 1284 publication date recorded as 2022-07-19 | Provenance for the bounded trade/export-control slice | Present-day legal force or transaction-specific applicability |
| `customs-clear/backend/data/official_sgr_rules.seed.json` | `official-sgr-contour-v2-curated-2026-05-issue17` | Reproducible curated SGR seed used by code/tests | Full SGR legal list; its generic EEC home-page URL is not item-level evidence |
| `customs-clear/backend/data/official_export_control_rules.seed.json` | Extracted 2026-08-15; six source lists; 1,087 candidate entries. Each list records an official `publication.pravo.gov.ru` URL and an `alta.ru` `extraction_reference_url`. | Reproducible code dataset, declared link metadata, and retirement metadata | No retained official response bytes/content hashes/source-row locators prove that the extracted candidates came from the official objects. Official-content validation remains required, as do list-item/technical/end-use facts for applicability. |
| `customs-clear/backend/scripts/monitor_official_ntm_sources.py` | Monitors Decision No. 30 slices, Decisions 299/317/318/157, PP 2425, export-control acts/FSTEC, TR and registry endpoints | Read-only drift detection/capture design | Automatic promotion of changed legal text into rules |
| `customs-clear/backend/app/services/regulatory_source_registry.py` | Per-source manual-review/monitor/registry policies and staleness contracts | Declared source ownership and update policy | That every runtime response is bound to the latest approved NTM source revision |

DM-0013 correctly requires reviewed default-branch promotion after legal-document drift and forbids automatic rule changes from a checksum change. That policy is safe, but it means “monitor reachable” and “rules legally current” are separate assertions.

The two structural audits must remain distinct. `ntm-full-gate-20260815.json` is the legacy 17,809-position catalog gate. `ett-current-table-ntm-compatibility-20260908.json` is the later 13,293-code current official-table compatibility check and expressly says that no synthetic full catalog or production DB was created, DB-backed broker/API/UI behavior was not exercised, and production readiness/legal applicability was not approved.

## Exact applicability and fail-closed gates

The transaction facts schema is closed (`extra=forbid`) and keeps absent facts unknown. It covers direction/route/origin/destination, intended use and end user, composition/CAS/name match, manufacturer/list/evidence documents, health/veterinary/phytosanitary predicates, Decision No. 30 product properties, radio/cryptography details, and export-control technical/end-use/catch-all facts.

Under accepted DM-0011, `official_ntm_curated_enforcement.py` is default-off via `NTM_V2_OFFICIAL_CURATED_ENFORCEMENT_ENABLED` and versioned as `official-ntm-curated-2026-08-15.1`. Its allowlist contains only:

- `D30-2.30-HCB-2903920000`
- `RF-PP1284-2.1.1-AMITON`

Even these rules require an exact positive result, complete facts, non-candidate status, matching family/permit, explicit enforcement eligibility, `trusted_source_verified=true`, and a trusted evidence kind (`trusted_official_registry_adapter` or `trusted_document_adapter`). A caller-provided claim of verification is not accepted as adapter proof. This is an intentional safety property.

`non_tariff_service.py` keeps broad official results separate from `broker_required_permits`. Required/missing-document state is computed only from the broker layer; export/transit does not reuse the legacy import broker. Catch-all risk can raise an otherwise `OK` result to `WARNING`. No-rule/no-broker cases also return `WARNING`, not a legal clearance.

## API, AI, and UI exposure

- `customs-clear/backend/app/api/non_tariff.py` exposes authenticated `/check` and `/normative-block` routes and accepts the closed facts object.
- `customs-clear/backend/app/services/normative_requirements_block.py` separates required, missing, and advisory rows; it also exposes family status, exact-applicability summary, exclusions, catch-all, and curated-enforcement audit data.
- `customs-clear/backend/app/services/grounded_assistant.py` labels advisory requirements as requiring clarification and not automatically mandatory, with citations. The assistant orchestration preserves the required/missing/advisory separation.
- `customs-clear/frontend/src/components/nonTariff/NormativeRequirementsBlock.tsx` renders the detailed advisory, exact, family, and catch-all data.
- `customs-clear/frontend/src/components/tnved/PermitDocumentsBlock.tsx` does not consume advisory rows and is rendered near the top of `ProductDetails.tsx`, while the detailed normative block is under a separate tab. This creates the contradictory green state recorded below.

Key executable contracts reviewed include:

- family construction: `official_ntm_contours.py:148` and `evaluate_official_ntm_contours()` at line 647;
- exact shadow evaluation: `official_ntm_exact_applicability.py:evaluate_official_ntm_exact_applicability()` at line 562;
- curated flag/version/allowlist: `official_ntm_curated_enforcement.py:15-23`;
- required/advisory separation: `normative_requirements_block.py:110-166`;
- exact/broad safety tests: `test_official_ntm_contours.py`, `test_official_ntm_exact_applicability.py`, and `test_official_ntm_curated_enforcement.py`;
- normative separation tests: `test_normative_requirements_block.py:129-368`.

## Findings

### Confirmed technical defects

#### NTM-RECHECK-001 — NTM freshness is unrelated and fail-open

Severity: high compliance presentation risk.

`customs-clear/backend/app/services/non_tariff_service.py::_data_freshness()` queries only `EEC_ETT`, although the NTM result is assembled from Decision No. 30, Decisions 299/317/318/157, PP 2425, export-control, TR, registry, and legacy NTM data. If that source is absent or the query raises, the method returns a local seed descriptor with `is_stale=false` and no synchronization time.

Reproduction:

```bash
cd customs-clear/backend
PYTHONPATH=. /tmp/tariff-payment-recheck-venv/bin/python - <<'PY'
from app.services import non_tariff_service, normative_store
normative_store.list_source_status = lambda: []
print(non_tariff_service._data_freshness())
PY
```

Observed result:

```text
{'source_name': 'Локальная база правил', 'source_code': 'LOCAL', 'synced_at': None, 'is_stale': False, 'revision': 'seed'}
```

Expected safety property: NTM freshness must aggregate the actual sources used by the returned result and must represent unavailable/pending/stale evidence as unknown or stale, never silently fresh.

#### NTM-RECHECK-002 — advisory-only result can coexist with green “no permits” message

Severity: high compliance UX risk.

`PermitDocumentsBlock.tsx` derives its display only from enforced `required_documents` types `CC`, `DC`, and `SGR`. If that list is empty, it renders a green message that no special permit documents were identified. Official contour rows deliberately stay in `advisory_requirements`, so a valid advisory-only response can show that green message while `NormativeRequirementsBlock.tsx` says the same goods require clarification.

Static reproduction:

```bash
rg -n "required_documents|Специальных разрешительных|advisory_requirements" \
  customs-clear/frontend/src/components/tnved/PermitDocumentsBlock.tsx \
  customs-clear/frontend/src/components/tnved/ProductDetails.tsx \
  customs-clear/frontend/src/components/nonTariff/NormativeRequirementsBlock.tsx
```

Expected safety property: the summary card must not make a negative compliance claim when official advisory families/signals are present. It should render a neutral clarification state or explicitly distinguish “no enforced broker document” from “no NTM detected.”

### Source/evidence gaps (not automatically code defects)

1. The 17,809-position gate is a 2026-08-15 structural snapshot. This worktree does not contain a populated `customs.db`, so the full-catalog gate could not be rerun against a retained current catalog database.
2. Exact health coverage is deliberately bounded to 19 code-declared shadow entries; its source binding is only URL+ETag/date observation metadata. There are no retained official bytes, content hashes, locators, or quotes proving extraction, so quote-bound official-source validation remains required. Device and trade exact rules are likewise small curated slices. The remaining broad contour is not full legal extraction.
3. Decision No. 30 quota sections 2.27, 3.1, and 3.2 are omitted pending year/origin/volume modeling.
4. Four technical regulations lack a primary filter in the full-gate evidence and therefore depend more heavily on description/fact clarification.
5. All six export-control source-list records use an `alta.ru` extraction reference alongside an official publication URL, but retain no official response bytes/content hashes/source-row locators proving the extraction. Revalidation against retained official content is required.
6. Static datasets and their runtime responses are not bound to an aggregated “latest approved NTM source set” status. DM-0013 safely prevents silent auto-promotion, but the product should expose pending drift and the approved revision set.
7. The curated SGR seed uses a generic EEC URL and a May 2026 issue revision; item-level source binding is still needed before any exact legal promotion.
8. No trusted source adapter currently establishes the facts required for the curated enforcement allowlist in this reviewed flow. This is a safe blocker, not a reason to weaken the gate.

### Human/legal decisions required before expansion

1. Whether any broad or exact source rule is legally applicable to a real transaction, including treatment of “из” clauses, exclusions, transition periods, and document alternatives.
2. Whether and how quota sections should be modeled for year, origin, volume, and allocation/licensing context.
3. Legal/source disposition for the four technical regulations without primary filters.
4. Approval of any new rule for enforcement, any expansion of the two-rule allowlist, or activation of the default-off enforcement flag. DM-0008 and DM-0011 are the accepted NTM boundaries; neither grants this approval.

These decisions must not block independent technical work on source provenance, freshness, neutral UI wording, tests, and adapter evidence.

## Executed validation

### Focused exact NTM suite

```bash
cd customs-clear/backend
/tmp/tariff-payment-recheck-venv/bin/pytest -q \
  tests/test_official_ntm_contours.py \
  tests/test_official_ntm_curated_enforcement.py \
  tests/test_official_ntm_exact_applicability.py \
  tests/test_official_ntm_exact_devices.py \
  tests/test_official_ntm_exact_health.py \
  tests/test_official_ntm_exact_trade.py
```

Result: **114 passed** in 0.39 s.

### Additional NTM policy/data/API tests

Individually executed DB-independent NTM schema, catalog-baseline, full-coverage-audit, history/red-team, legal-guard, legacy-boundary, noise, source-isolation, normative-block, curated-SGR, rule-validity, and v2 engine test modules.

Result: **349 passed**; three DB-bound cases failed because the checkout has no populated runtime database/tables. The failures were `sqlite3.OperationalError` fixture/runtime errors, not contradictory NTM assertions.

### Source registry, snapshot, review queue, and assistant tests

```bash
cd customs-clear/backend
/tmp/tariff-payment-recheck-venv/bin/pytest -q \
  tests/test_opendata_source_integrity.py \
  tests/test_regulatory_source_completeness.py \
  tests/test_regulatory_source_updates.py \
  tests/test_regulatory_snapshot_atomicity.py \
  tests/test_regulatory_review_queue.py \
  tests/test_assistant_copilot.py \
  tests/test_grounded_assistant.py \
  tests/test_assistant_batch.py
```

Result: **169 passed**, two warnings, in 4.81 s.

Total independently observed passing tests across the non-overlapping focused runs: **632**.

A broader selected NTM run observed 583 passes, one skip, and 230 failures caused by the same empty/missing runtime database (for example `no such table: non_tariff_measures` and `no such table: hs_rates`). It is not reported as a product pass or product regression. Frontend Vitest could not run because `node_modules`/`vitest` is absent (`vitest: not found`); frontend findings above are static and need executable regression coverage in a prepared frontend environment.

## Recommended scoped follow-ups

1. Replace `_data_freshness()` with a fail-closed aggregate over every NTM source actually used in the response; expose missing, stale, and pending-review sources and the approved revision set.
2. Change the permit summary card so advisory signals prevent the green negative claim; add a component/integration regression test for an advisory-only SGR/SS/DS response.
3. Preserve the 13,293-code current-table compatibility receipt separately and rerun/archive a DB-backed catalog/broker gate if production-runtime completeness is claimed; do not relabel it as the legacy 17,809-position gate.
4. Create quote-/locator-bound retained official-source evidence for exact health, export-control, and curated SGR extraction; extend exact rules only through reviewed official evidence.
5. Keep `NTM_V2_OFFICIAL_CURATED_ENFORCEMENT_ENABLED` off until trusted adapters, A5/A6 review, exact-head CI, and explicit human legal approval are all present.
