# AD30 Decision 12 → Decision 4 → Decision 121: source-fact review candidate

Status: **BOUNDED SOURCE-FACT CANDIDATE — NOT ADMITTED**

Repository base: `1c0272a34cbcbb3b99d6f32c86d86949bc0adc06`

Evidence observation date: `2026-09-12`

## Boundary

This candidate organizes facts already recorded in tracked evidence. It does not
fetch or reinterpret source bytes. It is not a legal-applicability decision, a
rate-admission record, a historical-code mapping, or an authorization to promote,
write production data, enable enforcement, or change a feature flag. A capture
status such as `original_retained` is reported only as the value stored in the
evidence JSON; permanent object versioning, retention and legal-hold attestation
remain unmet.

> **Blocking limitation:** the tracked evidence explicitly says that the complete
> amendment/history inventory beyond the three named acts has not been
> established. The linked AD30R1 final report was not captured as a valid PDF.
> Therefore this candidate makes no completeness or current-applicability claim,
> and none of its printed amounts may be used as an active rule.

The evidence inputs are:

- [`eec-ad30-decision12-capture-review-20260912.json`](evidence/eec-ad30-decision12-capture-review-20260912.json)
- [`eec-ad30-decision4-notice-review-20260912.json`](evidence/eec-ad30-decision4-notice-review-20260912.json)
- [`eec-ad30-source-discovery-20260912.json`](evidence/eec-ad30-source-discovery-20260912.json)
- [`eec-ad30-acquisition-plan-20260912.json`](evidence/eec-ad30-acquisition-plan-20260912.json)
- [`eec-ad30-capture-34716176823.json`](evidence/eec-ad30-capture-34716176823.json)

The acquisition plan describes its exact nine-target selection as not yet run.
The later capture record binds the actual nine-target run `34716176823`; the
Decision 12 evidence binds the separate two-target run `34717159548`. These
records must not be collapsed into one successful acquisition: both capture
records report a failed capture/acquisition step and a successful inspection
step, while also reporting all selected response bodies retained and no active
rate write.

## Machine-checkable evidence bindings

Every value below is copied from the named JSON pointer. `capture_status` is a
recorded field, not an independent retention or admissibility conclusion.

| ID | Object | Evidence JSON pointer | Run | Body SHA-256 | Receipt SHA-256 | Recorded status |
|---|---|---|---:|---|---|---|
| `AD30-D12-PDF` | Decision 12 PDF | `eec-ad30-decision12-capture-review-20260912.json#/capture/sources/1` | `34717159548` | `1d6936be2b492b2976e03b3558c55c36062a89dc612ffe54f7e54af49a372c4b` | `75b91c72da6a9a11e1e7d3a704747188a0c911a1f5348aedf2c658cb24a8a866` | `original_retained` |
| `AD30-D12-CARD` | Decision 12 card | `eec-ad30-decision12-capture-review-20260912.json#/capture/sources/0` | `34717159548` | `1ff8131e8e781f6d28b4985afbfc94d9e1330fc7e924b7439192d19a3be13655` | `618eedd2deaf306b13ad1a25b498832f9400df7aa4fc7843aa36879242ccbc55` | `quarantined_content_rejected` |
| `AD30-D4-PDF` | Decision 4 PDF | `eec-ad30-capture-34716176823.json#/sources/3` | `34716176823` | `44a277edf5f9bf76a0ccd79d6e41f9820548fcbaa1b638d1cd44469a79344aef` | `bfc2c3e618f5023ec2ce46252718fb4638d3b1a8c385d723cd023e6521220dfe` | `original_retained` |
| `AD30-D4-CARD` | Decision 4 card | `eec-ad30-capture-34716176823.json#/sources/2` | `34716176823` | `fcca5c74fba82a82427fd6c45eb305cc5c7ee9769ccb35356789cc8ca5c17169` | `185c14d637681de8fa065ba868d218828c1646247ce48f5e711f6d62403fece1` | `quarantined_content_rejected` |
| `AD30-D121-PDF` | Decision 121 PDF | `eec-ad30-source-discovery-20260912.json#/retained_original_reused` | `34600642623` | `56ffd2701fc5e0d85a2d02e1e9219c35a5ba4c59610aebe8d9f64eb496ce2e4c` | `95f085ef2d262a5d3c107da18089c86969f38c8650458dffad912da3004d4819` | retained original reused; no capture-status field at this pointer |
| `AD30-D121-CARD` | Decision 121 card | `eec-ad30-capture-34716176823.json#/sources/1` | `34716176823` | `c9acebc19e2af89b9b90b65e37675a1d1b1aafcb3518e6e83a7d5f5bef03fdba` | `30d6a0c95f787dd4aa270235f13d71ca281931e5631d6314358d20bf3289c8c3` | `quarantined_content_rejected` |
| `AD30-NOTICE-PDF` | AD30R1 completion notice | `eec-ad30-capture-34716176823.json#/sources/0` | `34716176823` | `db9177ce8da5061afef33e17c7e11dc2fbc23d7b8cec08ffcf3d29f3e8f601c9` | `e1f44b777ce6f0bed42aef63e796a395e6b2e84861e3adedd4a9c541ba1873ef` | `original_retained` |
| `AD30-FINAL-REPORT-ENDPOINT` | purported AD30R1 final-report response | `eec-ad30-capture-34716176823.json#/sources/4` | `34716176823` | `b42e98ffdaec05fc5fb8c5240d126b145b96bcf1ae986381f15386e1bac3b293` | `d629a8b6bba5abbe318492ad0207f9cc192a607f0a1699d4fa5acf7858513a87` | `quarantined_content_rejected`; `invalid_pdf_content` |

Capture artifact bindings recorded by the evidence:

| Run | Job | Capture commit | Input report SHA-256 | Archive artifact / filename / size | Archive SHA-256 | Recorded step result |
|---:|---:|---|---|---|---|---|
| `34717159548` | `103616352628` | `a1ce31b25c9dc03793804a98962b0804ecbf2158` | `cb3eef3766347d0b039461d65c7ef5d2b3ab708cfeb259d232b0d27cc8c70baf` | `10305550676` / `official-rate-originals-34717159548.zip` / `655764` bytes | `df8bc0fcc89780f53d6e29839e9b7a26835f2b19aa322fc6d4eb2b6546c5768e` | capture `failure`; inspection `success` |
| `34716176823` | `103613710651` | `4ee35fcb1214252a1fec236dbe8b50d34a961688` | `a7f6d0fb490624ed2e79dff6d85f5e40f27d5763e1bc0153e2c0f8620f6bba0d` | `10304930968` / `official-rate-originals-34716176823.zip` / `1093658` bytes | `d728387c458413b8bdd992a0ed330a8f45e7760ccacc77fc948958d44de3f6a7` | acquisition `failure`; inspection `success` |

## Source observations

### Decision 12 of 9 February 2021

The retained three-page PDF has body SHA-256 `1d6936be…a372c4b`.
Its pages have no native text layer; the evidence reports a visual reading by A3
and an independent visual reading by A5, without OCR. The following items are
transcriptions/observations from that evidence, not admitted rules:

- The printed issuing body is `Коллегия Евразийской экономической комиссии`,
  the printed number is `12`, and the printed date is `09 февраля 2021 г.`.
- Clause 1 describes welded tubes, pipes and hollow profiles of
  corrosion-resistant (stainless) steel, originating in
  `Китайская Народная Республика` and imported into the EAEU customs territory.
  It prints these dimensional fragments:
  - page 1: `с толщиной стенки от 0,4 до 6 мм включительно`;
  - page 1: `круглого поперечного сечения с наружным диаметром от 6 до 115 мм включительно`;
  - page 1: `квадратного поперечного сечения с периметром поперечного сечения не более 400 мм`;
  - page 2: `прямоугольного поперечного сечения с периметром поперечного сечения не более 400 мм и наибольшим размером стороны сечения до 120 мм включительно`.
- Page 2 prints codes `7306 40 200 9`, `7306 40 800 1`,
  `7306 40 800 8`, and `7306 61 100 9`. Clause 2 also prints
  `руководствуясь как кодами ТН ВЭД ЕАЭС, так и наименованием товара`.
  The evidence explicitly does not establish a historical mapping or code-only
  applicability.
- Clause 1 prints `установив срок действия данной антидемпинговой меры 5 лет`.
  Clause 3 says entry into force occurs after 30 calendar days from official
  publication. The evidence does not compute an absolute interval from either
  statement.
- The page 3 annex heading is `РАЗМЕРЫ СТАВОК антидемпинговой пошлины`; its
  printed unit is `процентов от таможенной стоимости`. Its rows are recorded as:

| Row | Printed producer | Printed address | Printed rate text |
|---:|---|---|---:|
| 1 | `Foshan Vinmay Stainless Steel Co., Ltd.` | `No. 6 Jingang Avenue, Baini Town, Sanshui District, Foshan City, Guangdong Province, China` | `14,62` |
| 2 | `Guangdong Sumwin New Material Group Co., Ltd.` | `South Sanhe Rd., East Renhe Rd., Yanhe Town, Gaoming District, Foshan, China` | `17,28` |
| 3 | `прочие` | no address printed | `17,28` |

The evidence does not verify producer identity/succession and creates no numeric
business rule. The card body is quarantined, but its recorded printed metadata is
adoption `09.02.2021`, publication `12.02.2021`, and effective date
`14.03.2021`. These are portal-field observations, not a verified legal interval.

### Decision 4 of 20 January 2026

The retained two-page PDF has body SHA-256 `44a277ed…344aef`. Its native text
layer is empty; the evidence records an A3 visual reading independently compared
by A5.

- Clause 1 prints an extension of the measure established by Decision 12 through
  `12 November 2026` inclusive; the recorded short literal excerpt is
  `Продлить по 12 ноября 2026 г. включительно`.
- Clause 2 refers, from entry into force of Decision 4 through that date, to
  collection at the rates established by Decision 12 under the procedure for
  collecting provisional anti-dumping duties. Decision 4 itself prints no
  numeric rate value.
- Clause 3 says entry into force is after 30 calendar days from official
  publication, but not earlier than `14 March 2026`; the recorded short literal
  excerpt is `но не ранее 14 марта 2026 г.`. The evidence does not compute the
  absolute effective date.
- The quarantined card's recorded printed metadata is adoption `20.01.2026`,
  publication `23.01.2026`, and effective date `14.03.2026`. These are
  portal-field observations, not a verified legal interval.

### Decision 121 of 8 September 2026 and completion notice

The reused retained Decision 121 PDF has body SHA-256 `56ffd270…ce2e4c` and two
pages with no native text. The bounded source-discovery evidence records:

- clause 1: extension of the measure established by Decision 12 through
  `7 September 2031` inclusive;
- clause 2: reference to the duty amounts in Decision 12 and crediting amounts
  paid or collected under Decision 4; it prints neither a numeric rate table nor
  a commodity-code list;
- clause 3: Decision 4 is declared no longer in force;
- clause 4: entry into force after 30 calendar days from official publication;
  the evidence records the literal text
  `Настоящее Решение вступает в силу по истечении 30 календарных дней с даты его официального опубликования.`;
  no absolute effective date is interpreted.

The quarantined Decision 121 card's recorded printed metadata is adoption
`08.09.2026` and publication `10.09.2026`; the evidence records no effective-date
field.

The one-page completion notice has body SHA-256 `db9177ce…f601c9`, printed
publication date `10 September 2026`, and printed identifier
`2026/512/AD30R1`. It says the repeated investigation completed on
`8 September 2026` and identifies a decision adopted that day extending the
measure through `7 September 2031`. The evidence expressly does not treat the
investigation completion date as an effective-from date. The notice links the
Decision 121 card and the final-report endpoint; the latter returned a 4,642-byte
HTML response recorded as `invalid_pdf_content`, so its report content is not
available in this evidence set.

## Proposed interpretations for review — not facts or decisions

The following are questions/hypotheses for the named reviewers. None is adopted:

1. **Chain hypothesis:** Decision 12 may supply the product description, printed
   codes and producer rows, while Decision 4 and Decision 121 may affect temporal
   treatment. A2 must establish whether that reading is legally sound and whether
   intervening amendments alter any element.
2. **Conjunctive scope hypothesis:** Decision 12's clause 2 may require assessment
   of both nomenclature code and product name/characteristics. A2 must not reduce
   this to a four-code match; A1 must not calculate from code alone.
3. **Date hypothesis:** portal metadata and the printed publication-plus-30-day
   clauses appear capable of producing dates, but the legal interval, boundary
   inclusivity, transition from Decision 4, and effect of Decision 121 require a
   separately documented interpretation. This candidate intentionally performs
   no date arithmetic.
4. **Producer hypothesis:** the two named rows and `прочие` row could be relevant
   only after exact legal-entity identity, succession/name-change handling, and
   the complete amendment inventory are verified.

## Unresolved items and stop conditions

| Area | Unresolved evidence/review | Required disposition before any admission |
|---|---|---|
| Amendments/history | No complete amendment/history audit beyond Decisions 12, 4 and 121 | A3 inventories official amending/repealing acts and binds source objects; A2 reviews the complete chain; A5 independently checks it |
| Final investigation report | Endpoint returned quarantined HTML (`invalid_pdf_content`); report body unavailable | Acquire and verify the actual official report or record why it is not required, subject to A2/A5 review |
| Dates | Printed clauses and portal fields are recorded, but legal effective intervals are not established | A2 documents publication authority, date arithmetic, inclusivity and transition semantics; A5 reproduces independently |
| Nomenclature | Four codes are printed in a 2021 act; historical/current mapping is unverified | Canonical nomenclature evidence and date-bound mapping must be reviewed separately; no silent normalization |
| Product scope | Product and dimensional text is observed, but current applicability is unverified | A2 creates a source-faithful product test only after amendment/date review; code-only matching remains insufficient |
| Producer identity | Printed names/addresses exist; identity, succession and name changes are unverified | Verify legal identity and amendments before any producer-specific selection |
| Amounts | `14,62` and `17,28` are printed with a percent-of-customs-value heading; no rule admitted | A1 may model only after A2 approval and separate admission authority; preserve source text and uncertainty until then |
| Authority | `legal_review_verified=false`, `can_promote=false`, `production_ready=false` in source evidence | Manifest-bound human review/separate approval remains required under the project decisions |
| Object governance | Permanent versioning, retention and legal-hold attestation are unmet | Resolve as a separate gate; this document does not attest retention |

Any missing official act, contradictory date, changed producer identity, changed
product wording, or nomenclature mismatch is a fail-closed stop, not permission to
reuse a legacy/AI/admin value.

## Reviewer handoff checklist

### A1 — rates/payments

- [ ] Treat all printed numbers as non-admitted observations.
- [ ] Do not create an active rate, payable amount, VAT-base component, fallback,
      or code-only match from this candidate.
- [ ] If A2 later provides an approved applicability record, bind calculations to
      the exact source/version, interval, product conditions and verified producer
      identity; preserve provisional versus confirmed amounts.
- [ ] Add boundary tests for every approved interval and producer/default branch,
      including unresolved identity and missing-fact fail-closed paths.

### A2 — NTM/compliance and formal applicability

- [ ] Establish the complete relevant amendment/repeal inventory; do not assume
      the three retained acts are complete.
- [ ] Reconcile printed clauses with authoritative publication metadata and record
      date arithmetic, inclusivity and transition treatment explicitly.
- [ ] Review product text, all four dimensional conditions, origin, joint
      code/name instruction and any exclusions as a unit.
- [ ] Verify current/historical nomenclature and producer identity/succession
      without delegating those conclusions to A1 or the source-fact reader.
- [ ] Keep any result non-activating until the required manifest-bound authority
      and separate admission approval exist.

### A5 — independent QA

- [ ] Rehash/replay the exact bodies and receipts from the two bound capture runs
      and the separately reused Decision 121 object; verify archive and input-report
      hashes without accepting capture labels at face value.
- [ ] Independently compare all PDF pages with the product/dimension/code/producer/
      rate/date observations, including the empty native-text limitation.
- [ ] Confirm the final-report response is not treated as a valid report and the
      quarantined cards are used only for bounded metadata observations.
- [ ] Challenge the amendment inventory, temporal interpretation, nomenclature
      mapping and producer identity independently before approving any later
      candidate HEAD.
- [ ] Verify no DB, flag, enforcement, promotion or production path changed.

## Local documentation validation

Validation is repository-local and source-fact only. No network or application
test is claimed. Run this replay command from the repository root on the committed
candidate. It binds the comparison to the exact assigned base and the checked-out
candidate `HEAD`, requires a clean worktree, and emits no `PASS` line until every
assertion and the complete `base..HEAD` diff check has succeeded.

```bash
set -euo pipefail
base=1c0272a34cbcbb3b99d6f32c86d86949bc0adc06
candidate="$(git rev-parse HEAD^{commit})"
report=docs/ai-workflow/AD30_CHAIN_REVIEW_CANDIDATE.md

test "$(git rev-parse "$base^{commit}")" = "$base"
test "$candidate" != "$base"
test "$(git merge-base "$base" "$candidate")" = "$base"
changed_output="$(git diff --name-only "$base..$candidate")"
mapfile -t changed <<<"$changed_output"
test "${#changed[@]}" -eq 1
test "${changed[0]}" = "$report"
test -z "$(git status --porcelain)"

refs=(
  evidence/eec-ad30-decision12-capture-review-20260912.json
  evidence/eec-ad30-decision4-notice-review-20260912.json
  evidence/eec-ad30-source-discovery-20260912.json
  evidence/eec-ad30-acquisition-plan-20260912.json
  evidence/eec-ad30-capture-34716176823.json
)
test "${#refs[@]}" -eq 5
for ref in "${refs[@]}"; do
  test -f "docs/ai-workflow/$ref"
done

candidate_body="$(sed '/^## Local documentation validation$/,$d' "$report")"
bindings_output="$(
  jq -r '(.capture.run_id,.capture.job_id,.capture.commit_sha,.capture.input_report_sha256,.archive.artifact_id,.archive.filename,.archive.size_bytes,.archive.sha256),(.capture.sources[]|.body_sha256,.receipt_sha256)' docs/ai-workflow/evidence/eec-ad30-decision12-capture-review-20260912.json &&
  jq -r '(.capture.run_id,.capture.job_id,.capture.commit_sha,.capture.input_report_sha256,.archive.artifact_id,.archive.filename,.archive.size_bytes,.archive.sha256),(.sources[0,1,2,3,4]|.body_sha256,.receipt_sha256)' docs/ai-workflow/evidence/eec-ad30-capture-34716176823.json &&
  jq -r '.retained_original_reused.capture_run_id,.retained_original_reused.sha256,.retained_original_reused.receipt_sha256' docs/ai-workflow/evidence/eec-ad30-source-discovery-20260912.json
)"
mapfile -t bindings <<<"$bindings_output"
test "${#bindings[@]}" -eq 33
for value in "${bindings[@]}"; do
  rg -Fq -- "$value" <<<"$candidate_body"
done

source_literals_output="$(
  jq -r '.document_observations.product_text_basis.printed_condition_fragments[].text,.document_observations.product_text_basis.printed_origin,.document_observations.codes_printed.values[],.document_observations.duration_printed.text,.document_observations.joint_code_and_description_requirement.text,.document_observations.annex.rate_column_unit_printed, (.document_observations.annex.producer_rows[] | .producer_name_printed,.producer_address_printed,.rate_text_printed | select(. != null))' docs/ai-workflow/evidence/eec-ad30-decision12-capture-review-20260912.json &&
  jq -r '.documents[0].observations[1].short_literal_excerpt,.documents[0].observations[3].short_literal_excerpt' docs/ai-workflow/evidence/eec-ad30-decision4-notice-review-20260912.json &&
  jq -r '.retained_original_reused.literal_content_observations[3].quote' docs/ai-workflow/evidence/eec-ad30-source-discovery-20260912.json
)"
mapfile -t source_literals <<<"$source_literals_output"
test "${#source_literals[@]}" -eq 23
for value in "${source_literals[@]}"; do
  rg -Fq -- "$value" <<<"$candidate_body"
done

dates=(09.02.2021 12.02.2021 14.03.2021 20.01.2026 23.01.2026 14.03.2026 08.09.2026 10.09.2026)
test "${#dates[@]}" -eq 8
for date in "${dates[@]}"; do
  rg -Fq -- "$date" docs/ai-workflow/evidence/eec-ad30-decision12-capture-review-20260912.json
  rg -Fq -- "$date" <<<"$candidate_body"
done

git diff --check "$base..$candidate"

printf 'candidate-scope: PASS (1 file; exact base..HEAD; clean worktree)\n'
printf 'referenced-paths: PASS (%d/%d exist)\n' "${#refs[@]}" "${#refs[@]}"
printf 'hash-run-binding-literals: PASS (%d/%d found)\n' "${#bindings[@]}" "${#bindings[@]}"
printf 'codes-product-producer-rate-clause-literals: PASS (%d/%d found)\n' "${#source_literals[@]}" "${#source_literals[@]}"
printf 'card-date-literals: PASS (8/8 found in evidence and candidate body)\n'
printf 'base-to-head-diff-check: PASS\n'
```

Recorded result on the committed candidate:

```text
Exit: 0
Output:
candidate-scope: PASS (1 file; exact base..HEAD; clean worktree)
referenced-paths: PASS (5/5 exist)
hash-run-binding-literals: PASS (33/33 found)
codes-product-producer-rate-clause-literals: PASS (23/23 found)
card-date-literals: PASS (8/8 found in evidence and candidate body)
base-to-head-diff-check: PASS
```
