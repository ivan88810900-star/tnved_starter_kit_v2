# CustomsClear — где и как запустить

## Один скрипт (рекомендуется)

```bash
cd tnved_starter_kit_v2
./start.sh
```

Скрипт установит зависимости (если нужно), инициализирует БД, запустит backend и frontend. Откройте http://localhost:3000

### PostgreSQL, Redis, планировщик (прод)

```bash
cd customs-clear
docker compose up -d
```

В `.env` бэкенда задайте `DATABASE_URL` (например `postgresql+psycopg2://customs:customs@127.0.0.1:5432/customs`) и `REDIS_URL=redis://127.0.0.1:6379/0`. Затем:

```bash
cd customs-clear/backend
alembic upgrade head
```

Автосинхронизация источников в процессе API: `SCHEDULER_ENABLED=true`, `SCHEDULER_SYNC_INTERVAL_HOURS=24`.  
Внешний cron без планировщика: `customs-clear/scripts/scheduled_sync.sh`.  
Проверка готовности: `GET /api/health/ready`.

---

## Быстрый старт (вручную)

### 1. Установка зависимостей

```bash
cd tnved_starter_kit_v2
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r customs-clear/backend/requirements.txt
```

### 2. Инициализация БД и загрузка тарифа

```bash
cd customs-clear/backend
PYTHONPATH=. python3 -c "
from app.services.normative_store import init_db
init_db()
print('БД инициализирована, сиды загружены')
"
```

### 3. Полная загрузка ТН ВЭД и ЕТТ (опционально)

Загрузка из PDF ЕЭК — 10–30 минут при полном объёме:

```bash
cd customs-clear/backend
PYTHONPATH=. ETT_PDF_MAX_GROUPS=0 python3 scripts/load_full_tariff.py
```

Или через API после запуска сервера:

```bash
# Запустите сервер (см. ниже), затем:
curl -X POST http://localhost:8001/api/sources/sync/ett
```

Переменная `ETT_PDF_MAX_GROUPS`: `0` = все группы, `3` = быстрый тест (3 группы).

### 4. Запуск backend

```bash
cd customs-clear/backend
PYTHONPATH=. uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Проверка: http://localhost:8001/api/health

### 5. Запуск frontend (веб-режим)

```bash
cd customs-clear/frontend
npm install
npm run dev
```

Откройте: **http://localhost:3000**

### 6. Десктоп-приложение

```bash
cd customs-clear/desktop
npm install
node build.js mac    # или: win
```

Результат: `desktop/dist/CustomsClear-1.0.0.dmg` (macOS) или `.exe` (Windows).

---

## API endpoints

| Endpoint | Метод | Описание |
|----------|-------|----------|
| `/api/health` | GET | Проверка состояния |
| `/api/calculator/compute` | POST | Расчёт платежей (пошлина, НДС, акциз, антидемпинг) |
| `/api/calculator/compare` | POST | Сравнение 2–8 ТН ВЭД при общих стоимости, фрахте, стране (`shared` + `scenarios`) |
| `/api/compliance/check` | POST | Комплаенс: платежи + нетарифка + риски |
| `/api/non_tariff/check` | POST | Нетарифное регулирование |
| `/api/sources/status` | GET | Источники + **`stats`** (счётчики БД) + **`hints`** (заполненность / предупреждения) |
| `/api/sources/sync` | POST | Полная синхронизация |
| `/api/sources/sync/ett` | POST | Загрузка ЕТТ из PDF |
| `/api/sources/sync/odata` | POST | Синхронизация OData ЕАЭС |
| `/api/classify` | POST | Классификация ТН ВЭД (Claude) |
| `/api/currency/rates` | GET | Курсы ЦБ РФ |

---

## Тестирование

```bash
cd customs-clear/backend
python3 -m unittest discover tests -v
```

---

---

## Полные базы данных

### ТН ВЭД и ЕТТ (тариф)

Полная загрузка — все 99 групп PDF, ~13 000 позиций, 10–30 минут:

```bash
cd customs-clear/backend
PYTHONPATH=. ETT_PDF_MAX_GROUPS=0 python3 scripts/load_full_tariff.py
```

Или через API (сервер должен быть запущен):

```bash
curl -X POST http://localhost:8001/api/sources/sync/ett
```

### OData (льготы, преференции)

Загружается автоматически в `load_full_tariff.py`. Отдельно:

```bash
curl -X POST http://localhost:8001/api/sources/sync/odata
```

### ТРОИС (товарные знаки)

В приложении — 100+ популярных брендов в локальной базе. Полный реестр ТРОИС (~4000 знаков) на customs.gov.ru; сайт может блокировать автоматические запросы.

**Варианты полной базы ТРОИС:**

1. **Ручная проверка** — https://customs.gov.ru/registers/objects-intellectual-property
2. **Расширение кэша** — добавить бренды в `backend/app/services/trois_service.py` в `_LOCAL_CACHE`
3. **Импорт из CSV** — при наличии выгрузки ТРОИС можно добавить парсер и загрузку в БД (требует доработки)

### CSV/JSON-фид ставок

Если есть свой фид нормативных ставок:

```bash
export NORMATIVE_CSV_URL="https://example.com/rates.csv"
# или
export NORMATIVE_FEED_URL="https://example.com/rates.json"
```

Затем: `curl -X POST http://localhost:8001/api/sources/sync`

### Excel TWS.BY (коды + пошлины)

Бесплатная ежедневная выгрузка: [tws.by — скачать ТН ВЭД в Excel](https://www.tws.by/tws/tnved/download).  
Импорт в БД приложения:

```bash
curl -X POST -F "file=@TNVED.xlsx" http://localhost:8001/api/sources/import
```

Поддерживаются `.xlsx` / `.xlsm` (распознавание колонок по заголовкам или первые столбцы). Подробнее: **`docs/integration/tws_by.md`**.

Подсказки по классификации от **Альта-Софт** — опционально, после договора (`docs/integration/`, `ALTA_*` в `.env`).

### Пакет ТН ВЭД + ЕТТ + нетарифка + примечания (JSON)

Один файл может обновить справочник наименований, ставки, нетарифные правила и текстовые примечания. Пример: `GET /api/sources/template/bundle` или `backend/data/normative_bundle.example.json`. Подробно — **`docs/integration/NORMATIVE_PIPELINE.md`**.

```bash
curl -X POST -F "file=@my_bundle.json" http://localhost:8001/api/sources/import/bundle
# или положить URL в NORMATIVE_BUNDLE_URL и вызвать POST /api/sources/sync
```

В UI: вкладка **«Справочник ТН ВЭД»**, в ответе калькулятора — блок **`tnved_context`**.

### Скрипт полной загрузки

```bash
cd tnved_starter_kit_v2/customs-clear/backend
PYTHONPATH=. ETT_PDF_MAX_GROUPS=0 python3 scripts/load_full_tariff.py
```

После загрузки перезапустите backend.

### Журнал решений → пары для обучения

Из `DECISIONS_LOG_PATH` (по умолчанию `data/user_decisions.jsonl`) формируется JSONL `text` / `label` (ТН ВЭД):

```bash
cd customs-clear/backend
PYTHONPATH=. python3 scripts/export_training_pairs.py
# опционально: python3 scripts/export_training_pairs.py /path/in.jsonl /path/out.jsonl
```

Полная выгрузка сырого журнала: `GET /api/assistant/decisions/export` (см. README, `ADMIN_API_TOKEN`).

### Демо-журнал и RAG из коробки

```bash
cd customs-clear/backend
cp ../.env.example .env   # при необходимости; в .env уже можно указать RAG_DOCS_DIR=../docs/rag_sources
PYTHONPATH=. python3 scripts/seed_demo_journal.py --append
```

После перезапуска backend подсказки ассистента и классификатора используют демо-записи; RAG подхватит тексты из `docs/rag_sources/*.md`.

---

## Переменные окружения

| Переменная | Описание |
|------------|----------|
| `DATABASE_URL` | SQLite по умолчанию: `sqlite:///./customs.db` |
| `ETT_PDF_MAX_GROUPS` | Групп PDF для загрузки (0 = все) |
| `NORMATIVE_FEED_URL` | URL JSON-фида ставок |
| `NORMATIVE_CSV_URL` | URL CSV-фида ставок |
| `CORS_ORIGINS` | Разрешённые origins для CORS |
| `RAG_DOCS_DIR` | `../docs/rag_sources` от каталога backend — см. [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md) |
