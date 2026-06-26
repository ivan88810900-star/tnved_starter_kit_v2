# Backend (FastAPI)

## 🚀 Быстрый старт

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

## 🔧 Конфигурация

Создайте `.env` файл на основе `.env.example`:

```env
# Database
DB_URL=sqlite:///./tnved.db

# API Security
API_KEY=your-secret-api-key-here
ADMIN_API_KEY=your-admin-api-key-here

# AI Configuration
AI_PROVIDER=openai
AI_OFFLINE_MODE=false
ALLOW_EXTERNAL_AI=false

# Audit & Logging
AUDIT_LOGGING=false

# AI Providers
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
```

## 🛡️ Безопасность

### Флаги безопасности:
- `ALLOW_EXTERNAL_AI=false` - Блокирует внешние ИИ-вызовы
- `AUDIT_LOGGING=false` - Отключает логирование классификаций
- `ADMIN_API_KEY` - Ключ для административных операций

Подробнее: [SECURITY.md](SECURITY.md)

## 📡 API Endpoints

### Основные
- `GET /health` - Проверка состояния
- `GET /codes/search?q=` - Поиск кодов ТН ВЭД
- `GET /codes/{hs_code}` - Детали кода с тарифами и мерами
- `GET /notes/{level}/{id}` - Примечания к разделам/главам
- `GET /data/sources` - Список источников данных

### Классификация
- `POST /classify` - Классификация товара с ИИ
- `POST /batch/classify_xlsx` - Пакетная обработка Excel

### Административные (требуют X-API-Key)
- `POST /admin/reindex` - Переиндексация данных

## 🤖 ИИ Провайдеры

Поддерживаемые провайдеры:
- **OpenAI** (GPT-4o, GPT-4)
- **Anthropic** (Claude-3.5-Sonnet)
- **Qwen** (Alibaba Cloud)
- **DeepSeek** (DeepSeek Chat)

## 🔒 Middleware

- **CORS** - Настройка кросс-доменных запросов
- **AI Security** - Контроль ИИ-вызовов
- **Audit Logging** - Логирование для безопасности

## 🧪 Тестирование

### Запуск тестов
```bash
# Все тесты
python run_tests.py

# С покрытием кода
python run_tests.py coverage

# Конкретный тест
python run_tests.py test_health.py
```

### Тестовые сценарии
- ✅ **Health endpoint** - проверка /health
- ✅ **Поиск кодов** - тестирование /codes/search
- ✅ **Офлайн классификация** - AI_OFFLINE_MODE=true
- ✅ **Пакетная обработка** - round-trip Excel файлов

Подробнее: [TESTING.md](TESTING.md)

