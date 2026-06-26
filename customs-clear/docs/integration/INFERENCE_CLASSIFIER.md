# Внешний классификатор (inference / HTTP)

В приложении слот для **не-LLM** подбора ТН ВЭД реализован через **`CUSTOM_CLASSIFIER_*`** и `POST /api/classify` (поля `use_custom_classifier`, `fallback_to_llm`, `CUSTOM_CLASSIFIER_MODE`).

## Контракт сервиса (рекомендуемый)

**Запрос:** `POST` на `CUSTOM_CLASSIFIER_URL`, тело JSON (настраивается `CUSTOM_CLASSIFIER_BODY_TEMPLATE`), по умолчанию ожидается описание товара.

**Ответ:** JSON с массивом кандидатов, совместимый с тем, что ожидает UI после `/api/classify`:

```json
{
  "status": "OK",
  "query": "краткий текст запроса",
  "results": [
    {
      "code": "8509400000",
      "name": "Наименование позиции",
      "duty_rate": "8",
      "permits": [],
      "confidence": 0.85,
      "recommended": true,
      "reasoning": "краткое обоснование"
    }
  ],
  "classifier_source": "custom_http"
}
```

Поле **`code`** — 10 знаков ТН ВЭД (как в ответе LLM). Пустой **`results`** — трактуется как «нет кандидатов»; дальше может сработать LLM при `fallback_to_llm=true`.

## Обучение отдельной модели

Экспорт пар для обучения: `scripts/export_training_pairs.py`, пайплайн вне репозитория — **`docs/ML_TRAINING_PIPELINE.md`**. Сервис inference (ONNX, Triton, отдельный FastAPI) должен сам загружать веса и отдавать ответ в формате выше.

**Локальный ONNX в том же процессе, что API:** см. **`ONNX_HS_CLASSIFIER.md`** (`ONNX_HS_*`, `requirements-ml.txt`).

## Локальный стаб (разработка)

В репозитории: **`customs-clear/backend/scripts/inference_classifier_stub.py`** — отвечает на `POST /classify` телом с полями `description` / `query` / `text`, возвращает JSON в совместимом формате (эвристики по словарю, не ML).

```bash
cd customs-clear/backend
PYTHONPATH=. python scripts/inference_classifier_stub.py
```

В `.env` основного API:

```env
CUSTOM_CLASSIFIER_ENABLED=true
CUSTOM_CLASSIFIER_URL=http://127.0.0.1:8765/classify
CUSTOM_CLASSIFIER_MODE=first_custom
# Если на стабе задан INFERENCE_STUB_API_KEY:
# CUSTOM_CLASSIFIER_API_KEY=<тот же ключ>
```

Стаб: переменные **`INFERENCE_STUB_HOST`**, **`INFERENCE_STUB_PORT`**, опционально **`INFERENCE_STUB_API_KEY`** (тогда нужен `Authorization: Bearer …`).

## Переменные

См. **`docs/ENVIRONMENT.md`**: `CUSTOM_CLASSIFIER_ENABLED`, `CUSTOM_CLASSIFIER_URL`, `CUSTOM_CLASSIFIER_API_KEY`, `CUSTOM_CLASSIFIER_MODE`, `CUSTOM_CLASSIFIER_TIMEOUT`, `CUSTOM_CLASSIFIER_BODY_TEMPLATE`.
