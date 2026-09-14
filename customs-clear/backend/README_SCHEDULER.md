# Автоматические обновления нормативных источников

Основной production-контур запускается вместе с FastAPI через
`app.services.scheduler` при `REGULATORY_SYNC_SCHEDULER_ENABLED=true`:

| Задача | Когда (по `REGULATORY_SYNC_TZ`) | Источники |
|---|---|---|
| `regulatory_sources_daily` | ежедневно 03:00 | ЦБ, СГР, нотификации ФСБ, РЭС/ВЧУ, OFAC, санкции ЕС |
| `regulatory_sources_weekly` | воскресенье 08:00 | ФСА, ТРОИС, справочники/маски документов ФТС |
| `regulatory_sources_monthly` | 1-го числа 13:00 | durable review-очередь для пяти курируемых слоёв |

Все адаптеры выполняются последовательно. SQLite защищён файловой блокировкой,
PostgreSQL — advisory lock между репликами. Каждый дочерний процесс работает со
строгим machine-readable контрактом и может писать только в явно разрешённые
таблицы. Пустой, fallback или частичный снимок не считается успешным. Проверить
наличие lifecycle-policy у всех 36 зарегистрированных источников без мутации
можно командами ниже. Это покрытие политиками, а не утверждение об
автоматической юридической актуальности содержимого каждого источника:

Окружение API целиком дочерним процессам не наследуется. Runner передаёт только
scoped `DATABASE_URL`, собственные guard-флаги, настройки порогов конкретного
адаптера, локаль и TLS CA. Admin/LLM/cloud credentials, `HTTP(S)_PROXY`, основной
PostgreSQL DSN и прочие секреты приложения через эту границу не проходят.

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

Последний результат, расписание и durable review-очередь доступны через
`GET /api/sources/updates/status`. Ежемесячный запуск атомарно создаёт по одному
`pending`-элементу для каждого из пяти `local_reconcile`-источников. Очередь
хранится в `regulatory_source_reviews`, поэтому следующий daily-запуск не может
стереть уведомление своим JSON-отчётом. Незакрытый элемент переносится в следующий
месяц без дубликата; закрытые строки остаются историей аудита.

Machine-readable notification contract:

```json
{
  "status": "review_required",
  "review_queue": {
    "contract_version": 1,
    "durable": true,
    "notification_required": true,
    "notification_event": "regulatory_source_review_required",
    "managed_source_ids": ["... exactly five local_reconcile sources ..."],
    "pending_count": 5,
    "pending_source_ids": ["..."],
    "items": [{
      "id": 1,
      "evidence_sha256": "<64 lowercase hex>",
      "evidence_generation": 1
    }]
  }
}
```

Полный список доступен только администратору через
`GET /api/sources/updates/reviews` с `X-Admin-Token`. После фактической проверки
администратор закрывает конкретную строку с заявленным именем проверяющего,
ссылкой на Issue/PR этого репозитория, точными `evidence_sha256` и
`evidence_generation` из очереди:

```bash
curl --fail-with-body \
  -H "X-Admin-Token: $ADMIN_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"asserted_by":"legal-reviewer","resolution_ref":"#321","evidence_sha256":"<64 lowercase hex>","evidence_generation":1}' \
  -X POST http://127.0.0.1:8001/api/sources/updates/reviews/1/resolve
```

`resolved_by` не принимается от клиента: API записывает необратимый fingerprint
проверенного admin credential. Человеческое имя хранится отдельно как
`asserted_by`. Разрешены только ссылки `#<issue-or-pr>` либо полный URL Issue/PR
репозитория, заданного `REGULATORY_REVIEW_GITHUB_REPOSITORY`. Закрытие выполняется
атомарным compare-and-set по
`id + pending + evidence_sha256 + evidence_generation`: если локальный
artifact изменился после начала проверки, старый digest больше не может закрыть
новый snapshot.

Смена локального digest не переписывает существующее evidence. Monthly-cycle
одной транзакцией выполняет CAS `pending A → superseded A`, записывает время и
`superseded_by_evidence_sha256=B` и `superseded_by_generation`, затем создаёт
отдельную `pending B`. Переход разрешён только к строго большей generation. Если A
успели разрешить параллельно, его статус `resolved` сохраняется, а переход A→B
добавляется как supersession-аннотация перед созданием B. Разрешить можно только
текущий `pending`, совпадающий с локальными digest и generation. Повторное
появление уже вытесненного A считается откатом старой rolling-реплики, завершает весь набор из
пяти источников ошибкой и не меняет очередь. История `superseded` доступна
администратору через фильтр `GET /api/sources/updates/reviews?status=superseded`;
удалять или переписывать её вручную нельзя.

Файл `data/regulatory_review_generations.json` является проверяемым монотонным
контрактом для всех пяти `local_reconcile`-источников: он содержит положительную
integer generation и точные path/SHA-256 каждого `local_paths`. Любая легитимная
смена artifact выполняется одним change-set: обновить artifact, его SHA-256 в
manifest и увеличить generation соответствующего источника. Изменение bytes без
обновления manifest, другой digest в той же generation и попытка перейти к меньшей
generation завершают весь monthly-cycle ошибкой до изменения очереди. Git SHA,
hostname и часы реплики для порядка версий не используются.

Digest детерминированно связывает generation, registry metadata, известные upstream
URL и точные SHA-256/размеры всех `local_paths`. Для трёх legacy geopolitics/sanctions
источников без official URL scope явно равен
`local_fixture_only_no_official_upstream`: такой review подтверждает только
локальный fixture и не доказывает актуальность или юридическую полноту.

Без успешной записи полного набора review-элементов monthly-cycle завершается
ошибкой. Ответ `review_required` означает успешное выполнение технического цикла,
но не зелёное состояние данных: внешний монитор должен алертить по
`review_queue.notification_required=true` до закрытия всех элементов.

Ежедневный GitHub workflow независимо проверяет update-plan и один раз за
календарный месяц создаёт issue
`Monthly curated regulatory-source review YYYY-MM`. Контракт fail-closed:
issue создаётся только если plan содержит ровно те же пять источников со
`strategy=local_reconcile`, `cadence=monthly` и
`operational_state=scheduled_review_due`; неполный или изменённый набор считается
ошибкой инфраструктуры и попадает в общий source-review issue. Поиск выполняется
среди открытых и закрытых issues, поэтому закрытие не порождает дубликат в том же
месяце; совпадение засчитывается только для issue от `github-actions[bot]` с
period-scoped marker, а не по одному пользовательскому title. Создание issue
разрешено только запуску на default branch, поэтому ручной
dispatch feature-ветки не может занять период и подавить настоящее уведомление.
GitHub issue — резервный канал уведомления: его закрытие не меняет
durable-очередь в БД, которую нужно разрешать через API с reviewer/evidence.

Для PostgreSQL миграцию выполняет отдельная deployment-role. Runtime API/scheduler
role нужны только `SELECT, INSERT, UPDATE` на `regulatory_source_reviews` и
`USAGE, SELECT` на `regulatory_source_reviews_id_seq`; `DELETE`, DDL и ownership
ей не требуются. Роль из `REGULATORY_SYNC_DATABASE_URL` не должна получать доступ
к этой очереди: адаптеры структурированных источников её не обслуживают.

Ручной `POST /api/sources/updates/run` требует admin token и заблокирован в
`CUSTOMSCLEAR_READ_ONLY`.

Нормативные PDF, перечни Решения №30, №299, ветеринарные/фитосанитарные акты,
ПП №2425 и экспортный контроль не превращаются в правила автоматически.
Текущая конфигурация ежедневного GitHub workflow разворачивает реестр в 50 URL:
15 прямых PDF/machine-readable artifacts имеют проверяемое содержимое и покрытие
revision-digest, 27 юридических HTML-карточек проверяются только на доступность и
identity и явно отражаются как gaps покрытия revision, ещё 8 landing URL имеют
явный режим availability-only. HTML checksum не считается редакцией НПА, не
попадает в approval и сам по себе не держит monitor-job постоянно красным;
notifier сохраняет открытый issue со списком таких gaps до появления прямого
revision-covered artifact. Отчёт
публикует точные счётчики `monitored_url_count`,
`revision_covered_source_count`, `revision_gap_source_count`,
`revision_unavailable_source_count` и `explicit_availability_source_count`.

Из 15 revision-covered artifacts шесть — юридические PDF, девять — structured
artifacts. Для девяти структурированных ответов digest автоматически отражает
техническую свежесть после проверки; это не утверждение юридической применимости.
Для шести юридических PDF workflow сохраняет ETag/SHA-256, обнаруживает
изменение и создаёт/обновляет review issue. Новый или изменившийся legal checksum
остаётся `pending` и не заменяет одобренный baseline. Любая недоступность,
невалидный artifact или потеря ранее имевшегося revision coverage остаётся
fail-closed. После юридической проверки baseline можно продвинуть только ручным
`workflow_dispatch` с
`approve_source_baseline=true`, обязательной ссылкой `approval_ref` на Issue/PR и
`approval_source_ids`, точно совпадающим со всем pending-набором, на default
branch. `approval_source_digests` должен содержать точный JSON mapping
`source_id → pending SHA-256`. Review issue рассчитывает binding этого mapping;
trusted dispatcher добавляет указанный `REGULATORY_BASELINE_APPROVAL_SHA256=…`
как отдельную строку комментария до запуска approval. Запуск разрешён только
actor-у с effective-правами `write` или `admin`; текущий digest каждого источника обязан
совпасть с pending-версией. Коммерческие зеркала по умолчанию отключены.

## Защита скачивания и замены снимков

Официальные загрузчики читают HTTP-ответы потоково, запрашивают identity encoding
и отклоняют неожиданное сжатие, неверные URL/MIME/Content-Length до чтения тела.
Фактический объём ограничивается и без Content-Length. ЦБ ограничен 1 MiB, NSI —
64 MiB, санкционные XML — 128 MiB, монитор — 64 MiB на ответ и 256 MiB суммарного
кэша. Архив ФСА до 4 GiB пишется непосредственно во временный файл с SHA-256;
частичная загрузка не заменяет предыдущий файл.

ФСА использует закреплённый `py7zr==1.1.3` с лимитом распаковки 8 GiB (4 GiB на
member). Проверяются все члены solid-архива, не только выбранные CSV: пути,
коллизии имён, типы, размеры, число файлов, шифрование. Извлекается только точный
набор CSV в закрытый временный каталог, затем повторно проверяется файловое
дерево без перехода по ссылкам. `extractall` не используется. Версия включает
[исправления безопасности py7zr](https://github.com/miurahr/py7zr/releases/tag/v1.1.3).

Курсы ЦБ, статус и успешный SyncLog коммитятся одной транзакцией под блокировкой,
включая самый первый запуск. Revision содержит дату и SHA-256 исходных байтов;
откат даты и изменение байтов той же даты запрещены. Старый date-only снимок
можно привязать к digest лишь при совпадении всех сохранённых курсов и номиналов.
Поздний ответ неудачного запроса не понижает статус более нового успешного.
Fallback может заполнить только пустую БД и никогда не считается official.

СГР/нотификации/РЭС-ВЧУ закреплены за NSI 1995/1994/1992. Неофициальный или
частичный импорт не получает свежую canonical provenance. При ошибке одного из
парных FSS/REO снимков откатывается вся пара, оба статуса остаются stale/error.
Санкционные digest считаются по исходным байтам. XLSX-корреляция ЕС проверяется
как ограниченный OOXML-архив, но остаётся partial evidence без blocking apply.

Browser session state исключён из Git и Docker build context. Удаление ранее
отслеживаемых Alta session-файлов не отзывает сессии и не очищает старую историю:
владелец должен завершить все сессии Alta. Переписывание истории не выполнялось.

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
