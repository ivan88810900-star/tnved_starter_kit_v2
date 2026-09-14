# Implementation plan — authorized 2026-09-12

## Discovery (read-only, before implementation)

Repository ivan88810900-star/tnved_starter_kit_v2, default main9712c7b.
PR187 draft22a7df55 -> canonical a5a811e6, 425 files,+86486/-2239; CI34714625756
success. PR189 draft1be6da4d,8 files, conflicting pilot from product branch; its
CI33989803389/33989803325 success. Neither PR is modified by setup.

AGENTS.md and .ai engineering/task/QA protocols/current focus/decisions reviewed.
Existing narrative state, ADR/DM and task markdown are preserved. Old manual
Cursor coordination and commit-approval instructions conflict with the current
explicit owner mandate and are normalized, with no product-rule weakening.
Main has no .github/workflows; canonical has scheduled-data-refresh; PR187 has
10 read-only/monitor workflows. Documentation about old auto-merge workflows is
stale. Repository auto_merge=false; branch metadata protected=false. This does
not prove absence of all rulesets. Permissions/production state were not changed.
Existing Work Automations: weekly Tariff status active, two old development
pollers paused. Reuse a paused development poller after verifying the new PR.
GitHub webhook supports PR events, not CI completion; hourly polling can cover
CI/source-monitor failures and periodic regression/stale/source-update review.

## Implementation

1. Main-based isolated infra branch, freeze interfaces/ownership before writers.
2. Stdlib deterministic state/leases/ownership/worktree/evidence gates. Native Work
   is active orchestrator; optional documented Agents API native multi-agent adapter.
   Use hosted API environment to avoid running custom infrastructure.
3. Restricted Claude packet and findings adapter. No key = UNAVAILABLE, no pass.
4. Read-only offline GitHub Actions; no write token, no scheduler/merge/deploy.
5. Real child sessions in distinct worktrees -> A5 independent regression. Save
   IDs/commits/results. Fresh session recovers board and source refs without chat.
6. Publish independent draft PR, verify CI for exact head, configure Work wake-up
   using existing GitHub permissions. Do not claim API/A6 live proof without keys.
7. Resume next Tariff work item on current product SHA through these controls;
   recheck actual current source documents before choosing implementation.

## Gates / remaining activation

Runtime Work smoke and optional API smoke are separate. Mock transport tests are
not live provider tests. A6 is conditional on configuration, as requested. NOT_CONFIGURED is disclosed;
configured audit failure cannot pass the high-risk gate. Owner receives exact safe credential setup instructions after all available
implementation and verification, not requests to send keys in chat.
