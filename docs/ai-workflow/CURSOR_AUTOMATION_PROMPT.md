# Cursor Automation — prompt

Скопируйте текст ниже в Cursor Cloud Agents / Automations для репозитория `tnved_starter_kit_v2`.

```text
Look for the oldest open GitHub issue labeled `cursor-task` in this repository that is not marked `blocked`.

Read the issue carefully and implement only that scope.

Follow:
- AGENTS.md
- docs/ai-workflow/CURRENT_PROJECT_FOCUS.md (if Status: Active)
- the issue acceptance criteria
- existing code style

Requirements:
1. Make the smallest safe PR.
2. Do not silently expand scope.
3. Run the tests requested in the issue, plus directly affected regression tests where reasonable.
4. If the task is ambiguous or requires product/architecture choice:
   - do not guess;
   - stop and create a Decision Memo draft instead.
5. Open a pull request with:
   - Summary
   - What changed
   - Tests run
   - Risks / limitations
   - Follow-up recommendation
6. Link the PR to the source issue.
```
