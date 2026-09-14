# Legacy country preferences: corrective decision and delivery contract

Date: 2026-09-10. Implements Ivan's continuing payment-correctness instruction
and evidence-first direction accepted in Decision #188 Option A. No new rollout,
production write, merge, deployment or NTM enforcement decision is made here.

## Problem and evidence

`country_tariff_preferences` is a legacy country lookup. It does not establish
the current agreement, goods coverage, origin, Union-goods status, date or shipment
conditions. The engine nevertheless multiplied a duty by any stored coefficient
below one. Existing tests even asserted that historic BR/IN/TR GSP seeds must
reduce duty. Those tests validated the defect, not current eligibility.

Council Decision 47 paragraphs 3/7 requires country, goods and origin conditions
together. Decision 60 requires evidence and shipment conditions; it permits
specified declaration alternatives, third-country sellers and conditional transit.
Neither a certificate boolean nor a direct-purchase-only rule is sufficient.

Official sources observed on 2026-09-10:

- [GSP conditions, Decision 47](https://eec.eaeunion.org/upload/medialibrary/577/a261ucvbqfdjx4dah7wl5cun0jv3v8op/Polozhenie-ESTP.pdf).
- [Current beneficiary countries](https://eec.eaeunion.org/upload/medialibrary/222/m3gyn7elrdc0hxo3j32w7k7vcwlf3wsi/Perechen-stran_polzovateley-15.05.26.pdf).
- [Preferential goods](https://eec.eaeunion.org/upload/medialibrary/1e5/z23azuqycqy567xgsu5awaukmdb2itvb/Perechen-preferentsialnkhykh-tovarov-_po-sostoyaniyu-na-08.03.2026_.pdf).
- [Origin rules, Decision 60](https://eec.eaeunion.org/upload/medialibrary/dc8/kz4432n8enb7uyp83hshzcagsi3wm1gj/Pravila-proiskhozhdeniya-dlya-razvivayushchikhsya-i-naimenee-razvitykh-stran_GSP_obnovlen.pdf).

## Decision

Suppress every country-only legacy reduction. Keep the original candidate and
its provenance visible. Calculate undiscounted arithmetic as a **provisional
estimate**, never as a confirmed final amount. This includes zero coefficients:
origin in a member state alone does not establish the status of the goods or
the transaction regime. No three-country blacklist or automatic seed replacement
is introduced.

Alternatives: changing a few country seeds leaves the systemic eligibility defect;
accepting caller-supplied eligibility flags creates an evidence bypass; removing
all arithmetic obscures useful estimates. Retaining explicit provisional values
while blocking final quotes provides useful calculations without claiming that
the missing eligibility review has occurred.

The existing MFN coefficient, upward coefficient, explicit manual duty and
separate geographic duty override paths retain their existing behavior. This
does **not** newly certify those source records or current ETT rates. A complete
authoritative eligibility engine and rate promotion remain separate unfinished work.

The same correction covers missing source rates: a missing duty or VAT lookup
sets a generic review reason instead of presenting fallback arithmetic as a
confirmed zero. An actual structured 0% rate remains zero; an explicit manual
rate remains a manual override. Missing duty also makes its dependent VAT amount
uncertain. The generic reason is kept separate from a preference warning.

## Required end-to-end behavior

- Raw result: `REVIEW_REQUIRED`, `amounts_provisional=true`, unapplied candidate
  with `needs_review`, reason and missing evidence dimensions. Payload assertions
  cannot bypass this guard.
- Quote: uncertain duty and dependent VAT are marked for review; final payable
  total is absent. Any retained numbers are explicitly preliminary assumptions.
- Comparison: provisional values cannot establish a cheapest scenario or savings.
  Recalculation retains actual scenario/manual inputs.
- History and export: preserve status and reason in saved JSON, API, CSV/XLSX
  and compliance summaries, invoice batches and document-check PDF reports.
  Older rows without flags remain unknown.
- Assistant: retain the material caveat through grounding and output; optional
  wording must not turn provisional payment figures into a final result.
- Frontend: label preliminary amounts, show the reason, and preserve status in
  comparisons/history/downloads. The two-code comparison consumes the actual
  nested `scenarios[].profile.breakdown` API contract; the previous flat-row
  assumption crashed with a real API response and is removed.

No migration or modification of the production database is needed. The new tests
use deterministic isolated fixtures, not assertions that old seeds are current law.

## Separate source gap

Decision 130 tariff exemptions and Decision 728 application conditions are not
fully represented by tariff-cell C footnotes. Current consolidated PDFs now include
amendments 75/77/80, but inconsistent amendment dates require individual-original
review. The source-capture addition preserves observed official links and original
bytes. Successful capture does not resolve those conflicts, prove complete legal
coverage, authorize a benefit, or make the entire rates block ready.
