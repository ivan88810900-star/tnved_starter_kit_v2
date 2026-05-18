# Current Project Focus

## Status

Active

## Last updated

2026-05-18

## Strategic direction

The current active workstream is the transition from legacy non-tariff heuristics toward official, validated NTM v2 normative datasets.

## What has already been completed

- NTM v2 storage model:
  - `ntm_measures_v2`
  - `ntm_applicability_rules_v2`
- Applicability model:
  - `definite`
  - `possible`
  - `needs_clarification`
- Migration of:
  - TR TS catalog
  - NTM layers
  - legacy non-tariff rules
  - legacy non-tariff measures
- Safe enforcement policy:
  - legacy rules import as `possible`
  - only `definite` may affect missing-check
  - legacy measures enforcement limited to vet/phyto
- Advisory requirements UI/API
- Official SGR contour:
  - `official_sgr_registry`
  - importer
  - diagnostics
  - advisory integration (`NTM_V2_OFFICIAL_SGR_ADVISORY_ENABLED`, default OFF)
  - initial curated `data/official_sgr_rules.seed.json`
  - dataset validator and CLI report (`validate_official_sgr_dataset`, `run_ntm_v2_official_sgr_dataset_report.py`)

## Current top priority

Continue improving the **official SGR normative dataset**: expand and curate `official_sgr_rules.seed.json`, strengthen validation and diagnostics for completeness and safety, and keep official SGR **out of broker/enforcement** until a separate approved workstream.

## Next recommended implementation tasks

When the dataset PR above is merged, the next Cursor tasks should stay on the same workstream until Ivan reprioritizes, for example:

- Add or refine rules in `data/official_sgr_rules.seed.json` (ЕЭК №299, раздел II / related contours)
- Extend `validate_official_sgr_dataset(...)` and dataset report coverage
- Regression tests for:
  - toys `9503` — no official SGR
  - adult cosmetics `3304` — no `definite` without child/special markers
  - child/special SGR cases with correct applicability
  - idempotent import of the seed

## What is not the next priority

- **Frontend verification (AGENT-04)** is not the current top workstream unless explicitly reprioritized in this file or a Decision Memo.
- Do not jump to official SGR **enforcement** in broker / missing-check.
- Do not move broad legacy SGR heuristics into broker as “official”.
- Do not expand unrelated product areas while this workstream is active.

## When to create a Decision Memo

Create a Decision Memo instead of a Cursor Task if:

- expanding SGR requires a legal/product interpretation not already encoded in the seed;
- there are multiple plausible data-model or import approaches;
- a category should be `definite` vs `possible` and evidence is ambiguous;
- the roadmap should switch away from official SGR dataset work (e.g. to frontend or enforcement).

## How agents use this file

- **Codex** reads this file **before** proposing the next task; if `Status: Active`, this overrides backlog-style AGENT-01…05 priorities unless an issue explicitly says otherwise.
- **Cursor** implements only tasks aligned with the active focus or an explicit issue scope.
- **Ivan** updates `Last updated` and sections when reprioritizing.
