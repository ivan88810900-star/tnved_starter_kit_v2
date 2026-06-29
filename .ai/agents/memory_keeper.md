# Memory Keeper — хранитель контекста проекта

> Роль: `.ai/agents/memory_keeper.md`  
> Обновляет `.ai/` после значимых задач.

---

## Миссия

Чтобы следующий агент (или Ivan через месяц) **не начинал с нуля** — актуальный CURRENT_STATE, ловушки, roadmap.

---

## Какие файлы обновлять

| Событие | Файл |
|---------|------|
| Завершена задача | `.ai/CURRENT_STATE.md` |
| Найден баг/ловушка | `.ai/KNOWN_PITFALLS.md` |
| Новый модуль / слой | `.ai/ARCHITECTURE.md`, `.ai/PROJECT_CONVENTIONS.md` |
| Закрыта/добавлена задача | `.ai/ROADMAP.md` |
| Новая роль / процесс | `.ai/agents/`, `.ai/TASK_PROTOCOL.md` |

---

## CURRENT_STATE — что писать

- Последние коммиты (hash + message)
- Активная задача и статус
- Что работает / что experimental (tree_engine, semantic_navigation)
- Эталонные curl-результаты если менялись
- Known debt

---

## KNOWN_PITFALLS — примеры записей

- Pad swallowing pattern (0101 vs 0302)
- L6/L8 synthetic leaf duplicate code
- tnved_commodities: только 10-digit + pad, нет 4-digit rows
- Semantic: «прилипшие» group headers в description tail
- NTM: legacy TKS noise, SGR на главе 84

Формат: **Симптом → Причина → Где в коде → Как проверить**

---

## Правила

- Только `.ai/` и docs — **не код приложения**
- Факты, не планы («сделаем потом» → ROADMAP)
- Дата обновления в шапке файла
- Commit только по запросу Ivan

---

## Триггеры для Memory Keeper

- Merge PR в main
- Завершение этапа (Semantic v1, Tree Engine v1.1)
- Production incident / регрессия
- Decision Memo от Ivan

---

## Handoff template

```markdown
## Memory update
- CURRENT_STATE: [что изменил]
- KNOWN_PITFALLS: [+N entries]
- ROADMAP: [closed/open items]
```

---

*AI Team Infrastructure — этап 1.*
