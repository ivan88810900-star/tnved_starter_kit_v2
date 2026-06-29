# .ai/tasks/ — Очередь задач AI Team

Каталог задач для Cursor / Cloud Agent. Каждая задача — один markdown-файл.

---

## Именование

```
TASK-<DOMAIN>-<NNN>.md
```

Примеры:
- `TASK-SEMANTIC-003.md` — semantic navigation, задача 3
- `TASK-TREE-004.md` — tree engine, задача 4

---

## Жизненный цикл

| Статус | Значение |
|--------|----------|
| **draft** | формулируется PO/Architect |
| **ready** | можно брать в работу |
| **in_progress** | исполнитель назначен |
| **qa** | на проверке QA |
| **done** | merged / принято Ivan |
| **cancelled** | не актуально |

Статус указывается в шапке файла задачи.

---

## Как взять задачу

1. Прочитать `.ai/VISION.md`, `.ai/TASK_PROTOCOL.md`
2. Открыть файл задачи
3. Выполнить scope
4. QA по `.ai/QA_PROTOCOL.md`
5. Отчёт; commit/push — **только по указанию Ivan**

---

## Шаблон

Новые задачи создавать из `TASK_TEMPLATE.md`.

---

## Активные задачи

| ID | Название | Статус |
|----|----------|--------|
| TASK-SEMANTIC-003 | Hierarchical grouping quality | ready |

---

## Связанные документы

- `.ai/PROMPTS.md` — короткие команды
- `.ai/agents/` — роли
- `docs/ai-workflow/` — GitHub/Codex workflow (legacy, совместим)
