# Архитектура CustomsClear (backend)

Документ описывает актуальное состояние кода в каталоге **`customs-clear/backend/`** (FastAPI, SQLAlchemy, интеграции). Обновляйте при крупных изменениях пайплайна или схемы БД.

---

## 1. Пайплайн анализа инвойса (строка товара)

Типичный путь: **`scripts/test_invoice_parsing.py`** → функции из **`app/services/invoice_analyzer.py`**.

| Шаг | Что происходит |
|-----|----------------|
| **1. Загрузка** | `load_specification_table` читает CSV/XLSX; для xlsx — `extract_images_from_xlsx` (вложения в колонке изображения → `data/temp_images/{row}.jpg`). |
| **2. Маппинг колонок** | `map_columns` — заголовки (в т.ч. `Наименование`, `Страна`, `Код`, `Image_Path`, китайские поля) → внутренние ключи (`name_ru`, `country_origin`, `declared_hs_code`, `image_path`, …). |
| **3. Vision (путь к фото)** | `DocumentVisionExtractor.extract_image_for_row` / `_resolve_invoice_row_image_path`: локальный путь из `Image_Path` или `_image_path`; при наличии файла — мультимодальный запрос к Gemini. |
| **4. Подбор ТН ВЭД** | `InvoiceAnalyzer.suggest_hs_code_for_item` → `suggest_hs_code`: прецеденты ФТС в промпт; **Structured JSON** (`hs_code`, `justification`, `attributes`, `confidence_score`, `compliance_warnings`, `vision_insights`); при сбое — повтор с меньшей температурой, затем **legacy** JSON с `suggested_description_31`. |
| **5. 31-я графа** | `_build_box_31_description(attributes)` → поля `Description_31` / `suggested_description_31`; при `confidence_score < 70` — суффикс `[LOW CONFIDENCE]` в обосновании. |
| **6. НДС (льгота)** | При попадании кода в справочник ПП РФ 908/688 — `gemini_vat_expertise_preferential` (второй запрос Gemini). |
| **7. Геополитика / санкции** | `enrich_with_customs_data` → `check_geopolitical_risks`: `CountryRisk`, **`geo_special_duties`** (LIKE по префиксу ТН ВЭД + страна), `sanction_import_risks`; эмбарго → `ЗАПРЕТ ВВОЗА` и блокировка сумм; повышенная пошлина → подмена `duty_rate`. |
| **8. Финансы Incoterms** | `InvoiceAnalyzer._calculate_financials` / `apply_financial_columns`: фрахт в руб., распределение по строкам, `customs_value`, при необходимости `landed_cost_freight_addon`. |
| **9. НДС в суммах** | В обогащении: базовая ставка импортного НДС **22%** (или **10%** при валидном override из шага 6). |
| **10. Риски по строке** | `analyze_item_risks` (Gemini, опционально с фото) → колонка `ai_risk_notes`. |
| **11. Excel** | `write_invoice_report_excel` + стили/формулы пошлины и НДС. |

Отдельно: **`Vision_Insights`** — краткий вывод модели по фото (шильдики, конструкция) из поля `vision_insights` structured-ответа.

---

## 2. База данных (основные таблицы / модели)

ORM: **`app/models/core.py`**, **`app/models/tnved.py`**. Файл БД по умолчанию: **`customs.db`** (`DATABASE_URL=sqlite:///./customs.db` относительно каталога запуска, обычно `backend/`).

| Таблица | Назначение |
|---------|------------|
| `source_status` | Статус синхронизации внешних источников. |
| `hs_rates` | Ставки пошлины/НДС/акцизы по коду ТН ВЭД (в т.ч. импорт из TWS и др.). |
| `exchange_rates` | Курсы валют (ЦБ РФ). |
| `non_tariff_rules` | Нетарифные правила по префиксам (ТР ТС, разрешения). |
| `sync_log` | Журнал синхронизаций. |
| `regulatory_sync_state` / `regulatory_sync_events` | Состояние и события фоновой синхронизации нормативки. |
| `regulatory_ai_extracts` | Извлечённые LLM правила из актов. |
| `bulk_import_jobs` / `bulk_import_file_checkpoints` | Массовый ИИ-импорт нормативных файлов. |
| `historical_crawl_checkpoints` | Чекпоинты исторического краулера. |
| `tnved_entries` | Каталог ТН ВЭД (код, иерархия, описание). |
| `tnved_entry_embeddings` | Эмбеддинги для RAG по ТН ВЭД. |
| `tr_ts_acts` | Справочник техрегламентов ТР ТС. |
| `normative_notes` | Примечания к кодам / главам. |
| **`country_risks`** | Справочник стран: ISO-2, `is_unfriendly`, `has_preference`, сертификаты. |
| **`geo_special_duties`** | Георегулирование: префикс ТН ВЭД × страна (`ALL_UNFRIENDLY` или ISO), ставка/эмбарго, `measure_type`, `document_basis`, `document_link`. |
| **`sanction_import_risks`** | Упрощённые риски по префиксу × юрисдикция (EU/US/UK). |
| `classification_decisions` | Классификационные решения ФТС (прецеденты для промпта). |
| `ingested_documents` / `parsed_invoice_lines` | Загруженные документы и разобранные строки. |
| `permits_verify_jobs` / `ved_intel_jobs` | Фоновые задачи проверок / intel. |
| `customs_calculation_history` | История расчётов. |
| `tnved_sections` / `tnved_chapters` / `tnved_commodities` | Иерархия ТН ВЭД (пакет tnved). |
| `hs_duty_rules` | Правила ставок (tnved). |
| `non_tariff_measures` | Нетарифные меры по коду товара. |
| `intellectual_properties` | ОИС / IP. |
| **`special_duties`** | Антидемпинг и спецпошлины (таблица **`special_duties`**, не путать с `geo_special_duties`). |
| `vat_preferences` | Льготы по НДС. |
| `tamdoc_sync_candidates` | Кандидаты синхронизации TamDoc. |

---

## 3. Интеграции и внешние источники

| Система | Где используется |
|---------|------------------|
| **Gemini (Google Generative AI)** | Классификация ТН ВЭД, НДС-экспертиза, риски, bulk AI, парсинг стран для geo; настройка `gemini_genai_configure` (в т.ч. `GEMINI_BASE_URL`). |
| **Anthropic** | Опционально (`claude_service`, ключ `ANTHROPIC_API_KEY`). |
| **TWS (tws.by)** | Импорт тарифа в `hs_rates` — `scripts/sync_tws_data.py`. |
| **TKS / ФТС прецеденты** | `sync_tks_predecisions`, клиенты в `app/services` — пополнение `classification_decisions`. |
| **ЦБ РФ (курсы)** | `CurrencyService` / синхронизация в `exchange_rates`. |
| **Playwright** | Исторический краулер, Tamdoc и др. (зависимости в `requirements.txt`). |
| **HTTP (httpx / requests)** | Парсеры alta.ru, sync_geo_regulations, внешние страницы. |
| **Открытые / публичные страницы** | Альта-Софт, Consultant и др. в скриптах синхронизации (не единый официальный SDK ФТС). |

---

## 4. Геополитика (`country_risks` + `geo_special_duties`)

- **`country_risks`**: по ISO-2 флаги «недружественная» / преференция и текстовые подсказки по сертификатам.
- **`geo_special_duties`**: строки с `hs_code_prefix`, `country_iso` (или `ALL_UNFRIENDLY` для всех недружественных из справочника), `duty_rate`, `document_basis`, **`measure_type`** (`embargo` | `increased_duty` | `anti_dumping` | `preference`), **`document_link`**.
- Подбор в **`normative_store`**: SQL `literal(hs_code).like(prefix || '%')` + фильтр по стране; приоритет эмбарго в `check_geopolitical_risks`; повышенная ставка подменяет базовую в `enrich_with_customs_data`.
- Сиды и демо: **`scripts/seed_geopolitics.py`**; парсинг справок: **`scripts/sync_geo_regulations.py`**.

---

## 5. Структура каталогов (кратко)

- **`app/api/`** — REST (в т.ч. assistant, admin, sync center).
- **`app/services/`** — бизнес-логика: `invoice_analyzer`, `normative_store`, `vision_extractor`, синхронизации, RAG, планировщик.
- **`app/models/`** — ORM.
- **`alembic/`** — миграции.
- **`scripts/`** — CLI: импорты, синхронизации, QC, тест инвойса, **диагностика** (`diagnostics.py`).

---

## 6. Мониторинг

Из каталога **`customs-clear/backend`**:

```bash
python3 scripts/diagnostics.py
```

Вывод: таблицы и `COUNT(*)`, статус ключевых переменных окружения (без значений секретов), список скриптов с первой строкой docstring.
