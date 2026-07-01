# TASK-CANONICAL-004: First production read-path on CanonicalModel

> **Status:** blocked-on-decision (design готов; реализация — только после ADR-0002 Accepted)
> **Owner:** Backend Engineer (+ Architect review)
> **Created:** 2026-07-01
> **Depends on:** **ADR-0002** (`.ai/decisions/ADR-0002-canonical-children-read-path.md`, *Proposed* — требует утверждения Ivan до кода), ADR-0001 (`.ai/decisions/ADR-0001-canonical-tnved-model.md`), TASK-CANONICAL-001, TASK-CANONICAL-002, Canonical Model Materialization (`CanonicalModel`, `TreeBuilder.build_model`, validator gate, full-tree content parity — уже в `main`)

> **Decision authority:** архитектурные обоснования (почему `/children`, почему flag OFF /
> request-time, почему отдельный shadow, почему legacy = oracle, почему контракт неизменен,
> почему overlay остаётся, почему cache build-once, fallback, частичность/временность смены
> source of truth) зафиксированы в **ADR-0002**. Эта задача — инженерная спецификация под него.
> **Код не начинать, пока ADR-0002 не переведён в Accepted (Ivan).**

---

## Context

- **TASK-CANONICAL-001/002 завершены.** Детерминированные `stable_id`, `snapshot_id`,
  `StructureNormalizer`, Builder без делегирования в legacy.
- **Canonical Model Materialization слита в `main`.** Есть иммутабельный `CanonicalModel`
  с индексами достижимости (`node_by_stable_id` / `node_by_code` / `node_by_display_code`
  / `parent_by_stable_id` / `children_by_stable_id`) и навигацией (`get` / `get_by_code`
  / `get_by_display_code` / `parent` / `children` / `path` / `descendants`); freeze/read-only
  на уровне интерфейса; validator gate перед freeze; full-tree structural + content parity
  против legacy `build_tree()`.
- **Runtime пока полностью использует legacy `build_tree()`.** API `/children`
  (`app/api/tnved_catalog.py::list_tnved_children`) резолвит структуру через
  `_resolve_tree_node → _build_wrapped_tree → _build_tree`, перечитывая до 2 000 000 строк
  на каждый запрос (`ROADMAP §2`, `CURRENT_STATE §6`).
- **Следующий этап (ADR-0001 §8, Этап 3):** первый production read-path — endpoint
  `/children` — читает **структуру** из `CanonicalModel` за feature flag **default OFF**,
  с shadow-сравнением и откатом одной переменной. Legacy остаётся production и oracle.

### Ключевой архитектурный принцип (обязателен к соблюдению)

Внутри `list_tnved_children` разделяются два слоя:

- **Structure** (что является узлом, его дети, `code` / `display_code` / `name` / флаги
  `is_leaf` / `is_codeless` / `is_group` / `import_duty`) — сейчас `_resolve_tree_node`
  → `_build_wrapped_tree` → `_build_tree`. **Только этот слой** переезжает на `CanonicalModel`.
- **Overlay / enrichment** (`_serialize_tree_node`: `duty_rate`, `vat_rate`, `measures`,
  `has_ds` / `has_ss`) — читает БД по коду на каждый запрос. **Не изменяется** (сохраняет
  свежесть ставок, `source_kind` isolation и NTM enforcement).

Мост между слоями: `TreeNode` из `CanonicalModel` → `TreeSerializer.to_legacy_dict(node)`
даёт ровно тот dict-shape, который уже потребляет `_serialize_tree_node`. Canonical-ветка
меняет **источник структуры**, а сериализатор обогащения переиспользуется без изменений —
это гарантирует идентичность JSON-контракта (ADR I20).

---

## 1. Goal

Первый production read-path `GET /api/v1/tnved/children/{code}` (и compat
`/api/tnved/children/{code}`) читает **структуру** из `CanonicalModel` вместо legacy
`build_tree()`, за feature flag `CANONICAL_TREE_ENABLED` **default OFF**, с shadow-режимом
и мгновенным откатом одной переменной. Контракт ответа неизменен. Один измеримый результат:
при `CANONICAL_TREE_ENABLED=1` ответ `/children` на всей тест-матрице **идентичен** legacy.

---

## 2. Scope (разрешённые, минимальные изменения)

- `app/config.py` (или `settings` / тонкий accessor) — единая точка чтения feature flags
  (`CANONICAL_TREE_ENABLED`, `CANONICAL_TREE_SHADOW`) с парсингом truthy-значений.
- `app/services/tree_engine/` — **provider/cache** (build-once + инвалидация по revision),
  **bridge** (`CanonicalModel` node → `to_legacy_dict`), **shadow-компаратор** (structural
  + content fingerprint, логирование/метрики). Новые модули внутри `tree_engine/`.
- `app/api/tnved_catalog.py` — **только** ветвление в `list_tnved_children` для `/children`
  (canonical при ON, legacy при OFF; переиспользование `_serialize_tree_node`).
- `customs-clear/backend/tests/` — тесты provider/shadow и ON-vs-OFF parity для `/children`
  (`test_tnved_catalog_api.py`, `test_tree_engine_v2.py`, `test_canonical_tnved_model.py`,
  при необходимости новый файл для provider/shadow).
- `.ai/` — `CURRENT_STATE.md`, `ROADMAP.md`, `DECISIONS.md` (отражение состояния,
  закрытие Open Decisions «Feature flag strategy» / «First production read-path»).

---

## 3. Out of scope (запрещено)

- ❌ Менять JSON-контракт ответа `/children` (набор и семантику полей `items[]`).
- ❌ Менять / удалять / депрекейтить legacy `build_tree()` (остаётся production и oracle).
- ❌ Менять `semantic_navigation`.
- ❌ Менять frontend.
- ❌ Менять БД / схему / Alembic-миграции.
- ❌ Трогать NTM / Duty enforcement и `source_kind` isolation (advisory ≠ enforcement).
- ❌ Подключать остальные endpoints (`/node`, `/preview`, `/{code}`, `hierarchy-tree`, …) —
  только `/children`.
- ❌ Deep-immutability узлов, окончательная формула `stable_id`, полный пересмотр
  `snapshot_id` сверх нужд cache-инвалидации.
- ❌ commit / push без QA + review + одобрения Ivan.

---

## 4. Required behavior

Общий инвариант: мигрирует **только структурный слой** `/children`; overlay/enrichment
(`_serialize_tree_node`) переиспользуется без изменений через bridge `to_legacy_dict(node)`
(ставки/НДС/меры/permit считаются как сейчас). JSON-контракт неизменен (ADR I20).

### 4.1 Feature flags
- **`CANONICAL_TREE_ENABLED`** — serving-флаг, **default OFF** (`AGENTS.md`).
- **`CANONICAL_TREE_SHADOW`** — отдельный флаг наблюдения, независим от serving, **default OFF**.
- Оба **читаются request-time** (не на старте) — обязательное условие мгновенного отката без
  рестарта/деплоя. Единая точка чтения — `app/config`/settings accessor (парсинг truthy).
- Комбинации: `SHADOW=1/ENABLED=0` → служим legacy, сравниваем в фоне; `ENABLED=1` → служим canonical.

### 4.2 Materialized provider / cache
- **Provider строит модель один раз и кэширует** (`TreeParser.parse` → `TreeBuilder.build_model`).
  Владелец — сервис-провайдер в `app/services/tree_engine/` (API модель сам не строит;
  слоистость `api → services`).
- **Тип кэша:** **in-memory singleton** (иммутабельный `CanonicalModel` в процессе).
  **Materialized persistent snapshot / файл / таблица в этой задаче НЕ делаем** — причина:
  минимальный blast radius и быстрый rollback (нет новых артефактов хранения для
  версионирования/инвалидации/отката). Persistent materialization — будущий этап, если
  in-memory окажется дорогим (см. ADR-0002 §3.8.1).
- **Build-once под lock**, конкурентное чтение безопасно (модель иммутабельна). Опциональный
  прогрев в `lifespan` при включённом флаге.
- **Пересборка — при смене revision-маркера. Gate-1 (жёсткий блокер, ADR-0002 §3a):** до
  первого `CANONICAL_TREE_ENABLED=1` **в любом окружении** revision / cache invalidation
  **ОБЯЗАН** учитывать `tnved_commodities` **и** `hs_rates`, влияющие на `leaf_flags` /
  `is_leaf_hs_code`. Пока это не выполнено — serving-флаг включать **запрещено**. Атомарная
  замена инстанса.
- **Validator gate:** `build_model` прогоняет `TreeValidator`; невалидная модель в runtime
  не отдаётся.

### 4.3 `/children` ON / OFF behavior
- **OFF = legacy.** Поведение `/children` бит-в-бит совпадает с текущим (никаких изменений
  на legacy-пути).
- **ON = CanonicalModel.** Структурная резолюция:
  - пустой `code` (список разделов) и Roman-section → chapters — **остаются на таблицах
    Section/Chapter** (никогда не строились через `build_tree`), не меняются;
  - 2-значная группа → дети = heading'и (`CanonicalModel` roots) под 2-значным префиксом
    (детерминированная фильтрация);
  - 4/6/8/10-значные → `model.get_by_code(code)`; дети — `model.children(node)` (depth
    `direct`) или `model.descendants(node)` (depth `all`);
  - спец-кейс синтетического одиночного leaf под leaf-кодом (текущая нормализация к `[]`
    в `list_tnved_children`) сохраняется 1:1.

### 4.4 Shadow mode
- **Сравнивает legacy vs canonical, но служит legacy.** Сравнение — по **структурному** слою
  (`structure_fingerprint` + content: `name`, `display_code`, `is_leaf` / `is_codeless` /
  `is_group`, `import_duty`, `notes`); обогащение из сравнения исключается (одинаково).
- Mismatch логируется (WARNING, с **семплированием**) + метрики `shadow_match` / `shadow_mismatch`.
- Включать в staging → canary; live-shadow — инструмент наблюдения.
- **Gate-2 (критерий serving ON, ADR-0002 §3a):** **полный offline-обход всех
  поддерживаемых `/children` кодов на полной БД должен дать 0 mismatch перед включением
  serving-флага.** Live/семплированный shadow **не заменяет** полный offline-обход.

### 4.5 Fallback / rollback
- **Failure → fallback на legacy, без 500**, если legacy доступен (`AGENTS.md`: не 500 при
  наличии локального fallback). Ошибка логируется (revision/код).
- **Rollback одной переменной:** `CANONICAL_TREE_ENABLED=0` → следующий запрос идёт по legacy
  (флаг request-time), мгновенно, без рестарта. `CANONICAL_TREE_SHADOW=0` — независимо.

---

## 5. Acceptance Criteria

- [ ] `CANONICAL_TREE_ENABLED` (default OFF) управляет только `/children`, читается request-time.
- [ ] **OFF** — поведение `/children` **байт-в-байт** = текущему legacy (регресс-тесты не меняются).
- [ ] **ON** — JSON-ответ `/children` **идентичен** legacy на тест-матрице кодов:
      heading (напр. `8517`), одиночный L6 (`0302`-ветвь), L8, декларируемый leaf,
      pad-код, subheading-group (`0101`), 2-значная группа (`01`), Roman-section.
- [ ] **Gate-1 (блокер):** provider build-once + инвалидация по revision, **обязательно**
      покрывающему `tnved_commodities` **и** `hs_rates` (leaf_flags / `is_leaf_hs_code`);
      без этого `CANONICAL_TREE_ENABLED=1` **запрещён в любом окружении**.
- [ ] Тип кэша — **in-memory singleton**; persistent materialization в этой задаче не делается.
- [ ] Validator gate: невалидная модель не попадает в runtime; `/children` fail-safe
      fallback на legacy + лог, **без 500**.
- [ ] `CANONICAL_TREE_SHADOW` логирует structural+content mismatch с семплированием.
- [ ] **Gate-2 (блокер):** полный offline-обход всех поддерживаемых `/children` кодов на
      полной БД даёт **0 mismatch** перед включением serving-флага.
- [ ] Rollback подтверждён: `CANONICAL_TREE_ENABLED=0` немедленно возвращает legacy без рестарта.
- [ ] Запрещённые пути не изменены: `build_tree()`, `semantic_navigation`, frontend,
      БД/Alembic, NTM/Duty enforcement, `source_kind` isolation, прочие endpoints.
- [ ] Тесты (см. §7) проходят; добавлены provider/shadow и ON-vs-OFF parity тесты.
- [ ] `.ai/CURRENT_STATE.md` / `ROADMAP.md` / `DECISIONS.md` обновлены (закрыты Open
      Decisions «Feature flag strategy» и «First production read-path»).
- [ ] QA Report с фактическим выводом команд (§7).

---

## 6. Risks / notes

| # | Риск | Митигирование |
|---|------|---------------|
| R1 | **`snapshot_id` / revision не включает влияние `hs_rates`** → stale-модель после ingestion (leaf-флаги зависят от `hs_rates`) | revision-marker кэша охватывает `tnved_commodities` **и** `hs_rates`; переиспользовать/расширить `preview_cache_revision`; закрыть Critical-долг из `CURRENT_STATE §8` в объёме, нужном для инвалидации |
| R2 | **Латентность первого запроса** (build-on-first-request) / гонки | build-once под lock; опциональный прогрев в `lifespan`; иммутабельная модель → безопасное конкурентное чтение |
| R3 | **Пустая/усечённая тестовая БД** даёт ложные расхождения (dev-окружение ≠ prod 52k) | parity/shadow гонять и на полном prod-объёме; отдельный оффлайн полный обход всех кодов до serving ON; не считать усечённую БД источником истины |
| R4 | **Shadow overhead** (удвоение работы) | семплирование логов; включать только staging/canary; полный обход — офлайн-скрипт, не live-трафик |
| R5 | **Stale cache** при изменении данных | инвалидация по revision-маркеру (R1); атомарная замена инстанса при смене revision |
| R6 | Структурное расхождение canonical vs legacy на краевых кодах | shadow + full-tree parity; обязательный оффлайн-обход до включения |
| R7 | 2-значный chapter-путь / Roman-section слабее покрыты parity | доп. shadow на chapter-уровне; эти ветки частично остаются на DB-таблицах |

---

## 7. QA commands

```bash
cd customs-clear/backend

# ON-vs-OFF контракт-parity первого read-path
pytest tests/test_tnved_catalog_api.py -k children -v

# Регрессия типизированного контура + build_model
pytest tests/test_tree_engine_v2.py -v

# CanonicalModel: индексы/навигация/freeze/validator gate/content parity
pytest tests/test_canonical_tnved_model.py -v

# Новые тесты provider/shadow (добавляются этой задачей)
# pytest tests/test_canonical_provider.py -v
# pytest tests/test_canonical_children_shadow.py -v
```

Также приложить фактический вывод:

```bash
git status
git diff --stat
git diff --name-status
```

QA по `.ai/QA_PROTOCOL.md`; отчёт по `.ai/ENGINEERING_PROTOCOL.md` §12.

> **Замечание про окружение:** dev-БД может быть усечённой (напр. ~14k позиций вместо
> ~52k prod). Часть API-children тестов чувствительна к данным — фиксировать baseline
> до/после и разделять «расхождение из-за данных» и «расхождение из-за кода» (см. R3).

---

## 8. Rollback plan

- `CANONICAL_TREE_ENABLED=0` → следующий запрос идёт по legacy (флаг читается request-time,
  откат мгновенный, без рестарта/деплоя).
- Опционально: сброс singleton-кэша модели (не обязателен для корректности).
- `CANONICAL_TREE_SHADOW=0` отключается независимо.
- Legacy `build_tree()` не удаляется (ADR §8) — остаётся полностью рабочим oracle.
- Нет миграций/схемы → на уровне данных откатывать нечего.

---

## 9. Commit rules

- Commit **только после QA + Review**.
- Push **только после одобрения Ivan**.
- Feature flags остаются default OFF до явного включения Иваном.
