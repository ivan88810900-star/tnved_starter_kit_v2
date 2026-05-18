# CustomsClear

Веб-приложение для автоматизации проверки таможенных документов.

**План развития (базы, реестры, ассистент):** [ROADMAP.md](ROADMAP.md).  
**Переменные окружения:** [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md) · шаблон [.env.example](.env.example) → скопировать в `customs-clear/backend/.env`.  
**Эксплуатация:** [docs/RUNBOOK.md](docs/RUNBOOK.md) · бэклог: [docs/NEXT_STEPS_ORDERED.md](docs/NEXT_STEPS_ORDERED.md).  
**RAG-источники по умолчанию:** [docs/rag_sources/](docs/rag_sources/) · демо-журнал: [docs/samples/](docs/samples/).

Сводная панель (БД, ИИ, журналы, ФСА): `GET /api/analytics/overview` — в UI вкладка **«Аналитика»** (стартовый экран).

Полный ВЭД-разбор упаковочного листа / инвойса (Excel/PDF, в т.ч. китайский текст): `POST /api/documents/ved-intelligent-analyze` — черновик ДТ (ИИ), нетарифка и платежи по строкам, ФСА, общая ИИ-сводка (риски, шаги). В UI: **Документы** → режим «ВЭД-аналитик» (по умолчанию).

Журнал расчётов: `GET /api/calculator/history`, экспорт `GET /api/calculator/history/export` (при `ADMIN_API_TOKEN` — `X-Admin-Token`; пример cron — `backend/scripts/cron_export_calculation_history.sh`). По документу: `GET /api/documents/ingested/{id}/calculations`. Async ФСА: `GET /api/permits/verify/jobs`, экспорт завершённого задания: `GET /api/permits/verify/jobs/{id}/export`. Стаб внешнего классификатора: `backend/scripts/inference_classifier_stub.py`.

## Где запускать

| Режим | URL |
|-------|-----|
| **Веб (разработка)** | http://localhost:3000 |
| **Веб (только backend)** | http://localhost:8001 |
| **Десктоп** | Приложение открывает окно автоматически |

Подробная инструкция: **[RUN.md](RUN.md)** — полная загрузка ТН ВЭД/ЕТТ, smoke-тесты, API.

---

## Запуск (веб-режим)

### 1. Backend (порт 8001)

```bash
cd tnved_starter_kit_v2
python -m venv .venv  # если ещё не создан
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r customs-clear/backend/requirements.txt

cd customs-clear/backend
PERMITS_VERIFY_SSL=false PYTHONPATH=. uvicorn app.main:app --host 127.0.0.1 --port 8001
```

### 2. Frontend (порт 3000)

```bash
cd customs-clear/frontend
npm install
npm run dev
```

Откройте в браузере: **http://localhost:3000**

По умолчанию API проксируется на `http://localhost:8001`. Для другого порта:

```bash
VITE_API_PORT=8000 npm run dev
```

---

## Десктоп-приложение (macOS и Windows)

Сборка создаёт нативное приложение: `.app` / `.dmg` для macOS, `.exe` / установщик для Windows.

### Требования

- Node.js 18+
- Python 3.10+
- npm, pip

### Сборка на macOS

```bash
cd tnved_starter_kit_v2
python -m venv .venv && source .venv/bin/activate
pip install -r customs-clear/backend/requirements.txt

cd customs-clear/desktop
npm install
node build.js mac
```

Результат: `desktop/dist/CustomsClear-1.0.0.dmg` и `CustomsClear-1.0.0-mac.zip`

### Сборка на Windows

```bash
cd tnved_starter_kit_v2
python -m venv .venv
.venv\Scripts\activate
pip install -r customs-clear/backend/requirements.txt

cd customs-clear/desktop
npm install
node build.js win
```

Результат: `desktop/dist/CustomsClear Setup 1.0.0.exe` (установщик) и `CustomsClear 1.0.0.exe` (portable)

Важно: полноценную Windows-сборку с встроенным backend (`customs-clear-server.exe`) нужно выполнять на Windows.

### Сборка Windows на macOS/Linux (frontend-only)

Если нужно собрать Windows-оболочку с интерфейсом без встроенного backend:

```bash
cd customs-clear/desktop
npm install
npm run build:win-frontend-only
```

Такой пакет не содержит `customs-clear-server.exe`; backend запускается отдельно (локально или удалённо).

### Запуск десктоп-приложения

- **macOS**: откройте `.dmg`, перетащите CustomsClear в Applications, запустите
- **Windows**: запустите установщик или portable-версию

Приложение само запустит backend и откроет окно с интерфейсом.

---

### Проверка

- Backend: http://localhost:8001/api/health
- Frontend: http://localhost:3000

## API endpoints

| Endpoint | Метод | Описание |
|----------|-------|----------|
| `/api/health` | GET | Проверка состояния |
| `/api/documents/check` | POST | Проверка документов (multipart: **`invoice` обязателен**, `packing_list` **необязателен**; опц. `extract_permits`, `verify_fsa`, `hs_code`, **`persist`**, `client_id`, черновик ДТ) |
| `/api/documents/upload` | POST | Быстрая загрузка + валидация; опция **`persist`** — запись в `ingested_documents` |
| `/api/documents/ingested` | GET | Список сохранённых загрузок (пагинация `limit`/`offset`) |
| `/api/documents/ingested/{id}` | GET | Детали документа и строк `parsed_invoice_lines` |
| `/api/permits/verify` | POST | Пакетная проверка СС/ДС/СГР в реестрах (JSON: `permits`, `hs_code`, `enrich`) |
| `/api/permits/suggest` | POST | Справочный подбор примеров СС/ДС под товар (`query`, `hs_code`, `exclude_trois`, `country_hint`, `doc_types`) |

Проверка документов (`/api/documents/check`): по умолчанию собирается **черновик декларации** (`declaration_draft=true`): ТН ВЭД, графа 31, веса/количество/места, типы СС/ДС/СГР из правил БД; опционально ИИ — поля формы `ai_api_key`, `use_ai_declaration`. Номера СС/ДС/СГР из текста и реестр — как раньше; `skip_registry_verify=true` — без запросов к реестру. По умолчанию **`persist=true`** — запись в БД (`ingested_documents`, `parsed_invoice_lines`); в ответе `document_id` совпадает с id в БД при успешном сохранении.

Проверка ДС в ФСА из автотестов делается с **моком** сети. Живой запрос к `pub.fsa.gov.ru` (часто 403 с не-браузерных клиентов):

`cd customs-clear/backend && RUN_FSA_LIVE=1 PYTHONPATH=. python3 -m unittest tests.test_permits_normalize_and_api.FsaLiveDeclarationSmoke -v`

| `/api/classify` | POST | Классификация ТН ВЭД (Gemini/Claude); `use_journal_hints` — подсказки из журнала в промпт |
| `/api/trois/check` | POST | Проверка товарных знаков (ТРОИС) |
| `/api/calculator/compute` | POST | Расчёт таможенных платежей; опц. **`save_history`**, **`document_id`**, **`user_ref`** |
| `/api/calculator/compare` | POST | Сравнение сценариев; те же поля истории |
| `/api/calculator/history` | GET | Список сохранённых расчётов (`limit`, `offset`, опц. `user_ref`, **`kind`**) |
| `/api/calculator/history/summary` | GET | Сводка числа записей по типам (`user_ref`); типы: compute, compare, compliance, copilot, copilot_batch |
| `/api/calculator/history/{id}` | GET | Полная запись входа/выхода расчёта |
| `/api/tnved/embeddings/status` | GET | Сводка по векторам семантического поиска |
| `/api/tnved/embeddings/ingest` | POST | Пакетная индексация эмбеддингов (OpenAI; опц. `X-Admin-Token`) |
| `/api/tnved/search/semantic` | GET | Семантический поиск по проиндексированным позициям (`q`, `limit`) |
| `/api/currency/rates` | GET | Курсы ЦБ РФ |
| `/api/non_tariff/check` | POST | Нетарифное регулирование |
| `/api/compliance/check` | POST | Комплаенс: платежи + нетарифка + риски; опц. **`save_history`**, **`document_id`**, **`user_ref`** → запись в `customs_calculation_history` (тип `compliance`) |
| `/api/assistant/analyze` | POST | ИИ по нетарифке (несколько позиций в теле `items[]`; событие в JSONL-аудите при `AUDIT_LOG_ENABLED`) |
| `/api/assistant/copilot` | POST | **Умный конвейер**: классификация (опц.) → платежи → нетарифка → реестр (опц.) → ИИ; опц. **`save_calculation_history`**, **`document_id`**, **`user_ref`** (платежи в журнал, тип `copilot`) |
| `/api/assistant/copilot/batch` | POST | Несколько позиций + ИИ; опц. **`save_calculation_history`** — сводка платежей в журнал (тип `copilot_batch`) |
| `/api/assistant/decisions/log` | POST | Журнал подтверждённого ТН ВЭД (`confirmed_hs`, описание, заметки) → JSONL |
| `/api/assistant/decisions/recent` | GET | Последние записи журнала (`limit`) |
| `/api/assistant/decisions/similar` | GET | Похожие подтверждённые решения по тексту (`q`, `limit`) — для UI и дублируется в контексте ИИ copilot/analyze |
| `/api/assistant/decisions/hints` | GET | Сразу `similar` + `hs_suggestions` (агрегация кодов из журнала по `q`) |
| `/api/assistant/decisions/suggest-hs` | GET | Только топ кодов ТН ВЭД из журнала (`q`, `limit`) |
| `/api/assistant/decisions/export` | GET | Выгрузка журнала `format=json` или `csv`; при заданном `ADMIN_API_TOKEN` — заголовок `X-Admin-Token` |
| `/api/assistant/decisions/stats` | GET | Сводка журнала: число записей, топ кодов ТН ВЭД, источники |
| `/api/integrations/alta/status` | GET | Конфиг интеграций Альта (без секретов) |
| `/api/integrations/alta/tik/search` | GET | Прокси XML-API «Товары и коды» (`srchstr`, опц. `tncode` / `tnfiltr` / `page`) — нужны `ALTA_TIK_*` |
| `/api/integrations/alta/apu/suggest` | GET | Подсказки АПУ «Подбор кода» (`q`, опц. `limit`) |
| `/api/integrations/alta/apu/codes` | GET | Коды ТН ВЭД по `payload` из suggest (`code`, опц. `limit`) — нужны `ALTA_APU_*` или `ALTA_TIK_*` |

Подробнее: **`docs/integration/`**.
| `/api/health/ready` | GET | БД + опционально Redis |
| `/api/trois/suggest` | GET | Подсказки брендов (fuzzy), query `q` |
| `/api/permits/cache/clear` | POST | Сброс кэша ФСА (опц. `X-Admin-Token` = `ADMIN_API_TOKEN`) |

**Docker:** `docker compose -f customs-clear/docker-compose.yml up -d` — PostgreSQL и Redis. Затем `DATABASE_URL` и `REDIS_URL` в `.env` бэкенда, `alembic upgrade head` из `customs-clear/backend`.

**Аудит ассистента:** при `AUDIT_LOG_ENABLED=true` в JSONL пишутся `assistant.copilot`, `assistant.copilot_batch`, `assistant.analyze`. Опциональные заголовки: `X-Client-Id`, `X-Audit-Subject` (на странице ассистента — два поля под API-ключом).

**RAG:** `RAG_DOCS_DIR` — `.txt` / `.md` / `.pdf`; токены + окна; опционально `RAG_USE_TFIDF=true` (переранжирование TF‑IDF); `RAG_CHUNK_*`, `RAG_MAX_CHUNKS_PER_FILE`. Векторы: `pip install -r customs-clear/backend/requirements-rag.txt`, задать `RAG_CHROMA_PATH`, выполнить `PYTHONPATH=. python3 scripts/ingest_rag_chroma.py`.

**Журнал решений:** `DECISIONS_LOG_PATH` (по умолчанию `data/user_decisions.jsonl`). Похожие записи и ранжирование кодов: `DECISIONS_SIMILAR_*`, `DECISIONS_LOG_MAX_READ`, `DECISIONS_CLASSIFIER_HINTS` — в промпт copilot/batch/analyze и `/classify`. **Приоритет своих записей:** заголовок `X-Client-Id` (в UI — «ID для аудита») или поле `client_id` в `POST /classify`; множитель **`DECISIONS_CLIENT_BOOST_MULT`** (по умолчанию 1.28). Выгрузка: `GET /api/assistant/decisions/export` (в проде задайте `ADMIN_API_TOKEN`). Скрипт пар для ML: `backend/scripts/export_training_pairs.py` (см. RUN.md).
