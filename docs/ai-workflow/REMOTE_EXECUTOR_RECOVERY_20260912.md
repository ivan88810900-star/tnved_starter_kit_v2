# Remote continuation after executor disconnect, 12 September 2026

Status: In progress. PR #187; issue #188 Option A remains binding.

## Confirmed remote state

The GitHub repository is exclusively `ivan88810900-star/tnved_starter_kit_v2`.
PR #187 now includes the independently checked source quarantine checkpoint
`22a7df5590a7442d943d89af285feb1228e80938`, mapped from local `63d7377`
with equal tree `97ab0dc91f96fef0089213bdd2a1a307a0c62e15`.
CI 34714034429 and 34714027008 passed. Main remains `9712c7b`;
base `feat/canonical-read-path` remains `a5a811e`. Draft PR #189 is separate.

The two previously rejected navigation responses are now retained in quarantine.
Capture 34714034422 deliberately remains failed: zero accepted originals and two
quarantined originals, no database creation, baseline acceptance or legal grant.
The archive and every object hash were verified and the archive retained beyond
temporary Actions storage. See
[evidence](evidence/official-rate-rejected-originals-20260912.json).

## Executor failure and recovery

The execution server disconnected. Read-only retries, including from the root
directory, returned transport-disconnected, recovery-timeout and environment-offline
errors. The queued root command to integrate agent commits failed to create its
process; it is not evidence of completed integration. Do not assume uncommitted
files or queued test-writing commands survived.

GitHub tools remained available, so work continues through GitData and isolated
Actions. Recovered patches use actual remote files and assertion-checked edits.
A new tree requires fresh CI and independent QA; earlier local test counts are
historical evidence only. No production/application DB or deployment is involved.

The shared no-positive-grant admission interface is published at `22473e172c042f08cd5b72aece5dd221c54bdc9d`.
The generic import/cache/decoder recovery checkpoint is
`062fcb90b85d33acec525e1d49f07d6c76ef8101` on `agent/admission-integration`.
Independent agent QA has a separate workflow with explicit per-branch test paths,
fresh temporary databases, no external LLM keys and all enforcement flags off.

## Ownership and pending work

| Role | Branch | Scope |
| --- | --- | --- |
| A0 lead | `agent/admission-integration` | Shared admission, generic imports, source API cache, integration, CI and state |
| A1 rates | `agent/rates-full` | Six ingestion services, payment diagnostics, TWS and rate/maintenance CLIs |
| A2 NTM | `agent/ntm-compliance` | Tamdoc candidates and legacy-v2 contextual read safeguards |
| A3 sources | `agent/source-registry` | Original/quarantined captures, explicit observed-source acquisitions and evidence |
| A4 classification/AI | `agent/classification-ai` | AI extraction admission, CLI safety and read-only diagnostic snapshots |
| A5 independent QA | `agent/qa-integration` | Adversarial tests, isolated integration and Actions verification |

A0 allocates disjoint files before editing. Three principal implementation tracks
run concurrently; a fourth is used only for independent files after ownership
review. A5 does not repair feature code to conceal a failing test.

Local checkpoints before disconnect, not automatically present remotely:
A0 `97ad963/29c5ad1`; A1 `db1f454/3a6114f/8e5ad92/61c8fe8`;
A2 `d620fff/b3b117a`; A3 `63d7377/6cfe571`;
A4 `6dd1971/631e6dd/685d522`; A5 `06e24df/bbabd49/fbf2e21`.
Inspect actual remote branch heads and local worktrees if they become available;
do not replay an already recovered patch or overwrite newer work.

Concrete unfinished checks include legacy-v2 date/direction/exclusion matching,
WAL/journal-safe optional CLI snapshots, the remaining maintenance entrypoints,
and acquisition of nine explicitly observed review-only source URLs. The original
four successful sources and the two quarantined navigation bodies are reused.

The full rates/NTM/source legal block remains incomplete: complete ETT note and
dependent-act interpretation, VAT/excise/remedy/origin applicability, durable legal
retention and manifest-bound human authorization are separate gates. DM-0014 does
not block technical preparation; AI QA is not human legal approval. No merge,
deployment, database rollout or enforcement activation is authorized here.
