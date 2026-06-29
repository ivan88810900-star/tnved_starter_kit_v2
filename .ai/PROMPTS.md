# PROMPTS.md — Короткие команды для телефона

> Копируй одну строку в Cursor / Cloud Agent. Агент сам найдёт контекст в `.ai/`.

---

## Быстрый старт

```
Прочитай .ai/VISION.md и .ai/TASK_PROTOCOL.md. Кратко скажи, где мы в проекте.
```

```
Прочитай .ai/CURRENT_STATE.md. Что сейчас в работе?
```

---

## Задачи (постановка)

```
Возьми .ai/tasks/TASK-SEMANTIC-003.md. Выполни. Commit/push не делать.
```

```
Создай новую задачу по .ai/tasks/TASK_TEMPLATE.md для [описание]. Положи в .ai/tasks/
```

```
Проверь scope задачи TASK-SEMANTIC-003. Что in/out?
```

---

## Semantic Navigation

```
Semantic Navigation этап 3: hierarchical grouping. Только semantic_navigation/. API не трогать.
```

```
Запусти diagnose_semantic_navigation.py. Покажи rejected candidates для 0303 и 8517.
```

```
Почему 5208 дублирует «полотняного переплетения»? Только анализ, без кода.
```

---

## Tree / TNVED

```
Проверь curl: 0302, 0304, 0805, 0101210000. Покажи counts. API не менять.
```

```
pytest test_tree_engine_v2 + test_tnved_catalog children. Покажи вывод.
```

```
Объясни разницу tree_engine и semantic_navigation одним абзацем.
```

---

## QA / Review

```
QA по .ai/QA_PROTOCOL.md для последних изменений. Покажи фактический вывод команд.
```

```
git status + diff --stat. Подтверди что только [папка]. Commit не делать.
```

```
Reviewer: проверь последний diff. Есть ли нарушения ENGINEERING_PROTOCOL?
```

---

## Commit (только когда Ivan просит явно)

```
Перед commit: git status, diff --stat, pytest [тесты]. Потом commit с сообщением: [текст]. Push не делать.
```

---

## Memory / Docs

```
Обнови .ai/CURRENT_STATE.md по последней работе. Только .ai/, commit не делать.
```

```
Добавь ловушку в .ai/KNOWN_PITFALLS.md: [описание].
```

---

## Архитектор / Product

```
Architect: оцени TASK-SEMANTIC-003. Риски и альтернативы. Без кода.
```

```
Product Owner: соответствует ли [фича] .ai/VISION.md? Да/нет и почему.
```

---

## Экстренное

```
Откати только [файл] к HEAD. Остальное не трогать.
```

```
Сервер :8001 не отвечает. Диагностика, без изменения кода.
```

---

## Подсказки

- Всегда добавляй **«Commit/push не делать»**, если не хочешь автоматический push.
- Для backend-тестов агент должен запускать команды сам, не описывать их текстом.
- Короткая команда = одна цель. Не смешивай «сделай фичу + закоммить + задеploy».

---

*Создан: 2026-06-29. Часть AI Team Infrastructure — этап 1.*
