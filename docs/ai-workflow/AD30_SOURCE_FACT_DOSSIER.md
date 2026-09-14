# AD30 source-fact dossier for offline review

Status: implemented and author-tested, 14 September 2026. Independent A5 and
integrated CI acceptance are separate gates recorded by the integration task.
This implements a machine-readable input contract for the retained Decision
12 → 4 → 121 observations; it does not repeat acquisition or the prose review
candidate already published separately in PR #192.

## Contract and scope

`app.services.ad30_source_facts` exposes frozen, slotted `AD30SourceFacts`,
`AD30SourceFact` and `AD30RateRow` dataclasses. Fields contain strict immutable
primitives/tuples; `value_json` contains the canonical JSON serialization of the
exact value at an existing evidence record's JSON pointer. Structured source
observations remain JSON strings inside the immutable DTO, not mutable mappings.

- `load_ad30_source_facts(repository_root: Path | None = None)` checks the pinned
  canonical dossier SHA, three exact raw evidence-record SHAs and all 24 pointer
  values. Fixed resource paths and bounded regular-file reads reject missing,
  changed, oversized, symlink and FIFO inputs. The existing strict official JSON
  decoder rejects duplicate keys and non-finite/malformed values. No fallback
  supplies an empty list, zero rate or replacement evidence.
- `validate_ad30_source_facts(bundle)` checks exact DTO/primitive types and all
  fields against a fresh load of the pinned dossier. Copying its digest does not
  authorize changed rows, source metadata, producer details or approval flags.
  The result is a fresh canonical DTO, never the supplied instance.
- The fixed row IDs are `foshan_vinmay`, `guangdong_sumwin`, and
  `other_producers`. Exact printed names, addresses and rate strings are retained.
  `прочие` is a source row, not automatic producer eligibility. The printed rate
  strings remain `14,62` and `17,28`; this module does not parse or calculate them.

The canonical dossier SHA is
`f3f9722c1f67ec0ea4cc2fa6d495d54d0de981cb351d8aef71104ec6eb584894`.
The canonical serialization uses UTF-8, sorted JSON object keys, separators
`,`/`:`, unescaped Unicode, and no NaN values. Evidence-record SHA checks use
unaltered file bytes, including whitespace; their source and receipt identities
remain bound by those complete records. Changing a pinned dossier requires a
separately reviewed code/data change, not a caller-supplied hash.

Each fact includes its evidence file SHA/path, JSON pointer, original response
body SHA, official URL, known page/clause locator and observation kind. Unknown
page values are null; no synthetic PDF row locator is supplied. Facts `d12.product`,
`d4.*` summaries and relevant `d121.*` summaries are explicitly recorded visual
summaries, not literal Russian source quotations. The dimension fragments,
printed code list, producer rows and printed unit retain the existing exact
transcriptions. Quarantined portal cards remain separately labeled metadata
observations and cannot establish a legal effective interval.

## Integrity is separate from authority

`source_record_integrity_verified=true` means only that the pinned repository
records and their selected values match. `original_artifacts_verified=false` and
`source_text_verified=false` remain explicit: this loader neither replays the
retained PDF/receipt stores nor verifies scanned text against machine rows.
Decision 12/4/121 have no native text rows. A previous or current visual reading
is not represented as native-text verification or legal approval.

The fields `legal_review_verified`, `can_promote`, `production_ready`,
`active_rates_written` and `durable_legal_retention_attested` remain false.
There is no network acquisition, clock, DB/session dependency, product predicate,
date calculation, producer selection, public API or runtime application path.
A2 owns interpretation; A1 owns isolated illustrative arithmetic; A5 independently
checks both. This dossier grants none of those callers legal authority.

Known limits remain the complete amendment inventory, current/historical
nomenclature mapping, effective intervals, producer identity/succession, the
unavailable final investigation report, manifest-bound human review/separate
approval and retention/legal-hold attestation. Full legal coverage is partial.

## Validation performed by A3

From `customs-clear/backend`:

```text
python -m pytest tests/test_ad30_source_facts.py -q
44 passed in 0.14s
```

Cases include copied-hash row tampering, producer/address/unit/literal drift,
false provenance and approval claims, missing/reordered/duplicate/coerced DTO
fields, raw evidence whitespace drift, missing inputs, replaced dossier pins,
duplicate JSON keys, non-finite/recursive/oversized data, and symlink/FIFO inputs.
No application API changed, so this scope does not claim HTTP validation.

Separately, without downloading again, A3 rehashed the existing capture archives
34716176823 (1,093,658 bytes) and 34717159548 (655,764 bytes), and all 18 + 4 CAS
objects matched their filenames. All three saved Decision 12 render hashes matched
the existing evidence record; visual rereading confirmed dimensional fragments,
four printed codes, producer names/addresses and printed values. Both Decision 4
pages were visually compared as well. These supporting checks are not a new
runtime integrity grant, amendment completeness or legal applicability review.

No existing capture evidence, PR #192 document, application DB, flag or workflow
was modified by this source-only task.

## A5-AD30-SOURCE-LABEL-001 correction

A5 independently compared Decision 12 page 2 with the dossier. The retained
record's `printed_origin` field contains the nominative country label
`Китайская Народная Республика`, while the source clause prints the inflected
phrase `происходящих из Китайской Народной Республики`. The original dossier
mistakenly labeled that exact record value `recorded_visual_transcription`.

The dossier now labels `d12.origin` as `recorded_origin_label`; its value and
original evidence record remain unchanged. The canonical dossier SHA and module
pin above were updated together. A targeted regression rejects reintroducing the
transcription label even with the copied new digest. The same bounded author
suite now has 45 passing cases. This is a source-observation label correction,
not a new country applicability rule or legal interpretation.
