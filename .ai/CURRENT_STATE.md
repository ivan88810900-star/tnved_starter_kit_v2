# CURRENT_STATE.md — Текущее состояние проекта

> Дата: 2026-06-26
> Последний коммит: `f42d2d4` (fix: codeless L6 wrappers for lone subheadings)

---

## 1. Реализованные функции

### Ядро платформы

- **Справочник ТН ВЭД** — полное дерево (разделы → группы → позиции → субпозиции → коды), FTS5-поиск по всей номенклатуре (BM25), карточка товара
- **AI-классификация** — Gemini structured JSON (код, обоснование, confidence_score, атрибуты), Claude Vision для фото
- **Расчёт платежей** — пошлина, НДС (22%/10%), акциз, антидемпинг, спецпошлины, утильсбор (РОП), тарифные преференции (161 страна)
- **Нетарифные меры** — ТР ТС каталог (96+ глав), NTM v2 контур, noise-classifier (22K записей), структурированный UI без сырого TKS-текста
- **Инвойс / пакинг-лист** — загрузка XLSX/CSV, Vision-классификация, async-задачи, экспорт в Excel
- **ТРОИС** — opendata ФТС (CSV ~42MB), fuzzy-поиск, cron-синхронизация
- **ФСА/СС/ДС** — opendata (7Z-архивы), backfill истории, мгновенная проверка номера
- **AI-ассистент** — copilot pipeline, batch-режим, RAG (PDF/TXT/MD), журнал решений, semantic search (embeddings)
- **РОП / экосбор** — ставки ПП №1041/2414, 39 категорий ТС, audit 97 глав
- **Официальные данные** — ETT 99.8%, VAT 100%, Excise 100%, Anti-dumping 82.8%, Special Safeguard 100%, Countervailing 100%

### Инфраструктура

- Alembic: ~60 миграций, merge-голова восстановлена (PR #115)
- APScheduler: cron-задачи (курсы ЦБ, ФТС краулер, РОП, ТРОИС, ФСА)
- GitHub Actions: auto-merge, claude-pr-reviewer, cursor-task-agent, opendata-sync (05:00 UTC)
- Rate limit middleware, JWT auth, admin token
- Docker + nginx.conf для production

---

## 2. Активная задача

### Исправление структуры дерева ТН ВЭД под эталон ТКС

**Цель:** Структура дерева в приложении должна совпадать со структурой на tks.ru.

**Проблема:** Некоторые коды отображались как прямые листья там, где по эталону должны быть бескодовые заголовки с декларируемым листом под ними.

**Выполненные шаги:**
1. `732c1e7` — L8 синтез: одиночные L8-узлы без детей → codeless heading + synthetic leaf
2. `f42d2d4` — L6 синтез: одиночные L6-субпозиции без детей → codeless heading + synthetic leaf

**Статус:** Оба фикса применены. Текущая ветка — основная (`main`).

**Проверка:**
```bash
curl http://localhost:8001/api/v1/tnved/children/0302
# Ожидается: L6 узлы как codeless, под ними L8 codeless, под ними 10-digit листья
```

---

## 2a. Принятые архитектурные решения

### ADR-0002 — First production read-path on CanonicalModel (`/children`) (Proposed, 2026-07-01)

Decision Memo: первый production read-path `/children` читает **структуру** из
`CanonicalModel` вместо legacy `build_tree()` за feature flag `CANONICAL_TREE_ENABLED`
(default OFF, request-time) + отдельный `CANONICAL_TREE_SHADOW`; overlay/enrichment
(`_serialize_tree_node`) остаётся legacy-путём; legacy `build_tree()` — oracle; JSON-контракт
неизменен; смена source of truth **частичная и временная**; откат одной переменной; сбой
canonical → fallback на legacy без 500. **Меняет source of truth для API → требует
утверждения Ivan до кода.** Полный документ: `.ai/decisions/ADR-0002-canonical-children-read-path.md`.
Реализация: `.ai/tasks/TASK-CANONICAL-004.md` (blocked-on-decision).

### ADR-0001 — Canonical TNVED Model (Accepted, Ivan, 2026-06-30)

**Source of Truth продукта Tariff — Canonical TNVED Model**, а не SQLite, не дерево
(`build_tree()`), не parser и не API. SQLite — слой хранения/ingestion; дерево,
семантика, AI, NTM, пошлины, поиск, RAG, граф знаний — проекции/overlay поверх
канонической модели (привязка по `stable_id` / `anchor`).

Зафиксировано:
1. Canonical TNVED Model — центральная source-of-truth модель.
2. **Recovery — стадия внутри `tree_engine`**, не отдельный top-level module.
3. **Semantic Navigation позже переводится на Canonical Model** (перестаёт читать БД сам).
4. Следующая задача — **`TASK-CANONICAL-001`**: deterministic `stable_id` + recovery
   stage skeleton (без подключения к API).
5. **Legacy `_build_tree` остаётся production и oracle до parity**; удаляется только после.

Полный документ: `.ai/decisions/ADR-0001-canonical-tnved-model.md`. Индекс: `.ai/DECISIONS.md`.

---

## 2b. Состояние Canonical Pipeline (после TASK-CANONICAL-001, 002 и Materialization)

**TASK-CANONICAL-001 — Completed.** Детерминированные `stable_id` (без `uuid4()`),
`snapshot_id`, skeleton стадии Recovery.

**TASK-CANONICAL-002 — Completed.** Recovery-логика перенесена в `StructureNormalizer`;
Builder собирает дерево напрямую из recovery-результата (без делегирования в legacy
`build_tree()`); добавлены full-tree parity-тесты против legacy-oracle.

**Canonical Model Materialization — Completed.** Добавлен иммутабельный `CanonicalModel`
поверх результата `TreeBuilder.build(...)` с индексами достижимости и навигацией;
freeze/read-only на уровне интерфейса; обязательный validator gate; content-parity с
legacy (сверх structural). Контур по-прежнему **не подключён** к runtime/API/overlay.

> **Прошло Architecture Review (Chief Architect): APPROVE WITH NOTES.** Контур
> изолирован, к runtime/API/overlay не подключён, прод-риска нет. Открытые замечания
> вынесены в разделы «Architecture Debt» и «Open Architecture Decisions» ниже.

### Реализовано (в `customs-clear/backend/app/services/tree_engine/`, изолированно)

- **Parser** (`parser.py`) — SQLite → плоская промежуточная модель `ParsedCommodityRecord`.
- **Recovery** (`recovery.py`, `StructureNormalizer`) — pad-имена, синтез бескодовых
  L6/L8, subheading-group, очистка имён, классификация типов; **чистая стадия** (без БД,
  без `uuid4`), leaf-флаги принимает аргументом.
- **Builder** (`builder.py`) — stack-сборка иерархии, материализация синтет-листьев,
  сортировка, восстановление имени группы, присвоение ID; **напрямую**, без legacy.
  Additive-метод `build_model(...)` → `CanonicalModel` (validator gate + freeze).
- **CanonicalModel** (`canonical_model.py`) — иммутабельный Source-of-Truth объект:
  `roots`/`snapshot_id`, индексы `node_by_stable_id` / `node_by_code` /
  `node_by_display_code` / `parent_by_stable_id` / `children_by_stable_id`; методы
  `get` / `get_by_code` / `get_by_display_code` / `parent` / `children` / `path` /
  `descendants`. Read-only на уровне интерфейса: `roots`/`children`/`path`/`descendants`
  → `tuple`, индексы → `MappingProxyType`, переустановка/удаление атрибутов запрещены.
- **Validator gate** — `CanonicalModel.from_roots(...)` прогоняет `TreeValidator` перед
  freeze; при ошибках модель не создаётся (`CanonicalModelValidationError`).
- **stable_id** — детерминированный (`node-<hex>`), воспроизводим между сборками.
- **snapshot_id** — вычисляется (`compute_snapshot_id(db_codes)`).
- **Parity tests** — `test_canonical_tnved_model.py`: full-tree **structural** parity
  (`structure_fingerprint`) и full-tree **content** parity (name / display_code /
  is_leaf / is_codeless / is_group / import_duty / notes) против legacy `build_tree()`.

### Чего ещё НЕТ (намеренно, по плану ADR-0001)

- **Deep-immutability узлов** — сами `TreeNode` (их `children`/`metadata`) физически не
  заморожены; иммутабельность обеспечена только на уровне интерфейса `CanonicalModel`
  (известное ограничение этапа).
- **Feature flag** — нет `CANONICAL_TREE_ENABLED`.
- **Runtime adoption** — контур не подключён к API / `lifespan` / роутерам.
- **Materialized snapshot** — модель строится in-memory на вызов `build_model(...)`; нет
  переживающего рестарт снапшота/кэша по `snapshot_id`.
- **Overlays** — Semantic Navigation / NTM / Duty / Notes / Search / RAG ещё не
  переведены на `anchor` (продолжают читать БД сами).

---

## 3. Последние архитектурные изменения

| Коммит | Дата | Описание |
|--------|------|---------|
| (uncommitted) | 2026-07-01 | Canonical Model Materialization: иммутабельный `CanonicalModel` (индексы + навигация), validator gate, freeze/read-only, full-tree content parity. Не подключён к runtime |
| (uncommitted) | 2026-06-30 | TASK-CANONICAL-002: recovery-логика → `StructureNormalizer`; Builder без делегирования в legacy; full-tree parity tests (APPROVE WITH NOTES) |
| `4a7eac2` | 2026-06-30 | TASK-CANONICAL-001: deterministic `stable_id`, `snapshot_id`, recovery skeleton |
| (docs) | 2026-06-30 | ADR-0001 Canonical TNVED Model принят (Ivan); зафиксированы DECISIONS.md, ROADMAP |
| `f42d2d4` | 2026-06-26 | L6 синтез: codeless L6 wrappers для одиночных субпозиций |
| `732c1e7` | 2026-06-26 | L8 синтез: codeless headings для L8-узлов без детей |
| `6c61f70` | 2026-06-26 | ntm_measures_v2: canonical sources, full names, badges |
| `60b0e08` | 2026-06-26 | Tree UX + non-tariff measures + data cleanup |
| `6de52fb` | 2026-06-26 | TNVED tree hierarchy, leaf click, duty badge, codeless nodes |
| `6fcad76` | 2026-06-26 | Drill-down TNVED tree с depth navigation (этап 2/5) |

---

## 4. Последние исправленные ошибки

| PR/коммит | Проблема | Решение |
|-----------|---------|---------|
| `732c1e7` | L8-коды показывались как листья, а не codeless headings | `elif lvl == 8` ветвь в `_classify()` |
| `f42d2d4` | L6-субпозиции без детей показывались как листья | `elif lvl == 6` ветвь в `_classify()` |
| PR #130 | Китай (CN) получал GSP-скидку 25% | CN → `mfn_graduated` (коэфф. 1.0) |
| PR #115 | Дублирующий `revision_id` в Alembic | Переименование + merge-миграция |
| PR #168 | IntegrityError при batch upsert FSA | Dedupe по `registry_number` |
| PR #134 | Битый FCS_OFFICIAL_URL | Исправлен URL, Decision Memo #135 |

---

## 5. Незавершённые задачи

| Задача | Статус | Приоритет |
|--------|--------|-----------|
| **TASK-CANONICAL-001** — deterministic `stable_id` + recovery stage skeleton | ✅ Completed | — |
| **TASK-CANONICAL-002** — recovery-логика → `StructureNormalizer`, Builder без legacy, parity tests | ✅ Completed (APPROVE WITH NOTES) | — |
| **Canonical Model Materialization** — иммутабельный `CanonicalModel` (индексы+навигация), validator gate, content parity | ✅ Completed (не подключён к runtime) | — |
| **ADR-0002** — Decision Memo: первый production read-path `/children` на `CanonicalModel` (меняет source of truth API частично/временно) | 📝 Proposed (ждёт Ivan) | Высокий |
| **TASK-CANONICAL-004** — реализация read-path `/children` за feature flag (default OFF) + shadow | 📋 Blocked-on-decision (ADR-0002; `.ai/tasks/TASK-CANONICAL-004.md`) | Высокий |
| Derisking (остаток): расширение входов `snapshot_id`, формула `stable_id` | Рекомендован | Высокий |
| Fine-tune модели на `training_pairs.jsonl` | Вне репозитория | Низкий |
| Live-parсер ФТС предрешений (tks.ru JS) | Decision Memo #135 | Средний |
| Мульти-воркер ФСА (Redis-очередь) | Бэклог | Низкий |
| Полный аудит graduated-стран по ЕЭК №17 | Бэклог | Средний |
| Alembic для FTS5 virtual table | Архитектурная проблема | Низкий |
| Дополнительные регрессионные тесты дерева | Follow-up | Высокий |

---

## 6. Текущие ограничения

### Данные
- **ETT (пошлины):** 27 строк из TKS bulk-AI краулера (legacy), не от ЕЭК → `manual_review_required`
- **Anti-dumping:** 82.8% покрытие, 5 мер из 29 без официального источника
- **ФТС предрешения:** live-парсер не реализован (customs.gov.ru/folder/519 — статистика, не предрешения)
- **ТРОИС:** fuzzy-поиск может давать false positives на коротких запросах

### Архитектура
- **SQLite** — ограничение параллельных записей; для production рекомендуется PostgreSQL (DATABASE_URL поддерживает)
- **FTS5** — вне Alembic, создаётся только при старте приложения
- **NTM v2 feature flags** — по умолчанию OFF, требует явного включения Иваном
- **L6/L8 синтез** — производительность: на каждый запрос к дереву пересчитывается из БД (кэш не реализован)

### Frontend
- **Тайпскрипт типы** — `openapi.generated.ts` требует ручной регенерации (`npm run gen:api-types`) при изменении схемы API
- **Tailwind CSS 3.4** (не 4.x) — конфигурация в `tailwind.config.cjs`

---

## 7. Версии технологий

| Технология | Версия |
|-----------|--------|
| Python | 3.13 |
| FastAPI | актуальная |
| SQLAlchemy | 2.x (Mapped columns) |
| Alembic | актуальная |
| React | 18.3.1 |
| TypeScript | 5.5.4 |
| Vite | 8.0.0 |
| Tailwind CSS | 3.4.4 |
| Node.js | актуальная LTS |

---

## 8. Architecture Debt (Canonical TNVED Model)

> Источник: Architecture Review TASK-CANONICAL-002 (Chief Architect, APPROVE WITH NOTES).
> Долги контура изолированы (к runtime не подключено), но должны быть закрыты до
> перехода к runtime-adoption / Этапа 3 ADR-0001.

### Critical
- ~~**Structural parity проверяет не весь контент.**~~ **Закрыто** (Canonical Model
  Materialization): добавлен `test_full_tree_content_parity_with_legacy` — сверяет
  полный контент узлов (name, `display_code`, `is_leaf`, `is_codeless`, `is_group`,
  `import_duty`, notes) рекурсивно против legacy `build_tree()`; проходит на всём дереве.
- **`snapshot_id` не учитывает все входы модели.** Считается от `db_codes`, но не
  включает другие входы, влияющие на результат — в частности `hs_rates` (через leaf-флаги),
  `import_duty`, примечания глав. Кэш/инвалидация по такому `snapshot_id` ненадёжны.
- **Recovery-логика временно дублируется** в legacy `build_tree()` и в canonical
  (`StructureNormalizer` + Builder). Два источника одной логики до достижения parity —
  риск дрейфа.

### Important
- **Формула `stable_id` не утверждена окончательно** (см. Open Decisions). Сейчас
  `node-<hex>`; не зафиксировано отношение к ревизиям номенклатуры/истории.
- **Документация отставала от кода** (001/002 были «Completed» по факту, но `.ai`
  отражал «не начато») — этим обновлением синхронизировано; держать в синхроне.
- ~~**Validator ещё не freeze-gate.**~~ **Закрыто** для `CanonicalModel`:
  `CanonicalModel.from_roots(...)` / `TreeBuilder.build_model(...)` прогоняют
  `TreeValidator` перед freeze; при ошибках модель не создаётся
  (`CanonicalModelValidationError`). Runtime по-прежнему использует legacy-путь.
- **Builder читает БД для `leaf_flags`** (`SessionLocal`/`HsRate` в `builder.py`).
  Противоречит ADR §6.1 «единственный путь чтения — Parser» и переписывает предикат
  `is_leaf_hs_code`. Должно переехать в Parser.

### Nice to have
- **provenance / history / aliases / breadcrumb** — поля модели из ADR §3.2 ещё не
  реализованы (нужны для Search/RAG/Graph/версионности).
- **SQLite / PostgreSQL / FTS5 долг** — FTS5 вне Alembic; миграция на Postgres
  потребует аналога полнотекстового поиска (ROADMAP §7).
- **Удаление переходных `serializer`/`structure_fingerprint`** после завершения
  миграции (нужны только в переходный период для дифф-тестов).

---

## 9. Open Architecture Decisions

> Решения, которые нужно закрыть осознанно (а не молча) — по `ENGINEERING_PROTOCOL` и
> `agents/architect.md`. Полный контекст — в ADR-0001.

| Решение | Статус | Почему важно | Когда закрыть |
|---------|--------|--------------|---------------|
| **stable_id formula** | Open (черновой `node-<hex>`) | ID — первичный ключ для Search/RAG/AI-журнала/Graph; смена формулы позже = миграция всех ссылок | До runtime-adoption (Этап 3); прежде, чем кто-то начнёт хранить ссылки на узлы |
| **snapshot_id inputs** | Open (только `db_codes`) | От полноты входов зависит корректность кэша/инвалидации и «snapshot-консистентности» (I19) | До materialized CanonicalModel / включения кэша |
| **Materialized CanonicalModel** | Частично (in-memory `CanonicalModel` реализован; переживающий рестарт снапшот/кэш — Open) | Определяет переживаемость рестарта, память, путь к PostgreSQL | Перед runtime-adoption (кэш по `snapshot_id`) |
| **Feature flag strategy** | Спроектировано в TASK-CANONICAL-004 (`CANONICAL_TREE_ENABLED` + `CANONICAL_TREE_SHADOW`, default OFF, request-time) | Управляет безопасным A/B old-vs-new и откатом | Реализация — TASK-CANONICAL-004 |
| **Deadline for legacy `build_tree` removal** | Open (oracle до parity) | Двойная логика — долг; нужен критерий «parity достигнута → удаляем» | После content-parity + стабилизации flag (Этап 6) |
| **First production read-path** | Спроектировано в TASK-CANONICAL-004 (`/children`; shadow structural+content vs legacy; overlay через `_serialize_tree_node`) | Какой эндпоинт первым читает CanonicalModel за флагом и как сверяется с legacy | Реализация — TASK-CANONICAL-004 |

---

*Обновлять после каждого значимого изменения.*
