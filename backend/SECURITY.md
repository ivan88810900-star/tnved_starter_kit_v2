# Безопасность TN VED Pro

## 🔒 Флаги безопасности

### AI_OFFLINE_MODE
- **По умолчанию**: `false`
- **Описание**: Отключает все ИИ-вызовы, работает только на основе правил и БД
- **Использование**: Для полностью автономной работы без внешних зависимостей

### ALLOW_EXTERNAL_AI
- **По умолчанию**: `false`
- **Описание**: Разрешает внешние ИИ-вызовы к OpenAI, Anthropic, Qwen, DeepSeek
- **Безопасность**: Блокирует все внешние ИИ-запросы если `false`

### AUDIT_LOGGING
- **По умолчанию**: `false`
- **Описание**: Включает логирование классификаций для аудита
- **Приватность**: Не сохраняет персональные данные, только метаданные

### ADMIN_API_KEY
- **Описание**: API ключ для административных операций (`/admin/*`)
- **Использование**: Отдельный от основного API_KEY для повышенной безопасности

## 🛡️ Middleware безопасности

### AI Security Middleware
Автоматически блокирует ИИ-вызовы если `ALLOW_EXTERNAL_AI=false`:

```python
# Блокируемые эндпоинты:
- /classify
- /batch/classify
- /ai/*
```

### Логирование ИИ-запросов
При `AUDIT_LOGGING=true` логируются:
- IP адрес клиента
- User-Agent
- Метод и путь запроса
- Временная метка

## 🔐 Конфигурация безопасности

### Рекомендуемые настройки для продакшена:
```env
# Безопасность
ALLOW_EXTERNAL_AI=false
AUDIT_LOGGING=true
ADMIN_API_KEY=strong-random-key-here

# ИИ (только для разработки)
AI_OFFLINE_MODE=true
AI_PROVIDER=openai
```

### Настройки для разработки:
```env
# Безопасность
ALLOW_EXTERNAL_AI=true
AUDIT_LOGGING=false
ADMIN_API_KEY=dev-key

# ИИ
AI_OFFLINE_MODE=false
AI_PROVIDER=openai
OPENAI_API_KEY=your-key
```

## 🚨 Обработка ошибок

### Блокировка ИИ-вызовов
```json
{
  "error": "External AI calls are disabled",
  "message": "Внешние ИИ-вызовы отключены для безопасности"
}
```

### Неверный API ключ
```json
{
  "detail": "Invalid admin API key"
}
```

## 📊 Аудит и мониторинг

### Логи классификации (AUDIT_LOGGING=true)
```json
{
  "timestamp": "2024-01-01T12:00:00Z",
  "has_text": true,
  "has_image": false,
  "hints_count": 2,
  "result_hs_code": "1234.56.78.90",
  "confidence": 0.85,
  "validated": true
}
```

### Логи ИИ-запросов
```
ИИ-запрос: POST /classify от 192.168.1.100 (Mozilla/5.0...)
```

## 🔧 Административные операции

### Защищенные эндпоинты
- `POST /admin/reindex` - Переиндексация данных
- Требуют заголовок: `X-API-Key: <ADMIN_API_KEY>`

### Проверка API ключа
```python
def verify_api_key(api_key: str = Header(..., alias="X-API-Key")):
    expected_key = os.getenv("ADMIN_API_KEY")
    if api_key != expected_key:
        raise HTTPException(401, "Invalid admin API key")
```

## 🛠️ Рекомендации по развертыванию

### 1. Настройка переменных окружения
```bash
# Создайте .env файл с безопасными значениями
cp .env.example .env
# Отредактируйте .env с реальными ключами
```

### 2. Генерация API ключей
```bash
# Генерация случайного API ключа
openssl rand -hex 32
```

### 3. Мониторинг логов
```bash
# Просмотр логов безопасности
tail -f logs/security.log | grep "ИИ-запрос"
```

### 4. Проверка конфигурации
```bash
# Проверка флагов безопасности
curl -X GET http://localhost:8000/health
```

## 🔍 Диагностика проблем

### Проблема: ИИ-вызовы блокируются
**Решение**: Проверьте `ALLOW_EXTERNAL_AI=true`

### Проблема: Админ операции не работают
**Решение**: Проверьте `ADMIN_API_KEY` и заголовок `X-API-Key`

### Проблема: Нет логов аудита
**Решение**: Установите `AUDIT_LOGGING=true`

## 📋 Чек-лист безопасности

- [ ] `ALLOW_EXTERNAL_AI=false` в продакшене
- [ ] `ADMIN_API_KEY` установлен и сложный
- [ ] `AUDIT_LOGGING=true` для аудита
- [ ] Логи мониторятся
- [ ] API ключи ротируются
- [ ] HTTPS используется
- [ ] CORS настроен правильно
- [ ] Rate limiting включен (рекомендуется)
















