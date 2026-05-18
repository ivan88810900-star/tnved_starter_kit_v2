# Пайплайн обучения классификатора ТН ВЭД (вне приложения)

Приложение **не обучает модель само** — оно даёт **журнал решений** и **экспорт пар** для внешнего MLOps.

## 1. Накопление данных

- Пользователи сохраняют решения в журнал: `DECISIONS_LOG_PATH` (JSONL).
- В запросах передавайте **`X-Client-Id`** для приоритета подсказок и последующей сегментации по клиенту.

## 2. Экспорт пар

```bash
cd customs-clear/backend
# формат по умолчанию: text + label + meta
PYTHONPATH=. python3 scripts/export_training_pairs.py [вход.jsonl] [выход.jsonl]

# формат диалога для fine-tune (OpenAI / совместимые API)
PYTHONPATH=. python3 scripts/export_training_pairs.py data/user_decisions.jsonl data/openai_ft.jsonl --format openai-chat
```

Строка **по умолчанию** (`training_pairs.jsonl`):

```json
{"text": "описание товара", "label": "8509400000", "meta": {...}}
```

Строка **`openai-chat`**:

```json
{"messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}, {"role": "assistant", "content": "8509400000"}]}
```

## 3. Внешнее обучение (на выбор)

| Подход | Инструменты |
|--------|-------------|
| Fine-tune чата | OpenAI / Azure OpenAI, документация провайдера по JSONL |
| Классификация | scikit-learn, XGBoost по эмбеддингам текста |
| LoRA / полная дообучка | Hugging Face Transformers + PEFT, локальный GPU |

Рекомендации:

- Держите **отдельный train/val** по времени или по `client_id`.
- Фильтруйте строки с **коротким описанием** или **неподтверждённым кодом** (скрипт уже отсекает `< 4` символов).
- Версионируйте датасет (дата выгрузки в имени файла).

## 4. Интеграция обратно в продукт

- **Вариант A:** подмена вызова `/api/classify` на ваш inference-сервис (прокси в бэкенде).
- **Вариант B:** использование **журнала** (`similar`, `suggest-hs`) как слоя поверх базовой LLM — уже реализовано в CustomsClear.
- **Вариант C (локальный ONNX):** переменные `ONNX_HS_CLASSIFIER_PATH`, `ONNX_HS_LABELS_PATH`, опционально `pip install -r requirements-ml.txt` — см. **`docs/integration/ONNX_HS_CLASSIFIER.md`**.

Подробности журнала: `docs/samples`, `POST /api/assistant/decisions/*`, `export_training_pairs.py`.
