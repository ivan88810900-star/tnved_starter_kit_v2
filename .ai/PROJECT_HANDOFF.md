# Tariff / A0 — единая точка передачи проекта

**Снимок:** 2026-10-08 (UTC). **Единственный репозиторий:** [ivan88810900-star/tnved_starter_kit_v2](https://github.com/ivan88810900-star/tnved_starter_kit_v2).  
**Авторитетное состояние:** ветка `agent/orchestration-state`, файлы `.ai/TASK_BOARD.json`, `.ai/COORDINATOR_LEASE.json`, `.ai/orchestration/A6_LIVE_STATUS.json`. Этот документ — указатель и контрольная точка, **не** право на запись/merge/A6. Перед действием заново читать текущие HEAD и state. Не полагаться на Business-чат.

## 0. Реальный продуктовый цикл — 2026-10-08, рабочий исполнитель

**Результат сохранён:** [draft PR #255](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/255), ветка `agent/core-payment-regressions-v1`, точный HEAD `7ce87f4eb3550f10a285dd04e38e9c6b60508e79`, tree `bb910341be886b587cff8eabc5cba478e5552bea`. Base — неизменный #244 `14e0ee8f034d94ffc5831d87e076f4d693a5a524`. Один общий исправляющий PR, три файла; merge не выполнен. Контроллер допускает рабочие ветки `agent/*`; исходные #244/#245 сохранены.

Исправлено и покрыто регрессиями:
- Некорректные/перевёрнутые даты специальной пошлины больше не превращают её в `not_applicable`: требуется ручная проверка, сумма строки/итог отсутствуют.
- Чисто процентная спецпошлина не требует курс валюты для нулевой фиксированной части; `fx_rate=null`, frontend тип приведён к `number | null`.
- Отрицательные, неконечные и иные недопустимые ставки специальных пошлин не попадают в предварительную арифметику.

### Среда и воспроизводимость

Полный Git checkout, 1590 tracked paths в исходном #244, история не shallow, missing objects не обнаружены. Отдельные полные worktrees для main, state, #244, его базы `08e030a6053ac9638957119373797e0fbf2b10c2` и #245. Python 3.12.14 / Git 2.51.1 / Node 24.19.0. Изолированный venv: `pip install -r customs-clear/backend/requirements.txt pytest-subtests pytest-asyncio`; `pip check` PASS. Frontend: штатный `npm ci --no-audit --no-fund` по lockfile каждой ветки. `PATH` должен начинаться с venv/bin — один тест запускает `python3` в subprocess.

Команды запускаются из `customs-clear/backend`, `PYTHONPATH=.`; **каждый прогон использует отдельный временный файл SQLite через абсолютный `DATABASE_URL=sqlite:////.../run.sqlite`**. Production DB не использовалась. Штатный `init_db()` выполнял Alembic/seed только на этой временной БД. Tests могут менять tracked `data/tnved_preview_cache_revision.txt`; побочный timestamp восстановлен, в PR не включён.

| Проверка | Фактический результат |
|---|---|
| Исходный #244: payment_engine, payment_quote, source_admission, automatic operands, antidumping fixed unit, FX provenance, special duties, tariff preferences, duty parser, normalization, invoice/compare, unavailable exports | 142 passed +348 subtests; 12 failures — отсутствует seed стран |
| Те же 18 тестов `test_tariff_preferences.py` после штатного `python -m scripts.seed_tariff_preferences` в тестовой БД | 18 passed; все 12 исходных failures воспроизведены и на базе #244. Seed не является доказательством актуальности правовых данных |
| #244 источники: ingestion/payment coverage/import duty/VAT/excise/PP908/regulatory completeness/source sync/sync diagnostics/data refresh | После исправления окружения: 303 passed +76 subtests, 4 failures. Не хватает полной TNVED fixture для PP908 coverage; 3 проверки отсутствующего scheduled-data-refresh.yml. Эти failures воспроизведены на базе |
| Полный #244: `python offline_pytest.py tests -q --tb=short --junitxml=full.xml` | 1402 passed, 181 failed, 13 errors, 2 skipped, +478 subtests; **NOT PASS** |
| Полная база #244, та же среда и отдельная новая БД | 1169 passed, 158 failed, 166 errors, 2 skipped, +73 subtests; **NOT PASS** |
| Сравнение full suite | 191 общий failing/error test ID. 3 дополнительных у #244: calculator_compare/recycling non_vehicle ждут старый `OK`; quantity_affects_excise ждёт расчёт unitless fixed excise. Требуется обновить контрактные проверки с сохранением строгих утверждений, а не ослаблять их. Общие сбои включают fixtures/shared DB/data dependencies; это не 191 доказанный дефект кандидата |
| Новые регрессии до fix | 7 failures, 12 passed, 2 subtests passed |
| Исправленный **опубликованный SHA #255**: 7 платёжных модулей | 114 passed +352 subtests, exit 0 |
| Независимый native A5 `/root/a5_core244_review`, опубликованный SHA #255 | 65 passed +343 subtests; scoped PASS. На идентичном backend дополнительно 23 boundary assertions: даты включительно/истёкшие/будущие, страны, missing bounds, FX и invalid operands |
| HTTP smoke исправления | uvicorn на loopback, lifespan off, одноразовые локальные auth values; реальные curl POST compute и payments/quote: 2/2 PASS, unknown code удерживает итог. Первоначальный код 8509400000 на минимальной БД возвращал CLARIFICATION_NEEDED — корректная проверка leaf, не дефект расчёта |
| Frontend #244 и исправление #255 | TypeScript/build PASS. У исходного #244 нет Vitest набора; frontend unit PASS для него не заявляется |
| #245 `e39e19787bd913baeb6f85577a13e1116458e633`: все 13 изменённых backend test-модулей | 268 passed +44 subtests |
| #245 frontend | 18 tests passed; TypeScript/build PASS |
| Полный #245 | 1537 passed, 181 failed, 13 errors, 2 skipped, +120 subtests; **NOT PASS** |

Точная команда повторной проверки исправления #255:
```sh
python -m pytest tests/test_special_duties.py tests/test_payment_engine.py tests/test_payment_quote.py tests/test_payment_source_admission.py tests/test_automatic_duty_operand_validation.py tests/test_antidumping_fixed_unit_fail_closed.py tests/test_payment_fx_provenance_fail_closed.py -q --tb=short --junitxml=published.xml
```

Дополнительные точные команды завершённых прогонов (те же disposable SQLite / venv / PYTHONPATH):
```sh
# #244 sources, exit 1: 303 passed +76 subtests, 4 failures
python -m pytest tests/test_data_refresh.py tests/test_excise_ingestion.py tests/test_import_duty_ingestion.py tests/test_official_payment_coverage_audit.py tests/test_payment_data_coverage.py tests/test_payment_source_ingestion.py tests/test_pp908_vat_coverage.py tests/test_regulatory_source_completeness.py tests/test_source_sync_index_currentness.py tests/test_sync_status_diagnostics.py tests/test_vat_ingestion.py -q --tb=short
# #245 focused backend, exit 0: 268 passed +44 subtests
python -m pytest tests/test_assistant_copilot.py tests/test_assistant_payment_review.py tests/test_compliance_permit_parser.py tests/test_embedding_service_safety.py tests/test_grounded_assistant.py tests/test_non_tariff_data_freshness.py tests/test_normative_requirements_block.py tests/test_ntm_child_product_markers.py tests/test_ntm_sgr_bad_token_boundary.py tests/test_ntm_trigger_food_contact.py tests/test_regulatory_ai_classifier.py tests/test_regulatory_keyword_token_boundaries.py tests/test_smart_tnved_search.py -q --tb=short
# Из customs-clear/frontend каждой ветки; exit 0
npm ci --no-audit --no-fund
npm run typecheck
npm run build
# Только #245, где существует штатный Vitest script; exit 0, 18 passed
npm test
```

Полный диагностический runner `offline_pytest.py` не менял тесты: удалял из окружения ANTHROPIC_API_KEY/OPENAI_API_KEY/GEMINI_API_KEY/GOOGLE_API_KEY, ставил Python audit hook на `socket.connect` (разрешал только localhost/127.0.0.1/::1, иначе RuntimeError OFFLINE_TEST_GUARD) и вызывал `pytest.main(sys.argv[1:])`. Ограничение времени 240 секунд; все три full-прогона завершились самостоятельно за 73–104 секунды. Это локальная диагностика; сетевые/живые провайдерные проверки не подтверждены.

CI #255: [offline-safety PASS, run 37771953943](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37771953943), job 113293439909. Это инфраструктурный CI и **не** замена продуктовым тестам выше. Full product CI на GitHub пока отсутствует.

### Незакрытые выводы / следующий конкретный шаг

1. Исправить подтверждённый **унаследованный** legacy fallback: `_parse_duty_rate` отдаёт `specific_eur`/`rule`, а `_find_duty_rule_for_hs` читает `specific_amount`/currency/uom. Для `2 евро/кг` возвращается 0; MAX/ADD теряют специфическую часть. Нужны persisted-row регрессии с подтверждёнными FX/единицами; не выводить единицы из предположений.
2. Производитель/описание товара в строках спецмер не сопоставляются со входом. Пока нет подтверждения совпадения, нельзя выдавать автоматическую применимость. Сначала воспроизводитель и существующий источник/контракт, без новой юридической интерпретации.
3. Разобрать isolated fixtures/full-suite failures и три устаревших контрактных теста; сохранить исходные выводы, не скрывать failures через skip/deselect.
4. Проверки #245 подтверждают технические ограничения AI/UI и тестовый набор, **не** полноту нетарифки или юридическую применимость.
5. Существующий A6 request `core-s1-6415f443120f-r9-g106` не пересоздан, не отправлен и не повторён. Его прежние результаты не переносятся на #255.

Удалённый Git transport не имеет write credentials (`could not read Username`), это **не security refusal**. Публикация выполнена существующим GitHub connector: 3 blobs -> tree с проверкой полного совпадения -> commit -> agent branch -> draft PR. Ни ключей, ни токенов у владельца не запрашивалось.

Состояние сохранялось под штатно приобретённым CAS lease generation 108, holder `/root/tariff_product_cycle_20261008`; перед продолжением перечитать live lease. Основной чат владельца не менялся; канал доставки туда не установлен.

### Проверка расписания

На 2026-10-08T11:54Z обнаружено существующее часовое расписание разработчика `6ac775d0feac8191abc1e60865ce1461` («Tariff — разработка»), **disabled**, last_run 10:55:48Z. Точный результат того запуска через доступное чтение не получен. Существующий включённый «Tariff — контроль остановок» `6ac775fd994c8191aea0165bc66b38b1` — read-only наблюдатель, не исполнитель и не координатор; он не заменяет разработку. Дублирующие задачи не созданы.

**Фактическая проверка:** после release generation108 в 11:55:59Z существующая задача была возобновлена с обязательным capability gate; единственный `automations.run_now` принят в 11:56Z. К 12:00Z новый результат не получен: `last_run_time` остался 10:55:48Z, `next_run_time=null`, нового checkpoint/lease исполнителя нет. Это **UNKNOWN / не подтверждённый запуск**, не доказанный CAPABILITY_BLOCKED и не успешная автономная разработка. API Automations не предоставляет чтение журнала запуска; Personal Context не нашёл этот разговор. Прямое открытие возвращённого conversation_id в ChatGPT показало sign-in wall. Требуется безопасный вход для чтения результата, без передачи паролей/токенов в чат.

В 12:00:12Z **повторения явно приостановлены** (`is_enabled=false`) до проверки результата; пользователю причина сообщена. Это не доказательство отмены уже принятого асинхронного запуска. Задача контроля остановок не менялась; новых задач/мониторов не создано. Дальнейшее включение допускается только после подтверждения полноценной среды исполнения и фактического тестового checkpoint. Обычная интерактивная разработка в текущей среде работоспособна и этой проверкой не заблокирована.

Продуктовый checkpoint сохранён commit `3a118f2bc37862673858f6285f6fb600ce861893`, затем дополнен записью о расписании; release108 commit `76fb75fed24c86cbd962ed99e6c3e01d009a59c9`, [state safety PASS run37773352840](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37773352840). Для сохранения результата проверки расписания штатно получен lease generation109, который освобождается сразу после записи. Перед продолжением читать live lease.

## 1. Восстановление инфраструктуры — PR #254

- [PR #254](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/254) — `fix(agents): verified recovery and preflight`; **MERGED 2026-10-08T10:45:47Z**; рабочая ветка `review/tariff-recovery-20261008`.
- Проверенный final candidate HEAD: `957702311efd8d29c0ff18c58bcd3b523b7fcd77`, base `main` `c29015e9c25232e07d06bc3869abc45db3b066a2`. Текущий live `main`: `e526dfbdb5a31b01bf6f743da0288b88f916de0c` — подтверждённый merge #254. Старые записи draft/ожидания разрешения ниже относятся только к истории.
- 14 инфраструктурных файлов: восстановление preflight, A6 structured-safety/receipts, recovery-status, CLI, required verifier, CI, runbook и тесты. В `test_audit_bridge.py` в двух disposable Git-fixtures отключены `maintenance.auto` и `gc.auto` — устранён race `tearDown` на Git 2.55; строгая очистка не подавлена.
- Независимый **whole-PR** Codex review на прежнем SHA `6031c4a8...` подтвердил P2: default `publication_policy=unknown` скрывал существующий A6 owner gate в `task_owner_action_required`. См. [finding](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/254#discussion_r4217405436).
- На текущем SHA `957702311e...` `recovery_status` теперь учитывает `observed["owner_action_required"]`; отдельный регрессионный тест внесён в `test_operations.py`. Новый [независимый Codex re-review](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/254#issuecomment-6057912061) завершён **без major issues** именно на `957702311e...`. Исторический P2 review thread закрыт после независимой воспроизводимости и проверки исправления. Не представлять это как формальное GitHub `APPROVED` от человека: Codex оставил advisory review.
- [Exact-head GitHub CI PASS, run 37763266913](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37763266913), job `113264825797`: `offline-safety`, проверка тестов и committed snapshot PASS. Независимый локальный replay A0 восстановил Git blobs текущих `operations.py`, `test_operations.py`, `test_audit_bridge.py` и запустил required verifier **225/225 PASS** и полный orchestration **225/225 PASS** с socket guard, **0 network attempts**; Python 3.13 / Git 2.47 локально, Git 2.55 на Actions. Это не product-suite и не запуск A6.
- Merge #254 уже выполнен владельцем; не повторять разработку, merge или запрос разрешения. В этой сессии защищённых действий не было.

## 2. Product candidates — НЕ приняты окончательно

| Приоритет | PR, candidate SHA | Зафиксированные доказательства и открытые ограничения |
|---|---|---|
| Ставки, преференции, специальные пошлины, расчёт и источники | [#244](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/244), `14e0ee8f034d94ffc5831d87e076f4d693a5a524` | draft; base `integration/customs-core-v1` `08e030a...`, 34 файла. Ранее заявлен A5 PASS; расчётный semantic harness 47/47. Exact-head [run 36853205641](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/36853205641) PASS, но это **Tariff agent safety**, не полный product/backend CI. Полная backend регрессия, обязательные официальные данные и юридическая применимость не доказаны; A6 LIVE PASS отсутствует. |
| NTM, документы, код ТН ВЭД, поиск, AI | [#245](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/245), `e39e19787bd913baeb6f85577a13e1116458e633` | draft; base `integration/compliance-ai-v1` `08e030a...`, 43 файла. Ранее заявлен A5 PASS после child-negation fix; focused backend 268 + 44 subtests, frontend 18/18 и build (см. тело PR). Exact-head [run 36853210034](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/36853210034) PASS, но workflow тоже только **Tariff agent safety**. Полная broad backend и end-to-end нормативная/юридическая приёмка не подтверждены; A6 LIVE PASS отсутствует. |

До работы над #244/#245: сверить HEAD/base/состав файлов/required checks, внимательно прочитать их текущие PR body и source-task lineage; не наследовать review/CI после изменения SHA. Проверить реальные сценарии, API/DB схемы, даты действия и версии нормативных источников. Эвристики и AI-подсказки — advisory, не юридический факт.

## 3. A6 — отдельный запрещённый пока внешний шаг

- Авторитетный файл: `.ai/orchestration/A6_LIVE_STATUS.json` **только** на `agent/orchestration-state`.
- Уже подготовлен, **не отправлен/не израсходован** immutable request `core-s1-6415f443120f-r9-g106`; packet SHA256 `e2a0d35aaae76d4a8fa0c74d4fe7d83d609371d75b7ef7eced1484890d1f22b8`; canonical serialization SHA256 `349339f5393176b83d02fea8965783b6237b0259110d835fff5bd55ec1886f89`; 8 tracked paths, 392515 bytes, 0 official URLs; lease generation **106** binds its request identity. Не пересоздавать и не делать retry.
- Для внешней передачи приватного кода Anthropic/A6 требуется **отдельное точное согласие владельца** на этот request/packet через предусмотренный trusted bridge. Разрешение merge PR #254 **не** разрешает A6. Даже live ответ A6 не заменяет проверку A0.

## 4. Следующие технические шаги

1. Продолжить исправления платёжного блока от опубликованного #255 `7ce87f4eb3550f10a285dd04e38e9c6b60508e79`: legacy specific/combined fallback теряет specific_eur; ограничения производителя/товара не проверяются. Не запускать/не пересобирать A6.
2. Main уже обновлён merge #254. Перед следующей удалённой записью приобрести coordinator lease через **current trusted main** `tools/tariff_agents/lease.py` и GitHub CAS; перечитать holder/token/TTL. На реальных непроизводственных сценариях проверять: recovery state/board, создание -> allocation -> implementation -> independent QA -> CI, зависание и освобождение, корректную диагностику и доказанную видимость уведомления. Не имитировать child session IDs, A5/A6, delivery receipts. Нет доступа к native Work executor — пометить unavailable.
3. #244: воспроизвести полный backend/CI по ставкам, FX, НДС, акцизам, спецпошлинам и преференциям с реальными source versions/effective dates, unknown/fail-closed, сформировать и протестировать payment quote end-to-end без production writes; независимый A5 текущего SHA.
4. #245: проверка применимости ТР, СС/ДС/СГР, лицензий, нотификаций, маркировки и исключений по кодам и свойствам, source/provenance и confidence; самостоятельная полнота нормативного набора и full backend+frontend; independent A5. Не включать SGR enforcement без отдельного решения.
5. Далее A3: реестр **официальных** документов, версии, даты вступления, полнота и обновления; A4: классификация/семантика/AI grounded-only; интеграция пользовательского сценария описание -> код -> ставки/платежи -> документы/доказательства.
6. По каждому готовому блоку: commit-bound A5 -> обязательные CI -> A6 **только когда разрешено и требуется** -> owner decision. Любой новый HEAD обнуляет прежнее «готово» для этого exact SHA.

## 5. Сроки / риски

Предыдущие ориентиры: **9 октября** — платёжный кандидат; **23 октября** — NTM; **30 октября** — официальные источники; **10 ноября** — RC1; **17 ноября** — целевая v1.0. На 8 октября платёжный draft уже существует, но **его окончательная приёмка к 9 октября под риском**: нет полного подтверждённого product backend/источников/A6-gate. Отсутствует подтверждение для обещания v1.0 по нормативной полноте. Перепланировать только по новой фактической evidence и явно отмечать gate.

## 6. Authority, безопасность, продолжение из другого чата

- A0 — один координатор; не порождать второй A0, не дублировать executor/automations. Рабочее состояние в GitHub, не в чате. Исходно расписание разработчика приостановлено; включён read-only контроль остановок. **Фоновое исполнение разработки не подтверждено**; см. фактический статус проверки расписания выше.
- **Перед любым remote write:** `main` `AGENTS.md`, `.ai/orchestration/CONTRACT.md`; state `.ai/orchestration/RUNBOOK.md`, `.ai/TASK_PROTOCOL.md`, `.ai/TASK_BOARD.json`, `.ai/COORDINATOR_LEASE.json`, `.ai/orchestration/A6_LIVE_STATUS.json`. Запрашивать lease актуальным helper; CAS на текущем blob SHA; reread holder/token; каждый существенный write проверять. Не обходить платформенный security refusal. Отдельно в журнале: предыдущая блокировка записи lease была устранена **только для штатного CAS acquisition generation 107 2026-10-08**; это не доказывает общий доступ без ограничений. При потере lease прекратить write.
- Во время перепроверки внешний сеанс внёс 2 коммита в PR #254 с исправлением P2; A0 здесь **не отправлял дублирующий патч**. При новом внешнем движении branch немедленно reconcile HEAD и избежать пересекающихся записей. Все дополнительные findings проверять самостоятельно, не признавать review автоматически.
- Никогда без Ivan: merge защищённых веток, production deploy/DB/migrations, enforcement flags, изменение credentials/permissions/secrets, удаление/force push, A6 export. Никакой доставки в основной пользовательский чат не подтверждено.
- Статус блоков честно разделять: **сделано / сейчас / осталось / что нужно от владельца**. Прогресс доказан конкретным SHA, CI job, A5 и diff, не «агент запущен».
