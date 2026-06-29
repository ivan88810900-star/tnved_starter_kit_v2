# TASK-XXX: [Краткое название]

> **Status:** draft | ready | in_progress | qa | done | cancelled  
> **Owner:** [роль / Ivan]  
> **Created:** YYYY-MM-DD

---

## Goal

<!-- Одно измеримое предложение: что должно быть достигнуто -->

---

## Context

<!-- Почему сейчас. Ссылки на коммиты, PR, .ai/CURRENT_STATE, предыдущие этапы -->

---

## Scope

### In scope
- ...

### Out of scope
- ...

---

## Files / areas to inspect

```
path/to/module/
```

---

## Required behavior

1. ...
2. ...

---

## Do not do

- Не менять production API / frontend (если не указано иное)
- Не commit / push без явного запроса Ivan
- Не подключать experimental layers к роутерам
- ...

---

## Tests

```bash
# Команды с ожидаемым результатом
pytest tests/... -v
# Ожидание: N passed, 0 failed
```

---

## Acceptance criteria

- [ ] ...
- [ ] QA Report с фактическим выводом команд
- [ ] `git diff` — только файлы из scope

---

## Report format

По `.ai/ENGINEERING_PROTOCOL.md` §12 + `.ai/QA_PROTOCOL.md`.

---

## Risks / notes

- ...
