# План развития CustomsClear: базы данных и умный ассистент

Документ фиксирует **целевое видение**, **этапы** и уже **реализованный** слой оркестрации (`/api/assistant/copilot`). Обновляйте статусы по мере внедрения.

---

## 1. Цели

| Направление | Сейчас | Цель |
|-------------|--------|------|
| **ТН ВЭД / классификация** | ИИ-классификатор (Gemini/Claude), локальная БД ЕТТ | + интеграция с официальными справочниками, история решений пользователя, обучение на отклонениях |
| **Платежи** | Движок по БД (пошлина, НДС, акциз, антидемпинг) | + актуальные выгрузки ЕТТ по расписанию, валидация ставок, сценарии «что если» |
| **Нетарифка** | Правила + ТР ТС в коде/БД | + расширяемые правила, привязка к редакциям ТР, учёт исключений |
| **Разрешения (СС/ДС/СГР)** | ФСА/fp.crc.ru (ограничения SPA/403), справочник подбора | + прокси/API (`FSA_EXTERNAL_API_URL`), очередь проверок, кэш с TTL |
| **ТРОИС** | Локальный кэш брендов + попытка customs.gov.ru | + выгрузка/индекс реестра, fuzzy-поиск, связка с декларацией |
| **Документы** | Инвойс/упаковка, извлечение СС/ДС | + NLP-сопоставление позиций, валидация реквизитов контрагентов |
| **Ассистент** | Нетарифка + ИИ; отдельно комплаенс | **Единый конвейер** (классификация → платежи → нетарифка → реестры → ИИ) |

---

## 2. Архитектура (целевая)

```
[Пользователь]
     │
     ▼
┌─────────────────────┐
│  API Gateway        │  auth, rate-limit, логирование
└─────────┬───────────┘
          │
     ┌────▼──────────────────────────────────────────┐
     │  Assistant Orchestrator (copilot)              │
     │  • шаги pipeline с метаданными                 │
     │  • агрегация в контекст для LLM                │
     └────┬──────────┬──────────┬──────────┬─────────┘
          │          │          │          │
    ┌─────▼───┐ ┌───▼───┐ ┌────▼────┐ ┌───▼────┐
    │ Classify│ │Payment│ │NonTariff│ │Permits │
    └────┬────┘ └───┬───┘ └────┬────┘ └───┬────┘
         │          │          │          │
    ┌────▼──────────────────────────────────────────┐
    │  Normative DB (SQLite/PostgreSQL) + файлы сидов │
    │  Внешние: ФСА (прокси), ТРОИС, курсы ЦБ       │
    └───────────────────────────────────────────────┘
```

---

## 3. Этапы (фазы)

### Фаза A — Оркестрация (сделано в коде v1)
- [x] Сервис `assistant_orchestrator.py`: последовательный запуск классификации (опц.), расчёта платежей, нетарифки, проверки реестра (опц.).
- [x] `POST /api/assistant/copilot` + расширенный промпт ИИ `analyze_copilot_bundle`.
- [x] UI: режим «Умный конвейер» на странице Ассистента.

### Фаза B — Данные и надёжность
- [x] Планировщик импорта: `SCHEDULER_ENABLED` + APScheduler (`sync_all_sources` по интервалу); внешний cron — `scripts/scheduled_sync.sh`.
- [x] PostgreSQL-ready: `DATABASE_URL`, `pool_pre_ping`; `docker-compose.yml`; Alembic уже в проекте (`alembic upgrade head`).
- [x] Кэш Redis + память: `REDIS_URL`, TTL; ФСА/СГР и ТРОИС; `POST /api/permits/cache/clear`; `/api/health/ready`.

### Фаза C — Внешние реестры
- [x] Прокси ФСА: `FSA_EXTERNAL_API_URL` (документировано; обязательность для прода — на стороне эксплуатации).
- [x] Подсказки ТРОИС: `GET /api/trois/suggest` (fuzzy + подстрока по локальному кэшу).

### Фаза D — Продукт и ИИ
- [x] Мультипозиционный copilot: `POST /api/assistant/copilot/batch`.
- [x] RAG v0: `RAG_DOCS_DIR` + поиск по токенам и скользящим окнам в .txt/.md, контекст в промпте copilot/batch.
- [x] Аудит v0: `AUDIT_LOG_ENABLED` + JSONL на copilot, batch и `analyze`; опционально `X-Client-Id` / `X-Audit-Subject`.

### Фаза E — UI и доработки
- [x] Страница ассистента: режим **«Пакет (несколько позиций)»** → batch API; **нетарифка + ИИ** — несколько строк в одном запросе.
- [x] Параллельный batch (`COPILOT_BATCH_CONCURRENCY`), порядок позиций сохраняется.
- [x] RAG: **PDF** (.pdf через PyMuPDF/pdfplumber), опц. **TF‑IDF rerank** (`RAG_USE_TFIDF`), опц. **Chroma** (`RAG_CHROMA_PATH` + `scripts/ingest_rag_chroma.py`, `requirements-rag.txt`).
- [x] **Журнал решений** v0: `POST/GET /api/assistant/decisions/*`, JSONL `DECISIONS_LOG_PATH`; UI — сохранение и просмотр последних записей; экспорт результатов в JSON.
- [x] **Подсказки из журнала**: `GET /decisions/similar`, поиск по гибридной похожести (difflib + Jaccard), debounce в UI; поле `similar_past_decisions` в контексте **copilot / batch / analyze** для ИИ.
- [x] **Ранжирование кодов из журнала**: `suggest_hs_codes`, `GET /decisions/suggest-hs`, объединённый `GET /decisions/hints`; подсказки в промпте **`/api/classify`** (`use_journal_hints`, `DECISIONS_CLASSIFIER_HINTS`); выгрузка **`GET /decisions/export`** (json/csv, опц. админ-токен).
- [x] **Приоритет по клиенту:** `prefer_client_id` из `X-Client-Id` в hints/similar/suggest-hs, copilot/batch/analyze и в подсказках `/classify` (+ опционально `client_id` в теле); скрипт **`export_training_pairs.py`**.
- [ ] Отдельная модель / fine-tune по `training_pairs.jsonl`.

### Фаза F1 — Эксплуатация и расширения (MVP в коде)
- [x] **Внешний классификатор**: `CUSTOM_CLASSIFIER_*` + `POST /api/classify` (`use_custom_classifier`, `fallback_to_llm`; режимы `first_custom` / `first_llm` / `custom_only`).
- [x] **ФСА**: фоновая проверка `POST /api/permits/verify/async` + `GET /api/permits/verify/jobs/{id}`; метрики `GET /api/permits/metrics`.
- [x] **Нетарифка**: таблица `tr_ts_acts`, `GET /api/non_tariff/tr-ts-registry`, в ответе `/non_tariff/check` поля `tr_ts_act_codes`, `tr_ts_registry`.
- [x] **ТРОИС**: `GET /api/trois/stats`, ранжирование подсказок с `score`, `POST /api/trois/reload-cache` + `TROIS_EXTRA_BRANDS_PATH`.
- [x] **Документы**: `POST /api/documents/match-lines`, `POST /api/documents/validate-counterparty` (ИНН РФ).
- [x] **Эксплуатация**: `RATE_LIMIT_*` middleware, `GET /api/health/normative`, скрипт `scripts/backup_sqlite.sh`.

### Фаза F — Контент и демо
- [x] Каталог **docs/rag_sources** с базовыми `.md` для RAG; **docs/samples** с примером журнала; скрипт **`seed_demo_journal.py`**; справочник **`docs/ENVIRONMENT.md`**; расширенный **`.env.example`**.
- [x] **`GET /api/assistant/decisions/stats`** и блок в UI ассистента.

### Фаза G — UI/UX
- [x] Единая премиальная тема (**`styles.css`**, шрифты), боковое меню без шума.
- [x] Все разделы: второстепенное в **`cc-disclosure`**, без сырых JSON в основном потоке (ассистент, классификатор, калькулятор, нетарифка, документы, ТРОИС, подбор СС/ДС).
- [x] **Аналитика:** `GET /api/analytics/overview` + вкладка «Аналитика» (сводка БД, ИИ, журналов, ФСА, ТРОИС, текстовые выводы); индикатор готовности API в шапке.

### Фаза H — Альта-Софт (XML-API)
- [x] Документация **`docs/integration/`** (auth, ТиК, АПУ).
- [x] Backend: **`alta_common`**, **`alta_xml`**, **`alta_client`**, роутер **`/api/integrations/alta/*`**.
- [x] UI классификатора: **запасной** блок Альты; основная нормативка — импорт, в т.ч. **Excel TWS.BY**.

### Фаза I — Выгрузка TWS.BY
- [x] **`docs/integration/tws_by.md`**, импорт **`.xlsx` / `.xlsm`** в `source_import.py`, подсказки в калькуляторе.

### Фаза J — Единый пакет нормативных данных
- [x] Таблицы **`tnved_entries`**, **`normative_notes`**, импорт JSON-пакета, **`NORMATIVE_BUNDLE_URL`**, API **`/api/tnved/*`**, вкладка «Справочник ТН ВЭД», **`tnved_context`** в калькуляторе. См. **`docs/integration/NORMATIVE_PIPELINE.md`**.

### Фаза K — Связка данных и UX
- [x] Поиск **`GET /api/search/hs`**: обогащение **`title`** из `tnved_entries` (параметр **`enrich=false`** — старый формат).
- [x] **`GET /api/sources/status`**: блоки **`stats`** и **`hints`** (пустой справочник, мало ставок, EEC недоступен).
- [x] Copilot / batch: в **`bundle`** — **`tnved_context`**, в промпт ИИ — сжатый **`tnved_from_db`**.
- [x] Документация и флаг **`--format openai-chat`** для **`scripts/export_training_pairs.py`**; гайд **`docs/ML_TRAINING_PIPELINE.md`** (само обучение — вне репозитория).
- [x] **`POST /api/calculator/compare`**: 2–8 сценариев при общих `customs_value` / фрахте / стране; UI на странице платежей.
- [x] Нетарифные правила: поля **`tr_ts_edition`**, **`exception_note`**, **`priority`**; импорт в пакете; Alembic **`8f1a2b3c4d5e`**; автопатч SQLite в **`init_db`**; UI нетарифки.

### Фаза L1 — Персистенция документов, история расчётов, семантика ТН ВЭД
- [x] Таблицы `ingested_documents`, `parsed_invoice_lines`, `tnved_entry_embeddings`, `customs_calculation_history` + Alembic.
- [x] Сохранение после `POST /api/documents/check` и `upload` (форма `persist`), строки с подсказкой ТН ВЭД из черновика ДТ.
- [x] `GET /api/documents/ingested`, `GET /api/documents/ingested/{id}`.
- [x] История калькулятора: `save_history` / `document_id` / `user_ref` в compute/compare; `GET /api/calculator/history*`.
- [x] Эмбеддинги OpenAI: `POST /api/tnved/embeddings/ingest`, `GET /api/tnved/search/semantic`, `GET /api/tnved/embeddings/status`; счётчики в `/api/tnved/stats` и нормативной статистике.
- [x] UI: флаги сохранения и Client ID на «Документах»; журнал расчётов и связь с `document_id` на «Платежах»; семантический поиск в «Справочнике ТН ВЭД».
- [x] Комплаенс: опциональная запись в `customs_calculation_history` (`save_history`, `document_id`, `user_ref`).
- [x] Copilot / batch: опционально **`save_calculation_history`** + связь с документом; аудит JSONL дополняется `document_id` / `user_ref`.
- [x] Список `/api/calculator/history`: корректные `total_payable` и код для типов `compliance`, `copilot`, `copilot_batch`.
- [x] Фильтр журнала по **`kind`**, **`GET /api/calculator/history/summary`**; чипы на UI «Платежи»; список загрузок на «Документах».

### Фаза M — Официальные платёжные контуры и аудит покрытия

- [x] **PR #56 (Issue #55)** — Official Payment Coverage Audit: read-only аудит 6 официальных доменов (EEC_ETT, EEC_VAT, EEC_EXCISE, EEC_ANTI_DUMPING, EEC_SPECIAL_SAFEGUARD, EEC_COUNTERVAILING); отдельные enum `BackfillSituation` (диагностика) и `RecommendedNextAction` (действие); `configured_official_source: bool`; `expected_official_source: str` (non-null); runnable script `app/scripts/official_payment_coverage_audit.py`; 24 теста. ✅ merged 2026-06-18
- [x] **PR #59 (Issue #51)** — Coverage table and dry-run backfill plan: `build_coverage_table()` → `Domain | In DB | Official | Coverage %`; `build_backfill_plan()` → приоритизированный dry-run план (acquire→apply→reapply→refresh→manual); script `app/scripts/coverage_backfill_plan.py`; 43 теста (19 новых). ✅ merged 2026-06-18
- [x] **PR #43 (Issue #42)** — Official Excise Ingestion MVP: `run_excise_dry_run()` / `run_excise_apply()`; row-level провенанс (`excise_source_*`); Alembic миграция; 25 тестов; API endpoints `/payment-ingestion/excise/*`. ✅ merged (PR #44 closed as superseded)
- [x] **Официальные бандлы и провенанс** — Скачаны/сгенерированы официальные JSON-бандлы для всех 6 доменов (`data/raw_normative/eec_*.json`); скрипты `fetch_eec_official.py` и `build_vat_excise_official.py`; VAT provenance проставлен на 13 296 строк (100%); Excise расширен до 24 позиций по НК РФ Ст. 193.

#### Финальная таблица покрытия (v1.0.0-coverage)

| Domain | In DB | Official | Coverage % | Status |
|--------|------:|---------:|-----------:|--------|
| EEC_ETT | 13 323 | 13 296 | 99.8% | `partial` (27 legacy TKS) |
| EEC_VAT | 13 296 | 13 296 | **100%** | `present` |
| EEC_EXCISE | 24 | 24 | **100%** | `present` |
| EEC_ANTI_DUMPING | 29 | 24 | 82.8% | `manual_review_required` |
| EEC_SPECIAL_SAFEGUARD | 3 | 3 | 100% | `manual_review_required` |
| EEC_COUNTERVAILING | 2 | 2 | 100% | `manual_review_required` |

Остаточные позиции:
- 27 ETT rows из TKS bulk-AI crawler (legacy, не от ЕЭК)
- Trade remedies `manual_review_required` by design — полнота не верифицируема автоматически
- 12 excise HS-кодов исключены (нет в `hs_rates`): сохранены в `excluded_missing_hs_rates`

### Фаза N — Точная система нетарифных мер (NTM v2)

- [x] **PR #67 (Issue #61)** — Principle-based noise classifier: `ntm_noise_classifier.py` с `is_measure_noise()` на основе официальных EEC доменов (SGR/VET/PHYTO/LICENSE); 34+12 тестов. ✅ merged 2026-06-18
- [x] **PR #68 (Issue #62)** — Mass noise marking: `ntm_mass_noise_marking.py` с `--dry-run` / `--revert`; batch-обновление quality="noise" по 500 строк; ~22K noise entries из 41K. ✅ merged 2026-06-18
- [x] **PR #69 (Issue #63)** — Regulatory documents mass sync: `seed_regulatory_documents.py` — 629 нормативных документов (50 ТР ТС, 12 решений ЕЭК, 20 приказов ФТС, 12 РПН, 17 РСН, 10 МПТ) + 1224 HS-привязки + 419 per-prefix ТР ТС application documents. ✅ merged 2026-06-18
- [x] **PR #70 (Issue #64)** — TR TS catalog 6-digit accuracy: ТР ТС 017/2011 split (610910 СС / 610990 ДС, 611510-611530 СС / 611594-611599 ДС); ТР ТС 018/2011 vehicle subtypes; ТР ТС 025/2012 furniture sub-categories. ✅ merged 2026-06-18
- [x] **PR #70 (Issue #65)** — Full regression suite 71 cases: расширение REGRESSION_MATRIX с 37 до 71 тест-кейсов, покрытие 22 новых глав ТН ВЭД. ✅ merged 2026-06-18
- [x] **PR #71 (Issue #66)** — Departmental letters HS binding accuracy: KEYWORD_HS_MAP (80+ терминов → HS), 4-digit extraction в контексте ТН ВЭД, `_extract_keyword_hs_codes()`, 20 тестов. ✅ merged 2026-06-18

### Фаза O — Максимальное наполнение нетарифных данных

- [x] **PR #78-80 (Issues #72-#74)** — Mass data seeding:
  - 5686 regulatory documents across 12 agencies, 6705 HS mappings (Issue #72)
  - 115 departmental instructions by 8 commodity groups (Issue #73)
  - 279 verified Honest Mark (Честный Знак) entries for 14 product groups (Issue #74)
- [x] **PR #81 (Issue #75)** — Country tariff preferences: `country_tariff_preferences` table with 161 countries across 6 preference types (EAEU 0% / SNG 0% / GSP 75% / LDC 0% / MFN 100% / non-MFN 200%); payment engine integration with duty coefficient; 16 tests. ✅ merged 2026-06-18
- [x] **PR #82 (Issue #76)** — NTM full sync: 609 NTM entries across 63 chapters; all 96 active chapters ≥10 entries with ≥3 measure types; normalized stale `licence` → `license`; total 42,631 NTM entries; 9 tests. ✅ merged 2026-06-18
- [x] **PR #83 (Issue #77)** — Customs procedures database: `customs_procedures` table with 22 procedure codes (ИМ40, ИМ51, ИМ53, ЭК10, ТТ80 и др.); payment rules, time limits, required documents, legal references; 12 tests. ✅ merged 2026-06-18

### Фаза P — Расширенные данные и справочники (Issues #85–#89)

- [x] **PR #91 (Issue #85)** — Recycling fee (утильсбор): таблица `recycling_fees` с 39 категориями транспортных средств и самоходных машин; коэффициенты по возрасту (новые/старше 3 лет); API `GET /api/recycling-fee/{hs_code}`; 12 тестов. ✅ merged 2026-06-18
- [x] **PR #92 (Issue #86)** — Import restrictions: таблица `import_restrictions` с запретами, квотами, лицензированием и двойным назначением; API `GET /api/restrictions/{hs_code}`; 12 тестов. ✅ merged 2026-06-18
- [x] **PR #93 (Issue #87)** — Declaration documents: таблица `declaration_documents` со списками документов для декларирования по кодам ТН ВЭД; API `GET /api/declaration/documents/{hs_code}`; тесты. ✅ merged 2026-06-18
- [x] **PR #94 (Issue #88)** — Classification rulings: таблица `classification_rulings` с 50 решениями КТС/ФТС/ЕЭК по классификации товаров; prefix-based lookup; API `GET /api/classification/rulings/{hs_code}`; 13 тестов. ✅ merged 2026-06-19
- [x] **PR #95 (Issue #89)** — Data refresh workflow: unified data_refresh_service (freshness checks для 6 доменов + CBR); CLI `scripts/data_refresh.py`; API `GET /data/freshness` + `POST /data/refresh`; GitHub Actions с CBR/EEC reachability, duplicate issue prevention; APScheduler currency refresh 09:00 daily; 16 тестов. ✅ merged 2026-06-19

### Фаза Q — Официальные платёжные провенансы, поиск и NTM-UX (Issues #39–#114)

- [x] **PR #40 (Issue #39)** — Official VAT Ingestion MVP: атомарный apply (no commit при blockers), row-level VAT провенанс (`vat_source_*`), строгие VAT-revision паттерны (`vat:` / `eec-vat:`), изоляция VAT от import-duty bundle/registry; coverage по VAT-провенансу, а не по duty revision. ✅ merged
- [x] **PR #46 (Issue #45)** — Official Anti-Dumping Ingestion MVP: уникальная Alembic-миграция, строгая official-URL валидация (`eec.eaeunion.org` / HTTPS), детерминированная identity меры (manufacturer/exporter) против коллизий; `trade_remedies` остаётся `manual_review_required`. ✅ merged
- [x] **PR #48 (Issue #47)** — Official Special Safeguard MVP: safeguard-специфичный провенанс (`safeguard_source_*`), изоляция от anti-dumping/VAT/excise/duty, coverage/readiness только по safeguard-полям; regression-тесты доменной изоляции. ✅ merged
- [x] **PR #105** — TNVED tree codeless subpositions: бескодовые субпозиции (`is_codeless`) отделены от 10-значных кликабельных листьев (`is_leaf`), `display_code` без пробелов; backend + frontend по стандарту TKS.ru. ✅ merged
- [x] **PR #111 (Issue #106)** — SYSTEM: FTS5 full-text search по всей номенклатуре ТН ВЭД: runtime-индекс `tnved_fts` (idempotent, вне Alembic из-за #112), синонимы + морфология (prefix), BM25-релевантность; `tnved_fts.py` + тесты. ✅ merged
- [x] **PR #113 (Issue #107)** — SYSTEM: универсальный `NonTariffBlock` для всех 97 глав: централизованный `permitVocabulary` (ДС/СС/ВС/ФСС/РУ/ЛЗ/НФ/СГР → человекочитаемые названия, орган, цветовые бейджи), без сырого TKS-текста. ✅ merged
- [x] **Issue #108** — SYSTEM: аудит полноты данных по главам (NTM / hs_rates / regulatory docs / ТР ТС); выявлены пробелы → дочерние issues #109/#110.
- [x] **PR #115 (Issue #112)** — CRITICAL Alembic fix: устранён дубликат ревизии `a1b2c3d4e5f6` (`country_tariff_preferences` → `a1b2c3d4e5f7`), воссоздана merge-миграция `merge_heads_001` (объединяет 3 головы); `alembic upgrade head` проходит на свежей БД. ✅ merged
- [x] **PR #116 (Issue #109)** — Backfill NTM для главы 97 (культурные ценности): идемпотентный `backfill_ch97_cultural_measures.py` (Закон РФ № 4804-1 + Единый перечень ЕАЭС разд. 2.20); clean NTM по главе 97: 6 → 18. ✅ merged
- [x] **PR #117 (Issue #110)** — Ревизия noise-классификации: доля ~54% признана обоснованной (исправление over-assignment краулера TKS), потери валидных мер нет (12/12 контрольных кодов + 71/71 брокерская регрессия); `audit_ntm_noise.py` для воспроизводимого отчёта. ✅ merged
- [x] **PR #118 (Issue #114)** — Чистка сырого TKS-текста в блоке «Санкции и риски»: скрыты сырые дампы `Мера (тип): …`, нормализованы запретительные меры, санитизация notes/risks (принцип #107). ✅ merged

### Фаза L — Дальше (бэклог)
- [x] Стаб HTTP-классификатора для разработки (`scripts/inference_classifier_stub.py`); боевой inference — вне репозитория по **`INFERENCE_CLASSIFIER.md`**.
- [x] Персистентная очередь async-проверок ФСА (`permits_verify_jobs` в БД).
- [x] Экспорт результата async-задания ФСА (`GET .../verify/jobs/{id}/export`).
- [ ] Мульти-воркер ФСА (Redis/очередь) и расширенная аналитика при необходимости.

---

## 4. Конфигурация окружения (чеклист)

Полный перечень: **`docs/ENVIRONMENT.md`**, шаблон **`customs-clear/.env.example`**.

| Переменная | Назначение |
|------------|------------|
| `DATABASE_URL` | БД нормативки |
| `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` | ИИ |
| `RAG_DOCS_DIR` | Каталог для RAG (`docs/rag_sources`) |
| `DECISIONS_*`, `COPILOT_BATCH_CONCURRENCY` | Журнал и пакетный copilot |
| `REDIS_URL`, `SCHEDULER_*` | Прод: кэш и синхронизация |
| `FSA_EXTERNAL_API_URL` | Прокси к API ФСА при 403 |
| `FSA_REQUEST_DELAY`, `FSA_RETRIES` | Нагрузка на ФСА |
| `CORS_ORIGINS` | Фронт |
| `ADMIN_API_TOKEN` | Экспорт журнала, сброс кэша ФСА |

---

## 5. Метрики готовности «полноценной работы»

1. **Классификация**: доля запросов с валидным 10-значным кодом после ИИ + ручное подтверждение в UI.  
2. **Платежи**: совпадение с контрольными примерами после обновления ЕТТ.  
3. **Нетарифка**: покрытие тестами критичных ТН ВЭД.  
4. **Реестры**: % успешных ответов ФСА не UNKNOWN (после прокси).  
5. **Copilot**: время полного ответа p95 < N сек (задать SLA).

---

*Последнее обновление: фаза Q завершена — официальные платёжные провенансы (VAT/anti-dumping/safeguard), исправление дерева ТН ВЭД, FTS5-поиск по всей номенклатуре, универсальный NonTariffBlock, критический фикс Alembic (#112), backfill главы 97, обоснование noise-разметки, чистка сырого TKS-текста в блоке рисков. 2026-06-19.*
