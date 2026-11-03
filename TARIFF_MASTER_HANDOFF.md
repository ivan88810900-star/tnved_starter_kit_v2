# TARIFF_MASTER_HANDOFF

Дата: 3 ноября 2026. Прямая сверка Neon: 08:45 UTC / 11:45 МСК.
Статус: управление документировано; применение настроек к существующему Dot/Automations НЕ подтверждено.

## 1. Единственный центр управления и источники фактов

Единственный репозиторий: [ivan88810900-star/tnved_starter_kit_v2](https://github.com/ivan88810900-star/tnved_starter_kit_v2).
Этот файл — единая точка входа для передачи управления, хранится в существующей ветке `agent/orchestration-state`. Не создавать новый репозиторий, базу, разработчика, координатора или расписание ради переноса.

- Владелец принимает продуктовые и юридические решения в существующем «Бизнес Tariff».
- Существующий Dot Tariff ведёт бизнес-контроль: одна очередь приоритетов, проверка прогресса и необходимых решений. Он не становится вторым техническим координатором.
- Существующий A0 — единственный ответственный разработчик и технический координатор; управление файлами, интеграцией и техническими доказательствами остаётся у него.
- A1–A4 — исторические доменные роли, A5 — независимая проверка, A6 — внешний аудит. Перечисление ролей не означает активные сессии. В рамках этой передачи новые агенты не создавались и не разрешаются.
- Продуктовый код: `customs-clear/backend`, `customs-clear/frontend`. Legacy `backend/` не расширять.
- Факты о коде: текущие Git refs/PR/CI. Runtime authority: `agent/orchestration-state/.ai`. Факты о постоянных данных: Neon. Чаты — исторические свидетельства, а не текущая база состояния.
- Этот документ индексирует состояние, не заменяет машинный TASK_BOARD, lease и исходные receipts. При расхождении свежая прямая проверка важнее старой сводки; разрешения определяются действующим мандатом владельца.

## 2. Цель и измеримый результат

Довести существующий Tariff до инструмента таможенного специалиста: поиск и структура ТН ВЭД, обоснованные ставки и расчёты, нетарифные меры и документы, объяснения с источниками, контроль изменений. Повторная разработка инфраструктуры и рост числа PR сами по себе не считаются продуктовым результатом.

Считать отдельно RAW, нормализованные, неоднозначные, юридически проверенные и допущенные данные. Структурный справочник не означает покрытие ставок/NTM. Синтаксический PARSED не означает юридическую применимость. Непроверенные факты не допускать к окончательному расчёту.

Сроки: текущая передача состояния выполнена 3 ноября. На первом доступном цикле существующего A0 — сверить актуальные refs/очередь и выбрать один незавершённый блок. Оценку срока этого блока A0 даёт после проверки зависимостей. Ранее обсуждавшиеся сроки продукта являются ориентирами, не подтверждёнными обязательствами. Новое расписание для этого не создаётся.

## 3. GitHub: непосредственно проверено

- Репозиторий публичный, не архивирован, default branch `main`.
- Текущий `main`: `ea633c769863bd55f5d11e4a807ba459f711a4a2` ([commit](https://github.com/ivan88810900-star/tnved_starter_kit_v2/commit/ea633c769863bd55f5d11e4a807ba459f711a4a2)).
- В API обнаружено 52 открытых PR (полный список ниже). Наличие PR и mergeable не означает готовность.
- Восемь ключевых кандидатов:

| PR | Текущий HEAD | Контекст |
|---|---|---|
| [244](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/244) | 14e0ee8f034d94ffc5831d87e076f4d693a5a524 | основной core, draft |
| [245](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/245) | e39e19787bd913baeb6f85577a13e1116458e633 | compliance/AI, draft |
| [255](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/255) | 27080f214a1cdbc6bb89e837a602a5dbaff38e72 | payment regressions поверх 244, draft |
| [256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256) | 407a01c55d972800d2219063a2c532d85f5640b9 | product/NTM поверх 245, draft |
| [260](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/260) | f50f8cbe10daef44a4f42c516aaf19a5f5b156f4 | восстановление структуры, draft |
| [263](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/263) | b26f938f236d707ac2ff2d875d5ffc9f94fbb58b | offline plan runner, draft |
| [268](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/268) | ec51b53d0d266ff146870fc5c17b944023e97264 | legacy preview, draft |
| [269](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/269) | ded231d0abe6793f4cc2ca110f4a4b11439f8efb | legacy apply preparation поверх 268, draft |

PR269: непосредственно перечитан exact-head PR CI [41484321363](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/41484321363), completed/success. Текущий body фиксирует fresh independent A5 pending. Это code-only кандидат, не разрешение повторить принятую загрузку главы 29.

Акт cycle431 связывает проверку plus-aware парсера с `aefbff907c390c42b3e2f3ba4d9166ece86914cb`; текущий HEAD PR256 другой. Старые A5/CI не переносить на новый HEAD. Запрос API PR-triggered workflow runs для текущего PR256 вернул пустой список: это пробел проверки, а не утверждение, что нет push/manual CI. Полный обзор CI/A5 всех 52 PR в этой передаче не выполнялся; readiness не присваивался.

Runtime:
- `.ai/COORDINATOR_LEASE.json`: generation 435, state released, holder/token null, updated_at `2026-11-03T04:21:24.506402Z` (07:21 МСК). Это снимок, не доказательство остановки A0.
- `.ai/TASK_BOARD.json` найден, blob `1d83ddadbffec8ba60089a2ebc9ce90765ba1e85`, но connector вернул пустой content. Текущая очередь/ownership полностью не сверены. Не заменять файл пустым/усечённым содержимым.
- CURRENT_STATE и PROJECT_HANDOFF непосредственно прочитаны; их верхний принятый baseline — cycle430.
- Учесть исторический отказ CAS TASK_BOARD revision927 (`user rejected MCP tool call`), записанный в cycle415/issue257. Эта передача не повторяет отклонённую операцию.
- Lease, board, ownership и старые документы этой передачей не изменяются. Публикуется только новый сводный документ; это не запуск технического A0 и не захват его роли.

## 4. Neon: прямая проверка только SELECT

Проект `tariff-staging` / `red-meadow-53765518`, регион `aws-eu-central-1`.
Ветка `staging` / `br-weathered-frost-ba9jri3c`, база `tariff_staging`, схема `tariff_ingest`.
Это существующий постоянный staging. Не создавать замену.

| Показатель | Фактически прочитано |
|---|---:|
| tnved_structure_rows | 18 014 |
| ett_collected_rows | 619 |
| ett_normalization_results | 619 |
| PARSED | 444 |
| AMBIGUOUS | 175 |
| verified=true | 0 |
| admitted=true | 0 |
| sgr_collected_rows | 3 420 |
| source_objects | 69 |
| ingest_runs | 38 |

Дополнительный SELECT по ЕТТ RAW: глава 01 — 86, глава 29 — 533; главы 30 нет.
Чтение агрегатов не подтверждает полную юридическую актуальность, целостность каждого объекта или полноту СГР/NTM. Частные оригиналы, object keys, credentials и построчные выгрузки не извлекались.

Сохранить все существующие RAW/source/run/hash identities. Не повторять уже принятую загрузку 533 нормализаций главы29 или 86 главы01. Предыдущая большая база около 6,78 ГБ и пакет около 13 319 строк упомянуты в исходном чате, но их фактическая доступность в этой проверке не установлена; не считать восстановленными.

## 5. Принятый результат и следующий блок

[cycle430 acceptance](https://github.com/ivan88810900-star/tnved_starter_kit_v2/blob/agent/orchestration-state/.ai/orchestration/evidence/cycle430_chapter29_normalization_acceptance.json):
533 технических результата главы29 приняты, итог 619/444/175/0/0; replay без INSERT/UPDATE/DELETE, RAW и прежние 86 сохранены. Это принятый исторический блок, а не обещание полной главы29: cycle431 отдельно выявляет пять дополнительных plus-кандидатов, не разрешённых к текущей загрузке.

[cycle431 receipt](https://github.com/ivan88810900-star/tnved_starter_kit_v2/blob/agent/orchestration-state/.ai/orchestration/evidence/cycle431_chapter30_raw_extraction/receipt.json):
- Следующий источник — глава30, редакция 2026-03-08, `ru.30_2022_08.03.2026.pdf`.
- Официальный GET ранее вернул HTTP403; receipt запрещает дальнейшие попытки скачивания после указания no-retry. Не обходить запрет прокси/неофициальным зеркалом.
- Сохранённый repo PDF имеет UNREVIEWED_ORIGIN_PROVENANCE, годен только для инвентаризации. Git blob presence не доказывает официальное происхождение.
- Диагностически найдено 82 кода в непроверенном snapshot; это НЕ принятый официальный объём.
- v1 пропускал leading-plus строки; opt-in `ett-pdftotext-layout-raw-v2-plus` исправляет этот отдельный формат. Многострочные продолжения не обеспечены: полного официального RAW package нет.
- Принятая история главы29 остаётся v1/533; пять дополнительных кандидатов требуют отдельного QA scope.
- Существующий structural parser `tnved_pdf_parser.py::_assemble_rows` меняет пробелы/поля и не является совместимой заменой immutable RAW extractor.

Следующее безопасное действие существующего A0:
1. Сверить текущую очередь/ownership/lease и HEAD256, проверить, не выполнен ли уже следующий шаг. Не начинать параллельного исполнителя.
2. Использовать уже сохранённые артефакты. Подтвердить происхождение официальных байтов главы30 через разрешённые доказательства/переданные проверенные байты; до этого не объявлять SHA/размер/число строк официально принятыми.
3. Определить сохраняющий исходные байты контракт многострочных продолжений в существующем pipeline; минимальный code delta только после подтверждения реального дефекта. Не создавать новые таблицы/архитектуру.
4. Получить независимые доказательства на точном кандидате и воспроизводимый offline package. До нового scoped разрешения не применять SQL в staging.
5. После offline QA представить конкретный план владельцу: source/version/SHA, exact candidate, диапазон/число строк, изменения, replay/rollback, контрольное чтение и риски. Запрашивать ровно недостающее действие.
6. Параллельно на уровне планирования учесть незавершённые core/payment и NTM acceptance; 3 420 СГР RAW не равны готовому синхронизированному нормативному NTM snapshot.

## 6. Полномочия и использованные разрешения

Текущее прямое поручение владельца: проверка GitHub/Neon/существующего контроля, сохранение единого handoff в этом репозитории и инструкция существующему Dot. Merge/deploy, staging writes, новые дублирующие агенты и расписания запрещены.

Сохраняется исторический мандат A0 на обычную техническую работу: ограниченные исправления, тесты, agent commits/push и draft PR по контракту. Эта передача не запускает разработку и не расширяет мандат. Репозиторные инструкции о запуске подагентов не отменяют текущий запрет создавать агентов в этой задаче.

Отдельные gates:
- Разовое разрешение на 533 нормализации главы29 ИСПОЛЬЗОВАНО; не действует на главу30 и новые варианты parser/package.
- Уже выполненные шаги главы01 не повторять по старой просьбе «продолжить»: прямое чтение показывает 86 результатов уже в общем baseline.
- A6 r7-g100 использован, provider HTTP400 / UNAVAILABLE, live_verified=false; retry_allowed=false. r8-g103 retired/non-retryable.
- `core-s1-6415f443120f-r9-g106` подготовлен offline, dispatched=false, consumed=false, provider_called=false; отдельное разрешение на внешний экспорт отсутствует. Packet SHA256 `e2a0d35aaae76d4a8fa0c74d4fe7d83d609371d75b7ef7eced1484890d1f22b8`. Не отправлять и не переупаковывать автоматически.
- A6 исходный файл датирован 7 октября; прямо проверено его текущее содержимое, но оно не доказывает новые события вне этого реестра.
- Merge/main/canonical, deploy, enforcement/admission, новые DB writes, чтение частных оригиналов за пределами разрешённого scope, destructive migration, secrets/permissions, force-push/branch deletion и экспорт A6 не разрешены этим поручением.
- Не сбрасывать ранее принятый advisory rollout ради старого default-OFF текста; не включать enforcement. Не принимать source facts за решение юридической применимости.
- Прежние отказы платформы не обходить сменой инструмента. Новое разрешение должно называть конкретное действие и scope.

## 7. Действующий контроль, Automations и Dot

Непосредственно подтверждено:
- Найдены существующие чаты «Tariff — контроль остановок», в том числе последний `6ae71fec-7478-83eb-9e58-58cac76e82a9`; его сообщения прочитаны. Наличие нескольких исторических чатов не доказывает несколько активных schedules.
- [Receipt A0 6081329929](https://github.com/ivan88810900-star/tnved_starter_kit_v2/issues/257#issuecomment-6081329929) реально существует: dispatch probe Dot → существующий A0 выполнен 9 октября. Это историческая доставка, не доказательство сегодняшнего запуска.
- Локального каталога Codex automations в этой среде нет. Доступный automation tool требует известный ID; достоверный ID существующего ChatGPT schedule не получен.
- Доступ через UI приложения запрещён средой: `Computer Use is not allowed to use the app 'com.openai.codex' for safety reasons`. Обход не выполнялся.

Сведения только из прежнего контроля:
- «Tariff — разработка» отмечалось disabled с 21 октября, последний зарегистрированный запуск 21 октября 15:50 МСК. Более поздние циклы отражены в GitHub, но этим не доказано возобновление штатного расписания.
- Текущий on/off, schedule ID, частота, настройки и привязка именно «Бизнес Tariff» в данной сессии непосредственно не проверены. Новая остановка после двух выполненных циклов не установлена.

Итог: существующие расписания/Dot не изменены, не включены, не удалены. Новые не созданы. Сохранён готовый текст обновления ниже. Для завершения переноса требуется применить его в существующем Dot и вернуть проверяемый receipt с ID изменённой задачи. Не выдавать сохранение этого файла за завершённую перенастройку Automations.

Официальная документация подтверждает возможность Dot читать/редактировать существующие Work automations, но не наличие доступа у этой сессии: [Tasks and memory](https://learn.chatgpt.com/docs/dots/tasks-and-memory).

## 8. Готовая инструкция существующему Dot «Бизнес Tariff»

Текст для передачи без создания нового Dot:

> Продолжай управление существующим проектом Tariff по TARIFF_MASTER_HANDOFF.md в ветке agent/orchestration-state единственного репозитория ivan88810900-star/tnved_starter_kit_v2. Прочитай документ целиком и свежие GitHub/Neon факты перед действием.
>
> Ты — существующий бизнес-координатор. A0 остаётся единственным ответственным разработчиком и техническим координатором. Не создавай новых агентов, рабочих чатов, репозиториев, баз или расписаний и не начинай повторную разработку. Существующие результаты и source/run/hash identities сохранить.
>
> Найди существующую задачу «Tariff — контроль остановок» по её ID и содержимому. Обнови её инструкцию по разделу9 этого handoff, сохрани частоту, часовой пояс, статус и настройки уведомлений. Не включай отключённую «Tariff — разработка» автоматически. Если совпадение неоднозначно — покажи найденные ID/статусы; ничего нового не создавай. После обновления перечитай задачу и зафиксируй ID, изменённое поле, сохранённые настройки и время.
>
> Проверь фактическую доступность существующего A0 и отсутствие другого holder. Не считай старый receipt запуском сегодня. Передавай следующий шаг существующему A0 только через уже установленный канал; сохрани реальный receipt, а не текст «передано».
>
> Ближайший продуктовый блок — подтверждённые официальные байты главы30 и полнота многострочного извлечения через существующий pipeline; сначала сверить, не закрыт ли блок. 82 диагностических кода не считать официальной полнотой. 533 результатов главы29 уже приняты; разрешение использовано.
>
> Merge/deploy, staging/production writes, enforcement/admission и внешний A6 не выполнять. Неразрешённые действия показывай владельцу конкретным планом; обычные разрешённые технические шаги оставляй A0.
>
> Вести один отчёт: принятый продуктовый результат; доказательства/точный SHA; RAW/normalized/ambiguous/verified/admitted; блокировка; следующее действие и исполнитель; требуется ли конкретное решение владельца. Молчать при неизменном или незначимом состоянии; сообщать о значимом прогрессе, сбое, завершении или нужном решении. Перенос управления считать завершённым только после подтверждённого обновления существующей задачи.

## 9. Текст для обновления существующей задачи контроля

Контролируй Tariff по TARIFF_MASTER_HANDOFF.md в agent/orchestration-state репозитория ivan88810900-star/tnved_starter_kit_v2. На каждом существующем запуске сверяй текущий main, ключевые PR/head/CI, CURRENT_STATE, PROJECT_HANDOFF, TASK_BOARD и COORDINATOR_LEASE с текущими доказательствами. Если connector возвращает пустой content или 404, отмечай предел проверки и используй правильную ветку; не объявляй отсутствие исполнения доказанным. При доступном Neon выполняй только SELECT агрегатов в существующем tariff_staging и различай RAW, normalized, ambiguous, verified и admitted. Сопоставляй со снимком 18014/619/3420, 619 normalized, 444 PARSED, 175 AMBIGUOUS, verified/admitted0; свежие изменения подтверждай фактами. Не повторяй принятую главу29 и не переноси её разрешение на главу30. Проверяй следующий безопасный блок главы30 и старые core/NTM блокировки без запуска дублирующей разработки. Не создавай агентов/чаты/репозитории/БД/расписания, не меняй lease/board/code/DB, не делай merge/deploy/flags/A6 export. Старый receipt не доказывает текущий прогресс. Не называй остановкой отсутствие новых PR; подтверждай реальные состоявшиеся циклы и их результат. Сообщай только о значимом изменении, завершении, сбое или конкретно необходимом решении владельца. При неизменном или незначимом состоянии сохраняй тишину. Не запрашивай повторно использованные разрешения и не обходи отказы платформы.

## 10. Приёмка этой передачи и незакрытый остаток

Выполнено: чтение исходного чата и существующего контроля, текущих GitHub refs/PR/docs/receipts, Neon metadata и SELECT агрегатов; единый handoff и инструкция сохранены в существующем репозитории. Никаких продуктовых исправлений, merge/deploy, DB writes, private object reads, A6 calls, новых агентов или расписаний.

Не выполнено из-за отсутствия доступного управления: непосредственная инвентаризация текущих Automations/Dot и изменение существующей задачи. Следующее действие принадлежит существующему Dot: проверить task ID и применить раздел9, сохранив настройки. До receipt статус передачи — DOCUMENTED / DOT_AUTOMATION_UPDATE_PENDING.

Сам факт сохранения документа не является новым разрешением на защищённые действия. Старые чаты не удалены и не архивированы; их существование не создаёт новую очередь поручений.

## 11. Полный снимок открытых PR

Состояние взято из GitHub search open PR, limit100, возвращено52. Это инвентаризация, не очередь на merge и не список завершённых функций.

- [#269](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/269) — feat(ett): prepare legacy chapter-29 normalization apply
- [#268](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/268) — feat(ett): add offline legacy normalization preview
- [#267](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/267) — feat(ett): add fail-closed legacy recovery envelope
- [#266](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/266) — fix(ett): bound chapter-aware offline normalization
- [#264](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/264) — fix(staging): bind retained legacy manifest semantically
- [#263](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/263) — feat(staging): add dependency-free ETT offline plan runner
- [#262](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/262) — feat(staging): add deterministic ETT normalization
- [#261](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/261) — fix(a6): skip unrelated issue comments before trusted gate
- [#260](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/260) — feat: deterministic TN VED structural recovery
- [#259](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/259) — test: isolate data refresh subprocess database
- [#258](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/258) — fix(ntm): preserve complete SGR snapshots
- [#256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256) — fix(ntm): harden product evidence and permit regressions
- [#255](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/255) — fix(payments): fail closed on unverified rates and scope
- [#245](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/245) — feat(product): consolidated compliance and AI candidate
- [#244](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/244) — feat(core): consolidated customs core candidate
- [#242](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/242) — feat(product): consolidate compliance and grounded AI safeguards
- [#241](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/241) — feat(core): consolidate fail-closed payments and source health
- [#240](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/240) — fix(sources): expose fail-closed sync schedule health
- [#239](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/239) — fix(ntm): stop machinery text mapping to tyres
- [#238](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/238) — A1: fail closed on invalid automatic duty operands
- [#235](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/235) — fix(sources): expose missing sync entrypoints
- [#234](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/234) — fix(ntm): bound alcohol classifier keywords
- [#233](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/233) — fix(ntm): bound SGR supplement acronym
- [#232](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/232) — fix(payments): fail closed on unverified FX rates
- [#231](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/231) — fix(sources): validate edition tracking provenance
- [#230](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/230) — fix(ntm): narrow tableware description trigger
- [#229](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/229) — fix(payments): fail closed on unitless fixed antidumping
- [#228](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/228) — fix(payments): require proven CBR rates for FX
- [#227](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/227) — fix(search): reject incompatible TN VED embeddings
- [#226](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/226) — fix(sources): fail closed on future bundle revisions
- [#224](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/224) — fix(ntm): separate control certificates from conformity
- [#223](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/223) — fix(sources): keep landing-page observations fail-closed
- [#222](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/222) — A1: fail closed on future special-duty measures
- [#221](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/221) — fix(ntm): prevent false child SGR matches
- [#220](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/220) — fix(payments): reject invalid manual payment operands
- [#216](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/216) — fix(payments): fail closed on fixed excise without a source unit
- [#213](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/213) — Assistant: surface NTM freshness limits
- [#212](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/212) — Sources: monitor known AD30 decision and review PDFs
- [#211](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/211) — NTM: surface fail-closed normative freshness
- [#208](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/208) — fix(ntm): distinguish advisory permit summary
- [#207](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/207) — fix(ntm): fail closed on unknown data freshness
- [#206](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/206) — docs(ntm): record bounded completeness recheck
- [#205](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/205) — docs(sources): record fail-closed AD30 freshness evidence
- [#204](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/204) — fix(payments): gate source-unbound legacy amounts
- [#203](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/203) — fix(invoice): keep model VAT candidates provisional
- [#202](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/202) — feat(fx): expose fail-closed stored CBR observations
- [#201](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/201) — docs(sources): recheck temporal and AD30 evidence gaps
- [#200](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/200) — docs(payments): recheck residual source-bound gaps
- [#192](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/192) — docs(sources): add bounded AD30 chain review candidate
- [#191](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/191) — ci(agents): verify dynamic branches and current payment admission boundaries
- [#189](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/189) — AI-TEAM-SAFE-001: изолированный пилот агентов (OFF, без production)
- [#187](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/187) — feat: official NTM, source updates and versioned ETT candidates

## 12. Основные исходные документы

В ветке agent/orchestration-state:
- [.ai/CURRENT_STATE.md](https://github.com/ivan88810900-star/tnved_starter_kit_v2/blob/agent/orchestration-state/.ai/CURRENT_STATE.md)
- [.ai/PROJECT_HANDOFF.md](https://github.com/ivan88810900-star/tnved_starter_kit_v2/blob/agent/orchestration-state/.ai/PROJECT_HANDOFF.md)
- [.ai/TASK_BOARD.json](https://github.com/ivan88810900-star/tnved_starter_kit_v2/blob/agent/orchestration-state/.ai/TASK_BOARD.json) — content неполучен
- [.ai/COORDINATOR_LEASE.json](https://github.com/ivan88810900-star/tnved_starter_kit_v2/blob/agent/orchestration-state/.ai/COORDINATOR_LEASE.json)
- [.ai/orchestration/A6_LIVE_STATUS.json](https://github.com/ivan88810900-star/tnved_starter_kit_v2/blob/agent/orchestration-state/.ai/orchestration/A6_LIVE_STATUS.json) — не .ai/A6_LIVE_STATUS.json
- [.ai/orchestration/CONTRACT.md](https://github.com/ivan88810900-star/tnved_starter_kit_v2/blob/agent/orchestration-state/.ai/orchestration/CONTRACT.md)
- [.ai/orchestration/RUNBOOK.md](https://github.com/ivan88810900-star/tnved_starter_kit_v2/blob/agent/orchestration-state/.ai/orchestration/RUNBOOK.md)
- [.ai/TASK_PROTOCOL.md](https://github.com/ivan88810900-star/tnved_starter_kit_v2/blob/agent/orchestration-state/.ai/TASK_PROTOCOL.md)

Исходное поручение: чат «Промт для повторного аудита Tariff» 6ad601ec-23dc-83ed-b5cf-c176200f1d6f; текущая передача: «Централизовать handoff проекта Tariff» 01a1a093-a61c-7802-a366-b66caa42cc99. Чаты сохраняются как история. Секреты, частные пути, signed URLs и частные оригиналы в этот публичный файл не включаются.
