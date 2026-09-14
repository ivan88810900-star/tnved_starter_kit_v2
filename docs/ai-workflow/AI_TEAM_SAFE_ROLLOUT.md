# AI team: безопасный пилот, не production-автоматика

Дата подготовки: 2026-09-05. Статус: STAGED / DISABLED / ONLINE NOT TESTED.

## Что подготовлено

- `tariff-ai-implement.yml`: официальный Codex Action, только ручной запуск,
  только проверенный commit и заранее согласованная задача. Результат — патч
  в артефакте, не commit/push/PR. Приложение и БД не запускаются.
- `tariff-ai-review.yml`: Claude анализирует ограниченный diff; Gemini сравнивает
  его с переданными выдержками источников. Обе модели работают без инструментов
  и без возможности исполнять код. PR checkout не выполняется.
- `tariff-ai-safety.yml`: отдельные бесплатные в смысле отсутствия AI API-вызовов
  локальные/CI-тесты. Расход GitHub Actions зависит от плана аккаунта.
- `tools/ai_team/runner.py`: ограничения объёма, фильтр известных шаблонов ключей,
  точные SHA, проверка структуры ответов, запрет неизвестных путей/источников,
  контроль изменений всего рабочего дерева, включая Git metadata.

Ни один отчёт не разрешает merge. `ADVISORY_ONLY`, `CANDIDATE_ONLY`,
`NEEDS_EVIDENCE` и `BLOCKED` не означают, что продукт проверен или готов к релизу.
Новые workflows не заменяют существующий CI и `scheduled-data-refresh.yml`.

## Изоляция от основного чата

Основа: `feat/ntm-official-full-contours` на
`4c543c1dc636e8203e0b7e75b607e788702af6cd` (2026-09-01).

`CURRENT_PROJECT_FOCUS.md` этой ветки обновлён 2026-09-01, не в мае.
Его приоритеты, принятые состояния advisory-флагов, Canonical и запрет
неодобренного enforcement не меняются. `AGENTS.md` также не переписывается.
Пилотная роль Codex-исполнителя относится только к явной задаче этого пилота;
это не молчаливое изменение общего workflow проекта.

Основной чат продолжает разработку. Эта ветка не пишет в его ветку, не запускает
импорт, миграции, сервисы или обновление нормативных данных. GitHub concurrency
сериализует только два новых AI workflow; это НЕ распределённая блокировка всех
чатов, локальных компьютеров и старых workflow. Межчатовой автосинхронизации нет.

## Перед первым платным запуском

1. Основной чат читает `AI_TEAM_HANDOFF.md`, проверяет новый diff относительно
   последнего рабочего HEAD и принимает или отклоняет пилот отдельно.
2. Проверить отсутствие секретов и клиентских документов в выбранном snapshot.
   Фильтр runner — ограниченная дополнительная защита, НЕ полноценный DLP/secret
   scanner. Cloud API получает выбранный код/выдержки: это нужно учитывать.
3. Выбрать доверенную ветку, защитить её от прямых/force push, ограничить доступ.
   Не включать автослияние. Не считать один зелёный AI workflow обязательным
   качественным gate: он не заменяет backend/frontend/нормативные тесты.
4. Создать отдельные GitHub Environments, ограничить разрешённые deployment
   branches только доверенной веткой. Добавить required reviewer там, где это
   поддерживает тариф и состав команды. Проверить, что защиты действительно
   действуют; не полагаться только на `if` внутри изменяемого YAML.
5. Сохранить ключи только как Environment secrets. Не в чат, не в issues,
   не в код, не в файлы `.env`, не в скриншоты.

| Environment | Secret | Что получает доступ |
|---|---|---|
| `tariff-ai-implement` | `OPENAI_API_KEY` | Изолированный proxy официального Codex Action |
| `tariff-ai-review` | `ANTHROPIC_API_KEY` | Один вызов Claude без tools |
| `tariff-ai-review` | `GEMINI_API_KEY` | Один вызов Gemini без tools, только при наличии evidence |

Путь в GitHub: repository → Settings → Environments → нужное окружение →
Environment secrets → Add environment secret. Ключи создаются владельцем в
аккаунтах провайдеров. Подключение этого чата не даёт возможности безопасно
создавать платёжные аккаунты, выбирать тариф или принимать секреты в переписке.

Публичность репозитория не означает, что правильно настроенные Secrets публичны.
Но код и потенциально артефакты/логи публичного проекта не подходят для
конфиденциальных клиентских материалов. Видимость репозитория не менялась.
При переводе в private сначала проверить поддержку Environments, branch
restrictions и reviewers тарифом GitHub: доступность защит различается.
Если необходимые защиты недоступны, оставить пилот выключенным.

## Variables (не секреты)

Settings → Secrets and variables → Actions → Variables:

| Variable | Начальное значение/правило |
|---|---|
| `TARIFF_AI_ENABLED` | `false` (отсутствие также блокирует запуск) |
| `TARIFF_AI_IMPLEMENT_ENABLED` | `false` |
| `TARIFF_AI_TRUSTED_REF` | После приёмки: полный `refs/heads/<доверенная-ветка>` |
| `TARIFF_AI_APPROVED_SHA` | После приёмки: точный полный SHA проверенного workflow commit |
| `TARIFF_CODEX_MODEL` | Явно выбранный API model ID, доступный аккаунту |
| `TARIFF_CLAUDE_MODEL` | Явно выбранный API model ID, доступный аккаунту |
| `TARIFF_GEMINI_MODEL` | Явно выбранный API model ID, доступный аккаунту |

Документированные примеры ID: `gpt-6-astra`, `claude-fable-5-1`,
`gemini-3.8-flash`. Доступ в конкретном аккаунте НЕ проверен. Модели не выбираются
молча и не заменяются автоматическим fallback. Недоступный ID — ошибка,
не разрешение переключиться на другой продукт/платный сервис.

GitHub обычно требует наличие `workflow_dispatch` workflow в default branch
для его штатного ручного запуска. Поэтому этот feature-branch PR сам по себе
ещё не создаёт готовую кнопку production-автоматики. Не сливать незавершённую
продуктовую ветку целиком ради активации: основной чат должен отдельно согласовать
доставку этих изолированных файлов в подходящую default/trusted branch.

## Поэтапная активация

Сначала только shadow review, с малым неконфиденциальным PR и точным HEAD SHA.
Включить `TARIFF_AI_ENABLED=true` только после проверки окружения и явного
разрешения владельца. Executor остаётся выключенным.

Потом отдельно разрешить `TARIFF_AI_IMPLEMENT_ENABLED=true` и запустить только
задачу `smoke`. Патч должен содержать одну заранее указанную Markdown-страницу
с `NOT_PRODUCTION_READY`. Проверить патч вручную; не применять автоматически.

Далее основной чат может добавлять явно рассмотренные task manifests с точными
allowed_paths. Это требует нового approved commit SHA. Контроллер не принимает
задачи из публичных comments/issues и не запускается по label, расписанию,
`pull_request_target` или `workflow_run`.

Автопубликация PR, запуск тестов над AI-кодом и включение блокирующего gate —
отдельный этап. Тесты такого кода следует запускать без API-ключей и production
доступов. В текущем пилоте этот этап намеренно отсутствует.

## Источники и отсутствие ложной нормативной проверки

Gemini читает только файл из доверенного commit:
`tools/ai_team/evidence/pr-<номер>.json`.

Контракт: объект `sources` (1–6 записей). Каждая запись содержит:
`id`, `url`, `text`, `text_sha256`, `document_sha256`, `captured_at` (ISO 8601
с часовым поясом). Максимум 16 KB UTF-8 на выдержку; общий пакет не более 120 KB.
URL должен иметь HTTPS и точный хост из `HOSTS` в runner. Дата захвата — не старше
7 дней и не из будущего. `text_sha256` сверяется с текстом; повторные ID запрещены.

ВАЖНО: наличие `document_sha256` и корректного URL НЕ доказывает происхождение
выдержки или актуальность акта. Этот пилот НЕ скачивает нормативные документы,
не проверяет их юридическую силу и не доказывает полноту охвата мер. Его статус
прямо говорит `provided_extracts_only_not_live_verification`.

В рабочей ветке уже есть DM-0013 и автоматический lifecycle источников. Следующий
согласованный этап — адаптер его проверенных результатов/снимков к этому контракту,
с сохранением provenance и coverage; НЕ второй независимый планировщик.
Без evidence Gemini возвращает `NEEDS_EVIDENCE`, не делает API-вызов и не выдаёт
нормативное одобрение. Тестовые фикстуры нельзя выдавать за официальные документы.

## Расходы, отключение и ограничения

Claude/Gemini: максимум один запрос на роль/запуск, без retry и agent loops,
120 KB входного пакета, до 6000 output tokens; HTTP timeout 90 секунд.
Codex: один ручной job, шаг 10 минут, job 15 минут. Лимит времени НЕ равен
жёсткому денежному лимиту. У провайдеров нужны отдельные project keys,
минимальные доступы, уведомления и поддерживаемые ограничения расходов.
Не считать бюджет-уведомление гарантированным hard cap.

Отключение: `TARIFF_AI_ENABLED=false` и `TARIFF_AI_IMPLEMENT_ENABLED=false`.
Это блокирует НОВЫЕ запуски; уже начатые нужно отменить в Actions. При подозрении
на утечку ключи отозвать/перевыпустить у провайдера. Простое удаление сообщения
или удаление секрета из файла не отзывает ранее выданный ключ.

Остаточные риски: ошибки моделей, prompt injection в данных, supply chain,
ошибки upstream sandbox, утечки содержимого выбранного кода провайдеру,
задержка/недоступность API, ручные ошибки настройки Environments.
SHA-pinning, root-owned validator и минимальные права уменьшают риск,
но не являются обещанием абсолютной безопасности.

## Проверка

`python3 -I -m unittest discover -s tools/ai_team -p 'test_*.py' -v`

Проверено локально на изолированном комплекте новых файлов. Полный backend,
frontend и рабочая БД не копировались и не запускались. Live API, GitHub-hosted
Codex sandbox и биллинг не тестировались без ключей. CI после публикации нужно
проверять отдельно; локальный PASS не является GitHub Actions PASS.

## Официальная документация, сверена 2026-09-05

- https://github.com/openai/codex-action — актуальные inputs и защитная модель.
- https://code.claude.com/docs/en/github-actions — безопасное хранение ключей.
- https://platform.claude.com/docs/en/api/messages/create — Messages API.
- https://ai.google.dev/gemini-api/docs/generate-content/structured-output
- https://docs.github.com/en/actions/reference/security/secure-use
- https://docs.github.com/actions/deployment/targeting-different-environments/using-environments-for-deployment
- https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow

Action pins: checkout `fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09`,
upload-artifact `ea165f8d65b6e75b540449e92b4886f43607fa02`,
Codex Action `86365089eb2b84e0a8fb0717b304f8bdcb13b20e` (peeled v1).
Codex CLI/proxy `0.138.0` pinned; runtime compatibility still requires the
owner-approved live smoke test. Pins are not proof of absence of vulnerabilities.
