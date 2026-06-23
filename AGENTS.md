# AGENTS.md — Мультиагентный pipeline для ВЭД-платформы

**Binding contract** для Codex (technical lead), Cursor (implementation), Ivan (product owner).
Workflow kit: `docs/ai-workflow/`.

---

## Project

Монорепозиторий платформы таможенного оформления (ВЭД, ЕАЭС).

| Область | Путь | Статус |
|---------|------|--------|
| **Основной backend** | `customs-clear/backend/` | Product engine (FastAPI) |
| **Основной frontend** | `customs-clear/frontend/` | React 18 + Vite |
| Desktop | `customs-clear/desktop/` | Electron |
| **Legacy backend** | `backend/` (корень) | Тонкий facade / legacy — **не расширять** |
| Альтернативные UI | `frontend/web/`, `frontend/app/` | Старые/параллельные — только по явной задаче |

**Правило:** новая бизнес-логика → `customs-clear/backend/app/services/`. Роутеры → `customs-clear/backend/app/api/`.

---

## Current architecture direction

### NTM v2 — целевая архитектура

- Таблицы: `ntm_measures_v2`, `ntm_applicability_rules_v2`
- **Applicability:**
  - `definite` — может влиять на enforcement
  - `possible` — только advisory
  - `needs_clarification` — только advisory

**Enforcement (broker / missing / status):**

- Только `applicability = definite` → `required_permit_types`, `missing_permit_types`, `ERROR` / `status`
- `possible` и `needs_clarification` → `advisory_requirements` (и UI advisory), **никогда** не поднимают ERROR сами по себе

### Official contours vs legacy

| Слой | `source_kind` (примеры) | Роль |
|------|-------------------------|------|
| Official contours | `official_sgr_registry`, … | Будущий **source of truth** (курируемые датасеты) |
| Legacy rules | `legacy_non_tariff_rules` | Переходный слой, **не** нормативная истина |
| Legacy measures | импорт из layers | Переходный слой |
| Catalog / triggers | runtime layers | До полной миграции |

- **source_kind isolation** обязателен: не смешивать official и legacy в одном broker-решении без явного merge-policy в PR
- **Feature flags** (`NTM_V2_*`, `NTM_V2_OFFICIAL_SGR_ADVISORY_ENABLED`, …): **default OFF**, пока Ivan не утвердил включение
- Official SGR в advisory ≠ broker; отдельные PR для enforcement

---

## AI team workflow

| Роль | Инструмент | Ответственность |
|------|------------|-----------------|
| **Cursor** | Cursor IDE / Cloud Agents | Код, тесты, PR с отчётом |
| **Codex** | ChatGPT Codex + GitHub | Ревью PR, следующие задачи, Decision Memo |
| **Ivan** | GitHub merge, issues | Утверждение merge и стратегии |
| **Strategic ChatGPT review** | Внешний чат | Арбитраж Decision Memo |

Цикл: `docs/ai-workflow/WORKFLOW.md`.

Актуальный стратегический фокус: `docs/ai-workflow/CURRENT_PROJECT_FOCUS.md`.

---

## Active project focus

Before proposing a next task, Codex must read:

- `docs/ai-workflow/CURRENT_PROJECT_FOCUS.md`

If that file has **Status: Active**, it is the **primary source** for next-step planning and takes precedence over older backlog-style **AGENT-01…05** priorities (including «Текущий приоритет» ниже), unless the issue or Ivan explicitly reprioritizes.

If repository state and `CURRENT_PROJECT_FOCUS.md` conflict, Codex must create a **Decision Memo** instead of silently choosing a direction.

Cursor should read the same file when picking up a `cursor-task` without a fully specified scope.

---

## Codex responsibilities

1. Проверять последний PR / изменения в `main`.
2. Сверять с issue и **acceptance criteria**.
3. Проверять: тесты, миграции Alembic, feature flags, архитектуру NTM v2, секреты.
4. Если работа корректна и следующий шаг очевиден → создать **Cursor Task** issue (`cursor-task`).
5. Если баг или пробел → **corrective** Cursor Task (`cursor-task` / `cursor-fix`).
6. Если стратегическая развилка → **Decision Memo** (`needs-ivan-decision`), **не** выбирать направление молча.

Чеклист: `docs/ai-workflow/CODEX_REVIEW_CHECKLIST.md`.

---

## When to create a Decision Memo

Обязательно, если:

- несколько архитектурных вариантов с разной стоимостью;
- решение влияет на семантику продукта (что видит пользователь / таможня);
- enforcement vs advisory неочевидны;
- важна legal/compliance интерпретация (ТН ВЭД, СГР, ТР ТС);
- локальный фикс маскирует системную проблему;
- меняется API, модель данных или source of truth;
- следующий шаг — **выбор направления**, а не реализация известного fix.

Шаблон: `docs/ai-workflow/DECISION_MEMO_TEMPLATE.md`, GitHub issue template `Decision Memo`.

---

## Cursor task standards

Каждая задача для Cursor (issue или markdown) содержит:

- **Goal** — один измеримый результат
- **Context** — почему сейчас, ссылки на PR/issue
- **Scope** — in / out
- **Files / areas to inspect**
- **Required behavior**
- **Tests** — pytest, curl, сценарии
- **Do not do** — legacy, broker, флаги, scope creep
- **Acceptance criteria** — чеклист
- **Report format** — см. PR template

Шаблон: `docs/ai-workflow/CURSOR_TASK_TEMPLATE.md`.

---

## Review checklist (binding)

- [ ] Без unrelated refactor
- [ ] Без скрытых semantic changes (advisory → ERROR)
- [ ] Feature flag discipline (default OFF)
- [ ] Без client-side AI keys; без секретов в diff
- [ ] Без расширения legacy `backend/` без явного согласования
- [ ] `possible` / `needs_clarification` не в broker
- [ ] `source_kind` isolation сохранён
- [ ] Импортеры идемпотентны
- [ ] Миграции только Alembic, аккуратные
- [ ] PR report полный (см. ниже)

Полный список: `docs/ai-workflow/CODEX_REVIEW_CHECKLIST.md`.

---

## Reporting (каждый PR)

1. **Changed files** (группировка по областям)
2. **What changed** — по смыслу, не только diff
3. **Before / after** — поведение API/UX
4. **Tests run** — команды и результат
5. **Risks / limitations**
6. **Recommended next step** — для Codex / Ivan

Template: `.github/PULL_REQUEST_TEMPLATE.md`.

---

## Контекст проекта

Платформа автоматизации таможенного оформления (ВЭД) на базе ЕАЭС.
Монорепозиторий. Основной движок: `customs-clear/backend/`.

### Стек
- **Backend:** Python 3.11, FastAPI, SQLAlchemy, Pydantic v2, Alembic
- **БД:** SQLite (dev) / PostgreSQL (prod), Redis (очереди)
- **AI:** Gemini API (LLM), keyword triggers, доменная классификация
- **Frontend:** React 18 + TypeScript + Vite + Tailwind
- **Desktop:** Electron (`customs-clear/desktop/`)
- **Infra:** Docker Compose, Nginx

### Ключевые сервисы
```
customs-clear/backend/app/services/
├── payment_engine.py            # Пошлины/НДС/сборы + fallback duty-rule
├── non_tariff_service.py        # Главный NTM пайплайн
├── non_tariff_rules.py          # Маппинг СС/ДС, SENSITIVE_OVERRIDES,
│                                  PERMIT_PATTERNS, NEGATIVE_MARKERS
├── ntm_triggers.py              # Триггеры по описанию (Wi-Fi → НФ и т.д.)
├── ntm_enricher.py              # AI-обогащение через Gemini
├── normative_store.py           # Поиск ТН ВЭД, breadcrumb, заметки
├── payment_profile_builder.py   # Сборка полного профиля платежей
└── exchange_rates.py            # Курсы ЦБ + local_cache fallback
```

### Состояние БД (на текущий момент)
- `tnved_entries`: 52 376 записей (справочник ТН ВЭД)
- `tnved_commodities`: товарные описания на русском
- `hs_rates`: 13 317 (пошлины + НДС 22% уже обновлен)
- `non_tariff_measures`: 41 743 (526 помечено `quality='noise'`)
- `tr_ts_acts`: 47 актов технических регламентов

---

## Глобальные правила для всех агентов

### ОБЯЗАТЕЛЬНО
- Читать AGENTS.md перед каждой задачей
- Основной backend: `customs-clear/backend/` (не корневой `backend/` — legacy)
- Dev-сервер: `http://127.0.0.1:8001`
- После каждого изменения — перезапуск uvicorn + регрессия curl-ами
- Новые сервисы → `customs-clear/backend/app/services/`
- Новые роутеры регистрировать в `customs-clear/backend/app/main.py`

### ЗАПРЕЩЕНО
- Не трогать корневой `backend/` — он legacy
- Не удалять данные из `non_tariff_measures` — только `quality='noise'`
- Не менять схему БД без Alembic миграции
- Не хардкодить НДС — берётся из `hs_rates.vat_import_rate`
- Не возвращать 500 если есть локальный fallback

### НДС (с 01.01.2026)
- Стандартная: **22%**
- Льготная: **10%** (еда, медтовары, детские)
- Нулевая: **0%** (экспорт)

### Чувствительные группы (whitelist)
```python
SENSITIVE_OVERRIDES = {
    "30": "РУ",           # Лекарства
    "2203-2208": "ЛЗ",    # Алкоголь
    "24": "ЛЗ",           # Табак
    "9301-9307": "ЛЗ",    # Оружие
    "3601-3604": "ЛЗ",    # Взрывчатка
}
```

---

## AGENT-01: NTM Agent (Нетарифные меры)

**Статус:** ✅ Работает, 13/14 регрессионных кейсов

### Зона ответственности
Точная привязка нетарифных мер к товарам по коду ТН ВЭД и описанию.

### Архитектура пайплайна
```
POST /api/non_tariff/check
  └── check_position_non_tariff()
      ├── 1. find_rules_for_code()             — _FALLBACK_RULES + БД
      ├── 2. find_measures_for_code()          — 41743 записей, 5 уровней
      ├── 3. find_measures_by_description()    — ntm_triggers
      ├── 4. enrich_measures_by_description()  — Gemini AI (опционально)
      └── 5. get_sensitive_override()          — whitelist
```

### Логика СС vs ДС
По Решению ЕЭК №620:
- **SS_DOMAINS** → СС: игрушки (9503), пылесосы (8508-8509), лифты (8428)
- **DS_DOMAINS** → ДС: обувь (6401-6405), ИТ (8471), смартфоны (8517),
  косметика (3303-3307), мебель (9401-9403), ТВ (8528)
- Функция: `get_default_cert_form(hs_code)` в `non_tariff_rules.py`

### Текущая регрессия (14 кейсов)
| # | Код | Описание | Статус |
|---|-----|----------|--------|
| 1 | 3004900001 | Лекарство | ✅ |
| 2 | 2204210000 | Вино | ⚠️ лишний СС |
| 3 | 9301000000 | Оружие | ✅ |
| 4 | 8471300000 | Ноутбук обычный | ✅ |
| 5 | 8471300000 | Ноутбук с Wi-Fi | ✅ |
| 6 | 8471300000 | Ноутбук БЕЗ Wi-Fi | ✅ |
| 7 | 6403990000 | Кроссовки взрослые | ✅ |
| 8 | 6403990000 | Кроссовки детские | ✅ |
| 9 | 9503007500 | Кукла | ⚠️ лишний СГР |
| 10 | 9503007500 | Игрушка Wi-Fi | ⚠️ лишний СГР |
| 11 | 3304990000 | Косметика | ⚠️ лишний СГР |
| 12 | 8528721000 | Телевизор | ✅ |
| 13 | 8517110000 | Смартфон Wi-Fi | ✅ |
| 14 | 9401310000 | Кресло офисное | ✅ |

### Open tasks
- Дочистить 7 хвостовых кейсов (точечная noise-разметка для 22**, 95**, 33**, 94**, 85**)
- Написать pytest-регрессию в `backend/tests/test_ntm_pipeline.py`

---

## AGENT-02: Calculator Agent (Платежи)

**Статус:** ✅ Работает

### Эндпоинты
```
POST /api/calculator/compute     — расчёт пошлин/НДС/сборов
POST /api/calculator/calculate   — alias для compute
POST /api/calculator/compare     — сравнение сценариев (с разными country)
GET  /api/calculator/duty-rule/{hs_code}  — ставка пошлины (fallback на hs_rates)
```

### Алиасы полей (важно!)
```python
currency         → invoice_currency
weight_kg        → net_weight_kg
country_of_origin → country
```

### Логика fallback duty-rule
1. hs_duty_rules по точному `commodity_code`
2. hs_duty_rules по убывающему префиксу (10→8→6→4)
3. hs_rates по точному коду
4. hs_rates по префиксу
5. Synthetic `_FallbackDutyRule` (0%, ad_valorem)

### Формула расчёта НДС
```
vat_base = customs_value_rub × (1 + duty_rate) × 0.22
```

---

## AGENT-03: Search Agent (Справочник ТН ВЭД)

**Статус:** ✅ Работает

### Эндпоинты
```
GET /api/tnved/search?q=...            — поиск по tnved_commodities.description
GET /api/v1/tnved/search?q=...         — поиск в каталоге Commodity
GET /api/search/hs?q=...               — поиск с обогащением ставками
GET /api/tnved/lookup/{hs_code}        — прямой lookup
GET /api/tnved/breadcrumb/{hs_code}    — хлебные крошки
GET /api/v1/tnved/reference/{code}     — справка с пошлиной/НДС
GET /api/v1/tnved/preview/{code}       — превью с payments
```

### Критичная деталь
Русские описания товаров — в `tnved_commodities.description`,
НЕ в `tnved_entries.title`!

---

## AGENT-04: Frontend Agent (UI)

**Статус:** 🔧 Не проверен

### Локация
`customs-clear/frontend/`

### Запуск
```bash
cd customs-clear/frontend
npm install
npm run dev   # http://localhost:5173
```

### Задачи (приоритет)
1. Проверить `vite.config.ts` — baseURL должен указывать на `:8001`
2. Проверить страницу поиска ТН ВЭД
3. Проверить калькулятор платежей (НДС должен быть 22%)
4. Проверить страницу нетарифных мер (отображение permit-типов)
5. Проверить compare-сценарии

---

## AGENT-05: Data Agent (Синхронизация)

**Статус:** 🔧 Частично

### Скрипты
```
customs-clear/backend/scripts/
├── sync_tks_nontariff.py        — парсинг TKS → non_tariff_measures
├── import_nontariff.py          — импорт из файлов
├── import_raw_extracted.py      — импорт downloads/raw_extracted.json
└── scheduled_sync.sh            — планировщик
```

### Источники
- TKS.ru — нетарифные меры
- ЦБ РФ — курсы валют (fallback на local_cache)
- ЕЭК — ЕТТ ЕАЭС
- pub.fsa.gov.ru — реестр сертификатов

---

## Порядок работы агентов

```
AGENT-01 (NTM) ─┬─ AGENT-02 (Calculator) ─┐
                │                          ├─ AGENT-04 (Frontend)
AGENT-03 (Search) ────────────────────────┘
                │
AGENT-05 (Data sync) ── обновляет данные для всех
```

**Текущий приоритет (исторический backlog AGENT-ов):**
1. 🔧 AGENT-01 — закрыть оставшиеся 7 кейсов до 14/14
2. 🔧 AGENT-04 — поднять frontend и подключить к API
3. 📋 AGENT-05 — настроить периодическую синхронизацию

> **Активная очередь задач** задаётся в `docs/ai-workflow/CURRENT_PROJECT_FOCUS.md` (если `Status: Active`), а не этим списком. AGENT-04 frontend verification не является top priority, пока focus не переключён явно.

---

## Быстрый старт

```bash
# 1. Запуск backend
cd /Users/aleks/Downloads/tnved_starter_kit_v2
.venv/bin/python -m uvicorn app.main:app \
  --app-dir customs-clear/backend \
  --host 127.0.0.1 --port 8001 --reload

# 2. Health check
curl http://127.0.0.1:8001/api/health/ready

# 3. Swagger
open http://127.0.0.1:8001/docs

# 4. Регрессионный smoke test NTM
curl -s -X POST http://127.0.0.1:8001/api/non_tariff/check \
  -H "Content-Type: application/json" \
  -d '{"items":[{"hs_code":"3004900001","description":"Лекарство","country":"DE"}]}' | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print(d['items'][0]['required_permit_types'])"
# Ожидаем: ['ДС', 'РУ']
```

---

## Changelog

| Дата | Агент | Изменение |
|------|-------|-----------|
| 2026-05 | AGENT-02 | Алиасы compute, fallback duty-rule, НДС 22% |
| 2026-05 | AGENT-03 | Поиск переключён на tnved_commodities |
| 2026-05 | AGENT-01 | Подключён non_tariff_measures (41 742) |
| 2026-05 | AGENT-01 | ntm_triggers: Wi-Fi→НФ, детск→СС, лазер→СЭЗ |
| 2026-05 | AGENT-01 | SENSITIVE_OVERRIDES: фарма/алкоголь/оружие |
| 2026-05 | AGENT-01 | SS_DOMAINS/DS_DOMAINS по Решению ЕЭК №620 |
| 2026-05 | AGENT-01 | noise-разметка (526 шумных записей) |
| 2026-05 | AGENT-01 | Регрессия: 13/14 ✅ |
| 2026-05 | Workflow | AI workflow kit: Codex/Cursor/Ivan, issue & PR templates |
| 2026-05-18 | Workflow | CURRENT_PROJECT_FOCUS.md — official SGR dataset workstream |
