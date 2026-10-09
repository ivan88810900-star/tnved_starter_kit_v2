# Tariff / A0 — единая точка передачи проекта

**Снимок:** 2026-10-09 (UTC). **Единственный репозиторий:** [ivan88810900-star/tnved_starter_kit_v2](https://github.com/ivan88810900-star/tnved_starter_kit_v2).
**Авторитетное состояние:** ветка `agent/orchestration-state`, файлы `.ai/TASK_BOARD.json`, `.ai/COORDINATOR_LEASE.json`, `.ai/orchestration/A6_LIVE_STATUS.json`. Этот документ — указатель и контрольная точка, **не** право на запись/merge/A6. Перед действием заново читать текущие HEAD и state. Не полагаться на Business-чат.

## 0aaaaaaaaa. #245 — Copilot/Batch показывает server grounding и fail-closed provenance

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `dd7ac413dc2f7698ffe1ce80375557afcbac2da5`, tree `48c43f8e00a4091c56425975cb28c63fcc235ab5`, parent `e452d967d86436fda4b49cf344b026b639eb7c5c`.

Воспроизведён frontend-дефект: `/assistant/copilot` и `/assistant/copilot/batch` уже возвращали server-owned `ai.grounding` и `ai.citations`, но типы и общий экран сводки полностью их отбрасывали. Пользователь видел «экспертную сводку» без режима, покрытия и источников.

Исправление показывает coverage, mode, использованные fact-блоки, limitations и citations в single/batch представлении. Положительные `grounded` / `llm_grounded` допускаются только при `generated_from_server_facts=true`, полной citation identity (`id/source_id/title/kind`) и непустом полностью allowlisted `facts_used`. Missing, incomplete и mixed metadata обозначается неподтверждённой; `javascript:` и другие небезопасные URL не становятся ссылками. UI прямо сообщает, что статус не является юридической проверкой и не подтверждает полноту НТМ.

Проверки:

- author focused: **6 passed**, полный frontend: **31 passed**, typecheck/build/diff-check — exit 0;
- независимый A5 дважды отклонил промежуточные trees: неполная citation + произвольный fact; затем valid citation без `facts_used` с положительным badge;
- финальный A5: **PASS без findings**, focused/adversarial **15 passed**, полный frontend **31 passed**, typecheck/build/diff-check — exit 0;
- exact-head CI: [run 37978226897](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37978226897), job `113981820756`, **success**.

Изменены только frontend type/view/focused test. Backend, БД, applicability, source admission, enforcement и feature flags не менялись. Полный #245 product/legal/source completeness остаётся **NOT PASS**; lawful populated synchronized NTM snapshot всё ещё недоступен. A6 `core-s1-6415f443120f-r9-g106` неизменён и не отправлялся.

Следующий шаг — следующий воспроизводимый bounded #245 assistant/search integration defect с теми же fail-closed source boundaries; full-sync audit запускать только при законно доступном populated synchronized snapshot.

## 0aaaaaaaa. #245 — UI чата показывает grounding и fail-closed проверяет metadata

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `e452d967d86436fda4b49cf344b026b639eb7c5c`, tree `e5252a9f45b717215dabf7d5ded1b297480f4435`, parent `43803039d7ce50bf88c3d9c08af2f638462767a2`.

Воспроизведён frontend-дефект контракта: текущий `/v1/assistant/chat` возвращает вложенный объект `answer`, но UI ожидал строку и вызывал `.trim()` на объекте. Одновременно coverage, citations и limitations полностью скрывались от пользователя.

Исправление поддерживает текущий и legacy envelope, показывает ограниченные coverage/mode/limitations/citations и превращает в ссылки только HTTP(S). Утвердительные `grounded` / `llm_grounded` labels допускаются лишь при `generated_from_server_facts=true` и минимум одной runtime-валидной цитате; иначе metadata обозначается неподтверждённой. UI прямо предупреждает, что покрытие данных не подтверждает юридическую полноту. Grounding metadata не попадает в историю; API получает только последние 40 текстовых сообщений, видимая история не обрезается.

Проверки:

- до исправления: **2 failed, 1 passed**, `.trim is not a function`, exit 1;
- author focused: **7 passed**, полный frontend: **25 passed**, typecheck/build — exit 0;
- независимый A5 сначала отклонил первый candidate из-за недоказанных affirmative labels; исправленный exact tree — **PASS без findings**;
- A5 adversarial matrix: **8 passed**, exit 0;
- root repeat focused/typecheck/build — exit 0;
- exact-head CI: [run 37971284152](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37971284152), job `113958262264`, success; [run 37971430723](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37971430723), job `113958761517`, success.

Изменены только frontend type/component/focused test. API, applicability, enforcement, source admission, БД и feature flags не менялись. Полный #245 product/legal/source completeness остаётся **NOT PASS**; populated synchronized NTM snapshot по-прежнему отсутствует. Внешний A6 `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий шаг — следующий bounded #245 assistant/search/frontend integration slice с сохранением fail-closed citations и source boundaries.

## 0aaaaaaa. #245 — assistant grounding больше не считает пустую карточку доказательством

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `43803039d7ce50bf88c3d9c08af2f638462767a2`, tree `efbbfb1764c40392b4ecc988f8f929d59fbb4bf6`, parent `321b4ac72b13ec40a0dc3e2b05f8079f39fb6ee7`.

Воспроизведён fail-open metadata defect: синтаксически корректного HS-кода было достаточно для `coverage="grounded"`, даже когда TNVED и NTM providers завершались ошибкой. Первый candidate A5 отклонил: штатно возвращённая пустая TNVED-карточка с одной generic EEC URL всё ещё создавала факт/цитату и могла допустить configured LLM selector.

Финальное исправление требует usable local evidence: непустые title/description/breadcrumb/notes/source revision или resolver-validated canonical anchor. При provider failure либо пустой карточке coverage становится `partial`, citations/facts остаются пустыми, LLM selector не вызывается. Содержательная карточка и canonical anchor сохраняют `grounded`. Пользовательский deterministic fail-closed ответ сохранён; legal applicability, source-of-truth и enforcement не менялись.

Проверки:

- regression до исправления: expected `partial`, получен `grounded`, exit 1;
- author focused: **25 passed + 26 subtests**, exit 0;
- author 12-module assistant/search/grounded/RAG tranche: **87 passed + 29 subtests**, exit 0;
- независимый A5: первый candidate **REJECT MEDIUM**, repaired tree **PASS без findings**; adversarial empty-card/canonical-only/provider-error/candidates/no-context matrix exit 0;
- remote commit tree побайтово совпадает с independently reviewed tree;
- exact-head CI: [run 37963680241](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37963680241), job `113932566080`, **success**.

Тесты выполнялись на новой disposable classification DB с пустыми provider keys, deny proxies и preview marker вне репозитория. `integrity_check=ok`, foreign key violations 0, source WAL/SHM отсутствуют.

Полный #245 product/legal/source completeness остаётся **NOT PASS**. NTM full-sync по-прежнему требует законно доступный populated synchronized snapshot. Внешний A6 `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий шаг — следующий bounded #245 assistant/search API и frontend grounding tranche, не расширяя legal/enforcement semantics.

## 0aaaaaa. #245 — NTM и mass-seed fixtures подтверждены в раздельных disposable-контурах

**Кодовый checkpoint не изменён:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `321b4ac72b13ec40a0dc3e2b05f8079f39fb6ee7`, tree `ef6fd5680b6c006be5c836643a0ab1cbceef111a`.

Расширенный выборочный запуск 35 NTM/non-tariff/regulatory/compliance/permits модулей сначала воспроизвёл **8 failures**: семь mass-seed assertions ожидали более 5 000 документов, а mass-seed-safety ошибочно выполнялся на classification inventory. Это конфликт двух fixture-контуров, а не runtime-дефект продукта. Контуры разделены без изменения кода и порогов:

- classification/NTM contour на каноническом bootstrap: 33 модуля, **790 passed, 2 skipped, 3 subtests**, exit 0;
- отдельный regulatory mass-seed contour: **5 057 документов / 5 481 mapping**, три audit-модуля, **24 passed, 3 subtests**, exit 0;
- суммарно: **814 passed, 2 skipped, 6 subtests**, обе команды exit 0.

Независимый A5 `/root/a5_ntm_fallback` повторил exact unchanged HEAD в свежем detached worktree: **790 passed, 2 skipped, 3 subtests** и **24 passed, 3 subtests**, обе команды exit 0. Worktree чистый, обе SQLite БД дают `integrity_check=ok`, catalogue WAL/SHM отсутствуют, synthetic admitted documents = 0. Новых findings нет.

Exact-head CI остаётся действующим для того же SHA: [run 37941232220](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37941232220) и [run 37941931512](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37941931512), оба `success`. Новый кодовый commit и новый CI run не требуются, потому что проверенный HEAD не изменился.

Полный broad/full-suite PASS и юридическая/source completeness не заявляются. `test_ntm_full_sync.py` всё ещё требует законно доступный populated synchronized NTM snapshot; существующий disposable classification bootstrap его не заменяет. Внешний A6 `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий шаг — следующий bounded offline #245 assistant/search/grounded tranche с сохранением раздельных fixture-контуров и без тестов, требующих неразрешённую внешнюю сеть.

## 0aaaaa. #245 — bootstrap подтверждён расширенным offline-срезом и exact-head CI

**Текущий кодовый checkpoint не изменён:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `321b4ac72b13ec40a0dc3e2b05f8079f39fb6ee7`, tree `ef6fd5680b6c006be5c836643a0ab1cbceef111a`.

На новой disposable DB выполнен следующий bounded offline #245 tranche: bootstrap плюс 12 модулей TN VED/classification/normative/API — **137 passed**, exit 0. Независимый A5 `/root/a5_ntm_fallback` повторил exact clean detached запуск с запретом исходящей сети и вынесенным `TNVED_PREVIEW_CACHE_REVISION_FILE`: **137 passed, 1 warning**, exit 0; tracked/untracked mutation и source WAL/SHM отсутствуют. Existing `test_tnved_catalog_api.py` без перенаправления marker обновляет tracked preview-revision файл, поэтому дальнейшие disposable прогоны обязаны выносить marker из репозитория.

Exact-head Actions подтверждены на alias ref, который свежим `ls-remote` связан с тем же SHA: [run 37941232220](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37941232220), job `113855829425`, success; [run 37941931512](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37941931512), job `113858391699`, success. Старый статус CI pending снят.

Полный broad/full-suite PASS не заявляется: ранее unrelated тест попытался обратиться к `api.proxyapi.ru`, и обход запрета не выполнялся. Lawful populated synchronized NTM snapshot по-прежнему отсутствует, поэтому NTM full-sync и legal/source completeness остаются **NOT PASS**. Внешний A6 `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий шаг — продолжить следующий ограниченный offline #245 fixture tranche на этом bootstrap с вынесенным preview marker; full-sync ждать только законно доступный populated synchronized snapshot.

## 0aaaa. #245 — канонический disposable bootstrap закрыл FTS classification fixture gap

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `321b4ac72b13ec40a0dc3e2b05f8079f39fb6ee7`, tree `ef6fd5680b6c006be5c836643a0ab1cbceef111a`, parent `a89904e335aa7cb3ae906b094031c0155254000e`; base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

Воспроизведён fixture gap: свежий `init_db()` оставлял 0 писем ФТС и 0 classification rulings, поэтому broad #245 останавливался на inventory assertions. Добавлен отдельный bootstrap, который создаёт только новую SQLite БД, проверяет SHA-256 committed TN VED каталога, открывает источник immutable/read-only, детерминированно оставляет `MIN(id)` для 39 legacy duplicate-code групп и загружает тестовый classification inventory. Существующий target отклоняется; запуск после уже загруженного `app.db` fail-closed, чтобы cached `engine`/`SessionLocal` не записал в ранее привязанную БД. Результат явно помечен как disposable test inventory, не legal/source-completeness snapshot.

Проверки exact final tree:
- reproduction до исправления: 0 FTS letters, первые 3 inventory assertions failed, exit 1;
- author safety tests: **5 passed**, exit 0; bootstrap + исходные FTS/classification suites: **32 passed**, exit 0;
- создано 13 979 уникальных кодов, 206 писем, 205 classification decisions, 50 formal и 520 reference rulings; `integrity_check=ok`;
- независимый A5 `/root/a5_ntm_fallback`: первый candidate **REJECT HIGH/MEDIUM** из-за cached-DB mutation и WAL sidecars; исправленный exact tree **PASS**. Pre-bound DB осталась 0/0/0/0, новый target не создан; hash источника неизменён, WAL/SHM отсутствуют, для всех 39 duplicate groups 0 расхождений с `MIN(id)`;
- remote tree побайтово совпадает с reviewed tree;
- полный backend run остановлен runtime security policy при попытке unrelated теста обратиться к `api.proxyapi.ru`; обход не выполнялся, full-suite PASS не заявляется;
- exact-head GitHub Actions: **PENDING_NO_RUN_OBSERVED**. После push основной ветки и fast-forward CI alias `agent/product-ntm-bootstrap-ci-v1` workflow runs и combined statuses остаются пустыми. Candidate не считается окончательно принятым.

Полный #245 product/legal/source-completeness **NOT PASS**. Lawful populated synchronized NTM snapshot всё ещё недоступен; этот bootstrap его не заменяет. Protected merge, production/DB writes, enforcement flags, secrets/permissions, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` неизменён и не отправлен.

Следующий шаг — повторно проверить mandatory exact-head CI, затем использовать bootstrap для следующего bounded offline fixture tranche #245. NTM full-sync completeness остаётся заблокированной до законно доступного populated synchronized snapshot.

## 0aaa. #245 — official SGR NTM v2 scope и runtime admission теперь fail-closed

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `a89904e335aa7cb3ae906b094031c0155254000e`, tree `641a1acf45728729c683bef2728521cff6e26604`, parent `d5dd222f108399eac82a5d8001d7615a00953d08`; base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

Воспроизведены четыре product defect: DB runtime расширял `exact` HS scope на потомков, допускал inactive measure и export-only rule в import evaluation, а importer принимал неизвестный `hs_scope_mode`. Первый candidate независимый A5 отклонил из-за более серьёзного fail-open: пустой или exclusion-only `description_only` мог совпасть с любым товаром. Финальное исправление требует positive contains/requires marker в importer и dataset validator, блокирует ранее сохранённые некорректные строки в DB runtime, объединяет seed/DB semantics и сохраняет неподтверждённую применимость вне автоматического вывода. Новая юридическая интерпретация и definite applicability не добавлялись.

Проверки exact final tree:
- direct reproduction до исправления: seed matcher `False`, DB runtime `True` для descendant exact scope; четыре targeted regression — **4 failed**, exit 1;
- author disposable-DB NTM v2 runtime/layer slice: **210 passed**, exit 0; focused importer/validator/pipeline после A5 repair: **189 passed**, exit 0; `compileall` и `git diff --check` — exit 0;
- broader #245 probe: **507 passed, 1 skipped, 26 subtests**, затем 10 fixture-inventory failures из-за отсутствующих в disposable DB FTS letters/classification seeds; это зафиксированный fixture/setup gap, не green broad-suite claim;
- независимый A5 `/root/a5_ntm_fallback`: первый candidate **REJECT HIGH**, финальный exact reviewed tree **PASS**; fresh-SQLite adversarial matrix `OFFICIAL_SGR_FAIL_CLOSED_MATRIX_OK`, focused **189 passed**, exit 0; вручную сохранённые empty/exclusions-only строки также не допускаются runtime;
- remote blobs пяти изменённых файлов побайтово совпали с reviewed tree; PR перечитан на exact remote HEAD;
- exact-head GitHub Actions: **PENDING_NO_RUN_OBSERVED** для `a89904e335aa7cb3ae906b094031c0155254000e`; workflow runs и combined status пусты после повторных проверок. Candidate не считается окончательно принятым.

Полный #245 product/legal/source-completeness **NOT PASS**. Protected merge, production/DB writes, enforcement flags, secrets/permissions, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` неизменён и не отправлен.

Следующий шаг — повторно проверить обязательный exact-head CI, затем подготовить canonical disposable fixture bootstrap для FTS classification inventory и продолжить fixture-backed broad/full-sync #245 проверки.

## 0aa. #244 — устаревшее или несвязанное evidence спецпошлины больше не попадает в автоматическую сумму

**Новый текущий checkpoint:** [draft PR #255](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/255), `agent/core-payment-regressions-v1` @ `7c12f21787b1d557630d8b0737c769b326ab112d`, tree `9ebd8fb4f9a11d066f1b538fb50d67861e249604`, parent `6f1f5522cfe304030d1be474e3f074e85a739835`; base #244 неизменён `14e0ee8f034d94ffc5831d87e076f4d693a5a524`.

Воспроизведён product defect: строка trade remedy с `SourceStatus.is_stale=true` всё ещё добавляла 7 000 RUB к публичному расчёту. Исправление связывает каждую anti-dumping, safeguard и countervailing строку с exact current `SourceStatus.revision` и единым 90-дневным budget свежести. Отсутствующий, stale, mismatched или future status, а также revision старше 90 дней, оставляет evidence и переводит расчёт в manual review: special-duty amount и итог удерживаются. Exact 90-day boundary остаётся допустимым. Новая юридическая применимость не выводилась и нормативные источники не переинтерпретировались.

Проверки exact final tree:
- direct reproduction до исправления: `test_public_path_rejects_stale_trade_remedy_source_status` — **FAIL**, получено 7 000 вместо 0, exit 1;
- author focused `tests/test_special_duties.py`: **18 passed + 9 subtests**, exit 0;
- author workflow-equivalent payment slice на disposable SQLite: **274 passed + 23 subtests**, exit 0;
- author broad source/ingestion slice: **254 passed + 63 subtests**, exit 0; `compileall` и `git diff --check` — exit 0;
- независимый A5 `/root/a5_special_scope`: **PASS exact reviewed tree**; focused **37 passed + 9 subtests**, broad **182 passed + 68 subtests**, public-API adversarial matrix **15/15** и future-row matrix **6/6**, все exit 0;
- exact-head GitHub Actions: **PASS** — [run 37921716308](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37921716308), [offline-safety job 113790958532](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37921716308/job/113790958532), [payment-regression job 113790958895](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37921716308/job/113790958895), все steps success.

Все шесть committed payment bundles остаются старше допустимого порога и требуют source-by-source refresh из удержанных первичных snapshots; это исправление делает trade-remedy расчёт fail-closed, но не обновляет и не переутверждает источники. Полный #244 product/legal/source-completeness **NOT PASS**; полный #245 также **NOT PASS**. Protected merge, production/DB writes, enforcement flags, secrets/permissions, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` неизменён и не отправлен.

Следующий шаг — продолжить текущий #245 source/applicability block и подготовить canonical disposable NTM v2 fixtures для воспроизводимых broad/full-sync проверок; неподтверждённую применимость сохранять как manual review.

## 0z. #245 — HTML fallback ФСА больше не принимает неоднозначную таблицу за действующую запись

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `d5dd222f108399eac82a5d8001d7615a00953d08`, tree `9a81a7381d327061050a4616aba3f7988e0bc210`, parent `ad111df595f323b25e9cef1e7e250a6df1a0bad9`; base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

Воспроизведён source/identity defect HTML fallback ФСА: таблица с любой строкой могла стать `VALID` без сопоставления номера, статуса и срока действия. Теперь разбираются все result tables; `VALID` требует точного canonical identity, явного active status и разбираемой непросроченной даты. Пропущенные колонки/ячейки, rowspan/colspan, неоднозначные заголовки, пустые номера, неизвестные даты и конфликтующие дубликаты остаются `UNKNOWN`/manual review; revoked/expired evidence остаётся `NOT_FOUND`. Query/search/organization metadata не считается реестровой записью, но неоднозначная registry-looking таблица блокирует положительный вывод. Справочная фраза «не найдено» не перекрывает точную полную запись и не удаляет evidence. Applicability/advisory/enforcement и правовая интерпретация не расширялись.

Три промежуточных candidate независимый A5 отклонил: из-за missing expiry/rowspan/multiple-table false `VALID`, затем из-за ambiguous header/organization/unparseable expiry, затем из-за ошибочного downgrade корректной active записи служебной metadata-таблицей. Они не публиковались.

Проверки exact final tree:
- author focused FSA/opendata/permits: **75 passed, 1 skipped, 6 subtests**, exit 0; `compileall` и `git diff --check` — exit 0;
- author broad #245 backend slice: **959 passed, 11 skipped, 38 subtests**, exit 0;
- независимый A5 `/root/a5_pravo_probe`: **PASS exact reviewed tree**; adversarial HTML matrix **28/28**, metadata + exact-active **3/3**, focused **20 passed +6 subtests**, related disposable-DB **71 passed, 1 skipped +6 subtests**, все exit 0; import-order probes и diff-check exit 0;
- connector remote tree побайтово совпадает с reviewed local tree; PR перечитан на exact remote HEAD;
- exact-head GitHub Actions: **PENDING_NO_RUN_OBSERVED** для `d5dd222f108399eac82a5d8001d7615a00953d08`.

Полный #245 product/legal/source-completeness **NOT PASS**. NTM full-sync audit всё ещё требует законно доступного populated synchronized snapshot. Protected merge, production/DB writes, enforcement flags, secrets/permissions, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` неизменён и не отправлен.

Следующий шаг — повторно проверить exact-head CI, затем продолжить следующий воспроизводимый #245 source/applicability defect, сохраняя неподтверждённые результаты в manual review.

## 0y. #245 — FSA JSON API больше не принимает чужую или неподтверждённую запись за действующую

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `ad111df595f323b25e9cef1e7e250a6df1a0bad9`, tree `961b8d8c1995900284d54f5143f7ae1db7633b47`, parent `af1f6301f871b5156fabe774505aa9184e452217`; base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

Воспроизведён source/identity defect: любой непустой JSON-ответ API ФСА становился `VALID`, даже если API вернул другой номер, аннулированную/неизвестную запись либо только положительный счётчик без строки. Теперь `VALID` требует точного canonical match по специальному полю номера сертификата/декларации и явного active status. Generic `number` не считается доказательством личности записи, потому что может быть внутренним ID API. Все точные дубликаты агрегируются независимо от порядка: revoked/expired не позволяют `VALID`, active+unknown остаётся `UNKNOWN`. `NOT_FOUND` для несовпадения допустим только когда каждая строка имеет доверенное поле номера; смешанные/ненумерованные ответы и positive count без строк остаются `UNKNOWN` для manual review. Evidence номера, статуса, count и ТН ВЭД сохраняется; applicability/advisory/enforcement и правовая интерпретация не расширялись.

Два промежуточных local candidate независимый A5 отклонил: первый был order-dependent на duplicate active/revoked и ошибочно считал mixed numbered/unnumbered ответ доказанным отсутствием; второй ещё доверял generic string `number` как номеру сертификата. Эти варианты не публиковались.

Проверки exact final tree:
- author focused FSA/opendata/permits: **58 passed, 1 skipped**, exit 0; `compileall` и `git diff --check` — exit 0;
- author broad #245 backend slice: **942 passed, 11 skipped, 32 subtests**, exit 0;
- независимый A5 `/root/a5_pravo_probe`: **PASS exact candidate**; adversarial identity/status matrix exit 0; focused **17 passed**; related FSA/opendata/permits **51 passed, 1 skipped**, exit 0; оба порядка imports exit 0, circular import отсутствует; false `VALID` не найден;
- connector создал remote tree, побайтово совпадающий с reviewed local tree; PR после публикации перечитан и показывает exact remote HEAD;
- exact-head GitHub Actions: **PENDING_NO_RUN_OBSERVED** для `ad111df595f323b25e9cef1e7e250a6df1a0bad9`; workflow runs пусты при проверке.

Полный #245 product/legal/source-completeness **NOT PASS**. NTM full-sync audit всё ещё требует законно доступного populated synchronized snapshot. Protected merge, production/DB writes, enforcement flags, secrets/permissions, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` неизменён и не отправлен.

Следующий шаг — повторно проверить exact-head CI, затем исследовать HTML-table fallback ФСА и следующий #245 source/applicability defect; неподтверждённые результаты оставлять `UNKNOWN`, не расширять definite rules.

## 0x. #245 — локальный FSA opendata статус fail-closed

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `af1f6301f871b5156fabe774505aa9184e452217`, tree `fd3d214ce25a01286f3110e2a42849f4ff31f7a6`, parent `758797f56b00ceb5fd78362a0dce80683dc1e96d`; base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

Воспроизведён source/applicability defect: любая непустая неизвестная строка статуса локальной FSA opendata записи (например, «Ожидает проверки» или «Архив») ошибочно становилась `VALID`. Исправление fail-closed сохраняет номер, держателя и исходный status как evidence: только явный active/valid считается `VALID`, inactive/revoked/expired — `NOT_FOUND`, неизвестный/архивный/неподтверждённый — `UNKNOWN`. Русские и английские отрицания проверяются раньше положительных слов; `invalid`, `unregistered`, `validated`, `reactivated` не дают substring false positive. Lookup scope, SQL matching, NTM applicability, advisory/enforcement и правовая интерпретация не расширялись.

Первый local candidate `98e92e236ff8f0a49a46fab997506f2a882231e9` независимый A5 отклонил: «Не зарегистрирован», «незарегистрирован» и `not registered` ещё попадали в positive marker. Этот вариант не публиковался. Финальный reviewed local tree опубликован как один remote commit и побайтово совпадает.

Проверки exact final tree:
- author focused FSA/permits: **34 passed, 1 skipped**, exit 0; explicit negation matrix, `py_compile`, `git diff --check` — exit 0;
- author broad #245 backend slice: **925 passed, 11 skipped, 32 subtests**, exit 0;
- независимый A5 `/root/a5_pravo_probe`: **PASS exact remote HEAD**; 23-case adversarial matrix exit 0; focused **20 passed**, related FSA **25 passed**, broader FSA/permits **34 passed, 1 skipped**, exit 0; unknown/archive evidence retained, active valid, inactive/expired fail closed; local reviewed tree и remote tree byte-identical;
- exact-head GitHub Actions: **PENDING_NO_RUN_OBSERVED** для `af1f6301f871b5156fabe774505aa9184e452217`; workflow runs пусты при повторной проверке.

Tracked `customs-clear/backend/customs.db.backup_before_pdf_import` проверен как возможный snapshot, но в нём отсутствуют таблицы `non_tariff_measures`/NTM v2; он не пригоден для full-sync audit. Полный #245 product/legal/source-completeness **NOT PASS**. Protected merge, production/DB writes, enforcement flags, secrets/permissions, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` неизменён и не отправлен.

Следующий шаг — повторно проверить exact-head CI; затем выполнить NTM full-sync audit на lawful populated synchronized snapshot, если он появится, либо продолжить следующий воспроизводимый #245 source/applicability defect без расширения definite rules.

## 0w. #245 — статус СГР fail-closed: неподтверждённая запись остаётся evidence, но не считается действующей

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `758797f56b00ceb5fd78362a0dce80683dc1e96d`, tree `b478bbdd8bc1552acda622d5f9c1453f8beb8148`, parent `afab417d008bc6e386091544ac6589884eb758e5`; base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

Воспроизведён product defect: fuzzy-match локального реестра СГР мог вернуть строку со статусом `Аннулировано` и одновременно рекомендовать «Найдено действующее СГР». Исправлено fail-closed без удаления evidence: номер и исходный статус сохраняются, но revoked/negated/unknown возвращают «Найдено совпадение, статус требует проверки» и явное требование сверки в официальном реестре. Положительные английские статусы распознаются только как отдельные слова, поэтому `invalid` и `unregistered` не становятся active по подстроке. Действующие exact/fuzzy сценарии сохранены. HS activation, SQL matching, applicability, advisory/enforcement и правовая интерпретация не расширялись.

Проверки exact remote tree:
- author focused: **19 passed**, exit 0; adversarial status matrix, `git diff --check`, `py_compile` — exit 0;
- author broad #245 backend slice: **917 passed, 11 skipped, 32 subtests**, exit 0;
- независимый A5 `/root/a5_pravo_probe`: первые два exact local commits отклонены из-за `Не действует/not active` и `invalid/unregistered`; финальный exact remote HEAD **PASS**. Focused **19 passed**, related fresh disposable SGR/NTM/normative **154 passed**, lookup/status matrices exit 0; remote tree побайтово совпадает с reviewed tree;
- exact-head GitHub Actions: **PASS** — [run 37897546292](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37897546292), job `offline-safety` `113712246088`, все steps success.

NTM full-sync audit по-прежнему требует законно доступного populated synchronized snapshot. Полный #245 product/legal/source-completeness **NOT PASS**. Protected merge, production/DB writes, enforcement flags, secrets/permissions, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` неизменён и не отправлен.

Следующий шаг — выполнить NTM full-sync audit на lawful populated synchronized snapshot, если он доступен, либо продолжить следующий воспроизводимый #245 source/applicability defect без расширения definite rules.

## 0v. #245 — официальный PRAVO probe больше не принимает synthetic/reference-only как покрытие

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `afab417d008bc6e386091544ac6589884eb758e5`, tree `a1c7cc38118d879135e2eba9ed1aa79f4c2e0b1e`, parent `ec4c3fc67fbb7ca90ec28e2ee89ff232711b2eac`; base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

Воспроизведён source-completeness дефект: одна `PRAVO_GOV` строка со статусом `reference_only` и quality `synthetic_seed` давала общий regulatory probe `0`, но отдельный `regulatory_documents_pravo` probe ошибочно возвращал `1`. Из-за этого synthetic/reference-only данные могли скрыть реальный gap официального правового источника.

Исправление: product retrieval, общий regulatory probe и PRAVO probe используют один fail-closed admission predicate. Допускаются active normal/NULL/verified; исключаются noise, synthetic_seed, reference_only и inactive. Applicability, advisory/enforcement, source status и правовая интерпретация не расширялись.

Проверки exact remote tree:
- author direct reproduction: общий probe `0`, PRAVO probe `1`, exit 0;
- author focused source/regulatory: **22 passed +3 subtests**, exit 0;
- author fixture-isolation с заранее существующей unrelated PRAVO строкой: **1 passed**, exit 0;
- author populated synthetic mass-seed: **5 057 документов / 5 481 mapping**, аудит **24 passed +3 subtests**, seed/tests exit 0;
- author broad #245 backend slice: **898 passed, 11 skipped, 32 subtests**, exit 0;
- независимый A5 `/root/a5_pravo_probe`: первый review отклонил абсолютный fixture-count; финальный exact remote HEAD **PASS** после baseline+delta. Focused **22 passed +3 subtests**, admission matrix exit 0, broader source/advisory/enforcement **80 passed +3 subtests**, exit 0; unrelated row сохранена;
- `git diff --check` и `py_compile`: exit 0;
- exact-head GitHub Actions: **PASS** — [run 37892321961](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37892321961), job `offline-safety` `113695775268`, все steps success.

Synthetic mass-seed dataset-аудит теперь выполнен на disposable БД; это не доказательство официальной полноты. NTM full-sync audit по-прежнему требует законно доступного populated synchronized snapshot. Полный #245 product/legal/source-completeness **NOT PASS**. Protected merge, production/DB writes, enforcement flags, secrets/permissions, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` неизменён и не отправлен.

Следующий шаг — выполнить NTM full-sync audit на lawful populated synchronized snapshot, если он доступен, либо продолжить следующий воспроизводимый #245 source/applicability defect без расширения definite rules.

## 0u. #245 — оставшиеся broad-suite fixtures изолированы без ослабления dataset-порогов

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `ec4c3fc67fbb7ca90ec28e2ee89ff232711b2eac`, tree `93571a51fdd03806693be76920163312edb24d68`, parent `b4fef2b9952a5b58f4bc2545523daf92a3bfd518`; полный двухкоммитный блок начинается от `4333061a162225f0efbbf0e971585a428ce78f82`, base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

Расширенный офлайн-срез сначала воспроизвёл **8 failures / 898 passed / 2 skipped / 32 subtests**: семь assertions массового regulatory seed ошибочно считали пустую disposable DB провалом импорта, а API measures ожидал существование кодов без собственных persisted fixtures. Теперь `test_regulatory_mass_seed.py` пропускается только при отсутствующем/пустом dataset; любой непустой partial snapshot исполняет исходные пороги. `test_tnved_measures_api.py` создаёт exact HsRate evidence для своих кодов и удаляет только ID, вставленные этим fixture-run.

Промежуточный HEAD `b4fef2b9952a5b58f4bc2545523daf92a3bfd518` не принят как финальный: author/A5 увидели, что cleanup по общему `source_revision` мог удалить чужие строки. Финальный HEAD хранит точные inserted IDs; A5 подтвердил, что case-code с тем же marker, official case-code и unrelated same-marker row сохраняются.

Проверки exact head/tree:
- author broad #245 backend slice: **897 passed, 11 skipped, 32 subtests**, exit 0;
- author focused: **3 passed, 9 skipped**, exit 0; отдельный pre-existing-row probe **2 passed**, exit 0;
- author one-row partial regulatory dataset: ожидаемый **1 failed**, exit 1; threshold 5000 не скрыт;
- независимый A5 `/root/a5_ntm_fallback`: **PASS exact remote HEAD**; empty DB **1 passed, 9 skipped**; partial dataset threshold exit 1; cleanup adversarial lifecycle PASS; relevant slice **111 passed, 9 skipped, 3 subtests**, exit 0;
- `git diff --check`: exit 0;
- exact-head GitHub Actions: **PASS** — [run 37886387124](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37886387124), job `offline-safety` `113677226792`, completed `2026-10-09T04:59:15Z`, все steps success.

Изменены только два test-файла; runtime/legal/source-admission/applicability/calculation semantics не менялись. Полный #245 product/legal/source-completeness **NOT PASS**. Mass-seed и full-sync coverage всё ещё требуют законно доступных заполненных synchronized snapshots. Protected merge, production/DB writes, enforcement flags, secrets/permissions, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` неизменён и не отправлен.

Следующий шаг — выполнить оба явных dataset-аудита на populated snapshots либо продолжить следующий воспроизводимый #245 source/applicability defect без расширения definite rules.

## 0t. #256 — exact-head GitHub Actions подтверждён

Для неизменённого HEAD `4333061a162225f0efbbf0e971585a428ce78f82` GitHub Actions run [37881930775](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37881930775) завершён успешно: job `offline-safety` и все его steps — `success` (completed `2026-10-09T04:01:43Z`). Review threads и submitted reviews отсутствуют. Это закрывает только прежний CI-polling blocker; полный #245 product/legal/source-completeness остаётся **NOT PASS**, а populated full-sync dataset audit всё ещё не выполнен. A6 `core-s1-6415f443120f-r9-g106` не отправлялся и не изменялся.

## 0s. #245 — broad fixtures изолированы, full-sync audit не скрывает partial snapshots

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `4333061a162225f0efbbf0e971585a428ce78f82`, tree `f14b0542d0fb8d730b4312c4db58b70b89e2674e`, parent `f1d3a5d451c8325a6c766bd6dce4f7368a2d790c`, base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

Разобраны оставшиеся 12 failures одинакового 20-file product slice. Шесть были зависимостью от произвольно заполненной developer DB: legacy NTM lookup теперь сам создаёт in-memory exact/prefix fixture; tree API сам создаёт и удаляет изолированную иерархию `99xx` и exact HsRate. Ещё девять assertions в `test_ntm_full_sync.py` явно являются аудитом заполненного full-sync snapshot: они пропускаются только при полностью пустой disposable DB, а любой непустой/частичный snapshot обязан исполнять исходные thresholds.

Промежуточный gate `count < 42000` независимый A5 отклонил: он делал порог строк недостижимым и скрывал regression на 41,999 строках. Этот вариант не принят. Финальный exact head использует только `count == 0`.

Проверки exact head/tree:
- author changed lookup/catalog: **25 passed**, exit 0;
- author exact 20-file backend/NTM slice: **322 passed, 10 skipped, 3 subtests**, exit 0;
- author 41,999-row probe: expected total-count failure, exit 1; audit не skipped;
- независимый A5 `/root/a5_ntm_fallback`: **PASS exact remote HEAD**; empty disposable **25 passed, 9 skipped**; сбалансированные 41,999 строк дали ровно **1 failed + 8 passed**; намеренно неправильные 42,000 строк дали **3 expected structural failures + 6 passed**;
- `git diff --check`: exit 0;
- exact-head GitHub Actions: **PENDING_NO_RUN_OBSERVED**; workflow run и commit status для `4333061a162225f0efbbf0e971585a428ce78f82` connector не показывает.

Изменения этого блока только в тестовых contracts/fixtures; legal/applicability/runtime calculation не менялись. Полный #245 product/legal/source-completeness **NOT PASS**. Девять full-sync assertions ещё нужно прогнать на законно доступном заполненном synchronized snapshot. Protected merge, production/DB writes, enforcement flags, secrets/permissions, destructive migration и внешний A6 не выполнялись. A6 `core-s1-6415f443120f-r9-g106` неизменён и не отправлен.

Следующий шаг — получить populated full-sync snapshot для явного dataset audit либо продолжить независимый #245 applicability/source block; не расширять definite rules без подтверждённых характеристик/источника.

## 0r. #245 — карточка отсутствующего кода требует exact persisted evidence

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `5717db24b7833d15182d1da231222559301b8e6f`, tree `97e493374c18b82f5472417bfad74716ec1cbee7`, parent `04979b50bf2926751dad92468e9beb4e2fa7b539`, base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

Воспроизведён product/API defect: произвольный отсутствующий 10-значный код получал успешную карточку только из-за соседнего названия или вычисляемых NTM. Теперь fallback закрыт по умолчанию: код подтверждает только точная сохранённая строка `HsRate.hs_code` или `HsRate.hs_prefix`; широкая prefix-ставка, derived NTM и соседний `Commodity` сами по себе код не легитимизируют. Exact rate-only карточка берёт пошлину из этой строки; обычный exact `Commodity` path не менялся. Тест 8401300000 теперь сам создаёт rate fixture и не зависит от общей developer DB.

Проверки exact head/tree:
- author targeted fallback: **4 passed**, exit 0; related code-card/preliminary tests: **13 passed**, exit 0; compileall и `git diff --check` PASS;
- полный `test_tnved_catalog_api.py` на fresh SQLite: **18 passed, 5 failed**, exit 1; остались только прежние tree/full-catalog fixture ожидания;
- frontend: **18 passed**, typecheck и build PASS, exit 0;
- независимый A5 `/root/a5_ntm_fallback`: **PASS exact remote HEAD**; targeted **6 passed**, adversarial matrix PASS; одинаковый 20-file slice улучшился с parent **14 failed, 315 passed, 1 skipped** до candidate **12 failed, 319 passed, 1 skipped**, новых failures нет;
- exact-head GitHub Actions: **PENDING_NO_RUN_OBSERVED** для `5717db24b7833d15182d1da231222559301b8e6f`; workflow run и commit status connector не показывает.

Доступны полная exact-tree копия, Git, Python, Node и реальное выполнение команд. Публикация выполнена только в существующую draft-ветку под coordinator lease generation 129. Protected merge, production/DB writes, flags, secrets/permissions, destructive migration и A6 не выполнялись. A6 request `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся.

Остаётся: 12 broad-slice failures зависят от полного каталога/seed fixtures; full #245 product/legal/source-completeness **NOT PASS**; exact-head CI не подтверждён. Следующий шаг — сделать канонический disposable full-catalog fixture для tree/lookup tests либо изолировать эти dataset contracts, не расширяя legal/applicability semantics.

## 0q. #245 — synthetic legacy NTM seed исключён из product evidence

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `04979b50bf2926751dad92468e9beb4e2fa7b539`, tree `051d77ca61ef1d70e28beee46d28fa977ef8b75c`, parent `a1984575e6c58360847a54ee8618944dbfb996b0`, base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

Воспроизведён source-safety defect: `seed_ntm_full_sync.py` создавал шаблонные legacy NTM строки как `quality=normal`; runtime, RAG, invoice enrichment, SGR trigger, catalog/completeness и legacy-to-v2 import могли признать их product evidence. Новые строки теперь `synthetic_seed` и fail-closed исключаются всеми этими read paths. Ремонт старых строк ограничен deterministic representative commodity code, полным generated payload и только прежним `quality=normal`.

Первый repair-вариант независимый A5 отклонил: text-only match мог relabel курируемую строку на never-selected code. Этот вариант не принят; финальный exact head сохраняет такую `verified` строку и меняет только точную старую generated запись.

Проверки exact head/tree:
- author focused: `25 passed, 1 skipped, 3 subtests`, exit 0; compileall и `git diff --check` PASS;
- author fresh disposable SQLite + init/migrations + полный NTM v2 import + безопасный backend/NTM срез: `867 passed, 2 skipped, 32 subtests`, exit 0;
- frontend: `18 passed`, typecheck и build PASS, exit 0;
- независимый A5 `/root/a5_ntm_fallback`: **PASS exact remote HEAD**; exact repair/adversarial quality matrix exit 0; focused `25 passed, 1 skipped, 3 subtests`; 20-file candidate/parent comparison одинаков: `14 failed, 315 passed, 1 skipped`, failure-name diff пустой, failures fixture-bound;
- exact-head GitHub Actions: **PENDING_NO_RUN_OBSERVED** для `04979b50bf2926751dad92468e9beb4e2fa7b539`. Connector не показывает run; обычный local push завершился exit 128 (`could not read Username`). Credentials/UI workaround не предпринимался, CI PASS не заявляется.

Доступны полная exact-tree копия, Git, Python, Node и реальное выполнение команд. Публикация выполнена только в существующую draft-ветку под coordinator lease generation 128. Protected merge, production/DB writes, flags, secrets/permissions, destructive migration и A6 не выполнялись. A6 request `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся.

Остаётся: exact-head CI не подтверждён; полный #245 product/legal/source-completeness **NOT PASS**; production remediation уже развёрнутых legacy rows не выполнялся. Следующий шаг — получить/проверить exact-head CI штатным авторизованным каналом, затем продолжить #245 applicability/source failures без расширения definite rules.

## 0p. #245 — permit job detail больше не перехватывается legacy verify route

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `9d4ffb38d7479f6f9a6983728612e01e0c28018e`, tree `824f644beec6a8ef219f737aede05a634fe9297f`, parent `9a8493e196202fdb752abc79302c02f6b1303b79`, base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

Воспроизведён product/API defect: ранний legacy catch-all `GET /api/permits/verify/{number:path}` перехватывал `GET /api/permits/verify/jobs/{job_id}`. Вместо job detail и ownership policy API возвращал permit-verification payload `200`, передавал `jobs/{id}` во внешний permit check и не закрывался для non-owner/ownerless jobs. Catch-all перемещён после всех статических `/verify/*` маршрутов; production-style auth добавлен в устаревшие API-тесты; негативные ownership тесты теперь требуют `404` и отсутствие вызова `check_permits`.

Проверки exact head/tree:
- author focused на свежей disposable SQLite: `python -m pytest -q -p no:cacheprovider tests/test_permits_normalize_and_api.py tests/test_permits_verify_jobs_ownership.py --tb=short` — **13 passed, 1 skipped**, exit 0;
- author широкий permit/auth/API/NTM срез после `init_db()` и полного NTM v2 import: **308 passed, 1 skipped**, exit 0; frontend: **18 passed**, typecheck/build PASS, exit 0; compileall и `git diff --check` PASS;
- независимый A5 `/root/a5_ntm_fallback`: **PASS exact remote HEAD**; focused **20 passed, 1 skipped**, extended **222 passed, 1 skipped**, exit 0; owner `200`, non-owner/ownerless `404`, admin foreign/ownerless `200`, anonymous protected endpoints `401`, негативные job detail/export без внешнего permit check, legacy path со slash сохранён;
- exact-head CI: **PASS** — [run 37872398938](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37872398938), job `offline-safety` `113633224151`, success на точном HEAD `9d4ffb38d7479f6f9a6983728612e01e0c28018e`.

Полный `test_api_integration.py` остаётся диагностически **NOT PASS**: 8 calculator failures / 246 passed / 1 skipped; независимый A5 воспроизвёл те же 8 failures на parent, поэтому это не регрессия текущего diff. Live FSA намеренно не вызывался. Порядок регистрации остаётся важным инвариантом: будущие статические `/verify/*` маршруты должны быть выше legacy catch-all.

Доступны полная exact-tree копия, Git, Python, Node и реальное выполнение команд. Публикация выполнена только в существующую draft-ветку под coordinator lease generation 127. Protected merge, production/DB writes, flags, secrets/permissions, destructive migration и A6 не выполнялись. A6 request `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся.

Остаётся: full #245 product/legal/source-completeness **NOT PASS**; PostgreSQL, payment/calculator fixtures и безопасный remediation уже развёрнутых synthetic rows не закрыты. Следующий шаг — продолжить #245 backend/frontend applicability и source failures без расширения definite rules.

## 0o. #245 — synthetic regulatory seed больше не считается официальным evidence

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `9a8493e196202fdb752abc79302c02f6b1303b79`, tree `19d2f245e7b851b98347fb20a5852fd6b03b5c6f`, parent `5a535d00056c5c46c2ca614eaa3194325647fe1b`, base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

Воспроизведён source-safety defect: `seed_regulatory_mass` создавал 5,057 шаблонных документов с построенными URL как `active/verified`, после чего они выдавались пользователю и считались в official-source completeness. Исправлено fail-closed: synthetic rows теперь `reference_only/synthetic_seed`, их mappings — `reference`, confidence 0, unapproved; runtime evidence и completeness принимают только active non-noise/non-synthetic документы. Повторный явный запуск seed ремонтирует ранее созданные небезопасные labels. Реальные `active/verified` и `active/quality=NULL` документы продолжают выдаваться и учитываться.

Проверки exact head/tree:
- author targeted regulatory safety: **21 passed +3 subtests**, exit 0; свежий полный mass seed: **5,057 documents / 5,481 mappings**, **10 passed**, surfaced 0, admitted completeness 0, exit 0;
- author fresh disposable SQLite + `init_db()` + полный NTM v2 import + широкий канонический NTM/regulatory срез: **808 passed, 1 skipped, 3 subtests**, exit 0; frontend: **18 passed**, typecheck/build PASS, exit 0;
- независимый A5 `/root/a5_ntm_fallback`: **PASS exact remote HEAD**; targeted **258 passed +3 subtests**, mass-seed **9 passed**, fresh-seed, forced legacy repair и adversarial real-document preservation PASS, exit 0;
- exact-head CI: **PASS** — [run 37867410107](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37867410107), job `offline-safety` `113617338713`, success на точном HEAD `9a8493e196202fdb752abc79302c02f6b1303b79`;
- `git diff --check` и compile checks PASS; remote tree совпадает с проверенным tree.

Доступны полная exact-tree копия, Git, Python, Node и реальное выполнение команд. Публикация выполнена только в существующую draft-ветку под coordinator lease generation 126. Protected merge, production/DB writes, flags, secrets/permissions, destructive migration и A6 не выполнялись. A6 request `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся.

Остаётся: full #245 product/legal/source-completeness **NOT PASS**. Уже развёрнутые legacy synthetic rows требуют отдельного безопасного remediation/reseed плана; production backfill не выполнялся. PostgreSQL и оставшиеся dataset-dependent legacy tests не закрыты. Следующий шаг — продолжить #245 applicability/source triage без расширения definite rules и без признания synthetic данных нормативным источником.

## 0n. #245 — startup schema-check больше не отключает fail-closed NTM diagnostics

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `5a535d00056c5c46c2ca614eaa3194325647fe1b`, tree `768e5143cae4f1d168d90acc1361188524543f9c`, parent `0650526aed724322fbe0842f1a8e22d91dfb6b90`, base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

Расширенный канонический NTM/normative/regulatory прогон воспроизвёл order-dependent observability defect: in-process `init_db()`/Alembic `fileConfig` отключал уже созданные application loggers, поэтому предупреждения `NTM_V2_TR_TS` и `NTM_V2_LAYERS` пропадали после schema-check. `alembic/env.py` теперь вызывает `fileConfig(..., disable_existing_loggers=False)`. Applicability, advisory/enforcement, схема и данные не менялись.

Проверки exact head/tree:
- author fresh disposable SQLite + `init_db()` + полный NTM v2 import + 40 backend modules: **819 passed, 1 skipped, 3 subtests**, exit 0; focused startup/warning sequence **3 passed**, exit 0;
- независимый A5 `/root/a5_ntm_fallback`: **PASS exact remote HEAD**; parent доказан как `target_disabled=True/sentinel_captured=False`, candidate как `target_disabled=False/sentinel_captured=True`; Alembic logger остался INFO и выдал 59 migration lines; independent regression **269 passed**, exact-remote focused **1 passed**;
- remote tree byte-identical прошедшему A5 tree; только `customs-clear/backend/alembic/env.py` и `tests/test_ntm_v2_pipeline_flag.py` изменены;
- exact-head CI: **PENDING_NO_RUN_OBSERVED** для `5a535d00056c5c46c2ca614eaa3194325647fe1b`; readiness/полный #245 PASS не заявляются.

Код и команды доступны в полной exact-tree копии; публикация выполнена только в существующую draft-ветку под coordinator lease generation 125. Protected merge, production/DB writes, flags, secrets/permissions, destructive migration и A6 не выполнялись. A6 request `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся.

Остаётся: дождаться exact-head CI; затем продолжить #245 backend/frontend applicability/source failures. Дополнительные definite rules без подтверждённой подкатегории/характеристик не добавлять; юридическая и источниковая полнота **NOT PASS**.

## 0m. #245 — канонический NTM v2 pipeline: исправлены definite over-claim каталога

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `0650526aed724322fbe0842f1a8e22d91dfb6b90`, tree `dad9ba0b58ab7b1815182a2bfc25a19ca033bb8b`, parent `4fdb291b254c8ebff4b9fa65e52cbd7f1ce13126`, base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

На свежей disposable SQLite штатные `init_db()` и `scripts/import_tr_ts_catalog_to_ntm_v2.py` отделили отсутствие fixture от реальных применимостных дефектов. Исправлено: игрушки `9503` больше не получают лишнюю ДС по ТР ТС 008 (только СС); обычная мебель `9401`–`9403` больше не получает ТР ТС 016 о газовых аппаратах; смартфон переведён на текущий код `851713` и definite 020/037 сужен до этого подзаголовка. ТР ТС 004 без подтверждённого напряжения не ставится. Части `851771`/`851779` не попадают в mandatory/document-check; широкий fallback `8517` остаётся только `possible`/manual review. Marking scope не расширен.

Проверки exact head/tree:
- author: `DATABASE_URL=sqlite:////tmp/... python -m pytest -q` для 15 NTM/backend suites после `init_db` и полного NTM v2 import — **504 passed**, exit 0;
- независимый A5 `/root/a5_ntm_fallback`: **PASS exact remote HEAD**; свежая БД/import и `267 passed`, затем exact-remote smoke `104 passed`; промежуточные over-claim 004 и широкого 020 были отклонены A5 и не опубликованы;
- remote tree совпадает с прошедшим A5 tree; локальный `git diff --exit-code` — exit 0;
- exact-head CI: **PENDING_NO_RUN_OBSERVED** для `0650526aed724322fbe0842f1a8e22d91dfb6b90`; readiness/полный #245 PASS не заявляются.

Код и команды доступны в полной exact-tree копии; публикация выполнена только в существующую draft-ветку под coordinator lease generation 124. Protected merge, production/DB writes, flags, secrets/permissions, destructive migration и A6 не выполнялись. A6 request `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся.

Остаётся: дождаться exact-head CI; затем продолжить #245 по следующим backend/frontend applicability/source failures. Дополнительные аппараты 8517 можно добавлять только на подтверждённой подкатегории/характеристиках; юридическая и источниковая полнота **NOT PASS**.

## 0l. #245 — TR TS noise classifier сохраняет product fallback без юридического over-claim

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `4fdb291b254c8ebff4b9fa65e52cbd7f1ce13126`, tree `58ea5b5f13c21ec505ed1b4a7f198aa0842dee02`, base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

Воспроизведён старый продуктовый дефект: `8517120000 + tr_ts` ошибочно удалялся как crawler noise, потому что классификатор читал только неполный legacy-каталог и игнорировал уже используемый product fallback. Общий fallback вынесен в отдельный DB-free модуль и используется для консервативного сохранения generic `tr_ts`; конкретный регламент не назначается. Граница `marking` не расширена. Первый вариант независимый A5 отклонил из-за ORM/DB import dependency; он не публиковался. Исправленный вариант не загружает `app.db`, ORM или SQLAlchemy.

Проверки exact head/tree:
- author #245/backend slice на disposable SQLite: `367 passed +44 subtests`, exit 0;
- отдельный focused: `115 passed`, compileall и diff-check PASS;
- независимый A5 `/root/a5_ntm_fallback`: **PASS exact remote HEAD**; `83 passed` и совместно с HS matching `99 passed`, DB/model-blocked import probe PASS, exhaustive `marking` parent/candidate hash identical;
- exact-head CI: **PASS** — [run 37851053652](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37851053652), job `offline-safety` [113563946657](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37851053652/job/113563946657), завершён успешно на точном HEAD `4fdb291b254c8ebff4b9fa65e52cbd7f1ce13126`; это инфраструктурная проверка, не полный DB-backed NTM acceptance.

Диагностический широкий NTM прогон на пустой SQLite не является PASS: pipeline требует инициализированных `ntm_applicability_rules_v2`/`ntm_measures_v2` и импортированных datasets. Это fixture/environment gap, который ещё надо закрыть и затем повторить полный backend/frontend блок. Доступ к полной копии, Git/Python/pytest и законная публикация draft-ветки подтверждены. Protected merge, production/DB writes, flags, secrets/permissions, destructive migration и A6 не выполнялись. A6 request `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся.

Следующий шаг: инициализировать канонические disposable NTM v2 fixtures и разобрать реальные pipeline/applicability failures отдельно от отсутствующих данных; не расширять legal/applicability semantics и не запускать A6. Полный #245, юридическая и источниковая полнота **NOT PASS**.

## 0k. Оставшиеся payment-fixtures из широкого среза закрыты и закреплены в CI

**Текущий checkpoint #255:** [draft PR #255](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/255), `agent/core-payment-regressions-v1` @ `6f1f5522cfe304030d1be474e3f074e85a739835`, tree `a7f640b4fb42320bb77f2c0bd70017a40b367075`, base #244 неизменён `14e0ee8f034d94ffc5831d87e076f4d693a5a524`.

Закрыт следующий воспроизведённый класс fixture/broad-suite failures: ROP importer больше не поглощает аргументы pytest; duty backfill сам поднимает pure-specific fixture и явный EUR/RUB test FX; normative bundle и VAT/PP908 проверки используют идемпотентный disposable seed и сохраняют fail-closed `REVIEW_REQUIRED`/withheld totals. Четыре фиктивных ETT-кода из старого snapshot отфильтровываются единым `is_ett_test_hs()` и покрыты двойным вызовом seed. Exact-head payment CI теперь включает `test_duty_rules_backfill.py`, `test_normative_bundle.py`, `test_rop_calculator.py`, `test_vat_preferences_audit161.py`; bootstrap использует тот же проверенный helper, а не собственный небезопасный загрузчик.

Проверки exact tree:
- author explicit offline-safe payment broad slice: `470 passed +370 subtests`, exit 0;
- author exact workflow-equivalent после исправления bootstrap: `265 passed +23 subtests`, exit 0; focused forward/reverse-order: по `45 passed`, exit 0;
- независимый A5 `/root/a5_special_scope`: **PASS** exact tree; `265 passed +23 subtests`, exit 0; четыре запрещённых fake-кода отсутствуют, permissions/actions не ослаблены;
- exact-head GitHub Actions [run 37844312369](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37844312369): `offline-safety` **SUCCESS** (job 113541234912), `payment-regression` **SUCCESS** (job 113541235424);
- `git diff --check`: PASS.

Доступ к коду подтверждён полной exact-tree копией; Git/Python/pytest и команды реально выполнялись. Законная публикация сделана только в существующую draft-ветку через connector под lease generation 121. Неограниченный root `pytest -q` не повторялся после platform security stop на unrelated outbound `api.proxyapi.ru`; поэтому full-suite PASS не заявляется. Checkpoint записывается CAS и должен быть перечитан. Protected merge, production/DB writes, flags, secrets/permissions, destructive migration и A6 не выполнялись. A6 request `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся.

Остаётся: этот ограниченный payment-broad блок PASS, но полный #244 и юридическая/источниковая полнота **NOT PASS**; шесть committed payment bundles stale. Следующий технический шаг — перейти к #245: воспроизвести текущие backend/frontend NTM failures, начиная с применимости требований по коду/характеристикам/источнику и без выдумывания source completeness.

## 0j. Самодостаточные payment-fixtures и fail-closed broad-suite

**Текущий checkpoint #255:** [draft PR #255](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/255), `agent/core-payment-regressions-v1` @ `26fac3bf5585284afac77734f7888a2fac64e991`, tree `6c7ce0fcdfe726c8803696f4f0fad428874933bd`, base #244 неизменён `14e0ee8f034d94ffc5831d87e076f4d693a5a524`.

Устранён воспроизведённый fixture-класс broad-suite падений: calculator/leaf/recycling/tariff-preference тесты больше не зависят от заранее наполненной чужой `customs.db`. Добавлен идемпотентный disposable test seed для восьми точных кодов и штатный bootstrap существующих test-справочников. Test-only строки остаются явно недоверенными: автоматические результаты обязаны быть `REVIEW_REQUIRED`, финальные VAT/total withheld, provisional-арифметика сохраняется только для диагностики. Четыре исправленных модуля добавлены в exact-head payment-regression CI.

Проверки exact tree:
- author disposable workflow-equivalent: `238 passed +23 subtests`, exit 0; изменённые модули `74 passed`, повторный прогон на общей БД `74 passed`, exit 0;
- orchestration verifier: `120 passed`; snapshot `4 passed`, exit 0;
- независимый A5 `/root/a5_special_scope`: **PASS**; свежий workflow-equivalent `238 passed +23 subtests`, normal/repeat/reverse-order по `74 passed`; все восемь fixture-кодов сохранили `REVIEW_REQUIRED`, `total_payable=null`, `withheld` и `hs_rate_source_binding_unverified`;
- exact-head GitHub Actions [run 37836111451](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37836111451): `offline-safety` **SUCCESS** (job 113513449756), `payment-regression` **SUCCESS** (job 113513450175);
- `git diff --check`: PASS.

Доступ к коду подтверждён полным checkout точного tree; Git/Python/pytest реально выполнялись. Законная публикация сделана только в существующую draft-ветку под lease generation 120. Checkpoint записывается CAS и будет перечитан. Protected merge, production/DB writes, flags, secrets/permissions, destructive migration и A6 не выполнялись. A6 request `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся.

Остаётся: это bounded fixture-cleanup, а не полный broad-suite или #244 PASS. Другие payment/source fixtures и актуальность шести committed bundles ещё требуют разбор; юридическая/источниковая полнота не подтверждена. Следующий технический шаг — продолжить triage оставшихся broad-suite fixture failures без ослабления fail-closed, затем перейти к #245.

## 0i. PP908 — типизированный признак для 30 неоднозначных animal-кодов

**Текущий checkpoint #255:** [draft PR #255](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/255), `agent/core-payment-regressions-v1` @ `ba8097d18d3512479df21cd9c15b768f3d835c93`, tree `648865448fa7576163fbc2549a5f34b39627d22d`, base #244 неизменён `14e0ee8f034d94ffc5831d87e076f4d693a5a524`.

Для 30 листьев `0102`–`0105`, где код не доказывает племенное назначение, добавлен типизированный вход `breeding | non_breeding | unknown` в Calculator, Payment Quote, Smart Payments UI и compare. `unknown` удерживает НДС и итог для ручной проверки; явно подтверждённое документами `non_breeding` выбирает 10%, `breeding` — 22%. Свободный текст не интерпретируется. Конфликт входа с 5 точными убойными или 10 точными племенными кодами также fail-closed. Отсутствующая/повреждённая карта удерживает результат. Compare теперь передаёт новый признак и ранее объявленные `net_weight_kg`, `extra_quantity`, `apply_reduced_vat` во все сценарии.

Проверки exact tree:
- author disposable CI-equivalent: `176 passed +23 subtests`, exit 0; focused `79 passed +14 subtests`, exit 0;
- frontend `npm run typecheck` и `npm run build`: PASS, exit 0;
- первый независимый A5 обнаружил потерю признака в compare; исправление вошло до публикации;
- финальный независимый A5 `/root/a5_special_scope`: **PASS** exact tree; все 30 исходов unknown/non-breeding/breeding, 15 конфликтов, 45 mapping-missing симуляций и API quote/compute/compare проверены;
- exact-head GitHub Actions [run 37829007811](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37829007811): `offline-safety` **SUCCESS** (job 113489177769), `payment-regression` **SUCCESS** (job 113489178130);
- `git diff --check`: PASS.

Доступ к коду и командам подтверждён: полный checkout, Git/Python/pytest/Node доступны; публикация выполнена в существующую draft-ветку через connector под lease generation 119. Checkpoint сохраняется в state и должен быть перечитан после CAS. Protected merge, production/DB writes, flags, secrets/permissions, destructive migration и A6 не выполнялись. A6 request `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся.

Остаётся: typed-признак является входным фактом декларанта и требует подтверждающих документов; source freshness и fixture/broad-suite failures не закрыты; полный #244 и юридическая/источниковая полнота **не PASS**. Следующий технический шаг — разобрать fixture/broad-suite failures, затем продолжить #245.

## 0h. PP908 — retained map живых животных без over-claim

**Текущий checkpoint #255:** [draft PR #255](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/255), `agent/core-payment-regressions-v1` @ `5092e99642387233ebbed6ada2fef8687b629a7a`, tree `392388557d2f7cbe8724de4a12bb45a0a998dd28`, base #244 неизменён `14e0ee8f034d94ffc5831d87e076f4d693a5a524`.

Добавлена сохранённая карта 45 десятизначных листьев `0102`–`0105`, сверенная с официальным PDF группы 01 ЕТТ ЕАЭС (`sha256 7942d2176d8c728dde35f55cc4871ba230fdef721b30d5c191fd444cd55537c9`, 168285 bytes). Автоматические 10% допускаются только для пяти кодов, прямо названных «убойными»; десять племенных кодов исключены; остальные 30 кодов остаются `product_characteristic_required`. Слово «прочие» не используется как доказательство пищевого/неплеменного назначения. Широкие `0102`/`0103`/`0104`/`0105` по-прежнему fail-closed.

Проверки exact tree:
- author disposable SQLite CI-equivalent slice: `157 passed +21 subtests`, exit 0;
- read-only audit: 119/119 безопасных targets покрыты, но ожидаемый exit 1 — `MANUAL_REVIEW_REQUIRED: product_characteristic_required`, auto 5 / breeding excluded 10 / characteristic-required 30;
- независимый A5 `/root/a5_special_scope`: **PASS**; `60 passed +12 subtests`, 45 листьев образуют точное непересекающееся разбиение, stale broad rows не дали ни одной утечки для 40 blocked-кодов;
- exact-head GitHub Actions [run 37822334976](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37822334976): `offline-safety` **SUCCESS** (job 113466271370), `payment-regression` **SUCCESS** (job 113466271764);
- `git diff --check`: PASS.

Полный #244, юридическая полнота и актуальность всех payment sources **не PASS**. A6 request `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся; merge/production/flags/secrets/permissions/destructive действия не выполнялись.

Следующий безопасный шаг: добавить в quote/input проверяемые характеристики товара для 30 неоднозначных animal-кодов, сохраняя withheld totals и manual review при отсутствии/неподтверждённой характеристике; затем продолжить source freshness и #245.

## 0g. PP908 VAT scope — broad over-claim закрыт, animal map остаётся fail-closed

**Текущий checkpoint #255:** [draft PR #255](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/255), `agent/core-payment-regressions-v1` @ `02573a121e3de7ccfab079eb436bce5e85917fc9`, tree `428752c8f8e61c40f239c91e9f6237a818672c3a`, base #244 неизменён `14e0ee8f034d94ffc5831d87e076f4d693a5a524`.

Устранён подтверждённый legal/product over-claim: широкие 10%-преференции `0102`, `0103`, `0104`, `0105` и `8715` удалены из committed seed и отфильтровываются на чтении даже при наличии старых строк в БД. Один и тот же fail-closed guard применяется к payment resolver и catalog UI. AI/reference trigger для колясок сужен до точного `8715001000`; sibling `8715009000` не наследует 10%. Для четырёх животноводческих заголовков точная карта включённых/исключённых десятизначных кодов не выдумывалась: audit сохраняет `MANUAL_REVIEW_REQUIRED: source_mapping_required`.

Проверки exact head/tree:
- author CI-equivalent disposable SQLite: `154 passed +21 subtests`, exit 0;
- audit: 114/114 безопасно суженных targets покрыты, но ожидаемый exit 1 из-за четырёх отсутствующих source mappings;
- первоначальный независимый A5 нашёл два обходных read path (catalog и AI reference); они исправлены до публикации;
- финальный независимый A5 `/root/a5_special_scope`: **PASS** exact remote HEAD/tree; stale broad rows дают 22%/пустой catalog/нет AI trigger, точный `8715001000` даёт 10%, sibling остаётся 22%;
- exact-head GitHub Actions [run 37814127865](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37814127865): `offline-safety` **SUCCESS** (job 113438242529), `payment-regression` **SUCCESS** (job 113438242162);
- `git diff --check`: PASS.

Среда разработки подтверждена: полный checkout exact parent/HEAD, Git/Python/pytest выполняются, draft branch опубликована законно под lease generation 117. Protected merge, production/DB write, flags, destructive migration, secrets/permissions и A6 не выполнялись. A6 request `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся.

Следующий безопасный шаг: получить retained primary-source mapping для включённых/исключённых десятизначных кодов `0102`–`0105`; до этого не снимать manual review. После этого продолжить source-by-source freshness и #245. Полный #244 и юридическая/источниковая полнота **не PASS**.

## 0f. PP908 fail-closed audit и payment regression CI

**Текущий checkpoint #255:** [draft PR #255](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/255), `agent/core-payment-regressions-v1` @ `942d0da1520081666ce3620708f1a692b80af0a2`, base #244 неизменён `14e0ee8f034d94ffc5831d87e076f4d693a5a524`.

PP908 audit больше не возвращает ложный `OK`: при VAT gaps или отсутствии representative code он возвращает `MANUAL_REVIEW_REQUIRED`, а CLI завершает работу с code 1. Герметичные тесты покрывают оба fail-closed случая, полный fixture и JSON CLI. Реальный committed fixture проверяется через миграции и committed snapshots; он явно фиксирует 118 проверенных headings, 113 covered и пять 22% gaps: `0102`, `0103`, `0104`, `0105`, `8715`. Это evidence о пробелах, не юридическое решение и не claim полноты.

Проверки exact head:
- GitHub Actions run [37809890335](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37809890335): `offline-safety` **SUCCESS**, `payment-regression` **SUCCESS**;
- payment regression выполняет полный `test_pp908_vat_coverage.py` и import-duty / bundle / payment-engine / special-duty slices;
- независимый A5 review exact head: **PASS**, предыдущие blockers (circular fixture assertion, отсутствие CLI exit test и DB bootstrap) закрыты;
- provider/network/A6 не вызывались; immutable request `core-s1-6415f443120f-r9-g106` не менялся.

Следующий безопасный шаг: source-backed разбор пяти PP908 gaps без broad heading over-claim; до этого audit обязан оставаться fail-closed. Merge, production, flags, secrets/permissions и destructive операции не выполнялись.

## 0e. Продолжение продуктового цикла — retained ETT source snapshot

**Новый текущий checkpoint #255:** [draft PR #255](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/255), `agent/core-payment-regressions-v1` @ `2751be626775964130af01874cded669427d452b`, tree `6de62435b74e55e195593248cb19dec491314ed1`, base #244 неизменён `14e0ee8f034d94ffc5831d87e076f4d693a5a524`.

ЕТТ import-duty теперь fail-closed без соседнего provenance manifest и сохранённого первичного snapshot. Manifest криптографически связывает точные bytes bundle и source snapshot, revision, официальный HTTPS EEC URL, число нормализованных строк, время захвата и transform id. Отсутствие/mismatch, traversal, symlink и future revision блокируют dry-run/apply; legal completeness не заявляется. Committed ETT bundle по-прежнему не содержит такого snapshot и теперь явно возвращает `manual_review_required: source_snapshot_manifest_missing`; данные не выдумывались и не обновлялись.

Проверки exact tree:
- author import-duty: **71 passed**, exit 0;
- author expanded source suite: **219 passed**, exit 0;
- independent A5 `/root/a5_special_scope`: **PASS**, **264 passed +73 subtests**, exit 0;
- independent adversarial traversal / external symlink / `ett:2099-01-01`: все blocked, `db_mutated=false`, HsRate/SourceStatus/SyncLog unchanged;
- compileall и `git diff --check`: PASS;
- exact-head GitHub CI: **ещё не наблюдался**.

Полный #244, юридическая полнота и актуальность источников **не PASS**. Следующий шаг — получить и проверить реальный immutable EEC snapshot/manifest для ЕТТ, затем интегрировать тот же контракт source-by-source для остальных payment domains; PP908 fixture и #245 остаются после этого. A6 `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся; merge/production/secrets/permissions не выполнялись.

## 0d. Продолжение продуктового цикла — fail-closed provenance builders

**Новый текущий checkpoint #255:** [draft PR #255](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/255), `agent/core-payment-regressions-v1` @ `fd48ed6d82cf0448e8e90469be8b0105eda1c7ee`, tree `e66ff8f046461b3115eb1b88a2d58109a74cdd62`, base #244 неизменён `14e0ee8f034d94ffc5831d87e076f4d693a5a524`.

Обнаружен и закрыт опасный путь source lineage: `build_official_bundles.py` копировал строки operational DB или placeholder-меры и маркировал их текущей датой как официальный revision; `build_vat_excise_official.py` аналогично мог маркировать broad 4-digit PP908 inference и константы акцизов 2025 как текущие. Оба legacy builder теперь fail-closed до DB/file access, import-time mkdir удалён. Для продолжения требуется retained immutable snapshot первичного источника с явным revision; изменение только даты запрещено.

Проверки exact tree:
- author guard: `python -m pytest -q tests/test_official_bundle_builder_safety.py` — **10 passed**, exit 0;
- оба CLI — ожидаемый exit 2, stdout пуст, DB/output не изменены;
- source suite с guard: **316 passed +76 subtests, 1 известный PP908 FAIL**, exit 1; `no_sample_code=118` остаётся видимым;
- независимый A5 `/root/a5_special_scope`: **PASS** exact tree; related suite **256 passed +73 subtests**, exit 0; AST/static и SHA256 bundle-файлов подтверждают отсутствие обхода/записи;
- compileall и `git diff --check`: PASS;
- exact-head GitHub CI: **ещё не наблюдался**.

Все 6 committed payment bundles остаются stale и не обновлялись. Полный #244, юридическая полнота и PP908 coverage **не PASS**. Следующий шаг — построить безопасный source-by-source importer из сохранённых первичных snapshots (сначала ЕТТ/акциз/меры), затем герметичный PP908 fixture. A6 `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся; merge/production/secrets/permissions не выполнялись.

## 0c. Продолжение продуктового цикла — source-refresh broad-suite

**Новый текущий checkpoint #255:** [draft PR #255](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/255), `agent/core-payment-regressions-v1` @ `f0e499e5e97ae83a63d9117e043420e52cb99da6`, tree `ec606fc15f76c73ad461f0ee84d8764b83f7644e`, base #244 неизменён `14e0ee8f034d94ffc5831d87e076f4d693a5a524`.

Восстановлен отсутствовавший `.github/workflows/scheduled-data-refresh.yml` на текущих интерфейсах: read-only `contents: read`, actions закреплены полными SHA, checkout credentials не сохраняются, production write/issue creation/secrets отсутствуют. Committed bundle freshness отделена от live CBR: CBR выполняется с `always()`, поэтому stale bundles не скрывают проверку источника валют.

Проверки exact tree:
- author payment/API/quote/invoice/Copilot/VED: `130 passed +358 subtests`, exit 0;
- source suite: `306 passed +76 subtests, 1 известный FAIL`, exit 1;
- workflow profile: `18 passed`, exit 0;
- независимый A5 `/root/a5_special_scope`: **PASS** на exact tree; чистый venv/pip-check PASS, bundle gate дал валидный JSON и ожидаемый exit 1 при `stale_count=6`, live CBR exit 0 / 54 валюты, safety assertions PASS;
- `git diff --check`: PASS;
- exact-head GitHub CI для этого HEAD пока не наблюдался; readiness не заявляется.

Незакрытые подтверждённые риски: все 6 committed payment bundles старше настроенного 90-дневного порога; PP908 audit на чистой инициализированной БД не находит 118 representative codes (`coverage_pct=0`) и не может доказать нормативное покрытие. Failure не skipped/xfail и не замаскирован фиктивным seed. Следующий шаг — источник-за-источником обновить/проверить payment bundles и сделать PP908 audit герметичным на подтверждённом полном TNVED/rates dataset без новой юридической интерпретации. Полный #244, юридическая полнота и exact-head CI **не PASS**.

A6 `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся. Merge/production/secrets/permissions не выполнялись.

## 0b. Продолжение продуктового цикла — special-duty scope

**Новый текущий checkpoint #255:** [draft PR #255](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/255), `agent/core-payment-regressions-v1` @ `fe7ce2da9cbcf776911f4b27a44ddb40e7e48cc9`, tree `17e1672b5ee98515a1e51e559961d5d7337be0e1`, base #244 неизменён `14e0ee8f034d94ffc5831d87e076f4d693a5a524`.

Исправлен воспроизведённый дефект: строки специальных пошлин с ограничением по изготовителю/экспортёру или описанию товара больше не применяются только по коду/стране. Для каждого непустого persisted scope требуется точное совпадение после NFKC, casefold и нормализации пробелов. Отсутствие, несовпадение, пунктуационное отличие или substring-only совпадение дают `special_duty_scope_unresolved`, нулевую сумму меры, `REVIEW_REQUIRED` и withheld totals. Fuzzy matching и новая правовая интерпретация не добавлены. Scope-поля передаются через Calculator, Payment Quote, Compliance, invoice, Copilot single/batch и VED Intel.

Проверки exact tree:
- author disposable SQLite: `130 passed, 358 subtests`, exit 0;
- точная команда: `python -m pytest tests/test_special_duties.py tests/test_payment_engine.py tests/test_payment_quote.py tests/test_payment_source_admission.py tests/test_automatic_duty_operand_validation.py tests/test_antidumping_fixed_unit_fail_closed.py tests/test_payment_fx_provenance_fail_closed.py tests/test_invoice_and_compare.py tests/test_assistant_copilot.py tests/test_orchestrator_batch_parallel.py tests/test_ved_intel_api.py -q --tb=short`;
- независимый A5 `/root/a5_special_scope`: **PASS**, `65 passed +21 subtests`, exit 0; отдельная adversarial matrix `8/8 PASS`, exit 0;
- exact-head CI: **PASS**, [run 37781116016 / job 113324157002](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37781116016/job/113324157002), `offline-safety`;
- `git diff --check` и compileall: PASS.

Возможности среды подтверждены: полный clone main `e526dfbdb5a31b01bf6f743da0288b88f916de0c`, Git/Python/pytest выполняются, draft-ветка опубликована законно через connector под lease generation 112. Этот checkpoint сохранён в state-ветке и будет перечитан после CAS. Protected merge, production, secrets/permissions и A6 не выполнялись. A6 request `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся.

Остаётся: canonical fixture/broad-suite разбор, затем продолжение #245. Полный #244, юридическая применимость и источниковая полнота **не PASS**.

## 0a. Продолжение продуктового цикла — persisted duty fallback

**Текущий checkpoint заменяет старый HEAD #255 ниже:** [draft PR #255](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/255), `agent/core-payment-regressions-v1` @ `a356f5302a2bb4388504c213b8c767ba1de0a786`, tree `c653cb79db95f82a0b943c1ec445c79038d6a1a8`, base #244 `14e0ee8f034d94ffc5831d87e076f4d693a5a524`.

Исправлено: fallback из persisted `HsRate.duty_rate` теперь сохраняет чистую специфическую часть, MAX и ADD; допускает фактические формы источника `EUR за 1 кг`/`EUR/кг` и русские эквиваленты; строка с валютой без знаменателя, отсутствующие FX/вес и переполнение завершаются fail-closed. Единицы и FX не выдумываются.

Проверки на byte-identical exact tree:
- author: `116 passed, 355 subtests`, exit 0; команда — семь payment/backend файлов на отдельной disposable SQLite;
- lineage scan: 1171/1171 persisted EUR/kg строк из `eec_ett_normative_bundle.json` приняты, 0 отклонено, exit 0;
- независимый A5 `/root/a5_payment_fallback`: **PASS** для опубликованного exact HEAD через совпадающий tree и `git diff --exit-code`; 288 passed +349 subtests, edge harness PASS;
- GitHub exact-head CI: **PASS**, [run 37774959207 / job 113303383038](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37774959207/job/113303383038), `offline-safety` на точном `a356f5302a2bb4388504c213b8c767ba1de0a786`. Это инфраструктурная проверка, не полный product CI.
- Контрольное воспроизведение опубликованного SHA в рабочем чате: `116 passed, 355 subtests`, exit 0 за 4.71s на отдельной новой SQLite; повторены семь payment-модулей через `offline_pytest.py`, JUnit `replay-a356.xml`. Это проверка исполнителя, не новый независимый A5. Worktree после запуска clean.

Доступ к коду: полная копия main `e526dfbdb5a31b01bf6f743da0288b88f916de0c` и candidate worktree доступны. Git/Python/pytest выполняются. Обычная публикация draft-ветки выполнена законно через GitHub connector под lease generation 110; protected merge/production/A6 не выполнялись. A6 request `core-s1-6415f443120f-r9-g106` не отправлялся и не пересоздавался.

Остаётся: продолжить manufacturer/product applicability и fixture/broad-suite разбор; exact-head CI этого исправления подтверждён. Полный #244 и юридическая/источниковая полнота **не PASS**.

### Плановый исполнитель — фактически проверен, 2026-10-08

После завершённого входа в интерфейсе прочитан фактический результат асинхронного пробного запуска задачи «Tariff — разработка» `6ac775d0feac8191abc1e60865ce1461`. Результат сверён с live GitHub: новый commit `a356f5302a2bb4388504c213b8c767ba1de0a786`, checkpoint `7926a5cba641dc74f049c73f570e24c04f456711`, release generation110. API фиксирует `last_run_time=2026-10-08T12:16:33.532805Z`. Исполнитель реально располагал полной копией, Git/Python, выполнил продуктовый тест и опубликовал исправление; ранее неизвестный исход trial установлен. Публикация, локальный повтор тестов и exact-head CI проверены отдельно.

**Существующее часовое расписание возобновлено 12:21:34Z:** `is_enabled=true`, `RRULE:FREQ=HOURLY;INTERVAL=1`, прежняя cadence с DTSTART 10:52Z, timezone Europe/Moscow. Новых расписаний нет. Старый «Tariff — фоновая разработка» и остальные дублирующие developer-задачи выключены; включённый «контроль остановок» остаётся read-only. Prompt обновлён: fallback уже завершён, следующая работа — ограничения производителя/товара и далее broad-suite/#245. Сохраняются единый live lease, запрет защищённых действий/A6 и явная остановка при недоступности полноценного исполнения.

Проверен **один асинхронный запуск того же расписания через run_now**, не обещана безусловная успешность всех будущих часовых запусков. API `next_run_time=null` не интерпретируется как доказанный будущий старт. Итог запуска виден в разговоре самой задачи; доставка в прежний управляющий чат не подтверждена. Для фиксации проверки использован штатный lease generation111; после checkpoint он освобождается.

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

### Проверка расписания — история до подтверждённого результата выше

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

1. Продолжить платёжный блок от опубликованного #255 `a356f5302a2bb4388504c213b8c767ba1de0a786`: legacy specific/combined fallback исправлен; следующая задача — ограничения производителя/товара, затем fixture/broad-suite разбор. Не запускать/не пересобирать A6.
2. Main уже обновлён merge #254. Перед следующей удалённой записью приобрести coordinator lease через **current trusted main** `tools/tariff_agents/lease.py` и GitHub CAS; перечитать holder/token/TTL. На реальных непроизводственных сценариях проверять: recovery state/board, создание -> allocation -> implementation -> independent QA -> CI, зависание и освобождение, корректную диагностику и доказанную видимость уведомления. Не имитировать child session IDs, A5/A6, delivery receipts. Нет доступа к native Work executor — пометить unavailable.
3. #244: воспроизвести полный backend/CI по ставкам, FX, НДС, акцизам, спецпошлинам и преференциям с реальными source versions/effective dates, unknown/fail-closed, сформировать и протестировать payment quote end-to-end без production writes; независимый A5 текущего SHA.
4. #245: проверка применимости ТР, СС/ДС/СГР, лицензий, нотификаций, маркировки и исключений по кодам и свойствам, source/provenance и confidence; самостоятельная полнота нормативного набора и full backend+frontend; independent A5. Не включать SGR enforcement без отдельного решения.
5. Далее A3: реестр **официальных** документов, версии, даты вступления, полнота и обновления; A4: классификация/семантика/AI grounded-only; интеграция пользовательского сценария описание -> код -> ставки/платежи -> документы/доказательства.
6. По каждому готовому блоку: commit-bound A5 -> обязательные CI -> A6 **только когда разрешено и требуется** -> owner decision. Любой новый HEAD обнуляет прежнее «готово» для этого exact SHA.

## 5. Сроки / риски

Предыдущие ориентиры: **9 октября** — платёжный кандидат; **23 октября** — NTM; **30 октября** — официальные источники; **10 ноября** — RC1; **17 ноября** — целевая v1.0. На 8 октября платёжный draft уже существует, но **его окончательная приёмка к 9 октября под риском**: нет полного подтверждённого product backend/источников/A6-gate. Отсутствует подтверждение для обещания v1.0 по нормативной полноте. Перепланировать только по новой фактической evidence и явно отмечать gate.

## 6. Authority, безопасность, продолжение из другого чата

- A0 — один координатор; не порождать второй A0, не дублировать executor/automations. Рабочее состояние в GitHub, не в чате. Подтверждён один реальный асинхронный цикл разработчика; существующее часовое расписание возобновлено. Включённый read-only контроль остановок не является вторым координатором. См. точные доказательства и ограничения проверки расписания выше.
- **Перед любым remote write:** `main` `AGENTS.md`, `.ai/orchestration/CONTRACT.md`; state `.ai/orchestration/RUNBOOK.md`, `.ai/TASK_PROTOCOL.md`, `.ai/TASK_BOARD.json`, `.ai/COORDINATOR_LEASE.json`, `.ai/orchestration/A6_LIVE_STATUS.json`. Запрашивать lease актуальным helper; CAS на текущем blob SHA; reread holder/token; каждый существенный write проверять. Не обходить платформенный security refusal. Отдельно в журнале: предыдущая блокировка записи lease была устранена **только для штатного CAS acquisition generation 107 2026-10-08**; это не доказывает общий доступ без ограничений. При потере lease прекратить write.
- Во время перепроверки внешний сеанс внёс 2 коммита в PR #254 с исправлением P2; A0 здесь **не отправлял дублирующий патч**. При новом внешнем движении branch немедленно reconcile HEAD и избежать пересекающихся записей. Все дополнительные findings проверять самостоятельно, не признавать review автоматически.
- Никогда без Ivan: merge защищённых веток, production deploy/DB/migrations, enforcement flags, изменение credentials/permissions/secrets, удаление/force push, A6 export. Никакой доставки в основной пользовательский чат не подтверждено.
- Статус блоков честно разделять: **сделано / сейчас / осталось / что нужно от владельца**. Прогресс доказан конкретным SHA, CI job, A5 и diff, не «агент запущен».
