# AI Workflow — Codex × Cursor × Ivan

Система совместной разработки для репозитория `tnved_starter_kit_v2`.

## Роли

| Участник | Роль |
|----------|------|
| **Cursor** | Implementation agent — пишет код, открывает PR |
| **Codex** | Technical lead — ревью, следующие задачи, Decision Memo |
| **Ivan** | Product owner — утверждение merge и стратегических решений |
| **Strategic ChatGPT review** | Внешний архитектурный арбитр по Decision Memo |

## Цикл в двух словах

1. Codex смотрит последний PR / состояние проекта.
2. Codex создаёт **Cursor Task** (очевидный следующий шаг) или **Decision Memo** (нужен выбор).
3. Cursor реализует задачу и открывает PR с полным отчётом.
4. Codex ревьюит PR по чеклисту.
5. Ivan мержит или отправляет Decision Memo в стратегический ChatGPT review.

## С чего начать

| Файл | Назначение |
|------|------------|
| **[CURRENT_PROJECT_FOCUS.md](./CURRENT_PROJECT_FOCUS.md)** | **Активный стратегический фокус (читать первым)** |
| [WORKFLOW.md](./WORKFLOW.md) | Полный цикл и правила эскалации |
| [SETUP_CODEX_CURSOR_WORKFLOW.md](./SETUP_CODEX_CURSOR_WORKFLOW.md) | Настройка для Ivan (Codex Review, Automations, Cursor) |
| [CODEX_REVIEW_CHECKLIST.md](./CODEX_REVIEW_CHECKLIST.md) | Обязательный чеклист ревью Codex |
| [CURSOR_TASK_TEMPLATE.md](./CURSOR_TASK_TEMPLATE.md) | Шаблон задачи для Cursor |
| [DECISION_MEMO_TEMPLATE.md](./DECISION_MEMO_TEMPLATE.md) | Шаблон стратегического решения |
| [CODEX_AUTOMATION_PROMPT.md](./CODEX_AUTOMATION_PROMPT.md) | Промпт для Codex Automation |
| [CURSOR_AUTOMATION_PROMPT.md](./CURSOR_AUTOMATION_PROMPT.md) | Промпт для Cursor Cloud Agents |
| [GITHUB_LABELS.md](./GITHUB_LABELS.md) | Рекомендуемые labels |

Корневой контракт для всех агентов: **[AGENTS.md](../../AGENTS.md)**.

GitHub: issue templates в `.github/ISSUE_TEMPLATE/`, PR template в `.github/PULL_REQUEST_TEMPLATE.md`.
