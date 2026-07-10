# ROADMAP.md — Техническая дорожная карта

> Только задачи, подтверждённые анализом кода и существующего бэклога.
> Не содержит бизнес-wishlist без технического обоснования.
> Дата: 2026-07-10.

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
- ▶ **TASK-CANONICAL-004 (Этап 3, read-path за флагом; in progress)** — структурный слой
  `/children` может читать CanonicalModel за `CANONICAL_TREE_ENABLED` (default OFF),
  с shadow-режимом `CANONICAL_TREE_SHADOW` (default OFF). Provider с in-memory кэшем
  (`provider.py`, build-once под локом, точная content-revision учитывает
  `tnved_commodities`, Section/Chapter notes и leaf-relevant `hs_rates`), fallback на legacy без 500, bridge через
  `TreeSerializer.to_legacy_dict` → существующий `_serialize_tree_node` (overlay не
  дублируется). Контракт JSON неизменён; legacy `build_tree()` не тронут. До завершения
  нужен полный Gate-2 audit на наполненной БД и повторный QA; флаг остаётся OFF.
  Stable requests используют дешёвый DB source-token и не хешируют весь каталог.
  Для Gate-2 передачи без полного DB-архива есть минимальный read-only exporter четырёх
  структурных таблиц (`scripts/export_canonical_gate2_db.py`).

**Текущее состояние и долги:** см. `.ai/CURRENT_STATE.md` §2b/§8/§9. Read-path
`/children` подключён к runtime **только за флагом** (default OFF). Overlay/остальные
эндпоинты по-прежнему legacy. Legacy `_build_tree` остаётся production и oracle.

#### Оставшийся derisking после materialization

> Materialization уже завершена, а первый runtime read-path реализован за default-OFF
> флагом. До расширения runtime и хранения ссылок остаются риски identity/snapshot;
> это направление, а не автоматически созданная задача.

Рекомендуемый порядок работ:
1. ✅ **Расширить parity от структуры до контента.** Сделано в Canonical Model
   Materialization: `test_full_tree_content_parity_with_legacy` сверяет имена,
   `import_duty`, notes, флаги, `display_code` рекурсивно. → Critical-долг закрыт.
2. **Расширить входы `snapshot_id` самой модели.** Включить все влияющие на результат
   входы (как минимум `import_duty`, примечания глав) в `compute_snapshot_id`.
   Частично: read-path **ревизия кэша** (`provider._compute_revision`) уже хеширует
   значимые поля `tnved_commodities`, Section/Chapter notes и leaf-relevant `hs_rates`,
   но это cache-key, а не `snapshot_id` модели.
3. **Закрыть решение по формуле `stable_id`** (Open Decision) до того, как ссылки на
   узлы начнут где-либо храниться.
4. ▶ **Первый read-path за feature flag** — реализуется в TASK-CANONICAL-004:
   `/children` (структурный слой) за `CANONICAL_TREE_ENABLED`, сверка с legacy через
   `CANONICAL_TREE_SHADOW` и `scripts/audit_canonical_children.py`.
   ADR-0002 принят с условиями; включение запрещено до Gate-2 и отдельного решения Ivan.

После Gate-2 и отдельного решения Ivan возможен rollout первого read-path. Расширение
runtime на overlays и удаление legacy допустимы только после отдельного derisking/parity.

**Инварианты и полный план миграции:** `.ai/decisions/ADR-0001-canonical-tnved-model.md`.

---

### 1. Регрессионные тесты дерева ТН ВЭД

**Обоснование:** `_build_tree()` и `_classify()` — критически важные функции без покрытия unit-тестами. Последние два фикса (L6 и L8 синтез) вносились без автотестов, что создаёт риск регрессий.

**Что нужно:**
- Unit-тесты для `_node_level()` (все 5 уровней: 4, 6, 8, 9, 10)
- Тесты `_classify()`: L6 синтез, L8 синтез, узлы с детьми, обычные листья
- Тесты `_build_tree()`: pad-коды, subheading_group, смешанные L6
- Интеграционный тест: проверить конкретный код (например, `0302`) через API

**Файл:** `customs-clear/backend/tests/test_tnved_tree.py` (создать)

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
