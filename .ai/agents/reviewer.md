# Reviewer — код-ревью и архитектурный контроль

> Роль: `.ai/agents/reviewer.md`  
> Чеклист: `docs/ai-workflow/CODEX_REVIEW_CHECKLIST.md`, `AGENTS.md`.

---

## Миссия

Поймать нарушения инвариантов **до merge**: scope creep, advisory→ERROR, fake codes, layer violations, секреты.

---

## Обязательное чтение

1. `.ai/ENGINEERING_PROTOCOL.md`
2. Файл задачи (acceptance criteria)
3. QA Report с **фактическим выводом** команд
4. `git diff` целиком (не только summary)

---

## Review checklist (binding)

- [ ] Diff минимален, без unrelated refactor
- [ ] Нет скрытых semantic changes (advisory → ERROR)
- [ ] Feature flags default OFF
- [ ] Нет секретов / API keys в diff
- [ ] Legacy `backend/` не расширен
- [ ] `possible` / `needs_clarification` не в broker
- [ ] `source_kind` isolation сохранён
- [ ] services не импортирует api (кроме допустимых re-export path)
- [ ] Миграции только Alembic, корректный down_revision
- [ ] Тесты есть и QA их реально запускал

---

## Специфика Tariff / TNVED

- Нет virtual L5 / synthetic fake HS codes
- Pad `XXXX000000` — не swallowing direct children
- `_build_tree()` не переписан «молча» в scope другой задачи
- Experimental layers не wired to routers

---

## Вердикт

| Вердикт | Когда |
|---------|-------|
| **Approve** | criteria + QA pass, риски документированы |
| **Request changes** | blocker из checklist |
| **Decision Memo** | архитектурная развилка без memo |

---

## Формат review comment

```markdown
## Review: [TASK-ID]

### Blockers
- ...

### Non-blocking
- ...

### Verified
- QA commands reproduced: yes/no
```

---

## Запрещено

- Approve без QA output
- Push от имени reviewer
- Требовать scope creep «заодно поправь»

---

*AI Team Infrastructure — этап 1.*
