# Автоматические обновления нормативных источников

Основной production-контур запускается вместе с FastAPI через
`app.services.scheduler` при `REGULATORY_SYNC_SCHEDULER_ENABLED=true`:

| Задача | Когда (по `REGULATORY_SYNC_TZ`) | Источники |
|---|---|---|
| `regulatory_sources_daily` | ежедневно 03:00 | ЦБ, СГР, нотификации ФСБ, РЭС/ВЧУ, OFAC, санкции ЕС |
| `regulatory_sources_weekly` | воскресенье 08:00 | ФСА, ТРОИС, справочники/маски документов ФТС |
| `regulatory_sources_monthly` | 1-го числа 13:00 | отчёт о курируемых слоях, требующих сверки и review |

Все адаптеры выполняются последовательно. SQLite защищён файловой блокировкой,
PostgreSQL — advisory lock между репликами. Каждый дочерний процесс работает со
строгим machine-readable контрактом и может писать только в явно разрешённые
таблицы. Пустой, fallback или частичный снимок не считается успешным. Проверить
полное покрытие 36 зарегистрированных источников без мутации:

```bash
python scripts/run_regulatory_source_updates.py --plan --strict
python scripts/run_regulatory_source_updates.py --cadence all --check-only --strict
```

Ручной guarded-запуск безопасных structured-sync:

```bash
python scripts/run_regulatory_source_updates.py --cadence daily --apply-safe --strict
python scripts/run_regulatory_source_updates.py --cadence weekly --apply-safe --strict
```

Для PostgreSQL обязателен отдельный `REGULATORY_SYNC_DATABASE_URL`: роль этого
DSN должна иметь `SELECT` и только необходимые `INSERT/UPDATE/DELETE` на union
таблиц адаптеров, без DDL, `EXECUTE` пользовательских функций и прав владельца.
Без отдельного DSN цикл завершается ошибкой. Для SQLite дополнительно действует
authorizer на уровне драйвера и табличный allowlist.

OFAC и санкционный список ЕС являются исключением из автоматического apply:
daily-задача скачивает только закреплённые официальные URL, разбирает и проверяет
полный снимок, но не меняет blocking-таблицы `ofac_sdn_list` и
`eu_sanctions_list`. Контракт такого запуска обязан содержать
`operation=validation_only`, `enforcement_changed=false` и `rows_applied=0`;
планировщик отклоняет любой другой результат. Применение проверенного снимка
остаётся отдельным ручным запуском соответствующего sync-скрипта с обязательным
явным флагом `--apply`; отсутствие `--validate-only` само по себе применение не
разрешает.

Последний результат и расписание доступны через `GET /api/sources/updates/status`.
Ручной `POST /api/sources/updates/run` требует admin token и заблокирован в
`CUSTOMSCLEAR_READ_ONLY`.

Нормативные PDF, перечни Решения №30, №299, ветеринарные/фитосанитарные акты,
ПП №2425 и экспортный контроль не превращаются в правила автоматически.
Ежедневный GitHub workflow сохраняет ETag/SHA-256, обнаруживает изменение и
создаёт/обновляет review issue. Новый или изменившийся legal checksum остаётся
`pending` и не заменяет одобренный baseline. После юридической проверки baseline
можно продвинуть только ручным `workflow_dispatch` с
`approve_source_baseline=true`, обязательной ссылкой `approval_ref` на Issue/PR и
`approval_source_ids`, точно совпадающим со всем pending-набором, на default
branch. `approval_source_digests` должен содержать точный JSON mapping
`source_id → pending SHA-256`. Review issue рассчитывает binding этого mapping;
trusted dispatcher добавляет указанный `REGULATORY_BASELINE_APPROVAL_SHA256=…`
как отдельную строку комментария до запуска approval. Запуск разрешён только
actor-у с правами write/maintain/admin; текущий digest каждого источника обязан
совпасть с pending-версией. Коммерческие зеркала по умолчанию отключены.

Нельзя одновременно включать новый планировщик и legacy `SCHEDULER_ENABLED`:
приложение завершит запуск с явной ошибкой вместо двух конкурирующих sync-контуров.

## Legacy-планировщик `scripts/auto_updater.py`

`auto_updater.py`, `auto_update.sh`, `run_critical_syncs.sh` и `initial_sync.py`
оставлены только для совместимости и **заблокированы по умолчанию**. Они не должны
использоваться как production-расписание параллельно новому контуру. Разовый
операторский запуск возможен только с явным opt-in
`CUSTOMSCLEAR_ALLOW_LEGACY_AUTOMATION=1`; этот opt-in не является настройкой для
постоянного сервиса или cron.

Даже при opt-in legacy-вызовы OFAC и санкционного списка ЕС работают только как
`validation-only`: официальный снимок проверяется, но blocking-таблицы не
изменяются. Ручное применение санкционного снимка выполняется отдельно и не
должно добавляться в автоматическое расписание.
