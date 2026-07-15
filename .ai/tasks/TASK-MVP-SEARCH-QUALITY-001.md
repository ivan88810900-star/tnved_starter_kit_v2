# TASK-MVP-SEARCH-QUALITY-001: Product-facing hybrid TN VED search

> **Status:** Completed
> **Owner:** Backend + Frontend
> **Created:** 2026-07-15
> **Depends on:** TASK-CANONICAL-006, existing FTS5 catalogue index

## Goal

Make the main `/tnved` search reliable for a non-technical user: codes, official
wording, everyday product names, Russian morphology and common typos must produce
ranked, explainable candidates without pretending that search alone is a final
customs-classification decision.

## Scope

- replace flat BM25 ordering with hybrid ranking across code, direct name match,
  curated domain vocabulary and full text;
- match synonym keys as words/stems rather than arbitrary substrings;
- add conservative typo recovery against curated product vocabulary;
- expose additive match reasons and correction metadata;
- show match reasons, corrections and fallback suggestions in the main accordion UI;
- preserve Canonical anchors and the existing FTS-unavailable LIKE fallback;
- fix the invalid print selector found by the production CSS build.

## Invariants

- search results are candidates, not a legally final TN VED classification;
- no remote AI call, client-side secret or automatic embeddings ingestion;
- no database migration or mutation of normative/source datasets;
- Canonical runtime flags remain default OFF;
- no merge or deployment.

## Acceptance criteria

- [x] exact and formatted code prefixes remain first;
- [x] `ноутбук` prefers 8471 over computer tomography;
- [x] `электрический чайник` does not leak into tea chapter 0902;
- [x] `куртка` and `автомобиль` prefer direct/product-family matches;
- [x] common typos such as `смартфн` and `пылесосс` are corrected visibly;
- [x] FTS control words and special syntax cannot create false/crashing queries;
- [x] the actual `/tnved` accordion consumes rich search metadata;
- [x] backend, live HTTP, TypeScript and production-build checks pass.

## Completion report (2026-07-15)

- Search/Canonical/backend regression matrix: **84 passed**.
- Deterministic hybrid-quality suite: **5 passed** (included above).
- Real-data audit: **14,021 catalogue rows**, code/name/synonym/morphology/typo and
  empty-result scenarios checked; warm searches completed in a few milliseconds.
- Live HTTP `/api/v1/tnved/search`: code, dictionary, corrected-query and empty
  scenarios returned the expected typed metadata.
- Frontend `npm run typecheck`: passed.
- Frontend production `npm run build`: passed; Tailwind/PostCSS output verified.
- Changed-file Ruff and Python compile checks: passed.
- Semantic embeddings remain a separate unfinished contour: the available databases
  contain zero vectors and no configured OpenAI key was found.
- No feature flag, database migration, merge or deployment was performed.
