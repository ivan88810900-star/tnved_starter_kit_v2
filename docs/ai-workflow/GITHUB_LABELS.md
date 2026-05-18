# Рекомендуемые GitHub Labels

Документация. Labels создаются вручную в GitHub: **Issues → Labels → New label**.

| Label | Цвет (пример) | Назначение |
|-------|----------------|------------|
| `cursor-task` | `#0E8A16` | Задача на реализацию в Cursor |
| `cursor-fix` | `#1D76DB` | Исправление после ревью / баг |
| `needs-ivan-decision` | `#D93F0B` | Decision Memo, ждёт Ivan + strategic review |
| `ready-for-codex-review` | `#FBCA04` | PR готов к ревью Codex |
| `ready-for-ivan-review` | `#C5DEF5` | Codex одобрил, ждёт merge Ivan |
| `blocked` | `#000000` | Не брать в работу до снятия блокера |
| `architecture` | `#5319E7` | Архитектурное изменение |
| `security` | `#B60205` | Безопасность / секреты |
| `ntm-v2` | `#006B75` | Нетарифка / NTM v2 контур |

## Связка с workflow

- Cursor Automation: брать открытые issues с `cursor-task`, без `blocked`.
- Codex Automation: после merge смотреть `ready-for-codex-review` или последний PR.
- Decision path: `needs-ivan-decision` → strategic ChatGPT → новый `cursor-task`.
