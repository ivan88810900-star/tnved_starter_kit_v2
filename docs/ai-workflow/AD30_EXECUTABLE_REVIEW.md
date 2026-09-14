# AD30 executable review — 14 September 2026

This completed implementation prepares an **offline, hypothetical review** of
the retained Decision 12 → 4 → 121 source candidate. It does not calculate an
admitted current or historical liability. Independent A5 approval covers the
source-fact bindings, bounded product interpretation and arithmetic/CLI; exact
publication CI is recorded separately in the integration evidence and PR #187.

The existing source acquisitions and PR #192 prose candidate were reused.
Repeated A6 findings against `22a7df55` were already reconciled in `a9d15c74`:
the payment engine and both A6 regression suites were verified unchanged at
recovery. This block neither repeats those fixes nor changes the live engine.

## Run one hypothetical scenario

From `customs-clear/backend`, using the project's Python dependencies:

```sh
python scripts/preview_ad30_candidate.py <<'JSON'
{
  "as_of": "2026-09-14",
  "facts": {
    "direction": "import",
    "destination": "RU",
    "origin_country": "CN",
    "commodity_code": "7306402009",
    "tubular_product": true,
    "welded": true,
    "corrosion_resistant_steel": true,
    "cross_section": "round",
    "wall_thickness_mm": "1",
    "outer_diameter_mm": "20"
  },
  "source_row_id": "foshan_vinmay",
  "customs_value": "0.01",
  "currency": "RUB"
}
JSON
```

The CLI writes one JSON object to stdout. For these expressly hypothetical
inputs, `amount` is the exact string `"0.001462"`, `status` is `calculated`,
and `rounding_applied` is false. Both legal and temporal applicability remain
`unavailable`; `final_payable_amount` is null. Selecting the row is an explicit
scenario operand, not a finding that this producer or rate applies to a shipment.
`as_of` is retained without selecting an effective legal interval.

`--input scenario.json` accepts a regular file; stdin is the default. JSON input
is bounded to 64 KiB and rejects duplicate/unknown fields, floats, nonfinite
values and forged approval claims. Decimal fractions must be plain strings.
The script never starts the application, accesses a DB, downloads a source or
writes a result file. These properties are independently checked in real CLI
processes, including attempted side effects, rather than inferred from imports.

| Exit | Meaning |
| --- | --- |
| 0 | Hypothetical arithmetic available; review/authority restrictions remain. |
| 3 | Valid review scenario is unresolved or outside this source candidate; no amount. |
| 2 | Input or source-record validation failed; no amount. |

Null/unavailable never means a zero duty or absence of another measure. A code
match alone cannot produce arithmetic. An unknown producer never selects the
`other_producers` row. All three explicit row choices retain their complete
source-row and percent-unit evidence in the standalone result.

## Interfaces and independent verification

- [A3 source dossier](AD30_SOURCE_FACT_DOSSIER.md): 24 immutable bound facts,
  three printed producer rows, three SHA-pinned existing evidence records.
- [A2 product interpretation](AD30_APPLICABILITY_REVIEW.md): code AND product,
  direction, origin/destination, declared shape and exact dimensional bounds.
- [A4 consumer contract](AD30_REVIEW_CONSUMER_CONTRACT.md): exact fields,
  evidence semantics, null handling and decimal values; no live AI integration.
- [A5 evidence](evidence/ad30-independent-qa-20260914.json): two independently
  reproduced defects repaired by their owners; same red assertions went from
  4 failed / 24 passed to 28 passed. Final independent suite: 43 passed,
  including 15 CLI processes with side-effect traps. Combined profile: 449 passed.
- [Integration task](../../.ai/tasks/TASK-AD30-EXECUTABLE-REVIEW-001.md): ownership,
  commits, CI scope and publication evidence.

Source-record integrity does not attest original PDF replay or native scanned
text. A5 corrected a normalized country label mistakenly presented as literal
transcription; original historical evidence stayed unchanged. A1 corrected
incomplete monetary-row provenance without changing arithmetic or legal guards.

## Remaining work

This candidate has no approved temporal rules, complete amendment/repeal
inventory, current nomenclature mapping, verified producer identity/succession,
transaction evidence or legally attested object versioning/retention/legal hold.
Country recognition and dimensional consistency checks are deliberately bounded
as documented by A2. It is not a general geometry, country or compliance service.

Next, extend the source-bound temporal/amendment review and producer/nomenclature
evidence for this chain, then the remaining ETT/VAT/excise/remedy/preference/origin
dependencies. Full rates and NTM coverage remains partial. Manifest-bound human
review and separate approval are required before any legal admission; DM-0014
does not prevent continued technical preparation. No deployment, enforcement,
production DB change or production rollout is part of this block.
