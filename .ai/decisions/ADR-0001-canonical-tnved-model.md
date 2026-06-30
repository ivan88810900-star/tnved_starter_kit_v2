# ADR-0001 — Canonical TNVED Model

> Status: Accepted
> Accepted by: Ivan
> Date: 2026-06-30

| Поле | Значение |
|------|----------|
| **ID** | ADR-0001 |
| **Название** | Canonical TNVED Model |
| **Статус** | Accepted |
| **Роль** | Architect |
| **Дата** | 2026-06-30 |
| **Контекст-источники** | `.ai/VISION.md`, `.ai/ARCHITECTURE.md`, `.ai/CURRENT_STATE.md`, `.ai/KNOWN_PITFALLS.md`, `.ai/ROADMAP.md`, `.ai/ENGINEERING_PROTOCOL.md`, `.ai/agents/architect.md`, код `tree_engine/`, `tnved_tree/`, `semantic_navigation/`, `models/tnved.py`, `api/tnved_catalog.py` |
| **Решает развилку** | Где находится Source of Truth продукта и как от него зависят все остальные слои |
| **Влияет на** | Дерево, Semantic Navigation, API, AI, NTM, Duty Engine, Search, RAG, Knowledge Graph |
| **Reversibility** | Высокая на этапах 1–3 (параллельный контур), низкая после отказа от `_build_tree()` |

---

## 0. Резюме для занятого читателя (TL;DR)

Сегодня **истиной де-факто является функция `build_tree()`**, которая на каждый запрос перечитывает до 2 000 000 строк из SQLite и собирает нетипизированное `dict`-дерево с синтетическими узлами (L6/L8), нестабильными представлениями и без устойчивых идентификаторов. Все остальные слои (API, NTM, пошлины, поиск) либо повторяют это чтение, либо строят собственную параллельную истину.

ADR фиксирует решение: **Source of Truth продукта Tariff — это Canonical TNVED Model: единое, детерминированное, иммутабельное, версионируемое представление всей номенклатуры с устойчивыми ID, построенное один раз и разделяемое всеми слоями.**

SQLite перестаёт быть «истиной» и становится слоем **хранения и ingestion**. Дерево, семантика, AI, NTM, пошлины, поиск, RAG, граф знаний — это **проекции и overlay** поверх Canonical Model, а не независимые перечитывания БД.

---

## 1. Что является Source of Truth продукта Tariff

### 1.1 Постановка вопроса

Vision (`.ai/VISION.md`) формулирует продукт так:

> «Tariff помогает пользователю **правильно классифицировать товар** для таможенного оформления — а не просто показывать коды ТН ВЭД.»

Из этого следует ключевой архитектурный вывод: **истина продукта — это не таблица, не дерево, не парсер и не API.** Это **классификационная модель номенклатуры**: устойчивое представление того, *что есть товарная позиция, где она находится в иерархии, какие у неё дочерние/родительские отношения, и какой у неё неизменный идентификатор* — к которому затем привязываются все остальные знания (смысл, пошлина, НТМ, обоснование AI).

### 1.2 Что НЕ является Source of Truth (и почему)

| Кандидат | Почему НЕ истина |
|----------|------------------|
| **SQLite (`tnved_commodities`)** | Это **физический носитель/выгрузка**. В нём хранятся только 10-значные padded-коды и pad-коды `XXXX000000` (см. `KNOWN_PITFALLS.md` §1). Структура иерархии (L4/L6/L8/L10), бескодовые заголовки, смысловые группы — в БД **отсутствуют как явные сущности**; они вычисляются. БД — вход, а не контракт. |
| **Дерево (`build_tree()`)** | Это **алгоритм + эфемерный результат**. Дерево пересобирается на каждый запрос (`_build_wrapped_tree` в `customs-clear/backend/app/api/tnved_catalog.py`), не имеет стабильных ID, содержит синтетические узлы и нетипизированные `dict`. Это **проекция истины, а не истина**. |
| **Parser** | Это **способ чтения** носителя. Меняется источник — меняется parser, истина не должна меняться. |
| **API** | Это **контракт доставки** проекции наружу. Сериализация (`_serialize_tree_node`) — это вид, не модель. |

### 1.3 Определение центральной модели продукта

> **Canonical TNVED Model** — единственная авторитетная, типизированная, детерминированная и иммутабельная in-memory/материализованная модель всей номенклатуры ТН ВЭД ЕАЭС, в которой каждый структурный узел (раздел → … → декларируемый код) имеет **устойчивый идентификатор**, явный **тип**, явные **отношения parent/children**, и точку привязки (anchor) для всех доменных оверлеев (смысл, пошлина, НТМ, AI, RAG).

Признаки того, что именно это — истина:
1. **Один источник** — все слои читают из неё, а не из SQLite напрямую.
2. **Детерминизм** — один и тот же снапшот БД → один и тот же набор узлов и ID.
3. **Иммутабельность** — модель не мутируется на лету ни AI, ни overlay; новые знания **аннотируют**, а не **переписывают**.
4. **Адресуемость** — любой узел можно сослаться стабильным ID из NTM, пошлин, журнала решений AI, RAG-чанков и графа знаний.

Зачатки этой модели уже есть в коде в виде **двух параллельных типизированных контуров**, которые пока не объединены и не подключены:
- `tree_engine/` — типизированные `TreeNode/HeadingNode/CommodityNode` (структурная истина);
- `semantic_navigation/` — типизированный смысловой overlay (`SemanticNode`), уже соблюдающий ключевые инварианты (реальные коды только 4/10 цифр, группы без кода, group-removal invariance).

**Решение ADR:** объединить структурный контур (`tree_engine`) и инвариантную дисциплину (`semantic_navigation`) в один Canonical Model, на который сядут все остальные слои.

---

## 2. Окончательная архитектура и ответственность слоёв

### 2.1 Целевая слоистая архитектура

```
┌───────────────────────────────────────────────────────────────────┐
│  INGESTION & PERSISTENCE                                            │
│  [1] SQLite (customs.db)                                           │
│        tnved_commodities / tnved_sections / tnved_chapters /       │
│        hs_rates / hs_duty_rules / ntm_measures_v2 / ...            │
└───────────────────────────────┬───────────────────────────────────┘
                                 │  (read-only, один раз на снапшот)
┌───────────────────────────────▼───────────────────────────────────┐
│  CONSTRUCTION PIPELINE (детерминированный, офлайн/при старте)      │
│  [2] Parser     — SQLite → плоская промежуточная модель           │
│  [3] Recovery   — восстановление неявной структуры (L6/L8, pad,    │
│                   breadcrumb, имена) из «сырых» строк              │
│  [4] Builder    — сборка иерархии + Validator + Stable ID         │
└───────────────────────────────┬───────────────────────────────────┘
                                 │  freeze()
┌───────────────────────────────▼───────────────────────────────────┐
│  ✦ [5] CANONICAL TNVED MODEL ✦   (Source of Truth, immutable)     │
│        узлы + stable id + parent/children + provenance + anchors   │
└───────────────────────────────┬───────────────────────────────────┘
                                 │  (никто ниже не читает SQLite напрямую)
        ┌────────────────────────┼────────────────────────┐
        ▼                        ▼                         ▼
┌───────────────┐   ┌──────────────────────┐   ┌────────────────────┐
│ [6] Semantic  │   │  Overlay-привязки      │   │  [12] Search index │
│   Navigation  │   │  по anchor (stable id):│   │  (FTS / embeddings)│
│ (overlay)     │   │   [9]  NTM             │   │                    │
└──────┬────────┘   │   [10] Duty Engine     │   └─────────┬──────────┘
       │            │   Notes / Expl. Notes  │             │
       ▼            └──────────┬─────────────┘             │
┌───────────────┐             │                            │
│ [7] API        │◄───────────┴────────────────────────────┘
│ (serializer →  │
│  стабильный    │
│  контракт)     │
└──────┬─────────┘
       ▼
┌───────────────┐   ┌────────────────────┐   ┌────────────────────┐
│ [8] AI Class.  │──▶│ [13] RAG           │──▶│ [14] Knowledge      │
│ (read-only)    │   │ (chunks ⇄ node id) │   │      Graph (node id │
│                │   │                    │   │      = вершина)      │
└────────────────┘   └────────────────────┘   └────────────────────┘
```

### 2.2 Ответственность каждого слоя

| # | Слой | Ответственность | Чего НЕ делает |
|---|------|------------------|----------------|
| 1 | **SQLite** | Хранение сырых данных и результатов ingestion; единственная точка записи (через Alembic). Источник снапшота для построения модели. | Не определяет структуру иерархии; не вызывается downstream-слоями на каждый запрос. |
| 2 | **Parser** | Прочитать `tnved_commodities` + примечания (`collect_chapter_notes`) → нормализованная плоская промежуточная модель `ParsedCommodityRecord`. Нормализация кода (`digits`/`zfill`), очистка ставки (`format_duty`), отбраковка obsolete-reserved. Уже реализовано в `tree_engine/parser.py`. | Не строит иерархию; не классифицирует узлы; не знает про L6/L8. |
| 3 | **Recovery** | Восстановить **неявную** структуру, которой нет в БД: pad-коды → имена заголовков (`split_position_pad_name`), синтез бескодовых L6/L8-заголовков, breadcrumb, выбор «лучшего имени» (`best_name_for_group`), снятие ведущих тире (`strip_leading_dashes`). Сейчас это «спрятано» внутри `_classify()` в `build_tree.py`. **Стадия внутри `tree_engine`, не отдельный top-level module.** | Не материализует fake-коды; не выдумывает узлы, не выводимые из данных. |
| 4 | **Builder + Validator** | Собрать иерархию из плоской + восстановленной структуры, присвоить **stable ID**, выставить тип узла, прогнать инварианты (`tree_engine/validator.py`) ДО публикации. | Не сериализует наружу; не привязывает пошлины/НТМ. |
| 5 | **Canonical TNVED Model** | Быть **единственной истиной**: иммутабельный граф узлов с ID, типами, отношениями, provenance и точками привязки overlay. Версионируется (snapshot revision). | Ничего не вычисляет по запросу клиента; не содержит бизнес-логику доставки. |
| 6 | **Semantic Navigation** | **Overlay** смысловых групп («лососевые → форель») поверх канонических узлов, без изменения структуры и набора реальных кодов (group-removal invariance уже проверяется). | Не меняет коды; не создаёт virtual L5; не подменяет структурное дерево. |
| 7 | **API** | Сериализовать проекцию Canonical Model в стабильный контракт (`/api/v1/tnved/...`), с обратной совместимостью. | Не строит дерево; не читает 2M строк; не содержит доменную логику (`ENGINEERING_PROTOCOL` §7). |
| 8 | **AI Classification** | Предлагать код + обоснование + confidence, **ссылаясь на stable node id** канонической модели; писать в журнал решений ссылку на узел. | Не изменяет модель (read-only к истине). |
| 9 | **NTM** | Привязывать нетарифные меры к **anchor-узлам** (definite → enforcement, possible/needs_clarification → advisory), сохраняя `source_kind` isolation (`AGENTS.md`). | Не поднимает ERROR на advisory; не смешивает official/legacy. |
| 10 | **Duty Engine** | Считать пошлину/НДС/сборы по anchor-узлу + страна, используя `hs_rates`/`hs_duty_rules`/преференции. | Не хардкодит НДС (берёт из данных); не дублирует обход дерева. |
| 11 | **Notes / Explanatory Notes** | Примечания разделов/глав и пояснения ЕТН ВЭД как overlay-аннотации на узлах (раздел/глава/позиция). | Не встраиваются в имя узла; остаются отдельным слоем. |
| 12 | **Search** | Индексировать узлы Canonical Model (FTS5 + embeddings) и возвращать **node id**, а не «сырые» строки. | Не строит собственную параллельную истину номенклатуры. |
| 13 | **RAG** | Связывать чанки нормативных документов с node id; обогащать AI-обоснование. | Не является источником структуры. |
| 14 | **Knowledge Graph** | Узлы Canonical Model = вершины; рёбра = parent/child, semantic-группы, меры, преференции, предрешения. Stable ID — естественный первичный ключ графа. | Не создаёт узлы без провенанса в Canonical Model. |

**Ключевое правило слоистости (из `architect.md`): `api → services → models`, services не импортирует api.** Canonical Model живёт в `services/`, API только сериализует.

---

## 3. Описание Canonical TNVED Model

### 3.1 Сущности (узлы)

Тип узла должен быть явным (как уже сделано в `tree_engine/models.py:NodeType` и `semantic_navigation/models.py:SemanticNodeType`). Минимальный полный набор структурных сущностей:

| Сущность | Источник в текущем коде | Несёт реальный код? |
|----------|--------------------------|---------------------|
| **Section** (раздел, римский I–XXI) | `Section` (`models/tnved.py`), `_wrap_in_sections` | Нет (навигатор) |
| **Chapter** (группа 2 знака) | `Chapter` | Нет (навигатор) |
| **Heading** (позиция 4 знака) | `HeadingNode`, `build_tree` p4-группировка | Да (4 цифры) |
| **Subheading** (субпозиция L6) | `_classify` L6-ветвь, `node_level==6` | Да (10-цифр канонический) либо бескодовый заголовок |
| **DashHeader / ClassificationGroup** (бескодовый заголовок) | `is_codeless=True`, `ClassificationGroupNode` | **Нет** (структурный группировщик) |
| **Subheading L8** (подсубпозиция) | `_classify` L8-ветвь | Да либо бескодовый |
| **Commodity / Leaf** (декларируемый 10-значный код) | `CommodityNode`, `is_leaf=True` | Да (10 цифр) |

Семантический overlay добавляет: **ClassificationGroup / ClassificationSubgroup** (смысловые «лососевые», «тунец → тунец синий»), которые **не несут код** (`GROUP_NODE_TYPES`).

### 3.2 Атрибуты узла (обязательные поля Canonical Model)

| Группа | Поля | Комментарий |
|--------|------|-------------|
| **Stable ID** | `stable_id` | Детерминированный, воспроизводимый между сборками (см. §3.4). **Сейчас отсутствует** — `tree_engine` использует `uuid4()`, что недетерминировано. Это разрыв, который ADR обязывает закрыть. |
| **Identity** | `node_type`, `level` (4/6/8/9/10), `code` (или `None` для групп), `display_code` | `display_code` без пробелов (см. `ROADMAP` §12). |
| **Relationships** | `parent_id`, `children[]` | Граф родитель/дети; для overlay — `anchor_node_id`. |
| **Content** | `title` (очищенное имя), `raw_title` | Очистка через `strip_leading_dashes`. |
| **Notes** | `section_notes`, `chapter_notes` | Overlay, не часть имени. |
| **Measures** | `ntm_refs[]` (definite/advisory), `permit_flags` | Привязка по anchor, не вшита в узел структуры. |
| **Rates** | `duty_ref`, `vat_ref`, `excise_ref`, `preferences` | Ссылки на `hs_rates`/правила, вычисляются Duty Engine. |
| **Metadata** | `is_codeless`, `is_synthetic`, `is_leaf`, `is_group`, provenance-флаги | `is_synthetic` уже учитывается в `tree_engine/validator.py` для fake_code-проверки. |
| **Aliases** | `aliases[]` (синонимы для поиска), `previous_codes[]` | Для Search/AI; основа сопоставления при ревизиях номенклатуры. |
| **History** | `valid_from`, `valid_to`, `superseded_by` | Версионность номенклатуры (ЕТН ВЭД меняется решениями ЕЭК). |
| **Provenance** | `source_kind`, `source_revision`, `snapshot_id` | Изоляция official vs legacy (`AGENTS.md`); провенанс ставок уже есть в `SpecialDuty.*_source_*`. |

### 3.3 Что нужно добавить сверх перечисленного в задаче

Помимо предложенного списка (Section…Provenance), Canonical Model **обязана** иметь:

1. **Snapshot/Model revision** — версия всей модели = хеш снапшота БД. Без неё нельзя ни кэшировать, ни инвалидировать, ни воспроизводить (см. `ROADMAP` §2: cache-key = prefix + DB revision).
2. **Anchor-контракт для overlay** — формальный способ для NTM/Duty/Semantic/RAG ссылаться на узел (`anchor_node_id` + `code`), а не на «сырой код».
3. **Reachability-индекс** — `code → stable_id` и `prefix → node`, чтобы Duty/NTM/Search не обходили дерево.
4. **Determinism contract** — функция сборки чистая относительно снапшота (никаких `uuid4`, времени, случайности).
5. **Breadcrumb / path** — путь от раздела до узла как первоклассный атрибут (нужен AI-обоснованию и UX).

### 3.4 Формула Stable ID (предлагаемая, детерминированная)

Текущие `uuid4()` (`tree_engine/models.py:_new_id`, `semantic_navigation/models.py:_new_id`) **нарушают детерминизм**. Предложение:

- Для узлов с кодом: `stable_id = f"{snapshot}:{code}:{level}"` или хеш от `(code, level, node_type)`.
- Для бескодовых/семантических групп: уже есть детерминированный паттерн `group_key = f"{heading4}:group:{source_code}:{title}"` в `builder.py` — его и канонизировать как основу ID.

Это совместимо с заметкой задачи TASK-SEMANTIC-003: *«consider deterministic id from (heading, title, source_code)»*.

---

## 4. Жизненный цикл данных: от SQLite до UI

```
Alembic-миграция / ingestion ── пишет ──▶ SQLite (мутабельно, версионируется миграциями)
        │
        │  снапшот: snapshot_id = hash(tnved_commodities + sections + chapters)
        ▼
[Parser]  rows → list[ParsedCommodityRecord]            (промежуточное, эфемерно)
        ▼
[Recovery] восстановление: pad-имена, L6/L8 заголовки,   (промежуточное, эфемерно)
           breadcrumb, очистка имён
        ▼
[Builder]  типизированные узлы + stable_id + отношения    (строится один раз)
        ▼
[Validator] инварианты выполнены? ── нет ──▶ сборка отклоняется, старая модель остаётся
        │ да
        ▼
freeze() ─▶ ✦ CANONICAL MODEL (snapshot_id) ✦           (IMMUTABLE, разделяемое)
        │
        ├──▶ [Semantic overlay]   аннотации (computed, кэш по snapshot_id)
        ├──▶ [NTM / Duty / Notes] вычисляемые проекции по anchor (computed)
        ├──▶ [Search/Embeddings]  индекс по stable_id (materialized, ребилд при смене snapshot)
        ▼
[API serializer] стабильный JSON (projection, не хранит состояние)
        ▼
        UI
```

### 4.1 Что создаётся на каждом этапе

| Этап | Создаётся | Тип жизненного цикла |
|------|-----------|----------------------|
| SQLite | строки `tnved_commodities` и пр. | Mutable (только через Alembic) |
| Parser | `ParsedCommodityRecord[]`, `db_codes` (frozenset) | Эфемерное, пересоздаётся |
| Recovery | восстановленные имена, синтез-заголовки, breadcrumb | Эфемерное |
| Builder | узлы + stable_id + parent/children | Долгоживущее (до смены snapshot) |
| Canonical Model | замороженный граф + индексы + snapshot_id | **Immutable** |
| Overlay (Semantic/NTM/Duty/Notes) | аннотации по anchor | **Computed**, кэшируется по snapshot_id |
| Search index | FTS5 / embeddings по stable_id | Materialized, ребилд при смене snapshot |
| API | JSON-проекция | Stateless, на каждый запрос |

### 4.2 Иммутабельные vs вычисляемые структуры

- **Immutable (часть истины):** `stable_id`, `code`, `node_type`, `level`, `parent_id`, `children`, breadcrumb, snapshot_id, provenance.
- **Computed (проекции/overlay):** duty_rate, vat_rate, NTM-бэйджи, semantic-группы, поисковая релевантность, RAG-связи, AI-обоснование. Они **читают** истину, но не входят в неё и не мутируют её.

Текущий код это нарушает в двух местах: дерево пересчитывается на каждый запрос (`CURRENT_STATE` §6, `KNOWN_PITFALLS` §3 «производительность»), а `_classify()` мутирует `dict` дважды-небезопасно (`KNOWN_PITFALLS` §14). Canonical Model устраняет оба класса проблем за счёт «строится один раз + immutable».

---

## 5. Инварианты Canonical Model

Многие из них **уже реализованы** в валидаторах — ADR возводит их в ранг контракта всей модели, а не одного экспериментального слоя.

| # | Инвариант | Где уже проверяется | Статус |
|---|-----------|---------------------|--------|
| I1 | **Нет virtual L5** — нет промежуточных кодов 5-й цифры | `semantic_navigation/validator.py:_check_no_virtual_l5` | Есть |
| I2 | **Нет fake codes** — каждый код узла существует в БД (или валидный 4-знач. префикс, или `is_synthetic`) | `tree_engine/validator.py` (fake_code), `semantic .. _check_real_codes` | Есть |
| I3 | **Stable IDs** — ID детерминированы и воспроизводимы между сборками | — (сейчас `uuid4`) | **Разрыв, обязателен** |
| I4 | **Детерминированность** — один снапшот → одна модель (без времени/случайности) | частично (`group_key`) | **Усилить** |
| I5 | **Реальные коды достижимы** — каждый ожидаемый код виден в дереве | `semantic .. _check_reachability` | Есть |
| I6 | **Одна модель истины** — нет параллельных перечитываний SQLite в downstream | — (сейчас нарушено: API, NTM, Duty читают БД отдельно) | **Цель ADR** |
| I7 | **Semantic overlay не меняет структуру** — удаление group-узлов сохраняет набор реальных кодов | `semantic .. _check_group_removal_invariance` | Есть |
| I8 | **AI ничего не изменяет** — классификатор read-only к модели | дисциплина (нет writeback) | Усилить контрактом |
| I9 | **Канонические длины кода** — реальные коды только 4 или 10 цифр | `semantic .. _check_no_virtual_l5` (len ∈ {4,10}) | Есть |
| I10 | **Группы не несут код** — навигаторы и DashHeader без `code`/`import_duty` | `semantic .. _check_groups_have_no_code` | Есть |
| I11 | **Нет дубликатов кода** (кроме codeless-заголовок ↔ его лист) | `tree_engine/validator.py` (allowed_dup), `semantic .. duplicate_code` | Есть |
| I12 | **Нет циклов / orphan / self-child** — корректный DAG-дерево | оба валидатора (`cycle`/`orphan`/`self_child`) | Есть |
| I13 | **Лист без детей** — leaf не имеет дочерних узлов | оба валидатора (`leaf_has_children`) | Есть |
| I14 | **Pad-код не лист** — `XXXX000000` только заголовок, не кликабельный код | `KNOWN_PITFALLS` §1, `tree_engine .. _check_pad_swallowing` | Есть |
| I15 | **Max semantic depth = 2** — overlay не плодит глубину (group → subgroup) | `semantic .. _check_max_semantic_depth` | Есть |
| I16 | **source_kind isolation** — official и legacy не смешиваются без явной merge-policy | `AGENTS.md`, provenance в моделях | Контракт |
| I17 | **enforcement ⊃ только definite** — possible/needs_clarification только advisory | `AGENTS.md`, NTM v2 | Контракт |
| I18 | **Provenance обязателен** — каждый узел/мера знает свой источник и ревизию | частично (`SpecialDuty.*_source_*`) | Расширить |
| I19 | **Snapshot-консистентность** — overlay и индексы привязаны к тому же snapshot_id, что и модель | — | **Новый, обязателен** |
| I20 | **Обратная совместимость API** — сериализация Canonical Model не ломает существующий контракт `/api/v1/tnved` | `ENGINEERING_PROTOCOL` §7 | Контракт |
| I21 | **Idempotent ingestion** — импортёры идемпотентны (повтор не плодит дубли) | `AGENTS.md` | Контракт |
| I22 | **No-writeback** — overlay/AI/RAG физически не имеют ссылки на запись в Canonical Model (frozen) | — | **Новый** |

---

## 6. Как должны выглядеть Parser / Recovery / Builder / Validator / Serializer через год

### 6.1 Parser
- **Останется:** чтение `tnved_commodities` + примечаний, нормализация кода/ставки/имени (`tree_engine/parser.py` уже близок к идеалу).
- **Изменится:** на выходе — не «адаптер к build_tree», а чистый вход Canonical Builder. Добавится вычисление `snapshot_id`.
- **Исчезнет:** дублирующие чтения БД в `_build_wrapped_tree` (`api/tnved_catalog.py`) и в `semantic_navigation/builder.py:_load_records`. Останется один путь чтения.

### 6.2 Recovery (стадия внутри tree_engine)
- **Появится как явная стадия внутри `tree_engine`** (не отдельный top-level module): сегодня логика восстановления неявной структуры размазана внутри `build_tree()/_classify()` (`tnved_tree/build_tree.py`) и `extractor.py`. Через год это — отдельная, тестируемая стадия pipeline: pad-имена, синтез L6/L8-заголовков, breadcrumb, выбор имён, dash-stripping.
- **Останется:** правила синтеза L6/L8 (зафиксированы в `KNOWN_PITFALLS` §2–3), но как **детерминированные функции с `is_synthetic`-маркировкой**, а не in-place мутации `dict`.

### 6.3 Builder
- **Останется:** сборка иерархии 4→6→8→10 + секционная обёртка.
- **Изменится:** перестанет делегировать legacy `build_tree` (сейчас `tree_engine/builder.py` оборачивает legacy `dict`-дерево). Будет строить типизированные узлы напрямую с **детерминированными stable_id**.
- **Исчезнет:** `_CommodityRowAdapter` и round-trip `dict → TreeNode → dict`.

### 6.4 Validator
- **Останется и усилится:** все инварианты §5 как **gate перед freeze()**. Сборка, не прошедшая валидацию, не публикуется (старая модель остаётся активной).
- **Изменится:** из «offline QA, не в production» (`tree_engine/validator.py` docstring) станет обязательной частью build-pipeline.

### 6.5 Serializer
- **Останется:** функция «модель → JSON для API».
- **Изменится:** `tree_engine/serializer.py:to_legacy_dict` сегодня сериализует **обратно в legacy-форму** ради совместимости. Через год legacy-форма — это **только compat-adapter** для старого фронта, а основной сериализатор отдаёт обогащённый контракт со `stable_id`.
- **Исчезнет:** `structure_fingerprint` как способ сравнивать с legacy (нужен только в переходный период для дифф-тестов).

### 6.6 Итоговая таблица «останется / исчезнет»

| Компонент | Через год |
|-----------|-----------|
| `tnved_tree/build_tree.py` (`_classify`, stack-build) | **Исчезает** как runtime-истина; логика мигрирует в Recovery+Builder с тестами |
| `api/tnved_catalog.py::_build_wrapped_tree` (чтение 2M строк на запрос) | **Исчезает**; API читает Canonical Model |
| `tree_engine` адаптеры к legacy | **Исчезают**; Builder самодостаточен |
| `uuid4()` ID | **Исчезают**; детерминированные stable_id |
| `semantic_navigation` overlay | **Остаётся**, но садится на anchor Canonical Model, перестаёт сам читать БД |
| Validator-инварианты | **Остаются и становятся обязательными** |
| Parser | **Остаётся**, единая точка чтения |

---

## 7. Как работают слои после появления Canonical Model (без повторного чтения SQLite)

Принцип: **downstream получает либо саму Canonical Model (in-process), либо её сериализованный снапшот; ни один слой не делает `db.query(Commodity)` для структуры.**

| Слой | До (сейчас) | После (Canonical) |
|------|-------------|-------------------|
| **Semantic Navigation** | `builder.py:_load_records` сам читает `Commodity` по heading | Получает узлы heading из Canonical Model по `anchor_node_id`; строит overlay поверх, кэш по snapshot_id |
| **AI Classification** | Gemini structured JSON, код «вслепую» | Кандидаты привязаны к stable_id; обоснование ссылается на breadcrumb/notes из модели; журнал решений хранит node id |
| **RAG** | PDF/TXT чанки отдельно | Чанк ⇄ stable_id; ретрив отдаёт узлы и их контекст без обхода дерева |
| **Search** | FTS5 по `tnved_commodities.description` | Индекс по узлам Canonical Model; результат — stable_id + breadcrumb (а не сырая строка) |
| **NTM** | `get_full_ntm_requirements` + отдельные lookup'ы | Меры привязаны к anchor; definite→enforcement, possible→advisory; `source_kind` isolation сохранён |
| **Duty Engine** | `payment_engine` тянет `hs_rates` по коду | Считает по anchor-узлу (код + level), reachability-индекс даёт префиксный fallback без обхода |
| **Notes** | `collect_chapter_notes` на каждый build | Notes — overlay-аннотация узлов раздела/главы, читается из модели |
| **Explanatory Notes** | отсутствуют как слой | Привязка пояснений ЕТН ВЭД к узлам по stable_id |

Выигрыш, прямо вытекающий из `CURRENT_STATE` §6 и `ROADMAP` §2: убирается перечитывание до 2M строк на каждый запрос; кэш-инвалидация становится тривиальной (сравнение snapshot_id).

---

## 8. План миграции (до полного отказа от legacy `_build_tree()`)

Миграция строго следует принципу `architect.md`: **«Не переписывать legacy сразу; параллельный контур; один PR — одна архитектурная идея; default OFF за feature flag.»**

### Этап 0 — Фиксация контракта (этот ADR)
- Утвердить Canonical Model как Source of Truth.
- Зафиксировать инварианты §5 и stable_id-формулу §3.4.
- **Без кода.** Выход: ADR + Decision-точки для Ivan.

### Этап 1 — Детерминизм типизированного контура
- Заменить `uuid4()` на детерминированные stable_id в `tree_engine` и `semantic_navigation` (I3/I4).
- Дифф-тест: сериализация `tree_engine` (через `to_legacy_dict`) **байт-в-байт** совпадает с legacy `build_tree` на репрезентативных heading'ах (0302, 0303, 5208, 8517, pad-кейсы). Использовать `structure_fingerprint`.
- Регрессионные тесты дерева (`ROADMAP` §1) — обязательны до миграции.
- Контур остаётся **не подключён к API**.

### Этап 2 — Materialized Canonical Model + Validator-gate
- Builder строит типизированную модель **напрямую** (без делегирования в legacy), Recovery выделен в отдельную стадию внутри `tree_engine`.
- Validator-инварианты — обязательный gate перед freeze().
- Модель строится при старте (`lifespan`) и кэшируется по snapshot_id (`cache_layer.py`).
- **Параллельно** с legacy: оба дерева доступны, сравниваются shadow-тестом в CI (`/api/health/pipeline`).

### Этап 3 — API за feature flag читает Canonical Model
- Новый код-путь `list_tnved_children` читает Canonical Model вместо `_build_wrapped_tree`, **за flag `CANONICAL_TREE_ENABLED` (default OFF)**.
- Контракт ответа неизменен (I20); добавляется только `stable_id` в конец структуры (`ENGINEERING_PROTOCOL` §7 — поля в конец).
- A/B сравнение ответов old vs new на полном наборе heading'ов; расхождения = блокер.

### Этап 4 — Overlay садятся на anchor
- Semantic Navigation, Notes перестают читать БД, работают через anchor.
- Search/embeddings индексируют узлы Canonical Model.
- AI/RAG/журнал решений переводятся на stable_id.

### Этап 5 — NTM и Duty через anchor
- Duty Engine и NTM получают узел из Canonical Model; `source_kind` isolation и definite/advisory сохранены (отдельные PR, согласование Ivan — как требует `AGENTS.md`).

### Этап 6 — Включение flag по умолчанию + удаление legacy
- После стабилизации: `CANONICAL_TREE_ENABLED` default ON.
- Удаление runtime-вызовов `_build_wrapped_tree`/`build_tree` из API.
- **Legacy `build_tree` остаётся production и oracle до достижения parity**; удаляется только после.
- Knowledge Graph строится на stable_id как первичных ключах.

Каждый переход 2→6 обратим откатом flag, что соответствует требованию rollback plan в `architect.md`.

---

## 9. Риски

| # | Риск | Вероятность | Влияние | Митигировать |
|---|------|-------------|---------|--------------|
| R1 | **Расхождение Canonical vs legacy** на краевых кейсах (pad, L6/L8, `subheading_group`) | Средняя | Высокое (структура продукта) | Дифф-тест fingerprint на всех heading'ах до переключения (Этап 1–3); кейсы из `KNOWN_PITFALLS` §1–6 как обязательные тесты |
| R2 | **Недетерминизм stable_id** (uuid4, порядок, время) ломает кэш/граф | Высокая (сейчас есть) | Высокое | I3/I4: чистая функция от снапшота; CI-тест «две сборки → идентичные ID» |
| R3 | **Неверная инвалидация кэша** при изменении `tnved_commodities` | Средняя | Среднее | snapshot_id = hash содержимого; I19; `preview_cache_revision.py` уже есть |
| R4 | **Производительность построения** полной модели при старте (2M строк) | Средняя | Среднее | Строить один раз, lazy по разделам, кэш; измерить на старте |
| R5 | **Скрытое изменение семантики** (advisory → ERROR) при переезде NTM | Низкая | Высокое (юр. значимость) | I17; отдельные PR; запрет в review-checklist `AGENTS.md` |
| R6 | **Нарушение source_kind isolation** при объединении overlay | Средняя | Высокое | I16; explicit merge-policy в PR; feature flag default OFF |
| R7 | **Breaking change API** при добавлении stable_id | Низкая | Высокое | I20; поля только в конец; Decision Memo при breaking |
| R8 | **FTS5 вне Alembic** (`KNOWN_PITFALLS` §9) рассинхрон с моделью | Средняя | Среднее | Индекс перестраивается при смене snapshot_id; задокументировать в health-check |
| R9 | **Объём миграции** провоцирует «big-bang» PR | Средняя | Высокое | Жёстко: один этап — один PR; параллельный контур; flag |
| R10 | **SQLite ограничения** при materialized-индексах под нагрузкой | Низкая | Среднее | PostgreSQL-путь (`ROADMAP` §7), но не блокирует ADR |
| R11 | **Дрейф номенклатуры ЕЭК** ломает stable_id при ревизии кодов | Средняя | Высокое | History/aliases (`valid_from/to`, `superseded_by`, `previous_codes`) в модели §3.2 |

---

## 10. Финальная архитектурная схема продукта

```
                         ┌───────────────────────────────────────────────┐
                         │              ВНЕШНИЕ ИСТОЧНИКИ                  │
                         │  ЕЭК ЕТТ · ЦБ РФ · ФСА · ФТС/ТРОИС · ТКС эталон │
                         └───────────────────┬───────────────────────────┘
                                             │ ingestion (Alembic + importers, идемпотентно)
                                             ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║  УРОВЕНЬ ХРАНЕНИЯ — SQLite (customs.db) [MUTABLE, only via Alembic]            ║
║  tnved_commodities · tnved_sections · tnved_chapters                          ║
║  hs_rates · hs_duty_rules · ntm_measures_v2 · vat_preferences ·               ║
║  country_tariff_preferences · special_duties · classification_rulings · ...   ║
╚══════════════════════════════════════════════════════════════════════════════╝
                                             │ snapshot_id = hash(structure tables)
                                             ▼
   ┌────────────────────── CONSTRUCTION PIPELINE (детерминированный) ───────────────────────┐
   │  Parser ─▶ Recovery ─▶ Builder ─▶ Validator(gate: инварианты I1..I22) ─▶ freeze()       │
   │  (чистые функции от снапшота; никаких uuid4/времени/случайности)                        │
   └────────────────────────────────────────┬───────────────────────────────────────────────┘
                                             ▼
        ╔════════════════════════════════════════════════════════════════════════╗
        ║      ✦✦✦  CANONICAL TNVED MODEL  (SOURCE OF TRUTH, IMMUTABLE)  ✦✦✦       ║
        ║                                                                          ║
        ║   Section → Chapter → Heading → Subheading(L6) → (DashHeader) →          ║
        ║            Subheading(L8) → Commodity(L10/Leaf)                          ║
        ║                                                                          ║
        ║   node: { stable_id, code|None, node_type, level, parent_id, children,  ║
        ║           title, breadcrumb, notes_ref, aliases, history, provenance,   ║
        ║           is_codeless, is_synthetic, anchors{duty,ntm,semantic,rag} }   ║
        ║                                                                          ║
        ║   индексы: code→stable_id · prefix→node · snapshot_id                    ║
        ╚════════════════════════════════════════════════════════════════════════╝
            │              │                │                │              │
   (read-only, по stable_id / anchor — НИКТО НЕ ЧИТАЕТ SQLite ДЛЯ СТРУКТУРЫ)
            ▼              ▼                ▼                ▼              ▼
   ┌─────────────┐ ┌──────────────┐ ┌──────────────┐ ┌───────────┐ ┌──────────────┐
   │  SEMANTIC   │ │  NTM         │ │ DUTY ENGINE  │ │  NOTES /  │ │  SEARCH      │
   │  NAVIGATION │ │  definite ➜  │ │ duty/VAT/    │ │  EXPLAN.  │ │  FTS5 +      │
   │  overlay    │ │  enforcement │ │ excise/préf  │ │  NOTES    │ │  embeddings  │
   │  group→sub  │ │  possible ➜  │ │ (hs_rates)   │ │  overlay  │ │  → stable_id │
   │  (computed) │ │  advisory    │ │              │ │           │ │              │
   └──────┬──────┘ └──────┬───────┘ └──────┬───────┘ └─────┬─────┘ └──────┬───────┘
          └───────────────┴────────────────┴───────────────┴──────────────┘
                                             ▼
                       ┌──────────────────────────────────────────┐
                       │  API (serializer → стабильный контракт)   │
                       │  /api/v1/tnved/* (+ stable_id, backcompat) │
                       └──────────────────────┬───────────────────┘
                                               ▼
            ┌──────────────┐         ┌──────────────┐        ┌────────────────────┐
            │  AI CLASSIF. │ ──────▶ │     RAG      │ ─────▶ │  KNOWLEDGE GRAPH    │
            │  (read-only, │         │  chunk ⇄     │        │  вершина = stable_id │
            │  → stable_id)│         │  stable_id   │        │  рёбра: parent/child,│
            │  + журнал    │         │              │        │  group, measure,     │
            │  решений     │         │              │        │  ruling, preference  │
            └──────────────┘         └──────────────┘        └────────────────────┘
                                               ▼
                                              UI
                                    (дерево · поиск · карточка ·
                                     калькулятор · NTM · AI-copilot)
```

**Главный архитектурный закон этой схемы:** стрелки структуры идут **только сверху вниз через Canonical Model**. Ни один слой ниже истины не имеет права восстанавливать структуру номенклатуры самостоятельно — он либо читает Canonical Model, либо привязывается к ней через `anchor`/`stable_id`. Это и есть смысл «одной модели истины» (I6) и реализация Vision: продукт не «браузер по Excel-выгрузке», а классификационная модель с контекстом и последствиями.

---

## Решения, требующие подтверждения Ivan (Decision-точки)

1. **Где материализуется Canonical Model:** in-memory при старте (быстро, но память) vs отдельная materialized-таблица/файл-снапшот (переживает рестарт, ближе к PostgreSQL-будущему).
2. **Формула stable_id:** `snapshot:code:level` (просто, но ID меняется при ревизии номенклатуры) vs контент-независимый ID с историей через `superseded_by` (стабильнее для графа/журнала AI, но сложнее).
3. **Судьба legacy `build_tree`:** оракул в тестах навсегда vs удаление после Этапа 6.

---

## Зафиксированные решения (binding)

1. **Canonical TNVED Model — центральная source-of-truth модель Tariff.** SQLite — слой хранения/ingestion, дерево/семантика/AI/NTM/пошлины/поиск/RAG/граф — проекции и overlay.
2. **Recovery — стадия внутри `tree_engine`**, не отдельный top-level module.
3. **Semantic Navigation позже переводится на Canonical Model** (anchor по stable_id), перестаёт читать БД самостоятельно.
4. **Следующая engineering-задача:** `TASK-CANONICAL-001` — deterministic `stable_id` + recovery stage skeleton (без подключения к API).
5. **Legacy `_build_tree` остаётся production и oracle до достижения parity**; удаляется только после.
