# Workflow — Codex, Cursor, Ivan, Strategic Review

## Полный цикл

```text
1. Codex reviews latest PR or project state
2. Codex creates:
   - Cursor Task issue, if next step is obvious
   - Decision Memo issue, if strategic choice is needed
3. Cursor implements Cursor Task (via [GitHub Action + Cursor CLI](./CURSOR_GITHUB_ACTION_AUTOMATION.md))
4. Cursor opens PR with full report
5. Codex reviews PR
6. Ivan merges or sends Decision Memo to strategic ChatGPT review
```

## Current Project Focus

The repository maintains a live strategic focus document:

`docs/ai-workflow/CURRENT_PROJECT_FOCUS.md`

Codex uses it to determine the next recommended implementation task.
This prevents older backlog items or archived priorities (for example AGENT-04 frontend verification) from overriding the currently approved workstream.

When `Status: Active`, Codex Automation and manual Codex review must read this file **before** drafting the next `cursor-task`.

---

## Правило Decision Memo

Если создан issue с label `needs-ivan-decision` (Decision Memo):

1. Ivan копирует текст memo в **стратегический ChatGPT review**.
2. Получает выбранное направление (Option A/B/C + обоснование).
3. Фиксирует решение в комментарии к issue или в новом комментарии «Decision: …».
4. Codex (или Ivan) создаёт следующий **Cursor Task** с явной ссылкой на принятое решение.
5. Cursor **не** реализует стратегическую развилку до фиксации решения.

## Когда Cursor Task, когда Decision Memo

| Ситуация | Действие |
|----------|----------|
| Следующий шаг однозначен, scope ясен | Cursor Task |
| Баг с понятным fix | Cursor Task (`cursor-fix` опционально) |
| Несколько архитектурных вариантов | Decision Memo |
| Меняется API / source of truth / enforcement | Decision Memo |
| Legal/compliance интерпретация | Decision Memo |
| Неочевидно: advisory vs ERROR | Decision Memo |

## Связь issue ↔ PR

- В PR в описании: `Closes #NNN` или `Relates to #NNN`.
- В issue после PR: комментарий со ссылкой на PR.
- Label `ready-for-codex-review` на PR после открытия Cursor.
- Label `ready-for-ivan-review` после одобрения Codex.

## Что не автоматизировать без Ivan

- Включение feature flags в production по умолчанию ON.
- Merge в `main` без ревью (кроме явно согласованных hotfix).
- Подключение GitHub Apps (Codex / Cursor) — один раз в UI.
- Публикация репозитория (только **private**).
