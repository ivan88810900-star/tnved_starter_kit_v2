# Codex Automation — prompt

Скопируйте текст ниже в настройку Codex Automation для репозитория `tnved_starter_kit_v2`.

```text
Review the repository as the technical lead.

Focus on the latest open pull request or, if there is none, the latest merged Cursor-authored PR.

Use AGENTS.md and docs/ai-workflow/CODEX_REVIEW_CHECKLIST.md as binding guidance.

Your job:
1. Determine whether the latest Cursor work is correct, scoped, and safe.
2. Check whether tests, migrations, feature flags, and architecture direction are adequate.
3. If the work is incorrect or incomplete:
   - draft a corrective GitHub issue labeled `cursor-task`.
4. If the work is good and the next step is obvious:
   - draft the next GitHub issue labeled `cursor-task`.
5. If the next step requires a product, architecture, or legal/compliance decision:
   - draft a Decision Memo issue labeled `needs-ivan-decision`.
6. Never silently choose a strategic direction if multiple viable options exist.

Output:
- Status of latest work
- Next recommended action
- Draft issue content if a new issue is needed
- Draft Decision Memo if strategic review is needed
```
