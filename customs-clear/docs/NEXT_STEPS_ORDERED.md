# Следующие шаги (бэклог)

**Мастер-план интеллектуального ВЭД** (фазы, статусы, эндпоинты): **`docs/VED_MASTER_PLAN.md`**.

Уже сделано в коде из этого списка: **§1 runbook**, **§2 экспорт + связка document_id + UI**, **§3.2 async ФСА** (БД + список + экспорт job), **§3.1 контракт inference** + **стаб** `scripts/inference_classifier_stub.py`.

## 1. Эксплуатация
- Регулярный **`alembic upgrade head`** и бэкапы → **`docs/RUNBOOK.md`**
- **`SCHEDULER_ENABLED`** / cron
- Мониторинг **`/api/health/*`**

## 2. Журнал и отчёты
- [x] Экспорт `customs_calculation_history` (CSV/JSON, фильтры, опц. `X-Admin-Token`)
- [x] `GET /documents/ingested/{id}/calculations` + UI на «Документах»
- [x] Пример cron: `backend/scripts/cron_export_calculation_history.sh`

## 3. Фаза L (крупное)
- Развёртывание **боевого** inference (модель) по **`INFERENCE_CLASSIFIER.md`** — вместо или рядом со стабом
- [x] Очередь ФСА: персистентные jobs в **БД** (`permits_verify_jobs`); опционально позже — Redis для мульти-воркеров
- [x] Экспорт результата async-задания ФСА: `GET .../verify/jobs/{id}/export`

## 4. Обучение
- Fine-tune вне репозитория (`training_pairs.jsonl`)

## 5. Документация
- Поддерживать **`ENVIRONMENT.md`**, **`README.md`**
