# TASK-MVP-PAYMENTS-001: Explainable Smart Payments in the TN VED card

> **Status:** Completed
> **Owner:** Backend + Frontend
> **Created:** 2026-07-15
> **Depends on:** TASK-CANONICAL-006, existing `/api/payments/quote`

## Goal

Turn the existing payment quote into a visible professional product block inside the
TN VED card: not just rates, but amounts, status, calculation base, explanation,
sources, assumptions, uncertainty and official follow-up links.

## Scope

- mount the existing `SmartPaymentsBlock` in the TN VED card Payments tab;
- expose additive calculation-base fields for duty, VAT and customs fee;
- attach the Canonical TN VED anchor to the quote for later grounded AI use;
- show warnings, partial-vs-final total, data quality and input assumptions;
- preserve existing legal-reference disclosure and all calculation semantics;
- validate user-entered country/quantity before calling the API.

## Invariants

- no changes to rate selection, VAT, excise, anti-dumping or fee mathematics;
- never show an uncertain amount as a confirmed final total;
- no DB/Alembic change and no payment-source mutation;
- no feature-flag activation, merge, or deployment;
- raw Canonical identifiers remain hidden from the human-facing UI.

## Acceptance criteria

- [x] Smart Payments is visible on the professional TN VED card;
- [x] every line exposes status, reason and source; formula lines expose their base;
- [x] warnings and assumptions are visible, with partial total clearly distinguished;
- [x] quote carries an optional Canonical anchor without trusting it for arithmetic;
- [x] deterministic backend contract tests pass;
- [x] frontend production build passes with zero TypeScript errors;
- [x] existing payment quote regressions introduce no new failures.

## Completion report (2026-07-15)

- Focused payment/Canonical matrix: **50 passed**.
- New deterministic explanation contract: **2 passed** (included in the matrix).
- Existing payment quote suite: **8 passed, 1 pre-existing failure**. The unchanged
  failure expects a final total while the conservative `special_duty=not_configured`
  contract intentionally returns only a partial confirmed total.
- Frontend `npm run typecheck`: passed.
- Frontend production `npm run build`: passed; only existing toolchain and bundle-size
  warnings remain.
- Python compile and Ruff checks: passed.
- No feature flag, DB migration, merge or deployment was performed.
