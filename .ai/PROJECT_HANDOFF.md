# Tariff / A0 — единая точка передачи проекта

**Снимок:** 2026-10-08 (UTC). **Единственный репозиторий:** [ivan88810900-star/tnved_starter_kit_v2](https://github.com/ivan88810900-star/tnved_starter_kit_v2).  
**Авторитетное состояние:** ветка `agent/orchestration-state`, файлы `.ai/TASK_BOARD.json`, `.ai/COORDINATOR_LEASE.json`, `.ai/orchestration/A6_LIVE_STATUS.json`. Этот документ — указатель и контрольная точка, **не** право на запись/merge/A6. Перед действием заново читать текущие HEAD и state. Не полагаться на Business-чат.

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
