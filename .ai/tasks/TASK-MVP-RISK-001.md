# TASK-MVP-RISK-001: Evidence-first sanctions and risk checks

> **Status:** Completed
> **Owner:** Backend + Frontend
> **Created:** 2026-07-15
> **Depends on:** TASK-CANONICAL-006, existing `/api/risk/check`

## Goal

Turn the existing conservative risk diagnostic into a professional TN VED card
workflow: the user can explicitly check a code, origin country and counterparty,
and can see exactly what was checked, what matched and which source supports it.

## Scope

- add a dedicated Risk tab to the TN VED code card;
- accept optional ISO-2 origin country and counterparty/manufacturer inputs;
- expose a typed screening scope for checked and missing inputs;
- expose actual matched entity, HS prefix, country and match method;
- link signals and source coverage to registered official source pages;
- attach the optional Canonical TN VED anchor for later grounded AI use;
- deduplicate counterparty inputs before local OFAC/EU matching.

## Invariants

- the check remains diagnostic and does not change broker/enforcement semantics;
- incomplete, partial or seed/manual sources are never presented as a clean result;
- substring entity matching is labelled preliminary and is not represented as KYC;
- no external sanctions API, DB/Alembic change or source-data mutation;
- no feature-flag activation, merge or deployment;
- raw Canonical identifiers remain hidden from the human-facing UI.

## Acceptance criteria

- [x] the TN VED card has an interactive Risk tab;
- [x] code-only checks run automatically and visibly disclose untested dimensions;
- [x] country and counterparty inputs are validated before the API call;
- [x] positive signals show the actual matched evidence and source;
- [x] duplicate entity inputs cannot duplicate a signal;
- [x] incomplete coverage yields manual review rather than a false clear result;
- [x] backend contract, auth and live HTTP paths are verified;
- [x] frontend typecheck and production build pass.

## Completion report (2026-07-15)

- Focused risk contract: **9 passed**.
- Broader relevant matrix: **54 passed, 5 pre-existing environment/data failures**
  outside this slice (calculator fixture expectations and missing `apscheduler`).
- Authenticated live HTTP: health, login and `/api/risk/check` all returned 200;
  the response carried HS/country/counterparty scope and conservative coverage.
- Frontend `npm run typecheck`: passed.
- Frontend production `npm run build`: passed; only existing Tailwind/toolchain and
  bundle-size warnings remain.
- Python compile and changed-file Ruff checks: passed.
- No feature flag, database migration, merge or deployment was performed.
