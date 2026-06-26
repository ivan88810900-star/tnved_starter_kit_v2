# Переменные окружения CustomsClear (backend)

Значения задаются в `.env` в каталоге `customs-clear/backend` или в системе. Полный шаблон: **`customs-clear/.env.example`**.

Сводка для дашборда (без секретов): **`GET /api/analytics/overview`** — см. вкладку «Аналитика» в веб-UI.

Полный разбор упаковочного листа / инвойса (ИИ + нетарифка + платежи по строкам): **`POST /api/documents/ved-intelligent-analyze`** — см. **`docs/VED_MASTER_PLAN.md`** и вкладку «Документы». Очередь параллельных запросов: **`VED_INTEL_MAX_CONCURRENT`** (по умолчанию `4`, макс. `64`).

PDF по тем же полям, что JSON-экспорт из UI: **`POST /api/documents/ved-report-pdf`** (тело — JSON). Если задано **`VED_EXPORT_MIN_ROLE`**, нужен заголовок **`Authorization: Bearer <JWT>`** после **`POST /api/auth/login`** (роль в токене не ниже порога).

Фоновый полный разбор: **`POST /api/documents/ved-intelligent-analyze/async`**, статус: **`GET /api/documents/ved-intel-jobs/{job_id}`**.

## ИИ

| Переменная | Назначение |
|------------|------------|
| `GEMINI_API_KEY` | Ключ Google AI Studio |
| `GEMINI_MODEL_NAME` | По умолчанию `gemini-1.5-flash` |
| `ANTHROPIC_API_KEY` | Ключ Claude |
| `ANTHROPIC_MODEL_NAME` | По умолчанию `claude-3.7-sonnet-20250219` |

### Внешний HTTP-классификатор (опционально)

| Переменная | Назначение |
|------------|------------|
| `CUSTOM_CLASSIFIER_ENABLED` | `true` — включить вызов внешнего сервиса |
| `CUSTOM_CLASSIFIER_URL` | URL `POST` (JSON) |
| `CUSTOM_CLASSIFIER_API_KEY` | Опционально: `Authorization: Bearer …` |
| `CUSTOM_CLASSIFIER_MODE` | `first_custom` (по умолчанию), `first_llm`, `custom_only` |
| `CUSTOM_CLASSIFIER_TIMEOUT` | Таймаут секунд |
| `CUSTOM_CLASSIFIER_BODY_TEMPLATE` | Необязательно: JSON с `%s` под JSON-строку описания, напр. `{"text":%s}` |

### Локальный ONNX (опционально, до HTTP и LLM)

| Переменная | Назначение |
|------------|------------|
| `ONNX_HS_CLASSIFIER_PATH` | Путь к файлу модели `.onnx` |
| `ONNX_HS_LABELS_PATH` | Путь к JSON-массиву кодов ТН ВЭД (порядок = индекс класса после argmax) |
| `ONNX_HS_FEATURE_DIM` | Если у входа ONNX в shape указано `None`, задайте размерность вектора признаков |
| Зависимость | `pip install -r backend/requirements-ml.txt` (`onnxruntime`) |

Подробности: **`docs/integration/ONNX_HS_CLASSIFIER.md`**. При настройке ONNX режимы `CUSTOM_CLASSIFIER_MODE` (`first_custom`, `custom_only`, `first_llm`) применяются к цепочке **ONNX → HTTP → LLM** так же, как раньше к **HTTP → LLM**.

В теле `POST /api/classify` можно передать `use_custom_classifier`, `fallback_to_llm`. Контракт внешнего сервиса: **`docs/integration/INFERENCE_CLASSIFIER.md`**. Для локальной проверки — стаб **`backend/scripts/inference_classifier_stub.py`** (переменные `INFERENCE_STUB_*` на стороне стаба).

## База и авторизация

| Переменная | Назначение |
|------------|------------|
| `DATABASE_URL` | `sqlite:///./customs.db` или PostgreSQL |
| Миграции | `cd customs-clear/backend && alembic upgrade head` — таблицы `ingested_documents`, `parsed_invoice_lines`, `tnved_entry_embeddings`, `customs_calculation_history` |
| pgvector (опц.) | `pip install -r requirements-pgvector.txt`, в PostgreSQL `CREATE EXTENSION vector`; столбец `embedding` сейчас JSON, при необходимости замените тип миграцией на `vector(dim)` |
| `SECRET_KEY` | JWT, минимум 32 символа в проде |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Срок токена |
| `ADMIN_PASSWORD` | Только для dev-логина |
| `VIEWER_PASSWORD` | Пользователь `viewer` (роль только просмотр) |
| `DECLARANT_PASSWORD` | Пользователь `declarant` (средний уровень для экспорта) |
| `VED_EXPORT_MIN_ROLE` | Пусто — PDF без JWT; `declarant` или `admin` — минимальная роль для **`POST /api/documents/ved-report-pdf`** |

## HTTP / CORS / загрузки

| Переменная | Назначение |
|------------|------------|
| `CORS_ORIGINS` | Список через запятую |
| `MAX_UPLOAD_SIZE_MB` | Лимит multipart |
| `OCR_LANGUAGES` | Tesseract для сканов PDF, напр. `rus+eng+chi_sim` (китайский упрощённый + рус + англ) |
| `OCR_DPI` | Плотность растра при OCR PDF (по умолчанию `132`) |
| `EXTRACTOR_COLUMN_ALIASES_JSON` | Путь к JSON с доп. подстроками заголовков колонок Excel (ключи: `description`, `quantity`, `unit`, `gross`, `net`, `unit_price`, `total`, `package`) — см. `docs/samples/extractor_column_aliases.example.json` |
| `RATE_LIMIT_ENABLED` | `true` — ограничение частоты запросов |
| `RATE_LIMIT_PER_MINUTE` | Лимит запросов с одного IP к `/api/*` (окно 60 с); `/api/health*` не режется |
| `VED_INTEL_MAX_CONCURRENT` | Сколько полных **`ved-intelligent-analyze`** может выполняться одновременно (остальные ждут освобождения слота) |

## ФСА и разрешения

| Переменная | Назначение |
|------------|------------|
| `PERMITS_VERIFY_SSL` | `false` при проблемах с сертификатами |
| `FSA_REQUEST_DELAY` | Пауза между запросами (сек) |
| `FSA_RETRIES` | Повторы |
| `FSA_EXTERNAL_API_URL` | Прокси к API ФСА при 403 |
| `FSA_CERT_URL` / `FSA_DECL_URL` | Базовые URL реестров |
| `ADMIN_API_TOKEN` | Для `POST /permits/cache/clear`, `GET /assistant/decisions/export`, `POST /api/tnved/embeddings/ingest`, **`GET /api/calculator/history/export`** — заголовок **`X-Admin-Token`** |
| `OPENAI_API_KEY` | Эмбеддинги ТН ВЭД: `POST /api/tnved/embeddings/ingest`, `GET /api/tnved/search/semantic` |
| `OPENAI_EMBEDDING_MODEL` | По умолчанию `text-embedding-3-small` |

## Кэш Redis

| Переменная | Назначение |
|------------|------------|
| `REDIS_URL` | Пусто = только память процесса |
| `CACHE_TTL_SECONDS` | Общий TTL |
| `PERMITS_CACHE_TTL_SECONDS` | Кэш ФСА |
| `TROIS_CACHE_TTL_SECONDS` | Кэш ТРОИС |
| `TROIS_EXTRA_BRANDS_PATH` | JSON со списком брендов для `POST /api/trois/reload-cache` |

## Планировщик и источники

| Переменная | Назначение |
|------------|------------|
| `SCHEDULER_ENABLED` | `true` — APScheduler в процессе API |
| `SCHEDULER_SYNC_INTERVAL_HOURS` | Интервал полной синхронизации |
| `NORMATIVE_FEED_URL` / `NORMATIVE_CSV_URL` | Внешние фиды ставок |
| `NORMATIVE_BUNDLE_URL` | URL JSON-пакета: ТН ВЭД + ставки + нетарифка + примечания (см. **`docs/integration/NORMATIVE_PIPELINE.md`**) |
| Импорт файла | `POST /api/sources/import` — также **`.xlsx` / `.xlsm`**, **JSON-пакет**; явно: `POST /api/sources/import/bundle` |
| `ETT_PDF_MAX_GROUPS` | Лимит групп PDF при импорте ЕТТ |
| `ETT_ODATA_REGISTRY_NAMES` | Фильтр реестров OData |

## Аудит

| Переменная | Назначение |
|------------|------------|
| `AUDIT_LOG_ENABLED` | JSONL событий |
| `AUDIT_LOG_PATH` | Путь к файлу |

Заголовки: `X-Client-Id`, `X-Audit-Subject`.

## RAG

| Переменная | Назначение |
|------------|------------|
| `RAG_DOCS_DIR` | Каталог `.md`/`.txt`/`.pdf` (из backend: `../docs/rag_sources`) |
| `RAG_CHUNK_SIZE` / `RAG_CHUNK_STEP` / `RAG_MAX_PER_FILE` / `RAG_MAX_CHUNKS_PER_FILE` | Окна и лимиты |
| `RAG_USE_TFIDF` | Переранжирование TF‑IDF |
| `RAG_TFIDF_POOL` | Размер пула кандидатов |
| `RAG_CHROMA_PATH` | Персистентное хранилище Chroma |
| `RAG_CHROMA_COLLECTION` | Имя коллекции |

## Ассистент и журнал решений

| Переменная | Назначение |
|------------|------------|
| `COPILOT_BATCH_CONCURRENCY` | Параллельность batch |
| `DECISIONS_LOG_PATH` | JSONL журнала |
| `DECISIONS_LOG_MAX_READ` | Хвост для поиска |
| `DECISIONS_SIMILAR_ENABLED` | Похожие в контекст ИИ |
| `DECISIONS_SIMILAR_LIMIT` / `DECISIONS_SIMILAR_MIN_SCORE` | Лимиты подсказок |
| `DECISIONS_CLASSIFIER_HINTS` | Журнал в промпте `/classify` |
| `DECISIONS_CLIENT_BOOST_MULT` | Усиление своих `client_id` |

Экспорт для внешнего ML: **`scripts/export_training_pairs.py`** (`--format openai-chat`), гайд **`docs/ML_TRAINING_PIPELINE.md`**.

## Интеграция Альта-Софт (XML-API)

Документация: **`docs/integration/`**.

| Переменная | Назначение |
|------------|------------|
| `ALTA_HTTP_TIMEOUT` | Таймаут HTTP к `alta.ru`, сек (по умолчанию 45) |
| `ALTA_TIK_ENABLED` | `true` — прокси «Товары и коды» |
| `ALTA_TIK_LOGIN` / `ALTA_TIK_PASSWORD` | Учётные данные сервиса |
| `ALTA_TIK_BASE_URL` | По умолчанию `https://www.alta.ru/tik/xml/` |
| `ALTA_APU_ENABLED` | `true` — прокси «Подбор кода» (шаги suggest + codes) |
| `ALTA_APU_LOGIN` / `ALTA_APU_PASSWORD` | Если пусто — подставляются `ALTA_TIK_*` |
| `ALTA_APU_BASE_URL` | По умолчанию `https://www.alta.ru/tnved/xml_apu/` |

Эндпоинты: `GET /api/integrations/alta/status`, `/tik/search`, `/apu/suggest`, `/apu/codes`.

## Демо-данные

```bash
cd customs-clear/backend && PYTHONPATH=. python3 scripts/seed_demo_journal.py --append
```

См. `docs/samples/README.md`.
