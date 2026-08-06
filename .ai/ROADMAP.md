# ROADMAP.md — Техническая дорожная карта

> Только задачи, подтверждённые анализом кода и существующего бэклога.
> Не содержит бизнес-wishlist без технического обоснования.
> Дата: 2026-08-06.

---

## Высокий приоритет

### 0. Canonical TNVED Model (ADR-0001) — целевая source-of-truth

**Обоснование:** ADR-0001 (Accepted, Ivan, 2026-06-30) фиксирует, что Source of Truth
продукта — Canonical TNVED Model, а не SQLite / `build_tree()` / API.

**Сделано:**
- ✅ **TASK-CANONICAL-001** — deterministic `stable_id`, `snapshot_id`, recovery skeleton.
- ✅ **TASK-CANONICAL-002** — recovery-логика → `StructureNormalizer`; Builder собирает
  напрямую (без делегирования в legacy); full-tree parity-тесты. Прошло Architecture
  Review: **APPROVE WITH NOTES**.
- ✅ **Canonical Model Materialization** — иммутабельный `CanonicalModel`
  (`canonical_model.py`) поверх `TreeBuilder.build(...)`: индексы достижимости
  (`node_by_stable_id` / `node_by_code` / `node_by_display_code`) + навигация
  (parent/children/path/descendants); freeze/read-only на уровне интерфейса; validator
  gate перед freeze; full-tree **content** parity с legacy. Не подключён к runtime.
- ✅ **TASK-CANONICAL-004 (Этап 3, read-path за флагом; completed)** — структурный слой
  `/children` может читать CanonicalModel за `CANONICAL_TREE_ENABLED` (default OFF),
  с shadow-режимом `CANONICAL_TREE_SHADOW` (default OFF). Provider с in-memory кэшем
  (`provider.py`, build-once под локом, точная content-revision учитывает
  `tnved_commodities`, Section/Chapter notes и leaf-relevant `hs_rates`), fallback на legacy без 500, bridge через
  `TreeSerializer.to_legacy_dict` → существующий `_serialize_tree_node` (overlay не
  дублируется). Контракт JSON неизменён; legacy `build_tree()` не тронут. Gate-2 на
  наполненной БД: 18 049/18 049 match, 0 mismatch/unresolved; флаг остаётся OFF до
  отдельного решения Ivan о rollout.
  Stable requests используют дешёвый DB source-token и не хешируют весь каталог.
  Для Gate-2 передачи без полного DB-архива есть минимальный read-only exporter четырёх
  структурных таблиц (`scripts/export_canonical_gate2_db.py`); `--audit-report` создаёт
  самодостаточный маленький JSON, поэтому БД нужна только для разбора mismatch.
- ✅ **TASK-CANONICAL-007** — Parser стал единственной DB-reading стадией Canonical
  pipeline: commodities, Section/Chapter metadata и leaf-evidence читаются в одной
  session и одном явном SQLite read-snapshot, затем передаются Builder как явный
  `TreeParseResult`. Builder не знает о БД; full/compact Gate-2 покрыты тестами,
  parity 18 049/18 049 сохранён.
- ✅ **TASK-CANONICAL-008** — Guided runtime больше не перечитывает `Commodity`
  после выбора модели: semantic source records принадлежат exact Parser snapshot и
  хранятся immutable внутри `CanonicalModel`; missing projection fail-safe.
- ✅ **TASK-CANONICAL-009** — 162 exact-rate terminal L4 `XXXX000000` без descendants
  материализуются как реальные leaves в legacy/Canonical/Guided; independent audit
  reachability защищает от общего пропуска. Gate-2: 18 211/18 211.
- ✅ **TASK-CANONICAL-010** — опубликованный Canonical graph физически immutable:
  scalar attributes/parent/tuple children и рекурсивные standard metadata-контейнеры
  заморожены после validator/stamping; Builder output до публикации остаётся mutable.
  Alias/mutation regressions зелёные; Gate-2 18 211/18 211 и census 1 228/1 228
  сохранены без изменений identity/API/flags.
- ✅ **TASK-SEMANTIC-005** — aggregate-only whole-catalog Guided census:
  1 228/1 228 headings, 16 708/16 708 source-backed code nodes и 13 254
  Canonical declarable leaves на одном snapshot, zero role mismatch/fake/duplicate/
  degraded/empty-root; semantic UX baseline измеряется отдельно.
- ✅ **TASK-SEMANTIC-006** — bounded official PDO slice для `2204` completed и
  accepted через DM-0005 Option A; implementation + verification находятся на
  feature branch. Exact ordered allowlist из 33 Canonical sibling leaves,
  fail-closed при source/topology drift; шаг `220421` сократился с 50/47 до 18/14,
  PDO открывает 33/33. Whole census 1 228/1 228 и golden 5/5 сохранены, flags OFF.
  Этот docs-only update не выполняет merge/rollout/deploy.
- ✅ **TASK-SEMANTIC-007** — exact product-form chain для `0304` реализована,
  проверена и принята через DM-0006 Option A:
  атомарно связать пять exact `(anchor, stop]` scopes с ordered source tuples и
  Canonical leaf/parent topology. Measured: root 19/16 → 13/8, max step 19/17 →
  13/9, semantic leaves 82/100 → 92/100 при неизменных 117/117 source nodes и
  100/100 leaves. Census 1,228/1,228, golden 6/6, Gate-2 18,211/18,211. Flags
  остаются OFF; merge/rollout/deploy не выполнялись.

**Текущее состояние и долги:** см. `.ai/CURRENT_STATE.md` §2b/§8/§9. Read-path
`/children` подключён к runtime **только за флагом** (default OFF). Guided overlay
уже читает source records и anchors выбранного Canonical model, но остальные
overlays/endpoints по-прежнему не мигрированы. Legacy `_build_tree` остаётся
production и oracle.

#### Оставшийся derisking после materialization

> Materialization уже завершена, а первый runtime read-path реализован за default-OFF
> флагом. До расширения runtime и хранения ссылок остаются риски identity/snapshot;
> это направление, а не автоматически созданная задача.

Рекомендуемый порядок работ:
1. ✅ **Расширить parity от структуры до контента.** Сделано в Canonical Model
   Materialization: `test_full_tree_content_parity_with_legacy` сверяет имена,
   `import_duty`, notes, флаги, `display_code` рекурсивно. → Critical-долг закрыт.
2. ✅ **Расширить входы `snapshot_id` самой модели.** ADR-0003 принят,
   TASK-CANONICAL-005 реализовал `canonical-snapshot-v2`: хеш детерминированного
   Canonical output отделён от source revision кэша и учитывает структуру, имена,
   `import_duty`, notes и результирующие флаги.
3. ✅ **Закрыть решение по формуле `stable_id`.** ADR-0003 принят,
   TASK-CANONICAL-005 реализовал snapshot-independent path-based `stable-id-v1` и
   внутренний anchor DTO до появления persistent consumers.
4. ✅ **Первый read-path за feature flag** — завершён в TASK-CANONICAL-004:
   `/children` (структурный слой) за `CANONICAL_TREE_ENABLED`, сверка с legacy через
   `CANONICAL_TREE_SHADOW` и `scripts/audit_canonical_children.py`.
   ADR-0002 принят с условиями; Gate-2 пройден, включение требует отдельного решения Ivan.
5. ✅ **Устранить скрытое DB-чтение Builder.** TASK-CANONICAL-007 перенёс
   leaf-evidence в Parser, закрепил один DB snapshot и сохранил full Gate-2 parity.
6. ✅ **Связать Guided semantic input с model snapshot.** TASK-CANONICAL-008 убрал
   второе runtime-чтение commodities и добавил mutation regression.
7. ✅ **Закрыть terminal L4 omission и усилить Gate-2.** TASK-CANONICAL-009
   восстановил 162 реальных кода; 18 211/18 211 paths зелёные.
8. ✅ **Deep-freeze shared model graph.** TASK-CANONICAL-010 исключил mutation
   опубликованных `TreeNode`, standard metadata/children aliases и split-brain с
   индексами; неизвестные custom mutable metadata objects требуют отдельного protocol,
   но в production metadata таких объектов нет.
9. **Следующий platform derisking:** PostgreSQL repeatable-read/read-only snapshot
   portability — отдельная bounded corrective task с реальным concurrent PG gate,
   без смешивания с aliases/history.

После отдельного решения Ivan возможен rollout первого read-path. Расширение
runtime на overlays и удаление legacy допустимы только после отдельного derisking/parity.

**Инварианты и полный план миграции:** `.ai/decisions/ADR-0001-canonical-tnved-model.md`.

---

### 1. Guided TN VED semantic-quality expansion

**Обоснование:** Correctness gate прошёл на supplied Gate-2 snapshot по
всем 1 228 heading: 16 708 source-backed code nodes и 13 254 declarable
leaves, zero leaf-role/Canonical-parent mismatch, empty-root/fake/duplicate/degraded.
Semantic choices есть у 548 heading (44.6254%) и покрывают 6 924 leaves
(52.2408%) на текущей feature branch. TASK-SEMANTIC-006 технически реализовал и
проверил первый bounded `2204` slice: шаг `220421` теперь 18 choices / 14 direct
code choices, а PDO открывает 33/33. Максимум первого шага остаётся 19, candidate
catalog-wide максимум любого следующего шага теперь 33/33 в `2204`. Эта exact
official группа сохраняет одну noncritical oversized warning, поскольку глобальный
лимит 30 намеренно не ослаблен. DM-0005 Option A принят: product-semantic choice
закрыт, но текущий docs-only update не выполняет merge, rollout или deployment.

**Что нужно:**
- Сохранить отдельный operational gate: DM-0005 acceptance не выполняет
  merge/rollout/deploy TASK-SEMANTIC-006 и не включает Canonical flags.
- Сохранить отдельный operational gate: принятие DM-0006 не выполняет
  merge/rollout/deploy TASK-SEMANTIC-007 и не включает Canonical flags.
- Для Option A требовать атомарную five-chain signature: точные source titles,
  `(anchor, stop]`, полные ordered tuples, leaf roles и Canonical parents должны
  проверяться Extractor и Builder; любой drift возвращает полный pre-task route.
- Выбирать небольшие наборы heading из `quality_outliers` по максимальной
  пользовательской пользе и добавлять только объяснимые вопросы из официального
  текста.
- Для каждого slice фиксировать golden assertions и сравнивать before/after census.
- Не создавать fake customs codes, не терять реальные коды, не ослаблять Canonical
  binding и safe fallback.
- Не вводить произвольный глобальный usability threshold без отдельного
  product/architecture решения на основе baseline.
- После доступности реального URL дополнить DOM-level тесты live-network/browser QA.

**Gate:** `scripts/diagnose_guided_tnved_navigation.py --all-headings --require-complete`.

---

### 2. Кэширование дерева ТН ВЭД

**Обоснование:** `_build_wrapped_tree()` загружает до 2M строк из БД на каждый запрос. При частых запросах — нагрузка на SQLite и CPU.

**Что нужно:**
- Cache-key: prefix + DB revision/hash
- In-memory (dict) или Redis (если `REDIS_URL` настроен)
- TTL: ~60 секунд или инвалидация при изменении данных
- Использовать `cache_layer.py` (уже есть)

**Риск:** Кэш должен инвалидироваться при изменении `tnved_commodities`. Нужен механизм cache invalidation (bump revision marker уже есть в `preview_cache_revision.py`).

---

### 3. Live-парсер ФТС предрешений

**Обоснование:** Decision Memo #135 зафиксировал, что customs.gov.ru/folder/519 — статистика, а не предрешения. Нужен корректный источник.

**Что нужно:**
- Исследовать актуальный URL предрешений на customs.gov.ru
- Или использовать open-data feed (если появится)
- Playwright-парсер (уже установлен в requirements.txt)
- Не выдавать fixture-данные за официальные решения (текущее ограничение)

**Файл:** `customs-clear/backend/app/services/fts_rulings_crawler.py` (расширить)

---

### 4. Полный аудит graduated-стран (тарифные преференции)

**Обоснование:** При исправлении Китая (PR #130) выявлено, что другие страны могут иметь некорректный GSP-статус относительно Решения Совета ЕЭК № 17 от 05.03.2021.

**Что нужно:**
- Скрипт `scripts/audit_graduated_countries.py`
- Сверить все страны в `country_tariff_preferences` с официальным перечнем ЕЭК
- Обновить через `seed_tariff_preferences.py`

---

## Средний приоритет

### 5. Миграция NTM на v2 (enforcement)

**Обоснование:** NTM v2 — целевая архитектура (см. AGENTS.md). Сейчас feature flags OFF. После валидации данных нужно включить enforcement для `applicability=definite`.

**Что нужно:**
- Активация `NTM_V2_OFFICIAL_SGR_ADVISORY_ENABLED` (отдельный PR, согласование Ivan)
- Миграция существующих `non_tariff_rules` → `ntm_measures_v2`
- Отключение legacy-контура после валидации

**Зависимости:** `app/services/ntm_v2_legacy_measures_enforcement.py` (уже есть)

---

### 6. ETT официальный источник — закрытие 27 legacy строк

**Обоснование:** 27 строк в `hs_rates` имеют провенанс TKS bulk-AI (не ЕЭК). Coverage EEC_ETT = 99.8%, цель 100%.

**Что нужно:**
- Идентифицировать 27 кодов (`source_revision` содержит "seed" или "tks-*")
- Заменить официальными данными из ЕЭК (`eec.eaeunion.org`)
- Обновить провенанс через ingestion pipeline (`import_duty_ingestion.py`)

---

### 7. PostgreSQL для production

**Обоснование:** SQLite ограничивает параллельные записи. При росте нагрузки (несколько воркеров uvicorn) WAL-режим SQLite недостаточен.

**Что нужно:**
- `DATABASE_URL` уже поддерживает PostgreSQL (в `db.py`)
- Проверить совместимость FTS5 (придётся мигрировать на `tsvector` / Elasticsearch)
- Docker-compose уже есть

**Заметка:** FTS5 — SQLite-специфика. При переходе на PostgreSQL нужен аналог (pg_trgm или отдельный поиск).

---

### 8. Semantic search через embeddings

**Обоснование:** Базовая инфраструктура готова (`tnved_entry_embeddings`, `embedding_service.py`, Chroma). Нужно наполнить и активировать.

**Что нужно:**
- Запустить `POST /api/tnved/embeddings/ingest` для всей номенклатуры
- Проверить качество поиска на тестовых запросах
- Интегрировать в `search_commodities_fts()` как дополнительный слой

---

### 9. Расширение регрессионной матрицы NTM

**Обоснование:** Текущая матрица покрывает 71 тест-кейс (увеличена в PR #70). После изменений в ТР ТС каталоге важно расширять покрытие.

**Что нужно:**
- Добавить тест-кейсы для глав с малым покрытием (выявлены в Issue #123)
- Проверить коды, где есть только advisory (не enforcement) требования
- Верифицировать фармацевтику (гл. 30), ветеринарию (гл. 05)

---

## Долгосрочные улучшения

### 10. Fine-tuning классификатора ТН ВЭД

**Обоснование:** `training_pairs.jsonl` формируется автоматически из журнала решений. При достижении достаточного объёма (цель ~10K пар) — доообучение специализированной модели.

**Что нужно:**
- `scripts/export_training_pairs.py --format openai-chat` (готов)
- Обучение — вне репозитория (по `INFERENCE_CLASSIFIER.md`)
- Интеграция через `CUSTOM_CLASSIFIER_URL` (endpoint уже есть)

---

### 11. Multi-worker FSA (Redis queue)

**Обоснование:** Текущая async-верификация ФСА — one-worker. При параллельных запросах очередь не гарантирует порядок.

**Что нужно:**
- Redis-backed task queue (Celery или встроенный)
- `permits_verify_jobs` уже персистирует задачи в БД
- Метрики через `GET /api/permits/metrics` (готов)

---

### 12. ТН ВЭД tree — display_code без spaces

**Обоснование:** Несоответствие между `display_code` (может содержать пробелы) и `code` (без пробелов). Фронтенд форматирует коды для отображения самостоятельно, но стандартизация снизит риски ошибок.

**Что нужно:**
- Проверить все случаи в `_serialize_tree_node()` где `display_code != _digits(code)`
- Убедиться, что frontend корректно использует `display_code` vs `code` для кликов

---

### 13. Алгоритм валидации дерева

**Обоснование:** Нет инструмента для сравнения структуры дерева с эталоном ТКС. Каждый фикс (L6, L8) обнаруживался вручную.

**Что нужно:**
- Скрипт `scripts/validate_tree_vs_tks.py`
- Парсинг tks.ru (уже есть базовый краулер)
- Сравнение: уровень узла, is_codeless, display_code

---

*Приоритеты пересматриваются по решению Ivan. Decision Memo при архитектурных развилках — обязательно.*
