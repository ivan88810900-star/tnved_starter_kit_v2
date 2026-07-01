# ADR-0002 — First production read-path on CanonicalModel (`/children`)

> Status: **Proposed**
> Role: Architect / Decision Memo
> Date: 2026-07-01

| Поле | Значение |
|------|----------|
| **ID** | ADR-0002 |
| **Название** | First production read-path on CanonicalModel (`/children`) |
| **Статус** | Proposed (требует утверждения Ivan до кода) |
| **Роль** | Architect |
| **Дата** | 2026-07-01 |
| **Контекст-источники** | ADR-0001 (`.ai/decisions/ADR-0001-canonical-tnved-model.md`), `.ai/CURRENT_STATE.md` §2b/§6/§8/§9, `.ai/ROADMAP.md` §0/§2, `.ai/tasks/TASK-CANONICAL-004.md`, `AGENTS.md`, код `app/api/tnved_catalog.py`, `app/services/tree_engine/` |
| **Решает развилку** | Как **впервые** и **безопасно** перевести production read-path со структуры legacy `build_tree()` на `CanonicalModel`, не меняя source of truth целиком и необратимо |
| **Влияет на** | API `/children`, кэш/производительность дерева, план миграции ADR-0001 (Этап 3), overlay-слои (косвенно) |
| **Reversibility** | **Высокая** — переключение одной переменной окружения (`CANONICAL_TREE_ENABLED`), legacy остаётся рабочим и oracle |

---

## 0. TL;DR

`CanonicalModel` уже материализован и проверен parity-тестами (structural + content), но
**runtime всё ещё читает структуру из legacy `build_tree()`** — до 2 000 000 строк на
запрос. Architecture Review отметил: перевод первого endpoint на `CanonicalModel`
**меняет source of truth для API** и потому требует Decision Memo до кода.

**Решение (proposed):** первым перевести **только** `GET /api/v1/tnved/children/{code}`
(+ compat `/api/tnved/children/{code}`), **только его структурный слой**, за feature flag
`CANONICAL_TREE_ENABLED` (**default OFF**, читается **request-time**), с отдельным
`CANONICAL_TREE_SHADOW` для сравнения legacy vs canonical. Overlay/enrichment
(`_serialize_tree_node`: ставки/НДС/меры/permit) **остаётся существующим legacy-путём**.
Legacy `build_tree()` **остаётся oracle**. Контракт ответа **не меняется**. Откат —
**одной переменной**.

---

## 1. Контекст

- ADR-0001 зафиксировал `CanonicalModel` как целевой Source of Truth и план миграции
  (Этап 3 = «API за feature flag читает Canonical Model», default OFF, A/B с legacy).
- В `main`: `Parser → StructureNormalizer → TreeBuilder → CanonicalModel` (индексы
  достижимости + навигация, freeze/read-only, validator gate, full-tree structural +
  content parity). Контур **не подключён** к runtime.
- `list_tnved_children` резолвит структуру через `_resolve_tree_node → _build_wrapped_tree
  → _build_tree` и обогащает каждый узел через `_serialize_tree_node` (ставки/НДС/меры/
  permit — читаются из БД по коду на запрос).
- Architecture Review: смена источника структуры для API — это изменение source of truth
  для внешнего контракта ⇒ Decision Memo обязателен (`AGENTS.md`: «меняется API / source
  of truth» → Decision Memo).

---

## 2. Ключевое разделение слоёв

Внутри `list_tnved_children` существуют два независимых слоя:

- **Structure** — какие узлы существуют, их дети, `code`/`display_code`/`name`/флаги
  (`is_leaf`/`is_codeless`/`is_group`)/`import_duty`. **Только он** мигрирует на `CanonicalModel`.
- **Overlay/enrichment** — `_serialize_tree_node`: `duty_rate`, `vat_rate`, `measures`,
  `has_ds`/`has_ss`. Читает БД по коду на запрос. **Не мигрирует.**

Мост: `TreeNode` → `TreeSerializer.to_legacy_dict(node)` даёт тот же dict-shape, который
уже потребляет `_serialize_tree_node`. Меняется **источник структуры**, а обогащение
переиспользуется без изменений — это математически гарантирует идентичность контракта.

---

## 3. Зафиксированные решения и обоснования

### 3.1 Почему `/children` — первый endpoint
- **Максимальная стоимость legacy:** перечитывает до 2M строк на каждый запрос
  (`CURRENT_STATE §6`, `ROADMAP §2`) → максимальный выигрыш от «строим один раз».
- **Чистая read-only навигация** — прямое соответствие `CanonicalModel` (`get_by_code`,
  `children`, `descendants`, `path`).
- **Уже покрыт parity** (structural + content) против legacy → минимальный риск.
- **Узкий изолированный контракт** (`items[]`) — легко shadow-сравнивать и откатывать.

### 3.2 Почему feature flag default OFF
- Дисциплина `AGENTS.md`: feature flags **default OFF** до явного утверждения Ivan.
- Смена source of truth для API обратима только при выключенном-по-умолчанию контуре;
  включение — осознанное решение после shadow-валидации.

### 3.3 Почему флаг читается request-time
- Мгновенный откат **без рестарта/деплоя** (см. §3.10). Если читать на старте, откат
  требует перезапуска — неприемлемо для source-of-truth переключения.
- Чтение флага дешёвое; тяжёлая модель кэшируется отдельно (§3.8), поэтому request-time
  чтение флага не бьёт по производительности.

### 3.4 Почему нужен отдельный `CANONICAL_TREE_SHADOW`
- Требуется сравнивать canonical vs legacy **на реальном трафике, продолжая служить
  legacy** — до переключения serving-флага. Совмещать это с `CANONICAL_TREE_ENABLED`
  нельзя: serving и наблюдение — ортогональные режимы.
- Комбинации: `SHADOW=1/ENABLED=0` — служим legacy, сравниваем в фоне; `ENABLED=1` —
  служим canonical. Независимость даёт canary/staging-валидацию без риска для ответа.

### 3.5 Почему legacy остаётся oracle
- ADR-0001 §8/§9: legacy `build_tree()` = production + oracle **до достижения parity** и
  стабилизации флага; удаляется только на Этапе 6. Он — эталон сравнения в shadow и
  fallback при сбое (§3.9).

### 3.6 Почему response contract не меняется
- Инвариант I20 (обратная совместимость API). Frontend и внешние клиенты не должны
  замечать переключения. Поскольку меняется только источник структуры, а обогащение —
  тот же `_serialize_tree_node`, набор и семантика полей `items[]` идентичны.

### 3.7 Почему overlay/enrichment остаётся существующим путём (`_serialize_tree_node`)
- Обогащение зависит от **свежих** данных БД (ставки/НДС/меры/permit) и от NTM/Duty-логики
  с `source_kind` isolation и enforcement/advisory-семантикой. Перенос его в модель на этом
  этапе (a) риск скрытой смены семантики (advisory→ERROR), (b) выходит за scope, (c) ломает
  свежесть. Поэтому bridge подаёт `to_legacy_dict(node)` в существующий сериализатор —
  ноль изменений в overlay.

### 3.8 Почему CanonicalModel-кэш строится один раз, а не per request
- Построение = парсинг всей номенклатуры + сборка дерева + validator gate — дорого.
  Строить на запрос = воспроизвести худшую сторону legacy (перечитывание на запрос).
- Модель **иммутабельна** → безопасно разделяется между запросами; провайдер строит
  build-once под lock, пересобирает только при смене revision-маркера, атомарно заменяя
  ссылку. Владелец — сервис-провайдер в `tree_engine/` (слоистость `api → services`).

### 3.9 Как работает fallback на legacy при ошибке CanonicalModel
- Если провайдер не смог построить/валидировать модель, либо резолюция узла в canonical-
  ветке бросает исключение — `/children` **прозрачно откатывается на legacy-путь** для
  этого запроса и **не возвращает 500**, если legacy доступен (`AGENTS.md`: не 500 при
  наличии локального fallback). Ошибка логируется (с revision/кодом).
- Validator gate гарантирует, что невалидная модель **не попадает** в runtime.

### 3.10 Rollback одной переменной
- `CANONICAL_TREE_ENABLED=0` → следующий запрос идёт по legacy (флаг request-time).
  Мгновенно, без рестарта/деплоя. `CANONICAL_TREE_SHADOW=0` отключается независимо.
  Кэш можно сбросить, но для корректности это не требуется. Миграций БД нет — на уровне
  данных откатывать нечего.

### 3.11 Почему source of truth меняется только частично и временно
- **Частично:** мигрирует только структура `/children`; overlay, прочие endpoints,
  section/chapter-навигация из таблиц — без изменений. Это ограничивает радиус изменения
  source of truth одним узким контрактом.
- **Временно/обратимо:** за флагом default OFF; legacy остаётся oracle и fallback.
  Полный перевод source of truth на `CanonicalModel` — последующие этапы ADR-0001
  (overlays на anchor, затем удаление legacy) отдельными ADR/PR.

---

## 4. Риски

| # | Риск | Влияние | Митигирование |
|---|------|---------|---------------|
| R1 | **`snapshot_id` inputs неполны** (только `db_codes`) — не отражает все структуро-влияющие входы | Некорректная инвалидация кэша | revision-маркер кэша должен покрывать структуро-влияющие таблицы (см. R2) |
| R2 | **`hs_rates` влияет на структуру** через leaf-флаги (synth-leaf/codeless классификация), но не входит в `snapshot_id` | Stale-структура после ingestion ставок | revision-маркер инвалидируется и при `tnved_commodities`, и при `hs_rates`; переиспользовать/расширить `preview_cache_revision` |
| R3 | **Stale cache** при изменении данных | Расхождение с БД | инвалидация по revision (R2); атомарная замена инстанса |
| R4 | **Shadow overhead** — удвоение работы на запрос | Латентность/нагрузка | семплирование логов; включать только staging/canary; полный обход — офлайн-скрипт |
| R5 | **Пустая/усечённая dev-БД** даёт ложные «расхождения» (dev ≠ prod 52k) | Ложные выводы QA | parity/shadow на полном prod-объёме; отдельный оффлайн-обход всех кодов; разделять «данные» vs «код» |
| R6 | **Performance первого запроса** (build-on-first-request) / гонки | Всплеск латентности | build-once под lock; опциональный прогрев в `lifespan`; иммутабельность → безопасное чтение |
| R7 | **Structural mismatch** canonical vs legacy на краевых кодах (pad §1, L6/L8 §2/§3, subheading-group §6, 2-значная группа, roman-section) | Расхождение контракта | shadow + full-tree parity; обязательный оффлайн-обход до serving ON; mismatch = блокер |

---

## 5. Acceptance criteria (ADR-level)

- [ ] Решение утверждено Ivan (Proposed → Accepted) **до** любого кода.
- [ ] Реализация соблюдает разделение слоёв (§2): мигрирует только структура `/children`.
- [ ] `CANONICAL_TREE_ENABLED` default OFF, request-time; OFF = byte-compatible legacy.
- [ ] ON: JSON `/children` идентичен legacy на тест-матрице (heading/L6/L8/leaf/pad/
      subheading-group/2-значная группа/roman-section).
- [ ] `CANONICAL_TREE_SHADOW` независим; логирует structural+content mismatch с
      семплированием; на репрезентативном обходе mismatch = 0.
- [ ] Provider build-once + инвалидация по revision, покрывающему `tnved_commodities` **и**
      `hs_rates`.
- [ ] Validator gate + fail-safe fallback на legacy без 500.
- [ ] Rollback подтверждён: `CANONICAL_TREE_ENABLED=0` мгновенно возвращает legacy.
- [ ] Запрещённые пути не изменены: `build_tree()`, `semantic_navigation`, frontend,
      БД/Alembic, NTM/Duty enforcement, `source_kind` isolation, прочие endpoints, JSON-контракт.

---

## 6. Реализация

Инженерная задача формализована в **`.ai/tasks/TASK-CANONICAL-004.md`** (Goal / Scope /
Out of scope / Required behavior / Feature flags / Materialized provider / `/children`
ON-OFF / Shadow / Fallback-Rollback / Acceptance / QA / Commit rules). Код — только после
перехода этого ADR в **Accepted** (Ivan) и прохождения QA + Review.

---

## Decision-точки для Ivan

1. **Утвердить `/children` как первый read-path** (vs выбрать другой endpoint / отложить).
2. **Утвердить состав revision-маркера кэша** (минимум `tnved_commodities` + `hs_rates`) —
   без этого инвалидация ненадёжна (R1/R2).
3. **Утвердить критерий «parity достигнута → serving ON»** (полный оффлайн-обход, 0 mismatch).
4. **Материализация модели:** in-memory (текущее) vs переживающий рестарт снапшот — до
   включения на prod-объёме (память, см. R6).

---

## Статус

**Proposed.** Требует утверждения Ivan (Accepted) до реализации. Связанные документы:
ADR-0001, `.ai/tasks/TASK-CANONICAL-004.md`, `.ai/CURRENT_STATE.md` §9, `.ai/DECISIONS.md`.
