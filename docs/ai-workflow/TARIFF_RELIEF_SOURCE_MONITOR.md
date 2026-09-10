# Tariff relief and GSP source monitoring

The source registry includes nine exact official PDF targets captured on 10 September 2026:

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

The nine PDF entries add three distinct parent HTML URLs. Counts after this addition are 45 registered sources and policies, and 62 monitor URLs: 45 in legal-drift mode, nine in structured-freshness mode and eight in availability mode. HTML pages do not establish PDF revision coverage.

## Replacement links and unresolved legal interpretation

An unchanged historical PDF URL cannot reveal that a landing page now points to a replacement. The companion bounded relief-capture/reconciliation step in the daily workflow compares the PDFs currently linked by the two fixed EEC landing pages, together with the explicitly selected legal-portal card, against the captured observation inventory. New, removed, replaced or changed PDFs require review. Parent HTML timestamps alone are not document drift. The retained current HTML/PDF objects establish what was observed; they do not approve it.

An unchanged, complete graph gives `operational_ok=true` and CLI exit 0 while `review_required=true` and all legal/activation flags remain false. A changed graph gives exit 3; invalid evidence or capture failure gives exit 2. First-time missing observations do not pass the comparison. This separation prevents unapproved but unchanged observation pins from making the operational gate permanently fail. The notifier continues to show the review status. Archive creation must also succeed; a nonempty partial archive cannot satisfy the final gate.

The workflow implementation is published in Draft PR #187. This PR has not been merged or deployed, so the changed schedule must not be described as already active on the default branch. A live isolated capture ran successfully in Actions run 34482224480; all 12 retained originals were then replayed locally against the observation manifest, with no new, missing or changed PDF sources.

Both pages of the original Decision 72 were visually reviewed: adoption is 30 January 2026. Its retained portal metadata gives publication on 7 August and entry into force on 17 August 2026. Decision 130's operative paragraph 7.1.95 and Decision 728's amendment header agree with that adoption date; the contrary 9 July date in Decision 130's introductory amendment header remains recorded as an editorial inconsistency. Decision 130's header and filename also disagree concerning Decision 77. The later Decision 80 amendment and complete exemption eligibility remain unverified. These findings do not alter retained bytes, update country coefficients or apply an exemption.

Targeted checks: `tests/test_tariff_relief_source_monitor.py` verifies source/observation binding, complete daily policy registration, absence from automatic import adapters, and pending-state preservation for first and changed observations of all nine PDFs. Existing monitor and policy regressions remain applicable.
