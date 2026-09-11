# Tariff relief and GSP source monitoring

The original observation inventory contains nine exact official PDF targets captured on 10 September 2026:

| Source ID | Document role |
| --- | --- |
| `eec_tariff_relief_130` | Consolidated Customs Union Commission Decision 130 |
| `eec_tariff_relief_728` | Consolidated Customs Union Commission Decision 728 |
| `eec_gsp_conditions_47` | Conditions for applying the common preference system |
| `eec_gsp_beneficiary_countries` | Developing and least-developed beneficiary-country lists |
| `eec_gsp_preferential_goods` | Preferential goods, descriptions and exclusions |
| `eec_gsp_origin_60` | Origin, supporting evidence, transport and administrative cooperation |
| `eec_gsp_treaty_article36` | Official treaty extract describing conditional preference levels |
| `eec_gsp_authorized_issuers` | Reference list of authorized certificate issuers |
| `eec_tariff_relief_council72_2026` | Individual PDF attached to legal-portal card 461/10843 |

`customs-clear/backend/data/ett_tariff_relief_source_observations.json` records the exact retrieved URL, final URL, PDF SHA-256, byte size, retrieval time and parent-page evidence for each target. Its source capture report SHA-256 is `afc55fd41c2bea027e2cb8c39d9c26ca90b7ad8731dfb8876a995d36232db396`.

These are captured observations, **not accepted checksum baselines or legal approval**. The manifest sets `is_accepted_monitor_baseline`, `is_legal_approval`, `can_promote` and `active_rates_written` to false. It is deliberately not registered as a locally loaded legal document and does not make the legal-coverage report complete.

## Existing daily check

Every entry uses `monitor_only`, daily cadence and a 48-hour freshness contract. `scripts/monitor_official_ntm_sources.py` obtains their exact PDF URLs from `RegulatorySourceEntry.monitor_urls`; the existing `scheduled-data-refresh.yml` workflow runs that monitor at 03:17 UTC. No automatic import adapter or writable tariff table is assigned to these sources.

A first PDF observation and a changed PDF SHA remain pending until the existing, separate checksum-review procedure accepts the exact digest. The captured observation manifest does not bypass that procedure. Acceptance of a monitoring baseline is only change-detection bookkeeping; it does not establish legal applicability or approve a production rate.

At the 10 September baseline, the nine PDF entries added three distinct parent HTML URLs: 45 registered sources and policies, and 62 monitor URLs (45 legal-drift, nine structured-freshness and eight availability). The current 48/48/68 counts after the Council supplement are detailed below. HTML pages do not establish PDF revision coverage.

## Replacement links and unresolved legal interpretation

An unchanged historical PDF URL cannot reveal that a landing page now points to a replacement. The companion bounded relief-capture/reconciliation step in the daily workflow compares the PDFs currently linked by the two fixed EEC landing pages, together with the explicitly selected legal-portal card, against the captured observation inventory. New, removed, replaced or changed PDFs require review. Parent HTML timestamps alone are not document drift. The retained current HTML/PDF objects establish what was observed; they do not approve it.

An unchanged, complete graph gives `operational_ok=true` and CLI exit 0 while `review_required=true` and all legal/activation flags remain false. A changed graph gives exit 3; invalid evidence or capture failure gives exit 2. First-time missing observations do not pass the comparison. This separation prevents unapproved but unchanged observation pins from making the operational gate permanently fail. The notifier continues to show the review status. Archive creation must also succeed; a nonempty partial archive cannot satisfy the final gate.

The workflow implementation is published in Draft PR #187. This PR has not been merged or deployed, so the changed schedule must not be described as already active on the default branch. A live isolated capture ran successfully in Actions run 34482224480; all 12 retained originals were then replayed locally against the observation manifest, with no new, missing or changed PDF sources.

Both pages of the original Decision 72 were visually reviewed: adoption is 30 January 2026. Its retained portal metadata gives publication on 7 August and entry into force on 17 August 2026. Decision 130's operative paragraph 7.1.95 and Decision 728's amendment header agree with that adoption date; the contrary 9 July date in Decision 130's introductory amendment header remains recorded as an editorial inconsistency. Decision 130's header and filename also disagree concerning Decision 77. At this original baseline, the later Decision 80 amendment had not been inspected; the subsequent recovery below reads its primary PDF. Complete exemption eligibility remains unverified. These findings do not alter retained bytes, update country coefficients or apply an exemption.

Targeted checks: `tests/test_tariff_relief_source_monitor.py` verifies source/observation binding, complete daily policy registration, absence from automatic import adapters, and pending-state preservation for first and changed PDF observations. Existing monitor and policy regressions remain applicable.

## Recovered Council source slice, 11 September 2026

The already-published `177da64` commit on `ops/ett-council-list-capture` is a direct
child of the recovery baseline `a5c884d3`. It is reused unchanged, not reimplemented.
[Capture run 34584814626](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/34584814626)
and its [CI run 34584814418](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/34584814418)
completed successfully. The capture discovers the year-list URL through a retained
return-to-list anchor on the already observed Council 72 card; all later document
URLs come from actual retained list rows. It does not generate document IDs, infer
missing pages, run page JavaScript or assert completeness of the legal inventory.

The archive SHA is `b688049d28355e91305d8b798999703f812d8a2f21f3f89d69bf7ba95da2c13f`.
Recovery verified all 18 objects / 7,183,746 bytes, replayed the list except for its
execution clock, and replayed the complete originals HTML-to-PDF graph offline.
Original retrieval timestamps remain unchanged. The archive was saved separately
from temporary Actions retention; this is recovery persistence, not an Object Lock
or legal-hold attestation. Detailed hashes, page observations and open limits are
in [the recovery evidence](evidence/ett-council-originals-20260911.json).

| Selected primary source | Pages visually inspected | Conditions that must not be lost |
| --- | --- | --- |
| [Council 75 of 9 July 2026](https://docs.eaeunion.org/documents/461/10846/) | 1–3 | `8112929101`, Kazakhstan, stated use, separate 450-tonne periods, authority documents, registration dates and use/disposal restrictions |
| [Council 77 of 9 July 2026](https://docs.eaeunion.org/documents/461/10848/) | 1–2 | `8433533000`, Belarus/Russia caps of 15/155 units, authority documents, registration window, and retroactive relationship scope distinct from commencement |
| [Council 80 of 9 July 2026](https://docs.eaeunion.org/documents/461/10854/) | 1–2 | Changes paragraph 15 of the Decision 728 procedure; does not cancel conditions imposed by individual exemptions; distinct from Council 80/2021 |

Both 75 and 77 condition commencement on the amendment to procedure paragraph 15.
The observed portal dates are not independently attested publication events; this
source-reading slice does not approve normalized effective dates. In particular,
the wording about relationships from 1 July in 77 must not be collapsed into an
unconditional `valid_from` date. A shipment being below a numeric cap does not
prove an available aggregate quota. These findings do not update exemptions,
country coefficients, payment results or NTM applicability.

Russian and Kazakh DOCX links remain observed but uninspected. Full legal review,
subsequent-change checks and permanent retention are still required. The current
full rates-and-sources block remains incomplete; the seven-page inspection is
not a claim of full ETT, VAT, excise, trade-defence or origin-rule coverage.

### Monitor integration and retained observation identity

The three new exact PDFs are registered as
`eec_tariff_relief_council75_2026`, `eec_tariff_relief_council77_2026` and
`eec_tariff_relief_council80_2026`: daily `monitor_only`, 48-hour freshness,
manual review, no apply adapter and no loaded legal-document claim.
The resulting registry has 48 sources and 48 policies; the monitor has 68 URLs
(51 legal-drift, nine structured-freshness and eight availability targets).
This describes the feature-branch implementation, not an active main schedule.

The original nine-source observation file remains byte-for-byte unchanged, SHA
`6972606d59d94aedec7e4b22d8cd39c11ad5b3da80a0e63bba9335faeb003b1d`.
The separate `data/ett_tariff_relief_council_source_observations.json` adds three
pins bound to capture report `5100837b60cf40857ab88da2fcf94f150cb5232c531365ea435f1d8c034746d3`.
Decision 72 keeps its earlier capture provenance; it is not relabeled as part of
the new eleven-PDF capture. The two manifests are unapproved observation sets,
not accepted checksum baselines or legal decisions.

The capture CLI accepts repeatable `--observed-baseline` arguments, validates
every file and rejects overlapping IDs/URLs or excess input before fetching.
Reconciliation preserves each input SHA separately instead of inventing a single
source-capture SHA for the union. Both capture workflows retain the existing 72
detail page and explicitly add the observed 75/77/80 pages. Any missing or changed
PDF remains review-required; an unchanged graph never approves legal applicability.

### Verification boundary

On the final source-monitor working tree, the exact backend suite selected in
`.github/workflows/ci.yml` passed locally: **3,228 passed, two dependency warnings**.
The source-focused and adjacent checks also passed (263 tests). The scheduled
workflow validator passed (7 actions, 13 bash blocks, 4 Python heredocs, 1 JavaScript
block). A fresh Uvicorn process in read-only mode passed health, real cookie login,
registry and update-plan HTTP checks: 48 entries, all four Council sources,
no automatic enforcement. Its disposable SQLite file retained the same SHA.

This is not a claim that every test in the repository passes. A delegated run
outside the controlled CI verification returned 4,657 passed / 130 failed / two
skipped, including missing admin-token/data-fixture and older expected-value
failures. Its command/collection provenance was inconsistent and no clean-baseline
comparison was made, so neither causation nor pre-existence of those failures is
established. Do not reclassify that run as green or as a full-data acceptance gate.
The test-written preview-cache revision was restored to its exact original bytes.
