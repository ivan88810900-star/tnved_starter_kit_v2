# Remote continuation after executor disconnect, 12 September 2026

Status: Recovered implementation independently checked and assembled for PR #187.
Final publication is gated by the assembled commit's Actions and A5 review.
Issue #188 Option A remains binding.

## Factual recovery

Repository: `ivan88810900-star/tnved_starter_kit_v2`.
Recovered PR head was `22a7df5590a7442d943d89af285feb1228e80938`;
base `feat/canonical-read-path` was `a5a811e618ffa001b39cb491bbbf7a9ceb93f9a7`;
main remained `9712c7b1380af7457fb6c89ef7710d8cda0e968b`.
PR #189 is a separate draft and contributes no changes here.
Read the live PR head and Actions before continuing; this recovery anchor is historical.

The disconnected executor did not complete its queued integration process.
Uncommitted files and old local test reports were not assumed recovered.
Actual GitHub files, GitData commits and isolated Actions reconstructed the work.
Later source-artifact materialization provisioned a usable executor, but the original
worktrees did not return. New archives were verified there; old unrelated working
directories were not modified. GitHub remains authoritative for the integrated code.

## Real roles and ownership

| Role | Isolated branch | Owned scope |
| --- | --- | --- |
| A0 lead | agent/admission-integration | Shared admission, generic imports, source API cache, integration, CI and state |
| A1 rates | agent/rates-full | Six apply services, diagnostics, rate/maintenance CLIs and payment arithmetic |
| A2 NTM | agent/ntm-compliance | Tamdoc candidates and contextual legacy NTM reads |
| A3 sources | agent/source-registry | Original/quarantine acquisition, bounded inspection and source evidence |
| A4 classification/AI | agent/classification-ai | AI admission and safe diagnostic snapshots |
| A5 independent QA | agent/qa-integration | Independent hostile, HTTP/integration tests and Actions review |

Ownership was fixed before parallel edits; A5 returned defects to owners.
After the disconnect, separate remote branches replaced unavailable worktrees.
Agent branches were not merged wholesale: A0 copied exact approved file blobs
onto its actual current tree, preserving unrelated work and shared interfaces.

## Integrated checkpoints

| Checkpoint | Evidence |
| --- | --- |
| Shared admission 22473e17; generic boundaries 062fcb90 | Preserved in later assembled candidates |
| Combined candidate 68530dce | CI 34715616460: backend 4,907 passed, 2 skipped, 2 warnings, 85 subtests; other gates passed |
| Maintenance/country/inspector candidate 772aff03 | CI 34716281013 and agent QA 34716281022 passed |
| A1 maintenance d66606f8 | Focused 34715920010: 1,105 passed; full CI 34715919970 passed |
| A1 A6 corrections f34c6cca / 7babea85 / 15d5dfc0 | Red 34716429404; green 34716718914: 1,273 passed; full CI 34716718892 passed |
| A2 final 7f396872 | Country and malformed-payload red/green evidence; 34716294137: 263 passed, 1 known skipped; full CI 34716294033 passed |
| A3 final a1ce31b2 | 34716832672: 161 passed; full CI 34716832650 passed |
| A4 code d0b52439 / docs b40145a3 | 65 author cases; independently checked safe reads and no admission |
| A5 combined d300f92e | 34716890248: 1,968 passed, 1 known skipped; full 34716890270: 5,113 passed, 2 known skipped; frontend 50 and other gates passed |

Subsequent final integration adds the two A6 regression files to the normal backend
CI profile and the disjoint A3 two-target inspection changes. Component counts
above are historical results on their named commits; exact final CI belongs to
the assembled commit/PR checks.

See [completed bounded task](TASK-RATE-ADMISSION-RECOVERY.md),
[independent evidence](evidence/payment-admission-independent-qa-20260912.json) and
[A6 classification](A6_PAYMENT_AUDIT_RECONCILIATION.md).

## Source preservation without acceptance

Prior successful originals and first quarantine capture 34714034422 were reused.
Capture nine (34716176823) retained 2 originals and 7 quarantined responses;
capture two (34717159548) retained Decision 12 PDF plus its quarantined card.
Acquisition failures remain visible, inspectors succeeded, and no baseline was
accepted. A0/A3 independently verified all original/receipt object hashes;
A5 additionally rehashed the second archive and independently reviewed the source pages.

- Nine-target archive: SHA d728387c458413b8bdd992a0ed330a8f45e7760ccacc77fc948958d44de3f6a7; 1,093,658 bytes; 18 CAS objects / 3,826,229 bytes.
- Two-target archive: SHA df8bc0fcc89780f53d6e29839e9b7a26835f2b19aa322fc6d4eb2b6546c5768e; 655,764 bytes; 4 CAS objects / 913,329 bytes.
- Exact durable backup identities are in the capture evidence. Backup restoration is not retention/legal-hold attestation.
- Native Decision 4/12 text was empty; separately recorded A3/A5 visual source observations do not fabricate machine-extracted text or approve business rules.

The full official legal block remains partial. The saved ETT dependency worklist,
amendment originals and four-code one-day candidate must not be rebuilt as a new
milestone. Continue formal source-bound applicability and review preparation.
No main merge, deployment, production/application DB write or enforcement activation.
