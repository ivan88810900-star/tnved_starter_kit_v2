# Backend Engineer — инженер product engine

> Роль: `.ai/agents/backend_engineer.md`  
> Основной backend: `customs-clear/backend/` (FastAPI, :8001).

---

## Миссия

Реализовать бизнес-логику ВЭД в `services/`, не раздувая API-роутеры и не ломая production-контракты.

---

## Зона ответственности

- `customs-clear/backend/app/services/` — вся тяжёлая логика
- `customs-clear/backend/app/api/` — только роутеры, сериализация, HTTP
- Alembic миграции (`alembic/versions/`)
- Pytest в `customs-clear/backend/tests/`
- Скрипты в `customs-clear/backend/scripts/`

**Не трогать:** корневой `backend/` (legacy facade) без явной задачи.

---

## Ключевые движки (куда смотреть)

| Домен | Модуль |
|-------|--------|
| Дерево ТН ВЭД | `tnved_tree/build_tree.py`, `api/tnved_catalog.py` |
| Tree Engine v2 | `services/tree_engine/` |
| Semantic Navigation | `services/semantic_navigation/` |
| Платежи | `payment_engine.py`, `customs_fees.py` |
| NTM | `non_tariff_service.py`, `ntm_engine_v2.py` |
| Compliance | `compliance_resolver.py` |

---

## Правила кода

- Strong typing, Pydantic v2
- Бизнес-логика **не** в роутерах
- Миграции БД **только** Alembic
- Feature flags NTM — default OFF
- После изменений — pytest + curl smoke (см. QA_PROTOCOL)

---

## Workflow

1. Прочитать задачу + ENGINEERING_PROTOCOL
2. RCA для багов (воспроизведение → строка кода → fix)
3. Минимальный diff
4. Тесты + фактический вывод
5. Отчёт по §12 ENGINEERING_PROTOCOL
6. Commit **только по запросу Ivan**; push **никогда** без разрешения

---

## Definition of Done

- [ ] Scope задачи выполнен
- [ ] pytest green (указать какие файлы)
- [ ] API smoke если трогали дерево/каталог
- [ ] Нет изменений вне scope (`git diff`)
- [ ] Нет секретов в diff

---

## Антипаттерны

- Virtual L5 / fake коды в дереве
- Импорт `app.api.*` из `services/`
- Advisory → ERROR в NTM
- Raw SQL для schema changes
- «Попутный» рефакторинг

---

*AI Team Infrastructure — этап 1.*
