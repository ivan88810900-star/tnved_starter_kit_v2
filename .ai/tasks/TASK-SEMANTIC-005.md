# TASK-SEMANTIC-005 — Whole-catalog Guided TN VED census

## Status

Completed — 2026-08-05

## Goal

Replace four-heading evidence with a strict, read-only whole-catalog integrity gate
and a separate usability baseline for the Canonical-backed Guided TN VED route.

## Context

The previous full-data gate made strong semantic assertions for `0302`, `0303`,
`5208` and `8517`, but those four headings represented only 328 active source code
nodes. For any other heading, the diagnostic could prove local response integrity
but did not census the complete Canonical catalog or quantify whether its first
question was usable.

This task adds catalog-wide evidence without inventing semantic-quality thresholds.
The correctness gate and the quality census are deliberately independent: incomplete,
fake, duplicate, unbound or mixed-snapshot codes fail the task; a large or mostly
direct choice set is reported for prioritization but does not silently redefine
product semantics.

Final review exposed a correctness gap hidden by the earlier census: topology-only
leaf marking labelled 382 childless semantic nodes as declarable even though their
Canonical anchors were non-leaf classification groups. The final gate therefore
checks Canonical role and parent evidence, not only reachability and counts.

## In scope

- Add `--all-headings` to the existing aggregate-only Guided diagnostic.
- Discover all four-digit headings from one loaded `CanonicalModel`, not a manual
  list or a second database query.
- Reuse that exact model for every Guided build and require one snapshot throughout.
- Gate every heading on complete reachability, 100% Canonical binding, exact
  Canonical declarable-leaf parity, preserved nearest code ancestry, zero fake or
  duplicate codes, zero `leaf_role_mismatch`, zero childless Canonical non-leaves,
  zero `canonical_parent_mismatch`, zero other critical issues and no degraded result.
- Preserve the strict hierarchy assertions for the four existing golden headings.
- Emit aggregate distributions for semantic coverage, choice counts, semantic depth,
  extraction diagnostics and latency.
- Emit only four-digit heading codes for problem and quality-outlier lists; do not
  export descriptions, choice titles or ten-digit commodity codes.
- Add self-contained discovery, aggregation, privacy and CLI regressions.
- Add a `0302350000` regression proving that the non-leaf remains a code branch,
  its two semantic subgroups remain usable and all four real declarable descendants
  stay reachable under their Canonical parent.

## Out of scope

- Arbitrary pass/fail thresholds for usability before a measured baseline exists.
- New endpoint/schema, frontend behavior, heuristic extraction policy or source-data
  mutation. The bounded runtime correction for Canonical leaf roles/parents and
  additive integrity counters are part of this task; existing JSON keys remain.
- Database/schema writes, migrations, feature-flag rollout or provider calls.
- LLM calls, embeddings or vector ingestion.
- Nomenclature aliases/history.

## Full-data result

The supplied compact Gate-2 export was opened in strict SQLite read-only mode. The
final run, after the separate terminal-L4 correctness repair, produced:

- **1,228 / 1,228 headings** with `status=OK` and complete integrity;
- **16,708 / 16,708 source-backed code nodes** reachable and Canonical-bound;
- **13,254 declarable leaves** and **3,454 non-leaf code branches**, with every
  leaf/branch role and nearest code parent matching Canonical;
- **0** fake codes, duplicate occurrences, critical issues, degraded headings or
  snapshot mismatches;
- one Canonical snapshot and all **4 / 4** golden hierarchy assertions green;
- **0** headings with an empty first step;
- semantic choices in **548 headings (44.6254%)**, covering **6,891 / 13,254
  declarable leaves (51.9919%)**;
- root-choice distribution p50/p95/max: **3 / 8 / 19**; the largest later step
  contains 50 choices, 47 of them direct code branches;
- per-heading build latency p50/p95/max in the recorded run:
  **0.246 / 2.034 / 125.077 ms**.

Latency is environment-dependent and is diagnostic only. The measured semantic
coverage is a baseline, not a claim that every heading already has a high-quality
exclusive question tree.

## QA

- Catalog diagnostic, terminal-L4, parser, Guided, semantic hierarchy and bridge
  selection: **48 passed**.
- Independent broad Canonical/semantic/API regression on an isolated full-schema
  database copy: **137 passed**.
- Full Gate-2 legacy-vs-Canonical audit: **18,211 / 18,211**, zero mismatch and
  unresolved paths, `gate2_ok=true`.
- Explicit four-heading compatibility gate: all four headings green on one snapshot.
- Report privacy regression and manual JSON inspection: aggregate metrics and
  four-digit heading codes only.
- `git diff --check` and Python compilation passed.

## Safety

No production database, schema, public API, feature-flag value, external model or
embedding index was changed. The supplied Gate-2 database was opened read-only.
