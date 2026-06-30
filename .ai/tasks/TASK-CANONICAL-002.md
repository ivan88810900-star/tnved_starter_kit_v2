# TASK-CANONICAL-002: Перенос recovery-логики в StructureNormalizer

> **Status:** ready
> **Owner:** Backend Engineer (+ Architect review)
> **Created:** 2026-06-30
> **Depends on:** ADR-0001 (`.ai/decisions/ADR-0001-canonical-tnved-model.md`), TASK-CANONICAL-001 (skeleton `recovery.py` + deterministic `stable_id`)

---

## Goal

Перенести логику **восстановления неявной структуры** ТН ВЭД (pad-коды, синтез бескодовых L6/L8-заголовков, очистка имён, выбор имени группы, pad-subheading-group) из legacy `build_tree()` в стадию `StructureNormalizer` внутри `tree_engine`, **с побайтовой/структурной parity** относительно legacy и без изменения production-поведения.

---

## Context

ADR-0001 зафиксировал слой `Parser → Recovery → Builder → Validator → freeze()` внутри `tree_engine`. TASK-CANONICAL-001 создал skeleton `recovery.py` с `StructureNormalizer.normalize(...)` (без переноса логики) и детерминированные `stable_id`.

Сейчас вся recovery-логика «спрятана» внутри `tnved_tree/build_tree.py` (функция `build_tree()` и вложенная `_classify()`) и в helpers (`tnved_tree/helpers.py`). Это:
- мешает тестировать восстановление структуры изолированно;
- завязано на in-place мутации `dict` (опасность двойного `_classify`, см. `KNOWN_PITFALLS` §14);
- завязано на прямой вызов БД из `_classify` (`is_leaf_hs_code`).

Эта задача — **только перенос (lift-and-shift с типизацией)** recovery-логики в `StructureNormalizer`, **без** изменения legacy `build_tree()` (он остаётся production и oracle до parity — ADR-0001 §8, этап 6).

Связанные источники: ADR-0001, TASK-CANONICAL-001, `.ai/TASK_TEMPLATE.md`, `.ai/ENGINEERING_PROTOCOL.md`, `.ai/KNOWN_PITFALLS.md`.

---

## Scope

### In scope (разрешённые файлы)

- `customs-clear/backend/app/services/tree_engine/recovery.py` — основной перенос логики в `StructureNormalizer`
- `customs-clear/backend/app/services/tree_engine/builder.py` — только подключение `StructureNormalizer` в canonical path (без изменения публичной структуры узлов)
- `customs-clear/backend/app/services/tree_engine/models.py` — только при необходимости добавить поля metadata для recovery-результата (additive, не ломая существующее)
- `customs-clear/backend/tests/test_tree_engine_v2.py` — расширение тестов
- `customs-clear/backend/tests/test_canonical_tnved_model.py` — новые тесты parity/детерминизма (создан в TASK-CANONICAL-001 или создаётся здесь)

### Out of scope (запрещённые файлы / действия)

- ❌ `customs-clear/backend/app/services/tnved_tree/build_tree.py` (legacy `_build_tree`/`build_tree`) — **не менять**
- ❌ `customs-clear/backend/app/services/tnved_tree/helpers.py` — **не менять** (можно только импортировать существующие чистые функции)
- ❌ `customs-clear/backend/app/api/tnved_catalog.py` и любой production API — **не менять**
- ❌ `customs-clear/backend/app/services/semantic_navigation/` — **не менять**
- ❌ frontend (`customs-clear/frontend/`, `frontend/`) — **не менять**
- ❌ БД / схема / Alembic-миграции — **не менять**
- ❌ Подключать Canonical Model / `StructureNormalizer` к runtime, роутерам, lifespan — **запрещено**
- ❌ Удалять или депрекейтить legacy `build_tree()` — **запрещено** (нужен как oracle)
- ❌ Менять формулу `stable_id` из TASK-CANONICAL-001 — **запрещено**
- ❌ commit / push без явного разрешения Ivan

---

## Files / areas to inspect

```
customs-clear/backend/app/services/tree_engine/recovery.py        # цель переноса
customs-clear/backend/app/services/tree_engine/builder.py         # подключение нормализатора
customs-clear/backend/app/services/tree_engine/models.py          # типы узлов
customs-clear/backend/app/services/tnved_tree/build_tree.py       # ИСТОЧНИК логики (read-only oracle)
customs-clear/backend/app/services/tnved_tree/helpers.py          # чистые helpers (read-only)
customs-clear/backend/tests/test_tree_engine_v2.py
.ai/decisions/ADR-0001-canonical-tnved-model.md
.ai/KNOWN_PITFALLS.md  (§1, §2, §3, §4, §5, §6, §11, §12, §14)
```

---

## Список переносимой логики (recovery)

Переносится в `StructureNormalizer` (источник — `tnved_tree/build_tree.py` + `helpers.py`):

1. **Обработка pad-кода `XXXX000000`** (`KNOWN_PITFALLS` §1): исключение pad из дочерних кодов; использование его описания для имени заголовка позиции через `split_position_pad_name` (title + sub).
2. **Восстановление имени заголовка позиции** при пустом/generic `name` (`is_meaningful_name`, fallback на pad-имя).
3. **Синтез бескодового L6-заголовка** для одиночной субпозиции без детей (`KNOWN_PITFALLS` §2): codeless heading + synthetic leaf, `display_code = code[:6]`, маркировка `is_synthetic`.
4. **Синтез бескодового L8-заголовка** аналогично (`KNOWN_PITFALLS` §3): `display_code = code[:8]`, `is_synthetic`.
5. **pad-subheading-group** (`KNOWN_PITFALLS` §6): создание codeless-узла из `pad_sub` только при выполнении `needs_pad_subheading_group(pad_sub, level6_codes)` (mix прямых `XXXX30/90` и непрямых L6, `is_direct_position_subheading`).
6. **Очистка имён**: `strip_leading_dashes` (`KNOWN_PITFALLS` §12), `best_name_for_group` для синтетических узлов без имени.
7. **Отбраковка obsolete-reserved** описаний (`KNOWN_PITFALLS` §11) — на стыке с Parser; зафиксировать, где именно она применяется (предпочтительно в Parser, в recovery — не дублировать).
8. **Маркировка типов узлов** (`is_leaf` / `is_codeless` / `is_group`), эквивалентная `_classify()`, но **без in-place двойного прохода** (`KNOWN_PITFALLS` §14) и **без прямого вызова БД** (см. ниже).

---

## Список логики, которую переносить ЗАПРЕЩЕНО

1. ❌ **Stack-based сборка иерархии** (порядок parent/children, `stack`, `by_heading`) — это ответственность `Builder`, не `StructureNormalizer`. Recovery восстанавливает атрибуты/синтез, Builder собирает дерево.
2. ❌ **Прямой вызов БД `is_leaf_hs_code()`** из recovery. `StructureNormalizer` должен быть **чистым** (вход — нормализованные записи Parser + при необходимости предвычисленный набор leaf-флагов, переданный аргументом). DB-доступ остаётся в Parser/слое доступа.
3. ❌ **Resolve ставок** (`_resolve_rates_for_code`), **permit-флаги** (`_permit_flags_for_hs`), **measures** (`_measures_for_api`) — это overlay/Duty/NTM, не recovery (живут в `tnved_catalog.py`, который не трогаем).
4. ❌ **Секционная обёртка** (`_wrap_in_sections`, Section/Chapter) — это Builder/serializer, не recovery.
5. ❌ **Сериализация в legacy-dict / API-форму** (`_serialize_tree_node`) — не recovery.
6. ❌ **Логика semantic-групп** (`extractor.py`, smysловые «лососевые/тунец») — отдельный overlay (`semantic_navigation`), не структурная recovery.
7. ❌ **Любая модификация самого `build_tree()`** — он остаётся неизменным oracle.

---

## Required behavior

1. `StructureNormalizer.normalize(...)` принимает нормализованные записи (от Parser) и возвращает структуру, из которой `Builder` собирает те же типизированные узлы, что и сегодня.
2. Поведение восстановления (pad, L6/L8 синтез, имена, subheading-group) **эквивалентно** legacy `build_tree()` — проверяется parity-тестом (`structure_fingerprint`).
3. `StructureNormalizer` — **чистая** функция/класс: без обращения к БД, без `uuid4`, без времени/случайности (детерминизм ADR-0001 I3/I4).
4. Синтетические узлы помечаются `is_synthetic=True` (для валидатора fake-code, ADR-0001 I2).
5. Canonical path использует deterministic `stable_id` из TASK-CANONICAL-001; структура и legacy-сериализация (`to_legacy_dict`) **не меняются**.
6. legacy `build_tree()` остаётся вызываемым и неизменным (oracle).

---

## Do not do

- Не менять `build_tree()` / `tnved_catalog.py` / `helpers.py` (только импорт чистых функций).
- Не менять production API, frontend, `semantic_navigation`, БД.
- Не подключать `StructureNormalizer` к runtime/роутерам.
- Не вызывать БД из `StructureNormalizer`.
- Не вызывать классификацию дважды на одном дереве (`KNOWN_PITFALLS` §14).
- Не удалять legacy `build_tree()`.
- Не commit / push без разрешения Ivan.

---

## Tests

```bash
cd customs-clear/backend

# Parity и детерминизм Canonical vs legacy
pytest tests/test_canonical_tnved_model.py -v
# Ожидание: passed; fingerprint StructureNormalizer == legacy build_tree

# Регрессия типизированного контура
pytest tests/test_tree_engine_v2.py -v
# Ожидание: passed; структура узлов не изменилась

# Контроль, что production API не задет
pytest tests/test_tnved_catalog_api.py -k children -v
# Ожидание: passed (без изменений поведения)
```

Краевые кейсы для parity (обязательны): heading с pad-кодом, одиночный L6 (`KNOWN_PITFALLS` §2), одиночный L8 (§3), mixed L6 с subheading-group (§6), obsolete-reserved (§11), имена с ведущими тире (§12). Рекомендуемые heading'и: `0302`, `0303`, `5208`, `8517` + пример с pad-subheading-group.

---

## Acceptance criteria

- [ ] Вся recovery-логика из «Список переносимой логики» присутствует в `StructureNormalizer`.
- [ ] Ни один пункт из «Список логики, которую переносить запрещено» не перенесён.
- [ ] Parity: `structure_fingerprint(StructureNormalizer)` == `structure_fingerprint(legacy build_tree)` на всех краевых heading'ах.
- [ ] `StructureNormalizer` детерминирован и не обращается к БД.
- [ ] Синтетические узлы помечены `is_synthetic`.
- [ ] `stable_id` (из TASK-CANONICAL-001) не изменён; структура узлов не изменена.
- [ ] legacy `build_tree()` / `tnved_catalog.py` / `helpers.py` — без изменений (`git diff` пуст для них).
- [ ] production API не изменён; frontend не изменён; `semantic_navigation` не изменён; БД не изменена.
- [ ] Все тесты из раздела Tests проходят.
- [ ] QA Report с фактическим выводом команд.
- [ ] `git diff` — только файлы из «In scope».

---

## QA criteria

Выполнить и приложить **фактический вывод**:

```bash
cd customs-clear/backend
pytest tests/test_canonical_tnved_model.py -v
pytest tests/test_tree_engine_v2.py -v
pytest tests/test_tnved_catalog_api.py -k children -v
```

```bash
git status
git diff --stat
git diff --name-status
```

QA по `.ai/QA_PROTOCOL.md`; отчёт по `.ai/ENGINEERING_PROTOCOL.md` §12.

---

## Rollback plan

- Перенос изолирован в `tree_engine` (canonical path), **не подключён к runtime** → откат не влияет на production.
- Откат = `git checkout -- customs-clear/backend/app/services/tree_engine/recovery.py builder.py models.py` + удаление новых тестов; legacy `build_tree()` остаётся единственным рабочим путём.
- Поскольку API/legacy не трогаются, в любой момент до parity истиной остаётся legacy `build_tree()` (ADR-0001: legacy = production + oracle до parity).
- Нет миграций БД и нет feature-flag-переключений в этой задаче → нечего откатывать на уровне данных/конфигурации.

---

## Risks / notes

- **R1. Расхождение с legacy на краевых кейсах** (pad-swallowing §1/§6, L6/L8 §2/§3). Митигировать parity-fingerprint на всех краевых heading'ах до закрытия задачи.
- **R2. Случайный занос DB-зависимости** (`is_leaf_hs_code`) в recovery → нарушение чистоты/детерминизма. Решение: leaf-флаги предвычисляются вне нормализатора и передаются аргументом.
- **R3. Двойная классификация** (`KNOWN_PITFALLS` §14) при повторном проходе. Решение: один проход, без in-place мутаций исходных записей.
- **R4. Незаметное изменение структуры** при «улучшении» имён/синтеза. Решение: запрет на семантические правки сверх legacy; только перенос.
- **R5. Scope creep** — соблазн заодно подключить к API или перенести stack-сборку. Запрещено этой задачей (отдельные этапы ADR-0001).
- **Notes:** фактический перенос obsolete-reserved (§11) согласовать с тем, где он уже делается в Parser (TASK-CANONICAL-001), чтобы не дублировать фильтрацию.

---

## Commit rules

- Commit только после QA и review.
- Push запрещён без прямого разрешения Ivan.
