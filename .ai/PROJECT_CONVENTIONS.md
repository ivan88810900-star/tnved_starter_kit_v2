# PROJECT_CONVENTIONS.md — Соглашения и архитектура проекта

> Автоматически составлен на основе анализа кода репозитория.
> Обновляйте при крупных архитектурных изменениях.

---

## 1. Архитектура

**Монорепозиторий платформы таможенного оформления (ВЭД, ЕАЭС).**

| Слой | Технология |
|------|-----------|
| Backend | FastAPI + SQLAlchemy (asynccontextmanager lifespan) |
| База данных | SQLite (`customs.db`) — файл в `customs-clear/backend/` |
| Миграции | Alembic (`customs-clear/backend/alembic/`) |
| Frontend | React 18 + TypeScript + Vite 8 + Tailwind CSS 3.4 |
| API proxy | Vite dev-proxy `/api/*` → `http://localhost:8001` |
| Планировщик | APScheduler (опциональный, `app/services/scheduler.py`) |
| Кэш | Redis (опц.) или in-memory (`app/services/cache_layer.py`) |
| LLM | Gemini (primary) + Anthropic Claude (optional) |

---

## 2. Структура директорий

```
tnved_starter_kit_v2/
├── .ai/                          # AI knowledge base (этот каталог)
├── .github/                      # GitHub Actions workflows
│   └── workflows/
│       ├── claude-auto-merge.yml
│       ├── claude-fix-pr.yml
│       ├── claude-pr-reviewer.yml
│       ├── cursor-task-agent.yml
│       └── opendata-sync.yml
├── AGENTS.md                     # Мультиагентный контракт (binding)
├── ARCHITECTURE.md               # Архитектура (исходная документация)
├── customs-clear/                # ОСНОВНОЙ продукт
│   ├── backend/                  # FastAPI backend
│   │   ├── app/
│   │   │   ├── api/              # REST-роутеры
│   │   │   ├── models/           # SQLAlchemy ORM
│   │   │   ├── schemas/          # Pydantic schemas
│   │   │   ├── services/         # Бизнес-логика
│   │   │   ├── scripts/          # CLI-скрипты
│   │   │   ├── data/             # Seed-данные и JSON-пакеты
│   │   │   ├── db.py             # SQLAlchemy engine + Base
│   │   │   ├── main.py           # FastAPI app + lifespan + роутеры
│   │   │   └── security.py       # JWT / admin token
│   │   ├── alembic/              # Миграции
│   │   │   └── versions/         # ~60 ревизий
│   │   ├── customs.db            # Основная БД (gitignore)
│   │   └── requirements.txt
│   └── frontend/                 # React frontend
│       ├── src/
│       │   ├── api/              # API-клиент (axios + generated types)
│       │   ├── components/       # UI-компоненты
│       │   ├── pages/            # Страницы (роуты React Router)
│       │   ├── store/            # Bridges / состояние
│       │   ├── types/            # TypeScript типы
│       │   ├── utils/            # Утилиты
│       │   ├── styles/           # CSS-токены
│       │   └── main.tsx          # Точка входа
│       ├── vite.config.ts
│       ├── tailwind.config.cjs
│       └── package.json
├── backend/                      # Legacy facade (НЕ РАСШИРЯТЬ)
└── ai/prompts/                   # LLM-промпты
```

---

## 3. Основные backend-модули

### `app/api/` — REST-роутеры

| Файл | Prefix | Назначение |
|------|--------|-----------|
| `tnved_catalog.py` | `/api/v1/tnved` | Главный файл: дерево ТН ВЭД, поиск, карточка товара |
| `classify.py` | `/api/classify` | AI-классификация ТН ВЭД |
| `calculator.py` | `/api/calculator` | Расчёт таможенных платежей |
| `payments.py` | `/api/payments` | Платёжный профиль |
| `non_tariff.py` | `/api/non_tariff` | Нетарифные меры |
| `invoice.py` | `/api/invoice` | Пакинг-листы и инвойсы |
| `assistant.py` | `/api/assistant` | AI-ассистент / copilot |
| `permits.py` | `/api/permits` | Разрешительные документы (ФСА, ТРОИС) |
| `trois.py` | `/api/trois` | Реестр ТРОИС (интеллектуальная собственность) |
| `rop.py` | `/api/rop` | РОП / экосбор |
| `regulatory.py` | `/api/regulatory` | Нормативные документы |
| `admin_v1.py` | `/api/v1/admin` | Административные функции |
| `auth.py` | `/api/auth` | Аутентификация JWT |
| `sources.py` | `/api/sources` | Статус источников данных |

### `app/services/` — Бизнес-логика

Ключевые сервисы:

| Файл | Назначение |
|------|-----------|
| `normative_store.py` | Центральный сервис: ставки, статус источников, `is_leaf_hs_code`, поиск |
| `invoice_analyzer.py` | Анализ инвойса с AI (Gemini) |
| `payment_engine.py` | Движок расчёта таможенных платежей |
| `non_tariff_service.py` | Нетарифные меры (legacy контур) |
| `ntm_engine_v2.py` | NTM v2 — целевой контур нетарифных мер |
| `tr_ts_catalog.py` | Каталог ТР ТС, `get_full_ntm_requirements` |
| `non_tariff_measures_lookup.py` | Каскадный поиск мер по префиксам |
| `tnved_fts.py` | FTS5 full-text search по номенклатуре |
| `tnved_code_card.py` | Карточка кода: предварительные решения |
| `assistant_orchestrator.py` | Оркестрация copilot-конвейера |
| `payment_quote_service.py` | Котировка таможенных платежей |
| `rop_calculator.py` | Расчёт РОП / утильсбора |
| `scheduler.py` | APScheduler: cron-задачи синхронизации |
| `cache_layer.py` | Redis / in-memory кэш |
| `exchange_rates.py` | Курсы ЦБ РФ |
| `smart_classifier.py` | SmartClassifier: Vision + web-search для пакинг-листов |
| `packing_list_parser.py` | Парсер пакинг-листов (CN/EN/RU, фото) |

### `app/models/` — SQLAlchemy ORM

| Файл | Основные модели |
|------|----------------|
| `core.py` | `HsRate`, `NonTariffRule`, `SourceStatus`, `SyncLog`, `ExchangeRate`, `ClassificationDecision`, `PreliminaryDecision`, `GeoSpecialDuty`, `CountryRisk`, `CountryTariffPreference` |
| `tnved.py` | `Section`, `Chapter`, `Commodity`, `HsDutyRule`, `NonTariffMeasure`, `IntellectualProperty`, `SpecialDuty`, `VatPreference` |
| `ntm_v2.py` | `NtmMeasureV2`, `NtmApplicabilityRuleV2` |
| `regulatory.py` | `RegulatoryDocument`, `RegulatoryAiExtract`, `IngestedDocument` |
| `rop.py` | `RopGoodsRate`, `RopPackagingRate` |

---

## 4. Основные frontend-модули

### `src/pages/` — Страницы

| Файл | Маршрут | Описание |
|------|---------|---------|
| `HomeDashboard.tsx` | `/` | Главная страница |
| `TnvedBook.tsx` | `/tnved` | Справочник ТН ВЭД (дерево + карточка) |
| `Classifier.tsx` | `/classifier` | AI-классификатор |
| `Calculator.tsx` | `/calculator` | Расчёт платежей |
| `NonTariff.tsx` | `/non-tariff` | Нетарифные меры |
| `Invoice.tsx` | `/invoice` | Загрузка инвойса / пакинг-листа |
| `Assistant.tsx` | `/assistant` | AI-ассистент |
| `PermitPicker.tsx` | `/permits` | Подбор разрешительных документов |
| `Trois.tsx` | `/trois` | Реестр ТРОИС |
| `Dictionary.tsx` | `/dictionary` | Словарь |

### `src/components/tnved/` — Компоненты дерева ТН ВЭД

| Файл | Назначение |
|------|-----------|
| `TnvedTree.tsx` | Основное дерево (drill-down) |
| `HierarchyView.tsx` | Иерархическое представление |
| `ProductDetails.tsx` | Карточка товара (полная) |
| `ProductCardSummary.tsx` | Краткий summary-блок карточки |
| `PermitDocumentsBlock.tsx` | Разрешительные документы |
| `ClassificationRulingsBlock.tsx` | Классификационные решения |

### `src/api/` — API-клиент

| Файл | Назначение |
|------|-----------|
| `client.ts` | Axios-инстанс с базовым URL |
| `tnvedCatalog.ts` | Функции для `/api/v1/tnved/*` |
| `paymentQuote.ts` | Котировка платежей |
| `openapi.generated.ts` | Автогенерированные TypeScript-типы |

---

## 5. Устройство БД

- **Файл:** `customs-clear/backend/customs.db` (SQLite WAL-режим)
- **ORM:** SQLAlchemy 2.x (Mapped columns, declarative)
- **Migrations:** Alembic (~60 версий в `alembic/versions/`)
- **Base:** `app/db.py` — `Base = declarative_base()`, `SessionLocal = sessionmaker(...)`
- **Engine:** создаётся при старте через `DATABASE_URL` (по умолчанию `sqlite:///./customs.db`)
- **FTS5:** виртуальная таблица `tnved_fts` — создаётся в runtime при старте, **не через Alembic** (ограничение SQLite FTS5)

### Ключевые таблицы

| Таблица | Назначение |
|---------|-----------|
| `tnved_sections` | Разделы ТН ВЭД (I–XXI, roman_number) |
| `tnved_chapters` | Группы (2-значный код) |
| `tnved_commodities` | Все товарные коды (10-значные + 4-значные) |
| `hs_rates` | Ставки пошлины/НДС/акцизы |
| `non_tariff_measures` | Нетарифные меры (legacy TKS) |
| `ntm_measures_v2` | Нетарифные меры v2 (целевой контур) |
| `ntm_applicability_rules_v2` | Правила применимости NTM v2 |
| `country_tariff_preferences` | Тарифные преференции по странам |
| `geo_special_duties` | Геополитические пошлины и эмбарго |
| `special_duties` | Антидемпинг / спецпошлины |
| `classification_decisions` | Классификационные решения ФТС |
| `exchange_rates` | Курсы валют (ЦБ РФ) |
| `source_status` | Статус внешних источников данных |
| `sync_log` | Журнал синхронизаций |

---

## 6. Основные сервисы и их роли

### `normative_store.py`
Центральный сервис. Содержит:
- `init_db()` — инициализация при старте (seed-данные, FTS-индекс)
- `find_rate_for_hs(hs_code)` — поиск ставки по коду
- `is_leaf_hs_code(code)` — проверка, является ли код декларируемым листом
- `get_integrated_data_stats()` — статистика БД
- `check_geopolitical_risks(hs_code, country_iso)` — геополитические риски

### `tr_ts_catalog.py`
- `get_full_ntm_requirements(hs_code, description)` — объединённые требования NTM (ТР ТС + v2 + legacy)
- `get_tr_ts_requirements(hs_code)` — только ТР ТС из каталога
- Словарь `TR_TS_FULL_NAMES` — полные названия техрегламентов

### `ntm_engine_v2.py`
- `get_tr_ts_requirements_for_pipeline(hs_code, description)` — требования для pipeline
- Работает с таблицами `ntm_measures_v2`, `ntm_applicability_rules_v2`

### `tnved_fts.py`
- `search_commodities_fts(query, limit)` — FTS5-поиск по номенклатуре
- Возвращает список `{code, description}` или `None` (FTS недоступен)

---

## 7. Важные инварианты проекта

1. **Коды ТН ВЭД хранятся как строки**, всегда 10 символов с ведущими нулями (zfill(10)). Не использовать int.
2. **4-значные "heading" коды** тоже хранятся в `tnved_commodities` — их `code` имеет длину ≤4 символов.
3. **Pad-коды (XXXX000000)** — технические заголовки, не декларируемые коды. `_node_level("9401000000") == 4`.
4. **`is_leaf=True`** означает кликабельный декларируемый 10-значный код.
5. **`is_codeless=True`** означает промежуточный бескодовый узел (отображается, но не кликабелен).
6. **NTM v2 — целевая архитектура.** Legacy NTM (`USE_LEGACY_NTM = False`) отключён в карточке.
7. **source_kind isolation:** не смешивать `official_*` и `legacy_*` без явного merge-policy.
8. **Feature flags** (`NTM_V2_*`): default OFF, включение только по разрешению Ivan.
9. **Новая бизнес-логика** → только `app/services/`. Роутеры → только `app/api/`.
10. **Legacy backend** (`backend/` в корне) — не расширять.
11. **FTS5 virtual table** — не создаётся через Alembic (bug в SQLite FTS5 + Alembic).

---

## 8. Что категорически запрещено менять

- **Схему таблиц напрямую** (только через Alembic).
- **`USE_LEGACY_NTM`** — не менять на `True` без явного разрешения.
- **`_build_tree()` и `_classify()`** — только при наличии регрессионного теста на конкретный код.
- **Поле `code` в Commodity** — строковый тип, не конвертировать в int нигде в коде.
- **Merge-миграцию** `merge_heads_001` — не трогать (создана специально для восстановления после PR #115).
- **Legacy backend** в корне репозитория (`backend/`) — не добавлять бизнес-логику.

---

## 9. Критичные части проекта

- `customs-clear/backend/app/api/tnved_catalog.py` — главный файл, 1400+ строк. Дерево ТН ВЭД.
- `customs-clear/backend/app/services/normative_store.py` — центральный сервис нормативных данных.
- `customs-clear/backend/app/services/tr_ts_catalog.py` — каталог ТР ТС, источник нетарифных требований.
- `customs-clear/backend/app/services/ntm_engine_v2.py` — NTM v2 runtime engine.
- `customs-clear/backend/app/services/payment_engine.py` — движок платежей.
- `customs-clear/backend/alembic/versions/` — история миграций (целостность критична).
- `customs-clear/frontend/src/components/tnved/` — компоненты дерева (сложная логика is_leaf/is_codeless).

---

*Создан: 2026-06-26 на основе анализа кода.*
