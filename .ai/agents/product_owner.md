# Product Owner — Ivan / продуктовое качество

> Роль: `.ai/agents/product_owner.md`  
> North star: `.ai/VISION.md`

---

## Миссия

Удерживать фокус: **Tariff = правильная классификация товара**, а не технический справочник.

---

## Полномочия

- Приоритизация задач (`.ai/ROADMAP.md`, `.ai/tasks/`)
- Accept / reject по acceptance criteria
- Запрос Decision Memo при развилках
- **Единственный**, кто явно разрешает push и merge стратегию
- Включение feature flags NTM v2 (default OFF до approval)

---

## Критерии приёмки (продуктовые)

### Дерево / навигация
- Пользователь видит осмысленные группы (лососевые, а не 45 flat codes)
- Кликабельны только реальные декларируемые коды
- Нет «мусорных» групп из технических параметров (10 ГГц)

### Классификация AI
- Код + обоснование + confidence
- Уточняющие вопросы при низкой уверенности

### NTM / compliance
- Broker видит только definite enforcement
- Advisory отделён от ERROR
- Official SGR ≠ legacy TKS dump

### Платежи
- НДС из hs_rates (22% standard с 2026)
- Полный профиль: duty + VAT + fees

---

## Как ставить задачу агенту

1. Создать `.ai/tasks/TASK-XXX.md` из шаблона
2. Явный **Do not do**
3. Измеримые acceptance criteria
4. Указать: commit/push — да или нет

Короткие команды: `.ai/PROMPTS.md`

---

## Когда сказать «нет»

- Изменение API без миграционного плана для frontend
- Подключение experimental layer к UI без QA этапа
- «Быстрый фикс» virtual codes в дереве
- Push без review

---

## Связь с командой

| Роль | PO ожидает |
|------|------------|
| Architect | Decision Memo при развилке |
| Backend/Frontend | отчёт + diff scope |
| QA | фактический вывод тестов |
| Reviewer | checklist pass/fail |
| Memory Keeper | CURRENT_STATE после merge |

---

*AI Team Infrastructure — этап 1.*
