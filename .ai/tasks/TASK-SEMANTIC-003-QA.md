# QA Report: TASK-SEMANTIC-003

> Date: 2026-07-24
> Environment: sandbox DB with 2 synthetic commodity rows
> Full-data status: pending read-only run on the user's 17,809-row commodity set

## Commands run

1. Controlled hierarchy + Guided contract:

   ```bash
   cd customs-clear/backend
   /tmp/tariff-hierarchy-venv/bin/python -m pytest \
     tests/test_semantic_navigation_hierarchy.py \
     tests/test_guided_tnved_navigation.py -q
   ```

   Result: `15 passed, 1 warning in 0.54s`, exit `0`. The warning is a
   Starlette deprecation notice inside the installed test client.

2. Python compile + lint for changed backend files:

   ```bash
   /tmp/tariff-hierarchy-venv/bin/python -m compileall -q \
     app/services/semantic_navigation \
     app/services/guided_tnved_navigation.py \
     scripts/diagnose_semantic_navigation.py \
     scripts/diagnose_guided_tnved_navigation.py

   /tmp/tariff-hierarchy-venv/bin/ruff check \
     --select E,F,I --ignore E402,E501 \
     app/services/semantic_navigation \
     app/services/guided_tnved_navigation.py \
     scripts/diagnose_semantic_navigation.py \
     scripts/diagnose_guided_tnved_navigation.py \
     tests/test_semantic_navigation_hierarchy.py \
     tests/test_semantic_navigation_v1.py \
     tests/test_guided_tnved_navigation.py
   ```

   Result: `All checks passed!`, exit `0`.

3. Actual Canonical-backed Guided smoke on the sandbox data:

   ```bash
   CANONICAL_TREE_ENABLED=0 CANONICAL_TREE_SHADOW=0 \
   /tmp/tariff-hierarchy-venv/bin/python \
     scripts/diagnose_guided_tnved_navigation.py \
     --headings 9988 \
     --require-complete \
     --output /tmp/guided-tnved-local.json
   ```

   Result: exit `0`; `status=OK`, `expected_real_codes=2`,
   `reachable_real_codes=2`, `canonical_coverage=1.0`, `fake_codes=0`,
   `critical_issues=[]`, `ok=true`. Both Canonical runtime flags stayed OFF.

4. Frontend:

   ```bash
   cd customs-clear/frontend
   npm run typecheck
   npm run build
   ```

   Result: both exit `0`; Vite transformed `3071` modules and produced the
   production bundle. The existing large-chunk and Vite plugin deprecation
   warnings remain non-blocking and are unrelated to this task.

5. Git whitespace:

   ```bash
   git diff --check
   ```

   Result: no output, exit `0`.

## Data-dependent checks

The mandatory full-data checks cannot be truthfully completed in this sandbox:
`customs-clear/backend/customs.db` contains only 2 rows (`9988100000`,
`9988200000`) and none of the target headings.

The attempted required regression makes this limitation visible:

```bash
/tmp/tariff-hierarchy-venv/bin/python -m pytest \
  tests/test_tree_engine_v2.py -q
```

Result: exit `1`; `2 failed, 2 passed`. Both failures are missing-fixture
failures (`legacy missing heading 0101`, `heading 0101 not addressable`), not
semantic-nesting failures.

The new aggregate-only v2 gate is ready for the full database:

```bash
cd customs-clear/backend
python3 scripts/diagnose_guided_tnved_navigation.py \
  --require-complete \
  --output "guided-tnved-$(date +%Y%m%d-%H%M%S).json"
```

It now requires both the existing Canonical integrity conditions and the
hierarchy checks for `0302`, `0303`, `5208`, and `8517`.

## Invariants covered by self-contained tests

- Every expected real code remains reachable.
- No semantic group carries a customs code.
- Reparenting refreshes every `parent_id` and `depth`.
- Rejected level-1 candidates close the parent segment.
- A subgroup over the 30-code unsplit limit remains flat with a diagnostic.
- `5208` duplicate plain-weave titles remain distinct under their own parents.
- `0303` strict tuna title-prefix children become subgroups.
- Guided serialization turns a subgroup into an extra user question.
- Canonical coverage remains 100%; incomplete binding still fails closed.

## Verdict

**IMPLEMENTATION READY; FULL-DATA APPROVAL PENDING.**

No merge and no Canonical flag enablement are authorized or performed.
