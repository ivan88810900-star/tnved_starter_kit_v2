# Runbook: эксплуатация CustomsClear

## Панель аналитики
- В UI откройте вкладку **«Аналитика»** или `GET /api/analytics/overview` — сводка по БД, Redis, ключам ИИ, журналам расчётов и решений, ФСА, ТРОИС, эмбеддингам и текстовые выводы.

## План развития ВЭД-контура
- Структура фаз и чеклист: **`docs/VED_MASTER_PLAN.md`**.

## Порядок при развёртывании
1. `cd customs-clear/backend && pip install -r requirements.txt`
2. `alembic upgrade head`
3. Заполнить `.env` по **`docs/ENVIRONMENT.md`**
4. Запуск API: `uvicorn app.main:app --host 0.0.0.0 --port 8001`

## Регулярные действия
- **Бэкап SQLite**: `scripts/backup_sqlite.sh` (или дамп PostgreSQL по политике инфраструктуры).
- **Синхронизация нормативки**: `SCHEDULER_ENABLED=true` или внешний cron → `scripts/scheduled_sync.sh`.
- **Проверки**: `GET /api/health`, `GET /api/health/normative`, `GET /api/health/ready`.

## Журнал расчётов
- Просмотр и фильтры: UI «Платежи» или `GET /api/calculator/history` (`kind`, `document_id`, `created_from`, `created_to`, `user_ref`).
- Экспорт: `GET /api/calculator/history/export?format=csv|json` — при **`ADMIN_API_TOKEN`** в .env нужен заголовок **`X-Admin-Token`**.
- Пример cron: **`backend/scripts/cron_export_calculation_history.sh`** (`API_BASE`, `OUT_DIR`, `ADMIN_TOKEN`).

## ФСА async
- Задания хранятся в БД (`permits_verify_jobs`): история и результат переживают рестарт. Незавершённые `queued`/`running` при старте API помечаются как ошибка «Прервано перезапуском сервера».
- `GET /api/permits/verify/jobs` — список; `GET /api/permits/verify/jobs/{job_id}` — результат.
- Экспорт завершённого задания: `GET /api/permits/verify/jobs/{job_id}/export?format=csv|json` — при **`ADMIN_API_TOKEN`** нужен **`X-Admin-Token`**.
