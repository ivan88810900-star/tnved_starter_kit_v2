# CURRENT_STATE.md — Текущее состояние проекта

> Дата: 2026-07-15
> Активная ветка: `feat/grounded-ai-assistant`; baseline: `9da2799`

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
- **AI-ассистент** — grounded chat/copilot по TN VED, платежам, definite/advisory
  требованиям и risk coverage; цитаты, no-key fallback, guarded LLM, batch и журнал решений
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

**Статус:** Оба фикса применены в `main`. Активная работа над первым canonical
read-path ведётся в `feat/canonical-read-path` и описана в §2b.

**Проверка:**
```bash
curl http://localhost:8001/api/v1/tnved/children/0302
# Ожидается: L6 узлы как codeless, под ними L8 codeless, под ними 10-digit листья
```

---

## 2a. Принятые архитектурные решения

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

## 2b. Состояние Canonical Pipeline (TASK-CANONICAL-004 completed)

**TASK-CANONICAL-001 — Completed.** Детерминированные `stable_id` (без `uuid4()`),
`snapshot_id`, skeleton стадии Recovery.

**TASK-CANONICAL-002 — Completed.** Recovery-логика перенесена в `StructureNormalizer`;
Builder собирает дерево напрямую из recovery-результата (без делегирования в legacy
`build_tree()`); добавлены full-tree parity-тесты против legacy-oracle.

**Canonical Model Materialization — Completed.** Добавлен иммутабельный `CanonicalModel`
поверх результата `TreeBuilder.build(...)` с индексами достижимости и навигацией;
freeze/read-only на уровне интерфейса; обязательный validator gate; content-parity с
legacy (сверх structural). До TASK-CANONICAL-004 контур не был подключён к runtime.

**TASK-CANONICAL-004 — Completed (Этап 3 ADR: read-path за флагом).** ADR-0002
принят Ivan 2026-07-10 с условиями; Gate-1 и Gate-2 пройдены. Структурный слой
эндпоинта `/children` может брать структуру из `CanonicalModel` **за feature flag**:

- Флаги `CANONICAL_TREE_ENABLED` и `CANONICAL_TREE_SHADOW` — **оба default OFF**,
  читаются **request-time** (rollback без рестарта). Централизованный accessor —
  `tree_engine/flags.py` (без scattered `os.getenv`).
- Provider `tree_engine/provider.py` — in-memory singleton кэш `CanonicalModel`,
  **build-once под локом** (double-checked), пайплайн `TreeParser → TreeBuilder.build_model`
  (validator gate внутри, не обходится). **Ревизия кэша** учитывает `tnved_commodities`
  точный content fingerprint значимых полей `tnved_commodities`, Section/Chapter notes
  и leaf-relevant `hs_rates`. Это закрывает stale-cache при in-place UPDATE, который
  не замечал прежний `count+max(id)`. Parser и leaf-flags используют одну session
  factory. Полный fingerprint пересчитывается только после изменения дешёвого DB
  source-token (SQLite DB/WAL stat; PostgreSQL WAL LSN), а не на каждый read. На
  synthetic 14k строк: cold hash ~129 ms, stable probe median ~0.021 ms. При сбое
  сборки/валидатора — лог + `None` → fallback на legacy, **не** 500.
- Bridge: `CanonicalModel.TreeNode → TreeSerializer.to_legacy_dict(node)` →
  **существующий** `_serialize_tree_node` (overlay/enrichment **не** дублируется и **не**
  меняется). Секционная обёртка `_wrap_in_sections` и поиск узла `_find_node_in_tree`
  переиспользуются.
- Branching **только** внутри `list_tnved_children` (через `_resolve_children_node`):
  OFF → строго legacy; ON → canonical structure, при неудаче (модель недоступна / узел
  не найден) → fallback legacy. Поведение сохранено для empty/root, roman sections,
  2/4/6/8/10-значных узлов, leaf → `[]`, synthetic/codeless-обёрток.
- Shadow (`SHADOW=1`, `ENABLED=0`): ответ legacy, canonical считается и сверяется
  (structural+content fingerprint); потокобезопасные `shadow_match`/`shadow_mismatch`
  считаются всегда, mismatch-warning семплируется (первый и каждый 100-й), на ответ
  **не** влияет; сбой canonical в shadow учитывается как mismatch и не даёт 500.
- Gate-2 инструмент `scripts/audit_canonical_children.py` строит legacy/canonical по
  одному разу и сравнивает все DB-backed `/children` пути. Финальный прогон 2026-07-14
  на наполненной БД: **18 049 checked/matched, 0 mismatch, 0 unresolved**,
  `gate2_ok=true`, exit `0`.
  Защита от false-green требует не менее 10 000 commodity-строк; меньшая БД может дать
  parity-smoke, но не `gate2_ok`.
- Для передачи без полного 1.5 GB `customs.db` добавлен read-only exporter
  `scripts/export_canonical_gate2_db.py`: в одной snapshot-транзакции копирует только
  `tnved_sections`, `tnved_chapters`, `tnved_commodities`, `hs_rates`, проверяет
  integrity/FK, считает SHA-256 и опционально создаёт ZIP. В `hs_rates` остаются только
  leaf-маркеры неоднозначных commodity-кодов `*0000`; значения ставок/provenance и
  операционные/user tables в экспорт не попадают.
  Опция `--audit-report` сразу запускает Gate-2 на экспорте и атомарно сохраняет
  переносимый JSON с SHA-256, coverage, parity и exit code; при `gate2_ok=true`
  достаточно передать этот маленький отчёт, без самой БД.
- Контракт JSON **не изменён**; legacy `build_tree()` и `semantic_navigation` **не тронуты**;
  БД/Alembic/frontend **не тронуты**.
- Self-contained тесты: `tests/test_canonical_read_path.py` (35),
  `tests/test_canonical_children_audit.py` (3) и
  `tests/test_export_canonical_gate2_db.py` (2). Они покрывают in-place UPDATE,
  notes, leaf-rate invalidation, метрики/семплирование, root/Roman parity, audit smoke
  и минимальный read-only export → полный audit.
  Финальный data-dependent Gate-2 выполнен на наполненной БД.

> Предыдущий QA-вердикт `APPROVE WITH NOTES` был отменён после воспроизведения stale-cache
> на in-place UPDATE. Corrective fix и повторный QA выполнены; финальный Gate-2 зелёный.
> Флаги остаются default OFF до отдельного решения Ivan о rollout.

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
- ~~**Feature flag** — нет `CANONICAL_TREE_ENABLED`.~~ **Закрыто** (TASK-CANONICAL-004):
  `CANONICAL_TREE_ENABLED` / `CANONICAL_TREE_SHADOW` (default OFF, request-time,
  `tree_engine/flags.py`).
- **Runtime adoption** — подключён к runtime **только** структурный слой `/children`
  **за флагом** (default OFF). Остальные эндпоинты / `lifespan` / overlay — по-прежнему
  legacy.
- **Materialized snapshot** — модель строится in-memory на вызов `build_model(...)`; нет
  переживающего рестарт снапшота/кэша по `snapshot_id`.
- **Overlays** — Semantic Navigation / NTM / Duty / Notes / Search / RAG ещё не
  переведены на `anchor` (продолжают читать БД сами).

---

## 3. Последние архитектурные изменения

| Коммит | Дата | Описание |
|--------|------|---------|
| MVP acceptance hardening | 2026-07-16 | `run_e2e_scenarios.py` синхронизирован с текущим продуктом: обязательный login/cookie, hybrid search + code card, Smart Payments, normative/risk evidence, grounded assistant; sandbox 4/4, flags OFF; ошибочный US→automatic embargo assertion удалён |
| TASK-MVP-ASSISTANT-001 | 2026-07-15 | Grounded assistant: no-key server answers, TN VED/payment/NTM/risk evidence, citations and guarded optional LLM wording |
| TASK-MVP-PAYMENTS-001 | 2026-07-15 | Smart Payments встроен в карточку ТН ВЭД: базы расчёта, статусы, источники, допущения, честный partial total и Canonical anchor |
| `f7df848..d2ef092` | 2026-07-15 | Canonical anchor identity + additive bridge в поиск/карточку ТН ВЭД |
| Gate-2 QA | 2026-07-14 | TASK-CANONICAL-004 completed: 18 049/18 049 match, 0 mismatch/unresolved; flags remain default OFF |
| `9fe1fa5..daf6be1` | 2026-07-10..14 | `/children` за default-OFF флагом; corrective, shadow metrics, Gate-2 auditor/export/report |
| `9712c7b` | 2026-07-01 | Canonical Model Materialization: иммутабельный `CanonicalModel`, validator gate, full-tree content parity |
| `f66d3c7` | 2026-06-30 | TASK-CANONICAL-002: recovery-логика → `StructureNormalizer`; Builder без legacy delegation |
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
| **TASK-CANONICAL-004** — read-path `/children` за флагом (provider/cache, shadow, fallback), контракт неизменён | ✅ Completed: Gate-1 + Gate-2 passed; flags default OFF | — |
| **TASK-CANONICAL-005** — freeze `stable_id` / output `snapshot_id` / anchor DTO | ✅ Completed; ADR-0003 Accepted | — |
| **TASK-CANONICAL-006** — TN VED search/code-card anchor bridge | ✅ Completed; optional soft-fail anchor | — |
| **TASK-MVP-SEARCH-QUALITY-001** — hybrid поиск: ranking, typo recovery, explainable UI | ✅ Completed; embeddings remain separate | — |
| **TASK-MVP-PAYMENTS-001** — объяснимый расчёт платежей в карточке ТН ВЭД | ✅ Completed; calculation semantics unchanged | — |
| **TASK-MVP-RISK-001** — санкционный скрининг: scope, evidence, coverage, sources | ✅ Completed; semantics remain diagnostic | — |
| **TASK-MVP-ASSISTANT-001** — grounded assistant: серверные факты, цитаты, no-key fallback, guarded LLM | ✅ Completed | — |
| Full-data MVP acceptance | Sandbox 4/4; прогон на пользовательской полной БД ещё требуется | Высокий |
| Derisking после TASK-005: aliases/history (`superseded_by`, previous codes/IDs) | Рекомендован | Высокий |
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
- **Special duties:** при отсутствии локальных данных Smart Payments намеренно не
  подтверждает финальный итог и показывает только известную частичную сумму
- **ФТС предрешения:** live-парсер не реализован (customs.gov.ru/folder/519 — статистика, не предрешения)
- **ТРОИС:** fuzzy-поиск может давать false positives на коротких запросах
- **Semantic embeddings:** в доступных QA-БД нет готовых векторов и серверный ключ
  провайдера не настроен; умный поиск и ассистент используют детерминированный hybrid/evidence fallback

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
> `/children` может читать canonical только за default-OFF флагом. Долги должны быть
> закрыты до serving ON и расширения runtime-adoption.

### Critical
- ~~**Structural parity проверяет не весь контент.**~~ **Закрыто** (Canonical Model
  Materialization): добавлен `test_full_tree_content_parity_with_legacy` — сверяет
  полный контент узлов (name, `display_code`, `is_leaf`, `is_codeless`, `is_group`,
  `import_duty`, notes) рекурсивно против legacy `build_tree()`; проходит на всём дереве.
- ~~**`snapshot_id` не учитывает все входы модели.**~~ **Закрыто**
  (TASK-CANONICAL-005): `canonical-snapshot-v2` хеширует детерминированный output
  модели, включая структуру, имена, `import_duty`, notes и результирующие флаги;
  provider source revision остаётся отдельным rebuild-key.
- **Recovery-логика временно дублируется** в legacy `build_tree()` и в canonical
  (`StructureNormalizer` + Builder). Два источника одной логики до достижения parity —
  риск дрейфа.

### Important
- ~~**Формула `stable_id` не утверждена окончательно.**~~ **Закрыто**
  (ADR-0003 / TASK-CANONICAL-005): `stable-id-v1` — snapshot-independent versioned
  Canonical path hash; будущая смена требует ADR и alias/migration plan.
- **Документация отставала от кода** (001/002 были «Completed» по факту, но `.ai`
  отражал «не начато») — этим обновлением синхронизировано; держать в синхроне.
- ~~**Validator ещё не freeze-gate.**~~ **Закрыто** для `CanonicalModel`:
  `CanonicalModel.from_roots(...)` / `TreeBuilder.build_model(...)` прогоняют
  `TreeValidator` перед freeze; при ошибках модель не создаётся
  (`CanonicalModelValidationError`). Runtime по-прежнему использует legacy-путь.
- **Builder читает БД для `leaf_flags`** (`HsRate` в `builder.py`). Жёсткая привязка
  к глобальному `SessionLocal` устранена: provider/Builder используют одну session factory.
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
| **stable_id formula** | ✅ Closed: ADR-0003 `stable-id-v1`; TASK-CANONICAL-005 implemented | ID — первичный ключ для Search/RAG/AI-журнала/Graph; смена формулы позже = миграция всех ссылок | New ADR + alias/migration plan for any change |
| **snapshot_id inputs** | ✅ Closed: ADR-0003 `canonical-snapshot-v2`; TASK-CANONICAL-005 implemented | Snapshot идентифицирует построенный artifact, source revision отдельно управляет rebuild | Revisit only when Canonical output contract expands |
| **Materialized CanonicalModel** | Частично (in-memory `CanonicalModel` реализован; переживающий рестарт снапшот/кэш — Open) | Определяет переживаемость рестарта, память, путь к PostgreSQL | Перед runtime-adoption (кэш по `snapshot_id`) |
| **Feature flag strategy** | ✅ Closed (`CANONICAL_TREE_ENABLED` / `CANONICAL_TREE_SHADOW`, default OFF, request-time) — ADR-0002 Accepted with conditions | Управляет безопасным A/B old-vs-new и откатом | Gate-2 пройден; включение — отдельное решение Ivan |
| **Deadline for legacy `build_tree` removal** | Open (oracle до parity) | Двойная логика — долг; нужен критерий «parity достигнута → удаляем» | После content-parity + стабилизации flag (Этап 6) |
| **First production read-path** | ✅ Completed — `/children` структурный слой за default-OFF флагом; Gate-2 green | Какой эндпоинт первым читает CanonicalModel и как сверяется с legacy | Отдельное решение Ivan о rollout |

---

*Обновлять после каждого значимого изменения.*
