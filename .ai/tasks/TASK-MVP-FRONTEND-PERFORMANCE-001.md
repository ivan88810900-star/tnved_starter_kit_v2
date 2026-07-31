# TASK-MVP-FRONTEND-PERFORMANCE-001 — Route-level production bundles

## Status

Completed — 2026-07-31

## Goal

Reduce the initial browser download after integrated MVP acceptance without changing
routes, product behavior or backend contracts.

## Context

The production build emitted one `1,277,432` byte JavaScript bundle and Vite warned
that it exceeded the 500 kB chunk threshold. A user opening a single screen therefore
downloaded the Dictionary, Calculator, Assistant and every other route up front.

## Scope

- Load each page module only when its existing route is opened.
- Keep the shared application shell visible while a route bundle is loading.
- Announce loading through an accessible `status` region.
- Catch route import/render failures and offer a safe page reload instead of a blank
  application surface.
- Protect successful loading, failure fallback and the real product-card → assistant
  route bridge with frontend tests.

## Out of scope

- Route or API contract changes.
- Backend, database or Canonical model changes.
- Visual redesign.
- Canonical feature-flag rollout, vector ingestion or external LLM calls.

## Acceptance

- `npm test`: 9 tests passed across 5 files.
- `npm run typecheck`: passed.
- `npm run build`: passed with no chunk-size warning.
- Initial JavaScript referenced by `dist/index.html`: `1,277,432` → `231,325` bytes
  (`-81.9%`); measured gzip total: approximately `374` → `79` kB (`-78.9%`).
- Main entry chunk: `1,277,432` → `51,580` bytes (`-96.0%`).
- Largest on-demand route chunk is Calculator at `384,916` bytes, below Vite's
  500 kB warning threshold.

## Safety

- Existing URL paths and navigation bridge are unchanged.
- Loading and error states remain inside the existing application layout.
- Backend diff is empty; no database access or writes occurred.
- No external provider request, merge or feature-flag enablement.
