# QA Report: TASK-SEMANTIC-003

> Date: 2026-07-29
> Environment: user Gate-2 export with 17,809 commodity rows
> Full-data status: approved

## Input integrity

- Archive SHA-256:
  `7a6e93ec298042ef97b6e08db2231651154f8ea2e84d5de597146858eeb44dfe`.
- Extracted DB SHA-256:
  `b3ece86c68b5010486ec64cce102759673ddc585e634e5698be596d22a8d8d2b`.
- Rows: 21 sections, 96 chapters, 17,809 commodities, 3,258 structural
  `hs_rates` keys.
- The archive was produced by the pre-`7f38de3` exporter and therefore lacked
  the later-required `hs_prefix` column. The original archive and extracted DB
  were not modified. A separate temporary compatibility copy added
  `hs_prefix = hs_code`, which preserves the exact structural leaf semantics
  of this legacy export. Current exporter code and its contract test already
  include `hs_prefix`.
- The original extracted DB retained the same SHA-256 after all checks.

## Defects found and corrected

1. Official dash depth was incorrectly compared with the number of semantic UI
   levels. Real depth-3/4 headers could never become a second-level semantic
   choice.
2. An active text parent could absorb a later neighbouring tariff range. A
   code-scope guard now requires the child source to remain inside the parent's
   official odd-level prefix range.
3. A narrow trailing group could retain following sibling codes. Out-of-scope
   children are detached and returned to the safe parent/root level.
4. Repeated same-title subgroups under one parent are merged with source
   variants retained in metadata, so `5208` no longer shows duplicate
   “полотняного переплетения” choices.
5. The tuna UX-load check counted every deep canonical descendant rather than
   the direct choices on the current screen. It now measures direct code
   choices; deep completeness remains independently gated by expected,
   reachable and Canonical coverage.

## Commands and results

### Self-contained hierarchy and Guided API

```bash
cd customs-clear/backend
DATABASE_URL=sqlite:////tmp/.../canonical-gate2-compatible.db \
CUSTOMSCLEAR_READ_ONLY=1 \
CANONICAL_TREE_ENABLED=0 \
CANONICAL_TREE_SHADOW=0 \
/tmp/tariff-full-gate-venv/bin/pytest -q \
  tests/test_semantic_navigation_hierarchy.py \
  tests/test_guided_tnved_navigation.py
```

Result: `17 passed, 1 warning`, exit `0`. The warning is the existing
Starlette test-client deprecation notice.

### Full-data aggregate-only acceptance

```bash
DATABASE_URL=sqlite:////tmp/.../canonical-gate2-compatible.db \
CUSTOMSCLEAR_READ_ONLY=1 \
CANONICAL_TREE_ENABLED=0 \
CANONICAL_TREE_SHADOW=0 \
/tmp/tariff-full-gate-venv/bin/python \
  scripts/diagnose_guided_tnved_navigation.py \
  --require-complete \
  --output /tmp/.../guided-full-final.json
```

Result: exit `0`, `ok=true`, one Canonical snapshot:

| Heading | Expected/reachable | Coverage | Fake | Semantic groups/subgroups | Hierarchy |
|---|---:|---:|---:|---:|---|
| 0302 | 120 / 120 | 1.0 | 0 | 12 / 4 | required groups present |
| 0303 | 146 / 146 | 1.0 | 0 | 11 / 3 | tuna species nested; direct span < 20 |
| 5208 | 37 / 37 | 1.0 | 0 | 8 / 3 | plain weave nested under three finishes |
| 8517 | 25 / 25 | 1.0 | 0 | 5 / 0 | technical ranges rejected |

All headings returned `status=OK`, `complete=true`, no critical issues and
semantic depth at most two. Non-zero fallback counts are expected safe
rejections of out-of-scope or unparented candidates, not data loss.

### Static checks

```bash
/tmp/tariff-full-gate-venv/bin/ruff check \
  --select E,F,I --ignore E402,E501 \
  app/services/semantic_navigation/builder.py \
  scripts/diagnose_guided_tnved_navigation.py \
  tests/test_semantic_navigation_hierarchy.py \
  tests/test_semantic_navigation_v1.py

/tmp/tariff-full-gate-venv/bin/python -m compileall -q \
  app/services/semantic_navigation \
  scripts/diagnose_guided_tnved_navigation.py \
  tests/test_semantic_navigation_hierarchy.py \
  tests/test_semantic_navigation_v1.py
```

Result: all checks passed, exit `0`.

## Verdict

**APPROVED FOR THE DEFAULT-OFF GUIDED READ PATH.**

No merge was performed. `CANONICAL_TREE_ENABLED` and
`CANONICAL_TREE_SHADOW` remained OFF throughout; no rollout decision is implied.
