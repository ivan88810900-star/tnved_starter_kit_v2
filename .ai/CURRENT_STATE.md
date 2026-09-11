# CURRENT_STATE.md — Текущее состояние проекта

> Дата: 2026-09-11
> Активная ветка: `feat/ntm-official-full-contours`, Draft PR #187 → `feat/canonical-read-path`

---

## 1. Реализованные функции

### Ядро платформы

- **Справочник ТН ВЭД** — полное дерево (разделы → группы → позиции → субпозиции → коды),
  гибридный поиск, карточка товара и отдельный Canonical-backed «Умный маршрут»
  по смысловым группам без фиктивных кодов
- **AI-классификация** — Gemini structured JSON (код, обоснование, confidence_score, атрибуты), Claude Vision для фото
- **Расчёт платежей** — пошлина, НДС, акциз, антидемпинг, спецпошлины, утильсбор (РОП); старый справочник стран сохраняется как неподтверждённый кандидат преференции
- **Нетарифные меры** — ТР ТС каталог (96+ глав), NTM v2 контур, noise-classifier (22K записей), структурированный UI без сырого TKS-текста
- **Инвойс / пакинг-лист** — загрузка XLSX/CSV, Vision-классификация, async-задачи, экспорт в Excel
- **ТРОИС** — opendata ФТС (CSV ~42MB), fuzzy-поиск, cron-синхронизация
- **ФСА/СС/ДС** — opendata (7Z-архивы), backfill истории, мгновенная проверка номера
- **AI-ассистент** — grounded chat/copilot по TN VED, платежам, definite/advisory
  требованиям и risk coverage; цитаты, no-key fallback, guarded LLM, batch и журнал решений
- **РОП / экосбор** — ставки ПП №1041/2414, 39 категорий ТС, audit 97 глав
- **Официальные данные** — coverage-диагностика отделена от юридической актуальности.
  Старые процентные метрики не доказывают актуальность ставок. DB-derived ЕТТ
  находится в карантине (см. №188), положительный staging gate закрыт.

### Инфраструктура

- Alembic: ~60 миграций, merge-голова восстановлена (PR #115)
- APScheduler: guarded daily/weekly structured-sync и monthly review; legacy
  automation default OFF. Новый runtime scheduler ещё не задеплоен этим PR.
- GitHub Actions: CI, мониторинг источников и review-notifications; без записи
  в production DB, автоматического утверждения legal-drift и merge этого PR.
- Rate limit middleware, JWT auth, admin token
- Docker + nginx.conf для production

---

## 2. Активная задача

Продолжение после `d757dfb` (11.09.2026): прежняя остановка всей разработки из-за
DM-0014 была преждевременной. Иван поручил продолжить работу; независимая
техническая проверка выполняется агентами, без выдачи её за юридическое
утверждение. DM-0014 касается будущей положительной авторизации, а не запрета
на подготовку кандидатов, исправления и тесты.

Потерянные байты позднего пакета 111C не найдены. Вместо них из сохранённого
proposal v2 и исходных объектов построен и сохранён **новый** воспроизводимый
пакет: manifest `55d25bcc…b9b1045`, dossier `d6c83c3e…357720`, архив
`639bfb47…ca727`. Замыкание содержит 113 объектов / 43 850 110 байт;
проверены 124/124 цитаты, 143 случая выбора ставки и четыре повреждения.
Охват кандидата — четыре кода 7112 и только `[2026-09-08, 2026-09-09)`.
Это не восстановление прежних SHA и не текущий полный ЕТТ. Подробные идентичности:
`docs/ai-workflow/evidence/ett-111c-reconstruction-20260911.json`.

Добавлен изолированный `preview-duty`: точная предварительная арифметика пяти
существующих видов пошлины после выбора кандидата и повторной проверки цитат.
Дата, страна, характеристики, стоимость и количество задаются явно; неясность
не становится нулевой ставкой или финальным платежом. Курс валюты, переданный
оператором, не получает статус проверенного источника. На новом реальном
кандидате пройдены 12 CLI-сценариев: явный ноль в пределах покрытия, отсутствие
стоимости и дата вне покрытия. Временная пяти-табличная БД и байты источников
не изменились при preview; application DB не создавалась. Контракт:
`docs/ai-workflow/ETT_DUTY_PREVIEW.md`.

Preview опубликован в `5526b6df`; CI #34596589318 прошёл: 3 344 backend-теста,
frontend/typecheck/build, workflow contract и staging smoke успешно.

Отдельная диагностика полного backend-набора на свежей тестовой БД сравнила
`a5c884d3` и `d757dfb`: соответственно 4 622 / 4 657 passed, одинаковые
130 failed, 2 skipped и 73 subtests. Все 35 добавленных тестов прошли; новых
failed ID нет. 120 падений связаны с отсутствующим полным интеграционным
набором данных в demo seed, остальные выявили проверяемые ошибки контрактов.
Это диагностический прогон, не успешная full-data acceptance. Нормативные
данные для зелёных тестов не выдумывались. Исправлены перехват authenticated
permit-job маршрута публичным catch-all, отключение логгеров при Alembic,
устаревшая авторизация тестов и виртуальная карточка неизвестного кода,
которая заимствовала название/ставку соседа. Точная существующая карточка и
её мягкий Canonical fallback сохранены.

Продолжение проверки выявило подмену ошибочных входных чисел в официальных
VAT/excise/trade-remedy импортерах. Теперь неправильные/отсутствующие значения
и неподдерживаемые формы блокируют bundle до планирования записей; истинный
ноль сохраняется. Две исходные `combined` строки табачных акцизов остаются
неподдержанными и дают `parser_failed`, без исправления нормативных байтов.
Неопределённые TR-записи неполного legacy-каталога сохраняются для advisory
review, без превращения в обязательные документы. См.
`docs/ai-workflow/RATE_SOURCE_FAIL_CLOSED_CORRECTIONS.md`.

Восстановление 2026-09-11 выполнено по GitHub, а не по истории чата. `main`
остаётся на `9712c7b`, base — `a5a811e`; опубликованный HEAD PR #187 при
восстановлении — `a5c884d3`, его CI #34486721242 успешен (3 193 backend / 50
frontend). Независимый draft PR #189 не переносился и не активировался.
Найден дополнительный уже опубликованный commit `177da64` в технической ветке
`ops/ett-council-list-capture`: он является прямым потомком `a5c884d3`, а не
новой альтернативной реализацией. Этот commit восстановлен без повторного
написания кода и без merge-коммита. CI #34584814418: 3 217 backend, 50 frontend,
typecheck/build, workflow contract и staging smoke успешны.

Успешный capture #34584814626 уже содержит оригиналы решений Совета №75/77/80
от 09.07.2026. Архив восстановлен с проверкой его SHA, всех 18 объектов и полного
HTML→PDF графа; наблюдаемый список и связи list→detail→PDF повторно проверены
офлайн. Все 7 страниц трёх PDF визуально прочитаны. №80 находится на карточке
`461/10854`, меняет п.15 Порядка №728 и не является основополагающим актом
№80/2021. №75/77 содержат зависимое начало действия; у №77 отдельно указан
ретроактивный охват отношений с 01.07.2026. Эти наблюдения не превращены в
действующие ставки, юридическое утверждение или подтверждённое наличие квоты.
Исходный архив сохранён отдельно от временных CI artifacts. См.
`docs/ai-workflow/evidence/ett-council-originals-20260911.json`.

Три новых PDF добавлены только в `monitor_only`: теперь 48 источников / политик
и 68 URL. Исторический observation-файл на девять источников неизменён; три
новых pin хранятся отдельно с собственным capture SHA. Повторяемый аргумент
`--observed-baseline` сравнивает их совместно, отклоняя пересечения до загрузки,
но не выдаёт объединение за один исходный capture. Страница №72 сохраняется в
обоих workflow. Checksum acceptance, применение ставок и enforcement не добавлены.
Контролируемый локальный прогон точного backend CI-профиля: 3 228 passed,
2 dependency warnings; HTTP smoke и workflow contract успешны. Это не full-data
legal acceptance и не утверждение о прохождении всех тестов вне CI-профиля;
ограничения отдельного непрофильного прогона записаны в документе мониторинга.

Дополнение 2026-09-10: актуальный код восстановлен в отдельном checkout от
`ec1a200`; прежняя рабочая папка после восстановления среды имела старую версию
`6bcaa31`. Два пользовательских PDF в ней сохранены без изменения. Восстановлены
и по SHA проверены резервные архивы исходного корпуса и полного графа зависимостей.
Новый пакет review 111C, который не успел сохраниться до отключения среды,
в восстановленной папке отсутствует; не считать его восстановленным из Git.

Исправлен страновой дисконт без проверки применимости: исторический коэффициент
меньше единицы не снижает пошлину автоматически. Суммы сохраняются как
предварительные с причиной. Отсутствующая ставка пошлины/НДС также требует
проверки, настоящий ноль и ручной ввод различаются. Quote не выдаёт окончательный
итог при неопределённости пошлины или зависимого НДС. Статус проходит через
сравнение, историю, инвойсы, документы, CSV/XLSX/PDF и ИИ-помощника; старым строкам
без флагов не приписывается подтверждённость. Исправлен реальный контракт
двухкодового сравнения (вложенный profile вместо ошибочных плоских полей).

Добавлен ограниченный захват оригиналов по наблюдаемым ссылкам тарифных льгот
и GSP, включая выбранную страницу акта №72. Успешная загрузка не подтверждает
юридическую полноту или даты. Полный блок ставок, manifest-bound legal review,
retention attestation и production promotion остаются незавершёнными. Merge,
deployment, production DB и NTM enforcement не выполнялись. Детали:
`docs/ai-workflow/PAYMENT_PREFERENCE_REVIEW_GUARD.md`.

На этапе 10.09.2026 ежедневный монитор был расширен до 45 источников / 45 политик /
62 URL (актуальные 48/48/68 после добавления №75/77/80 описаны выше). Девять новых
PDF работают в monitor_only; исходные контрольные суммы остаются наблюдениями
для review, не утверждёнными baseline. Текущие ссылки на страницах льгот/GSP
захватываются и сравниваются отдельно, чтобы обнаруживать замену адреса PDF.
Новые/пропавшие ссылки и изменения байтов не обновляют ставки автоматически.
Проверенный этап платежей `b3f6241` прошёл CI #34483670679: backend 3 137 passed,
frontend 50 passed, typecheck/build, workflow contract и staging smoke успешно.

Приоритет на 2026-09-08: официальные ставки ЕТТ и точность нормативных источников.
Ivan принял Option A решения №188 и разрешил продолжать разработку без покупки
облака. Предыдущий опубликованный этап: `5db8245`, дерево совпадает с локальным
`399fc6b`. PR #187 остаётся Draft. Его CI: 2 928 backend-тестов, frontend tests /
typecheck / build, staging images и scheduled-workflow contract прошли.
Следующий проверенный этап добавляет детерминированный пакет review для реального
кандидата 111C; это ещё не полный блок ставок.

TASK-ETT-001–003 реализуют изолированные версионные кандидаты, пять таблиц,
выбор выражения ставки по точному коду, дате, стране и характеристикам,
получение оригиналов и воспроизводимую проверку PDF-строк. Старые небезопасные
PDF/OData/index-hash пути переведены в REVIEW_REQUIRED. Активные ставки и НДС
не переписывались. Производный перечень поправок теперь связан с исходным
индексом, парсером и точными байтами отчёта: staging/preview повторяет разбор,
вымышленный официальный URL не требуется, старые v2 SHA сохранены.

Полный технический capture Run #34244241195 имеет проверенный v2 receipt
`ab67a2d3055a3fcd8416c874b9bc388ce0b0919e4b964e5de7c1f18c08a6f72e`:
106 оригиналов, включая 100 core PDF. По текущим 96 главам / 1 537 страницам
разобраны 13 293 точных кода, полные описания и ячейки ставок; 124 примечания,
0 неразобранных ячеек, дубликатов и непривязанных номеров сносок. Оригиналы
сохранены отдельно от временных GitHub artifacts; восстановление receipt проверено.
Это полнота поддерживаемого плана загрузки и извлечения, а не юридическое
подтверждение ставок. Старые incomplete captures сохраняют прежний статус.

Run #34248830768 сохранил десять наблюдаемых страниц поиска / 500 результатов.
Повторный разбор нашёл 96/105 поправок, 59/61 ссылок из примечаний и отдельный
основополагающий акт №80 — исходный план из 97 точных URL. Ни дата публикации
в метаданных, ни пустой поисковый ответ не подтверждают юридический эффект.
Run #34251758308 сохранил свежий индекс/примечания, десять страниц поиска и
девять дополнительных запросов. Найдены 104/105 поправок, все 61 зависимости
примечаний и основополагающий акт; сохранены 105 HTML и 85 PDF. Загрузка
завершилась с 20 ошибками разбора метаданных. Повторная проверка оригиналов
выявила 18 заголовков без пробела после № и два сокращённых заголовка с полной
категорией ЕЭК; узкая совместимость исправлена, все 105 HTML теперь проходят.
Resume Run #34255440473 завершён успешно: повторно использованы 105 HTML + 85 PDF,
загружены 20 недостающих PDF, всего 105 HTML + 105 PDF без ошибок. Байты,
timestamps, URL и redirects повторно использованных записей сверены; исходный
неуспешный отчёт неизменён. Все 302 исходных объекта сохранены, новый архив
содержит 344 объекта / 178 543 558 байт. Проверенная добавка из 42 объектов
сохранена вместе со ссылкой на пять базовых частей резервного архива.
Единственный нестрого сопоставленный акт №42 содержит опечатку и на detail page;
номер, дата, категория и независимая подпись PDF-ссылки согласуются. Оригинальный
PDF отдельно сохранён Run #34256700964 и визуально проверен по обеим страницам;
прежняя диагностика не исправляется. В совокупности получены оригинальные PDF
всех 105 именованных поправок и основополагающего №80. Это не полнота всех
применимых актов, исключений или вложений.

Native-прогон 85 PDF: 76 файлов / 353 страницы без извлекаемого текста;
девять неподдержанных файлов — восемь с поворотом 270° и основополагающий
№80 на 1470 страниц при лимите 1000. Повреждения и шифрование не выявлены.
Это разные состояния, ошибки worker не считаются отсутствием текста.
На текущих 13 293 кодах отдельно пройден NTM compatibility audit: 9 семейств
для каждого кода, 15 695 advisory-требований, 0 утечек в enforcement;
рабочая БД и проверка юридической применимости в этот аудит не входят.

29 страниц двух сканов обработаны OCR, оригиналы/модель/изображения/TSV связаны
контрольными суммами. Визуальная проверка обнаружила ошибки сносок и чисел;
OCR не утверждает ставки. Два ZIP-вложения перепроверены без повторной загрузки:
4 DOC и 1 DOCX, исходный отчёт с ошибками сохранён отдельно от новой проверки.

Новый opt-in OCR CLI сохраняет оригинал, pinned rus model/license, PNG, TSV/TXT,
слова/confidence и точные SHA. Отдельный ограниченный worker допускает явно
выбранные страницы больших/повёрнутых PDF (до 64); native-лимиты не подняты.
Реальные проверки: первые 2 из 1470 страниц №80 и две страницы с поворотом 270°
обработаны; оставшиеся страницы №80 явно не проверены. Визуально найдено OCR
«|» вместо «1» в п.4 №80; исправление хранится отдельно от исходного OCR.
OCR завершён: 104 акта / 426 страниц, отдельно №42 / 2 страницы и первые
2 страницы №80 — всего 106 наборов / 430 страниц. Проверены SHA оригиналов,
PNG, TSV/TXT, модели и отчётов; оставшиеся 1468 страниц №80 не обработаны.
23 части резервного архива сохранены и перепроверены, отсутствующих data
dependencies нет. Отдельный literal inventory содержит 1638 точных совпадений
по 104 актам; он не вычисляет юридические даты и не утверждает ставки.
Native worker теперь также отклоняет Encrypt trailer с пустым user password.
Его новый SHA требует новой derivation notes/audit: прежние отчёты не изменяются
и не объявляются воспроизводимыми другим парсером. Прямые OCR-кандидаты отдельно
связывают оригинальные байты и фактически использованную версию парсера.

Typed HTML evidence теперь разрешён только в effective_evidence и сохраняет
точные строку/label/value, identity акта и ссылку на оригинальный PDF без
вымышленного номера страницы. Mixed verifier повторяет native PDF и HTML
проверки; прежние canonical v2 SHA и строгость PDF verifier сохранены.
CLI: `ett_candidates.py verify-evidence`. Исправлена типизация результата preview.

Первый реальный review manifest `8f1c56eac5a3d6082084a6eba7e463eee563c1c170572df2fceaaf70f10fe832`:
4 кода 7112, 101 оригинальный artifact, 4 правила 0% по 111C, 2 примечания.
124/124 source references проверены, независимая повторная сборка идентична.
Coverage 08–09.09.2026 отделён от предложенного периода 25.01.2026–01.01.2029;
первое введение кодов не утверждается. Portal date, ограниченная история кодов
и охват 5 стран явно остаются review-интерпретациями. Старые 15% не подставляются
вне coverage. Свежая изолированная Alembic DB: 46 сценариев, 64 остальные таблицы
не изменены. Полное приложение: 30 HTTP-проверок с JWT, БД осталась побайтно
неизменной, startup read-only. Проверяется выбор выражения, не активный расчёт.
213 связанных тестов прошли локально; опубликованный этап прошёл общую CI выше.

Review package реализован: exact canonical manifest/prior, полный v2 core receipt,
source-role и response metadata, свежие inventory/notes/mixed evidence, semantic
diff и closure повторно вычисляются. Дополнительные источники проверяются только
по выбранным capture records и исходным HTML→PDF связям; полный discovery/search
plan не объявляется повторно проверенным. CLI build/verify не открывает БД/сеть,
не меняет originals и не перезаписывает готовый output. Пакет v2 SHA
`4d4f22daccaef53b14429e3f958359273dcc47467a89d8594b69c9907c586e8c`:
921 041 байт, 113 объектов / 43 850 110 байт, 124/124 ссылок, воспроизведение
из изолированного closure и CLI идентично. 63 service/CLI теста прошли.
`assembly_ready=true` означает готовность технического dossier к review;
legal/source completeness, retention и promotion остаются false.

Полная юридическая привязка условий и дат, manifest-bound legal review,
подтверждённое архивное хранение и reviewed promotion остаются незавершёнными.
Первый четырёхкодовый кандидат не меняет `legal_inventory_complete=false`
и `production_ready=false` и не утверждает юридическую применимость 13 293 ставок.
Облако, merge, deployment и NTM enforcement не включались. Контракты и evidence:
`ETT_VERSIONED_CANDIDATES.md`, `ETT_TABLE_INTERPRETATION.md`,
`ETT_REVIEW_PACKAGE_READINESS.md` в `docs/ai-workflow/`.
Смысловая навигация ниже остаётся достигнутым baseline, а не текущим rollout.

Recovery checkpoint 2026-09-11: PR #187 опубликован на `dc1cd389` поверх
сохранённого `177da64`; CI #34589072638 и #34589067268 успешны. `main` остаётся
`9712c7b`, PR #189 — отдельный Draft на `1be6da4`. Восстановлены, а не пересобраны,
8 файлов полного dependency worklist (13 293 кода / 124 примечания) и 6 файлов
legal-interpretation backup; все SHA совпали. Это не восстановление утраченных
байтов более позднего manifest/review package 111C и не юридическое утверждение.
[DM-0014](decisions/DM-0014-ett-review-authority.md) запрашивает выбор полномочий
для положительного manifest-bound legal review и отдельного approval. Option A
№188 остаётся принятым; отсутствие купленного облака не объявляется блокером
offline-разработки. Полный блок ставок ещё не завершён, production не изменён.

### Intelligent TN VED structure — whole-catalog hardening

**Цель:** Canonical-backed «Умный маршрут» должен сохранять каждый реальный
декларируемый код, не создавать фиктивных кодов и задавать понятные вопросы поверх
одного согласованного Canonical snapshot.

**Текущий проверенный статус:**

1. Guided использует описания, захваченные той же Parser-сборкой, что и выбранный
   `CanonicalModel`; второго runtime-чтения `Commodity` больше нет.
2. 162 терминальных exact-rate L4-кода `XXXX000000` восстановлены как реальные
   листья под отдельными heading-wrapper; технические pad-записи с потомками не
   дублируются.
3. Publication boundary физически замораживает published nodes и `parent` links.
   `children` становятся tuple, standard metadata containers — recursively
   immutable; Builder output до публикации mutable, retained aliases отсоединены.
4. Full Gate-2: 18,246/18,246 legacy-vs-Canonical paths, 0 mismatch/unresolved.
5. Whole-catalog Guided census: 1,263/1,263 headings, 16,708/16,708 source-backed
   code nodes reachable/Canonical-bound, из них 13,254 declarable leaves; leaf-role
   проверяется по Canonical, а не по отсутствию semantic children.
6. На текущей feature branch semantic questions покрывают 6,949 из 13,254 leaves.
   Catalog-wide максимум шага равен 29 choices / 27 direct codes; это честный
   проверенный baseline, но не разрешение на rollout.
7. DM-0012/TASK-SEMANTIC-009 завершили bounded `2204` slice: точный PDO-набор
   `220421` сохранён как 18/17 + вложенные «прочие» 16/16; соседний `220422` —
   27/25 + «прочие» 7/7. Все 211/211 source codes и 170/170 leaves сохранены,
   oversized-шагов более 30 больше нет.
8. DM-0005 Accepted — Option A (Ivan, 2026-08-05); TASK-SEMANTIC-006 имеет статус
   Completed. Код пока остаётся только на feature branch: этот docs-only update не
   выполняет merge, rollout или deploy.
9. TASK-SEMANTIC-007 для `0304` завершён и принят через DM-0006 Option A: exact
   five-chain сократила root 19/16 → 13/8 и maximum step 19/17 → 13/9, подняла
   semantic coverage 82/100 → 92/100 и сохранила 117/117 source nodes, 100/100
   leaves. Whole census 1,228/1,228, golden 6/6, Gate-2 18,211/18,211. Это не
   выполняет merge/rollout/deploy и не включает флаги.
10. TASK-SEMANTIC-008 для `0406` завершён и принят через DM-0007 Option A:
    exact bounded fat/moisture chain сократила maximum step 27/26 → 16/15 и
    подняла semantic coverage 10/47 → 21/47 при неизменных 54/54 source nodes и
    47/47 leaves. Whole census 1,228/1,228, golden 7/7, Gate-2 18,211/18,211.
    Это не выполняет merge/rollout/deploy и не включает флаги.
11. Официальный NTM-срез восстановлен и завершён как безопасный advisory-контур:
    93 уникальных диапазона разделов 2.16/2.19, индекс 30 **базовых** разделов
    приложений 1 и 2 Решения ЕЭК №30 и стабильная матрица 9 семейств мер.
    Квотные 2.27/3.1/3.2 не выдаются за code-only правила. Ivan принял
    advisory-only rollout 2026-08-15: показ default ON, kill switch —
    `NTM_V2_OFFICIAL_FULL_ADVISORY_ENABLED=false`. Контур не пишет в БД и не
    участвует в missing-check; enforcement не одобрен (DM-0008).
12. Legal-contours уточнены по первичным источникам: prefix/«из»/свободный marker
    всегда остаётся `needs_clarification`; Решение КТС №299 проверяется по коду,
    наименованию, назначению и исключениям; ветеринарный контроль не выдаётся за
    универсальный документ `ВС`; фитосанитарный контур разделяет высокий риск
    (advisory ФСС) и низкий риск (без ФСС). Для Решения №30 исправлены исключения
    и overbroad/missing-контуры, включая 2.2, 2.6, 2.11, 2.16, 2.17, 2.20, 2.23 и
    import-only 2.30. Реестр технических регламентов содержит 53 позиции (001–053).
13. Раздел II Решения КТС №299 содержит 98 текущих advisory code-ranges, включая
    ранее пропущенные `4812000000` и `7412`. Экспортный контроль ПП РФ
    №1284–1288/№1299 выделен в девятое семейство: source-faithful union содержит
    1 087 raw HS-кандидатов, два versioned retired exact-кода исключены, поэтому
    runtime effective count равен 1 085. Направление — `export`; идентификация по
    техническим параметрам обязательна; enforcement отсутствует (DM-0009).
14. Full-catalog claim остаётся fail-closed (DM-0010), и его критерий теперь
    выполнен. После parser baseline fix все 96 tracked official PDFs rebuilt во
    временный audit-only SQLite artifact: exact 21 раздел / 96 групп / 17 809
    уникальных позиций, 0 duplicate/invalid, 17 774 непустых описания. Все 35
    blank catalog codes absent from the pinned active ETT rate snapshot; причина
    или юридический статус из этого не выводятся. Все 13 290 кодов revision
    `ett:2026-06-18` присутствуют и описаны. Pinned PDF-manifest, parser, ETT
    code-set, catalog code-set и code+description digests совпали. Artifact был
    открыт audit-процессом read-only; production/application DB не изменялась.
    `ntm-full-gate-20260815.json` имеет
    `ok=true`, `full_commodity_catalog`, `catalog_complete=true`, 9/9 семейств,
    30/30 базовых разделов и 0 enforcement leaks. Code-only и partial evidence
    сохранены как supplementary, но не подменяют full result. Этот исторический
    аудит подтверждает каталог/NTM, **не** текущие ставки пошлин и **не** разрешение
    на положительный staging launch: тарифная часть прежнего вывода отозвана.
15. DM-0011 добавляет structured `facts` в NTM API/UI и bounded exact advisory
    для санитарных/ветеринарных/фитосанитарных мер, РЭС/ВЧУ, криптографии,
    Решения №30 и экспортного контроля. Запрос без facts сохраняет broad-only
    контракт. Exact `definite`/`excluded` всегда остаётся вне missing-check.
    Versioned curated broker bridge реализован для shadow-аудита, но
    `NTM_V2_OFFICIAL_CURATED_ENFORCEMENT_ENABLED=0` является обязательным default;
    production activation отложен до отдельного решения и trusted source adapters.
    Caller-supplied exact facts fail-closed даже при включённом флаге; для
    export/transit legacy import broker/payment отключены, catch-all имеет отдельный
    transaction-risk UI, а санкционный country/HS screening маркируется неполным.
16. CI проверяет backend safety/semantic suites, frontend tests/types/build,
    workflow contracts и read-only staging. Schema-v1 baseline теперь строго
    quarantine-only: без одобренного schema-v2 и temporal-rate модели невозможно
    сформировать положительный full staging snapshot. Enforcement остаётся OFF.
17. DM-0013 подключает полный update-policy для 36/36 зарегистрированных
    нормативных источников. Семь структурированных официальных реестров (ЦБ,
    СГР, нотификации ФСБ, РЭС/ВЧУ, ФСА, ТРОИС и справочники ФТС) получили
    строгие ежедневные/еженедельные адаптеры с snapshot-gates.
    OFAC и ЕС автоматически загружаются и валидируются, но scheduled-контур не
    меняет blocking-таблицы. Нормативные документы контролируются по ETag/SHA-256
    и ставятся в review issue при drift; никакое изменение источника не включает
    NTM enforcement.
18. Монитор v4 содержит 50 URL: шесть legal PDF требуют digest-bound approval,
    девять structured artifacts автоматически обновляют техническую свежесть,
    27 legal HTML — явные revision gaps, восемь landing — availability-only.
    36/36 update-policy не означает автоматическое юридическое обновление всего.
    Пять курируемых слоёв используют durable очередь с CAS, SHA и generation.
19. В ЕТТ выявлены 13 319 raw / 13 290 unique кодов, две невалидные строки,
    27 дубликатов по 23 кодам и 18 материальных конфликтов ставок. Требуется
    [решение №188](https://github.com/ivan88810900-star/tnved_starter_kit_v2/issues/188).
    Никакой дефолтный или автоматически выбранный last-row тариф не публикуется.
20. Добавлены bounded HTTP streaming, исходные SHA-256, exact NSI pins,
    проверенная распаковка ФСА на py7zr 1.1.3 и атомарная CBR provenance.
    Browser-session файлы удалены из текущего дерева и исключены из Git/Docker;
    старые сессии Alta необходимо отозвать, история не переписывалась.

Основные `CANONICAL_TREE_ENABLED` / `CANONICAL_TREE_SHADOW` остаются default OFF.

---

## 2a. Принятые архитектурные решения

### ADR-0001 — Canonical TNVED Model (Accepted, Ivan, 2026-06-30)

**Source of Truth продукта Tariff — Canonical TNVED Model**, а не SQLite, не дерево
(`build_tree()`), не parser и не API. SQLite — слой хранения/ingestion; дерево,
семантика, AI, NTM, пошлины, поиск, RAG, граф знаний — проекции/overlay поверх
канонической модели (привязка по `stable_id` / `anchor`).

Зафиксировано:
1. Canonical TNVED Model — центральная source-of-truth модель.
2. **Recovery — стадия внутри `tree_engine`**, не отдельный top-level module.
3. **Semantic Navigation позже переводится на Canonical Model** (перестаёт читать БД сам).
4. Следующая задача — **`TASK-CANONICAL-001`**: deterministic `stable_id` + recovery
   stage skeleton (без подключения к API).
5. **Legacy `_build_tree` остаётся production и oracle до parity**; удаляется только после.

Полный документ: `.ai/decisions/ADR-0001-canonical-tnved-model.md`. Индекс: `.ai/DECISIONS.md`.

---

## 2b. Состояние Canonical Pipeline (through TASK-CANONICAL-010)

**TASK-CANONICAL-001 — Completed.** Детерминированные `stable_id` (без `uuid4()`),
`snapshot_id`, skeleton стадии Recovery.

**TASK-CANONICAL-002 — Completed.** Recovery-логика перенесена в `StructureNormalizer`;
Builder собирает дерево напрямую из recovery-результата (без делегирования в legacy
`build_tree()`); добавлены full-tree parity-тесты против legacy-oracle.

**Canonical Model Materialization — Completed.** Добавлен иммутабельный `CanonicalModel`
поверх результата `TreeBuilder.build(...)` с индексами достижимости и навигацией;
обязательный validator gate; content-parity с legacy (сверх structural).
Первичная реализация замораживала facade, а TASK-CANONICAL-010 закрыл
физическую deep-immutability опубликованных узлов. До TASK-CANONICAL-004
контур не был подключён к runtime.

**TASK-CANONICAL-004 — Completed (Этап 3 ADR: read-path за флагом).** ADR-0002
принят Ivan 2026-07-10 с условиями; Gate-1 и Gate-2 пройдены. Структурный слой
эндпоинта `/children` может брать структуру из `CanonicalModel` **за feature flag**:

- Флаги `CANONICAL_TREE_ENABLED` и `CANONICAL_TREE_SHADOW` — **оба default OFF**,
  читаются **request-time** (rollback без рестарта). Централизованный accessor —
  `tree_engine/flags.py` (без scattered `os.getenv`).
- Provider `tree_engine/provider.py` — in-memory singleton кэш `CanonicalModel`,
  **build-once под локом** (double-checked), пайплайн `TreeParser → TreeBuilder.build_model`
  (validator gate внутри, не обходится). **Ревизия кэша** учитывает `tnved_commodities`
  точный content fingerprint значимых полей `tnved_commodities`, Section/Chapter notes
  и leaf-relevant `hs_rates`. Это закрывает stale-cache при in-place UPDATE, который
  не замечал прежний `count+max(id)`. После TASK-CANONICAL-007 `TreeParser` читает
  commodities, Section/Chapter metadata и leaf-relevant `hs_rates` в **одной DB
  session**, передаёт `leaf_flags` как явный `TreeParseResult`; `TreeBuilder` больше
  не знает о БД/session factory. Для SQLite Parser явно начинает read-транзакцию до
  первого `SELECT`, поскольку legacy transaction mode драйвера иначе не гарантирует
  один snapshot нескольким чтениям. Полный fingerprint пересчитывается только после
  изменения дешёвого DB
  source-token (SQLite DB/WAL stat; PostgreSQL WAL LSN), а не на каждый read. На
  synthetic 14k строк: cold hash ~129 ms, stable probe median ~0.021 ms. При сбое
  сборки/валидатора — лог + `None` → fallback на legacy, **не** 500.
- Bridge: `CanonicalModel.TreeNode → TreeSerializer.to_legacy_dict(node)` →
  **существующий** `_serialize_tree_node` (overlay/enrichment **не** дублируется и **не**
  меняется). Секционная обёртка `_wrap_in_sections` и поиск узла `_find_node_in_tree`
  переиспользуются.
- Branching **только** внутри `list_tnved_children` (через `_resolve_children_node`):
  OFF → строго legacy; ON → canonical structure, при неудаче (модель недоступна / узел
  не найден) → fallback legacy. Поведение сохранено для empty/root, roman sections,
  2/4/6/8/10-значных узлов, leaf → `[]`, synthetic/codeless-обёрток.
- Shadow (`SHADOW=1`, `ENABLED=0`): ответ legacy, canonical считается и сверяется
  (structural+content fingerprint); потокобезопасные `shadow_match`/`shadow_mismatch`
  считаются всегда, mismatch-warning семплируется (первый и каждый 100-й), на ответ
  **не** влияет; сбой canonical в shadow учитывается как mismatch и не даёт 500.
- Gate-2 инструмент `scripts/audit_canonical_children.py` строит legacy/canonical по
  одному разу и сравнивает все DB-backed `/children` пути. Финальный прогон 2026-07-14
  на наполненной БД: **18 049 checked/matched, 0 mismatch, 0 unresolved**,
  `gate2_ok=true`, exit `0`.
  Защита от false-green требует не менее 10 000 commodity-строк; меньшая БД может дать
  parity-smoke, но не `gate2_ok`.
- Для передачи без полного 1.5 GB `customs.db` добавлен read-only exporter
  `scripts/export_canonical_gate2_db.py`: в одной snapshot-транзакции копирует только
  `tnved_sections`, `tnved_chapters`, `tnved_commodities`, `hs_rates`, проверяет
  integrity/FK, считает SHA-256 и опционально создаёт ZIP. В `hs_rates` остаются только
  leaf-маркеры неоднозначных commodity-кодов `*0000`; значения ставок/provenance и
  операционные/user tables в экспорт не попадают.
  Опция `--audit-report` сразу запускает Gate-2 на экспорте и атомарно сохраняет
  переносимый JSON с SHA-256, coverage, parity и exit code; при `gate2_ok=true`
  достаточно передать этот маленький отчёт, без самой БД.
- Контракт JSON основного `/children` **не изменён**; legacy `build_tree()` не тронут.
  Guided navigation подключена отдельно и не включает Canonical feature flags.
- Self-contained тесты: `tests/test_canonical_read_path.py` (35),
  `tests/test_canonical_children_audit.py` (3) и
  `tests/test_export_canonical_gate2_db.py` (2), плюс
  `tests/test_tree_parser_leaf_flags.py` (5). Они покрывают in-place UPDATE,
  notes, leaf-rate invalidation, метрики/семплирование, root/Roman parity, audit smoke
  минимальный read-only export → полный audit, full/compact `hs_rates`, чистый Builder
  один DB snapshot на provider build и изоляцию от конкурентного SQLite commit.
  Финальный data-dependent Gate-2 выполнен на наполненной БД.

> Предыдущий QA-вердикт `APPROVE WITH NOTES` был отменён после воспроизведения stale-cache
> на in-place UPDATE. Corrective fix и повторный QA выполнены; финальный Gate-2 зелёный.
> Флаги остаются default OFF до отдельного решения Ivan о rollout.

### Реализовано (в `customs-clear/backend/app/services/tree_engine/`, изолированно)

- **Parser** (`parser.py`) — единственная DB-reading стадия: из одной session собирает
  `ParsedCommodityRecord`, Section/Chapter notes и leaf-evidence L4/L6 в явный
  `TreeParseResult`; SQLite read-snapshot начинается до первого запроса, полная и
  compact Gate-2 схемы поддерживаются.
- **Recovery** (`recovery.py`, `StructureNormalizer`) — pad-имена, синтез бескодовых
  L6/L8, subheading-group, очистка имён, классификация типов; **чистая стадия** (без БД,
  без `uuid4`), leaf-флаги принимает аргументом.
- **Builder** (`builder.py`) — чистая DB-независимая stack-сборка иерархии,
  материализация синтет-листьев,
  сортировка, восстановление имени группы, присвоение ID; **напрямую**, без legacy.
  Additive-метод `build_model(...)` → `CanonicalModel` (validator gate + freeze).
- **CanonicalModel** (`canonical_model.py`) — иммутабельный Source-of-Truth объект:
  `roots`/`snapshot_id`, индексы `node_by_stable_id` / `node_by_code` /
  `node_by_display_code` / `parent_by_stable_id` / `children_by_stable_id`; методы
  `get` / `get_by_code` / `get_by_display_code` / `parent` / `children` / `path` /
  `descendants`. После validator/stamping каждый опубликованный `TreeNode`
  физически заморожен: scalar attributes и `parent` не переустанавливаются,
  `children` → `tuple`, а standard metadata mappings/lists/sets/bytearray
  рекурсивно detached/frozen; индексы → `MappingProxyType`.
  `TreeBuilder.build(...)` до публикации остаётся mutable.
- **Validator gate** — `CanonicalModel.from_roots(...)` прогоняет `TreeValidator` перед
  freeze; при ошибках модель не создаётся (`CanonicalModelValidationError`).
- **stable_id** — `stable-id-v1`, детерминированный snapshot-independent hash
  Canonical path, воспроизводимый между эквивалентными сборками.
- **snapshot_id** — `canonical-snapshot-v2`, детерминированный hash полного
  результирующего Canonical output; provider source revision остаётся отдельным
  rebuild-key.
- **Parity tests** — `test_canonical_tnved_model.py`: full-tree **structural** parity
  (`structure_fingerprint`) и full-tree **content** parity (name / display_code /
  is_leaf / is_codeless / is_group / import_duty / notes) против legacy `build_tree()`.

### Чего ещё НЕТ (намеренно, по плану ADR-0001)

- **Generic freeze arbitrary custom metadata objects** — неизвестный mutable
  object как metadata value сохраняется как есть; для него нужен отдельный
  cloning/serialization protocol. В production Canonical metadata таких
  объектов нет.
- ~~**Feature flag** — нет `CANONICAL_TREE_ENABLED`.~~ **Закрыто** (TASK-CANONICAL-004):
  `CANONICAL_TREE_ENABLED` / `CANONICAL_TREE_SHADOW` (default OFF, request-time,
  `tree_engine/flags.py`).
- **Runtime adoption** — подключён к runtime **только** структурный слой `/children`
  **за флагом** (default OFF). Остальные эндпоинты / `lifespan` / overlay — по-прежнему
  legacy.
- **Materialized snapshot** — модель строится in-memory на вызов `build_model(...)`; нет
  переживающего рестарт снапшота/кэша по `snapshot_id`.
- **Overlays** — Guided Semantic Navigation проверяет каждый реальный код по
  Canonical anchor/snapshot и строит смысловые группы из immutable source records
  той же модели, не перечитывая `Commodity` после выбора snapshot. NTM / Duty /
  Notes / RAG ещё не переведены на `anchor`.

## 2c. Guided TN VED v1 — пользовательская умная структура

Реализован additive read-only маршрут `GET /api/v1/tnved/guided/{heading}` и
пользовательский интерфейс «Умный маршрут» у 4-значных товарных позиций:

- CanonicalModel — единственная истина кодов; semantic extraction создаёт только
  бескодовые навигационные группы из официального текста.
- Все кодовые узлы получают Canonical `stable_id`/`snapshot_id`; ID смысловых групп
  детерминированы и не используют `uuid4`.
- Integrity gate проверяет достижимость, отсутствие fake/duplicate codes и 100%
  Canonical binding. Частичное дерево запрещено: при любой ошибке возвращается
  `DEGRADED` со ссылкой на обычный `/children`, без 500.
- В UI пользователь последовательно выбирает понятные смысловые варианты и приходит
  к реальному 10-значному коду; группы явно помечены как подсказки, а не коды.
- Controlled nesting восстанавливает один уровень смысловых подгрупп только по
  явной глубине тире официального текста либо строгому title-prefix внутри текущего
  parent segment и внутри его официального code scope. Реальная глубина тире
  нормализуется в два пользовательских semantic-уровня; вышедшие за scope соседние
  коды возвращаются на безопасный уровень, одинаковые подгруппы одного parent
  объединяются. Сомнительный или unsplit-сегмент более 30 кодов остаётся плоским
  с диагностической причиной.
- Validator и aggregate-only full-data gate проверяют semantic depth/parent,
  code invariance, bounded unsplit span и строгие целевые случаи
  `0302/0303/2204/5208/8517`; whole-catalog режим дополнительно обходит все heading
  одного Canonical snapshot.
- UI различает «Смысловую группу» и «Смысловое уточнение» и показывает вложенность
  как следующий вопрос, не выдавая бескодовую группу за код ТН ВЭД.
- Основные `CANONICAL_TREE_ENABLED` / `CANONICAL_TREE_SHADOW` остаются OFF.
- TASK-SEMANTIC-006 и TASK-SEMANTIC-009 реализуют только для `2204` exact-source
  projection. Исходный PDO scope из 33 Canonical sibling leaves остаётся полным;
  retained depth-7 «прочие» создаёт вложенный шаг 16/16, а независимый retained
  boundary под `2204220000` — шаг 7/7. Любой source/topology drift атомарно
  возвращает полный прежний маршрут. Итоговый catalog/`2204` максимум — 29/27,
  oversized warning более 30 отсутствует. DM-0005 и DM-0012 приняты; rollout и
  feature activation этим не разрешены.
- TASK-SEMANTIC-007 — завершённый и принятый через DM-0006 Option A bounded slice
  для `0304`. Пять product-form
  titles с exact `(anchor, stop]` source scopes, ordered tuples и полной Canonical
  leaf/parent topology как одну fail-closed chain. Measured metrics: root 13/8,
  max step 13/9, coverage 92/100; 117/117 source nodes и 100/100 leaves сохранены.
  Full official titles меняют codeless guide IDs; coded-node `stable_id`
  неизменны. Merge/rollout/flag activation не выполнялись.
- Feature-branch full-data read-only Gate на пользовательском экспорте:
  1,263/1,263 heading,
  16,708/16,708 source-backed code nodes reachable/Canonical-bound и 13,254
  Canonical declarable leaves на одном snapshot; fake/duplicate/critical/degraded/
  empty-root/leaf-role/Canonical-parent mismatch = 0, golden hierarchy 7/7.
  Semantic choices покрывают 6,949 leaves; maximum step 29/27. Quality
  distributions не подменяют correctness gate произвольным threshold. Canonical
  runtime flags оставались OFF.
- Текстовое описание товара теперь даёт ранжированные Canonical-позиции для
  запуска Guided-вопросов. Curated semantic evidence выше случайного full-text:
  на полном Gate-2 экспорте «смартфон» ведёт сначала в `8517`, «портативный
  компьютер» — в `8471`; цифровой поиск кодов не изменён.
- Canonical provider, leaf detection и revision fingerprint поддерживают
  компактную Gate-2 схему `hs_rates(id, hs_code)` без `hs_prefix`; read-only
  fallback не повторяет неуспешное создание FTS на каждом запросе.

## 2d. Frontend acceptance интегрированных умных цепочек

**TASK-MVP-FRONTEND-ACCEPTANCE-001 — Completed.** Добавлен первый автоматический
frontend acceptance-контур (Vitest + jsdom + Testing Library), который проверяет
реальную композицию `Dictionary` / поиска / Guided-навигации:
`смартфон` → Canonical-кандидат `8517` → смысловой вопрос → реальный код
`8517130000` → карточка товара.

Это DOM-level проверка, а не заявление о визуальном live-browser QA: доступный
облачный браузер не подключается к локальному адресу приложения. Одновременно
поиск получил доступное имя, оба полноэкранных окна — корректную dialog-семантику
и начальный фокус, а фон блокируется от прокрутки на время открытого окна.
**TASK-MVP-FRONTEND-ACCEPTANCE-002 — Completed.** Второй автоматический контур
проверяет реальную композицию карточки товара:
`8517130000` → объяснимые платежи → обязательные документы → проверка рисков →
передача кода и названия в grounded assistant.

Карточка теперь fail-safe по отсутствующим данным: пока preview и нормативный
блок загружаются, показываются нейтральные состояния; при ошибке отсутствие
документов, специальных мер и ставка НДС не выдаются за подтверждённый факт.
Нормативный блок загружается сразу при открытии карточки, вкладки получили
доступную tab-семантику, а кнопка «Спросить помощника» формирует grounded-вопрос
по текущему коду. Второй тест намеренно имитирует отказ обоих источников.

Оба контура являются DOM-level проверкой. Визуальная и live-network browser
проверка остаётся отдельным шагом, когда приложение будет доступно браузеру по
достижимому URL.

**TASK-MVP-FRONTEND-ACCEPTANCE-003 — Completed.** Реальный navigation bridge
теперь проверяется от продуктового вопроса до маршрута `/assistant`, а настоящий
`Assistant` / `DeclarantChatThread` — до отправки `/v1/assistant/chat` и показа
ответа с provenance. Детерминированный режим явно маркируется как «серверные
факты», guarded optional LLM — как «ИИ + серверные факты»; citation, ограничения
и follow-up действия остаются видимыми. Вопрос из карточки получает фокус, чтобы
пользователь мог проверить и отправить его без повторного поиска поля.

Для тестируемости route composition вынесена из browser bootstrap `main.tsx` в
`App.tsx`; URL-контракты не изменены. Тест optional LLM использует только
валидированный API-ответ на mocked boundary и не вызывает внешнего провайдера.

**TASK-MVP-FRONTEND-PERFORMANCE-001 — Completed.** Все существующие экраны теперь
загружаются по маршрутам, а общий shell остаётся видимым. Начальный JavaScript
сокращён с `1,277,432` до `231,325` байт (`-81.9%`), основной entry chunk — до
`51,580` байт. Самый большой on-demand chunk (`Calculator`, `384,916` байт) ниже
порога Vite 500 kB. Доступный loading-status и error boundary с безопасным reload
не оставляют пользователя на пустом экране при задержке или сбое загрузки.
URL/API-контракты не менялись; backend, БД, флаги и внешний LLM не затронуты.

---

## 3. Последние архитектурные изменения

| Коммит | Дата | Описание |
|--------|------|---------|
| TASK-SEMANTIC-009 / DM-0012 | 2026-08-18 | Exact retained `2204` «прочие» boundaries; max 29/27, census 1,263/1,263, Gate-2 18,246/18,246 |
| DM-0011 + exact NTM applicability | 2026-08-15 | Structured facts, bounded exact advisory/exclusions and versioned default-OFF curated broker bridge; production activation deferred |
| DM-0008/0009/0010 + official NTM contour | 2026-08-15 | Ivan approved advisory-only default-ON rollout with kill switch; enforcement not approved; 9 families / 30 base sections; temp read-only 96-PDF artifact passed exact 21/96/17 809 gate with pinned digests and no production DB mutation |
| TASK-SEMANTIC-008 | 2026-08-10 | Completed; DM-0007 Option A, exact `0406` moisture chain, 27/26 → 16/15, golden 7/7 |
| TASK-SEMANTIC-007 | 2026-08-06 | Completed; DM-0006 Option A |
| TASK-SEMANTIC-006 (feature branch) | 2026-08-05 | Completed and accepted via DM-0005 Option A: exact bounded `2204` PDO slice, 50/47 → 18/14 → PDO 33/33, census 1,228/1,228 and golden 5/5; not merged/rolled out/deployed |
| TASK-CANONICAL-010 | 2026-08-05 | Published Canonical graph deep-frozen |
| TASK-SEMANTIC-005 | 2026-08-05 | Whole-catalog Guided census: 1,228/1,228 headings, 16,708/16,708 source code nodes, 13,254 Canonical leaves, zero role mismatch/fake/duplicate/degraded/empty-root; semantic UX baseline measured separately |
| TASK-CANONICAL-009 | 2026-08-05 | 162 terminal exact-rate L4 pad records restored as real leaves; hardened Gate-2 18,211/18,211 |
| TASK-CANONICAL-008 | 2026-08-05 | Guided semantic records retained inside the selected Canonical model; no mixed model-A / DB-B runtime response |
| TASK-CANONICAL-007 | 2026-08-01 | Parser — единственная DB-reading стадия; явные leaf flags и один snapshot, Builder чистый; Gate-2 18,049/18,049 |
| TASK-MVP-FRONTEND-PERFORMANCE-001 | 2026-07-31 | Route-level bundles: initial JS −81.9%, accessible loading/error fallback, no route/API changes |
| TASK-MVP-FRONTEND-ACCEPTANCE-003 | 2026-07-31 | Реальный card→assistant route bridge, focused prefill, cited deterministic/guarded-LLM frontend contracts |
| TASK-MVP-FRONTEND-ACCEPTANCE-002 | 2026-07-31 | Интегрированная карточка `8517130000`: платежи → документы → риск → assistant; fail-safe состояния при недоступных evidence |
| TASK-MVP-FRONTEND-ACCEPTANCE-001 | 2026-07-31 | Автоматический frontend-путь `смартфон` → `8517` → Guided → реальный `8517130000` → карточка; dialog/accessibility hardening |
| Controlled semantic nesting | 2026-07-29 | Full-data approved bounded group→subgroup hierarchy with official code-scope guards, spillover protection, duplicate subgroup merge and 328/328 target-code coverage; flags OFF |
| Guided TN VED v1 | 2026-07-23 | Canonical-backed смысловой маршрут, fail-closed integrity gate, отдельный API и UI без включения `/children` flags |
| Full-data MVP acceptance | 2026-07-21 | Пользовательская БД 6.78 GB прошла strict read-only gate: 21 раздел, 96 групп, 17,809 commodities, 13,322 rates; auth + 4/4 сценария; файл БД неизменён; Canonical flags и внешний LLM OFF; evidence сохранён в `docs/ai-workflow/evidence/mvp-acceptance-20260721.json` |
| Strict read-only MVP gate | 2026-07-21 | Acceptance открывает SQLite через `mode=ro` + `query_only`, отключает startup-записи/планировщики/внешний LLM и Canonical flags, проверяет неизменность файла БД, выдаёт aggregate-only JSON; sandbox 4/4, full-data threshold корректно отклоняет малую БД |
| MVP acceptance hardening | 2026-07-16 | `run_e2e_scenarios.py` синхронизирован с текущим продуктом: обязательный login/cookie, hybrid search + code card, Smart Payments, normative/risk evidence, grounded assistant; sandbox 4/4, flags OFF; ошибочный US→automatic embargo assertion удалён |
| TASK-MVP-ASSISTANT-001 | 2026-07-15 | Grounded assistant: no-key server answers, TN VED/payment/NTM/risk evidence, citations and guarded optional LLM wording |
| TASK-MVP-PAYMENTS-001 | 2026-07-15 | Smart Payments встроен в карточку ТН ВЭД: базы расчёта, статусы, источники, допущения, честный partial total и Canonical anchor |
| `f7df848..d2ef092` | 2026-07-15 | Canonical anchor identity + additive bridge в поиск/карточку ТН ВЭД |
| Gate-2 QA | 2026-07-14 | TASK-CANONICAL-004 completed: 18 049/18 049 match, 0 mismatch/unresolved; flags remain default OFF |
| `9fe1fa5..daf6be1` | 2026-07-10..14 | `/children` за default-OFF флагом; corrective, shadow metrics, Gate-2 auditor/export/report |
| `9712c7b` | 2026-07-01 | Canonical Model Materialization: иммутабельный `CanonicalModel`, validator gate, full-tree content parity |
| `f66d3c7` | 2026-06-30 | TASK-CANONICAL-002: recovery-логика → `StructureNormalizer`; Builder без legacy delegation |
| `4a7eac2` | 2026-06-30 | TASK-CANONICAL-001: deterministic `stable_id`, `snapshot_id`, recovery skeleton |
| (docs) | 2026-06-30 | ADR-0001 Canonical TNVED Model принят (Ivan); зафиксированы DECISIONS.md, ROADMAP |
| `f42d2d4` | 2026-06-26 | L6 синтез: codeless L6 wrappers для одиночных субпозиций |
| `732c1e7` | 2026-06-26 | L8 синтез: codeless headings для L8-узлов без детей |
| `6c61f70` | 2026-06-26 | ntm_measures_v2: canonical sources, full names, badges |
| `60b0e08` | 2026-06-26 | Tree UX + non-tariff measures + data cleanup |
| `6de52fb` | 2026-06-26 | TNVED tree hierarchy, leaf click, duty badge, codeless nodes |
| `6fcad76` | 2026-06-26 | Drill-down TNVED tree с depth navigation (этап 2/5) |

---

## 4. Последние исправленные ошибки

| PR/коммит | Проблема | Решение |
|-----------|---------|---------|
| TASK-CANONICAL-009 | Legacy и Canonical одинаково удаляли terminal `XXXX000000`, поэтому 162 Guided headings были пустыми, а parity gate не замечал общий пропуск | Exact L4 leaf materialization + independent Parser-backed reachability requirement; Gate-2 18,211/18,211 |
| TASK-CANONICAL-010 | Mutable published graph | Deep-freeze boundary |
| TASK-CANONICAL-008 | Guided мог смешать Canonical structure/snapshot A с повторно прочитанными описаниями DB state B | Immutable source-record projection внутри `CanonicalModel`; runtime pure builder, fail-safe DEGRADED без records |
| `732c1e7` | L8-коды показывались как листья, а не codeless headings | `elif lvl == 8` ветвь в `_classify()` |
| `f42d2d4` | L6-субпозиции без детей показывались как листья | `elif lvl == 6` ветвь в `_classify()` |
| PR #130 | Китай (CN) получал GSP-скидку 25% | CN → `mfn_graduated` (коэфф. 1.0) |
| PR #115 | Дублирующий `revision_id` в Alembic | Переименование + merge-миграция |
| PR #168 | IntegrityError при batch upsert FSA | Dedupe по `registry_number` |
| PR #134 | Битый FCS_OFFICIAL_URL | Исправлен URL, Decision Memo #135 |

---

## 5. Незавершённые задачи

| Задача | Статус | Приоритет |
|--------|--------|-----------|
| **TASK-CANONICAL-001** — deterministic `stable_id` + recovery stage skeleton | ✅ Completed | — |
| **TASK-CANONICAL-002** — recovery-логика → `StructureNormalizer`, Builder без legacy, parity tests | ✅ Completed (APPROVE WITH NOTES) | — |
| **Canonical Model Materialization** — иммутабельный `CanonicalModel` (индексы+навигация), validator gate, content parity | ✅ Completed (не подключён к runtime) | — |
| **TASK-CANONICAL-004** — read-path `/children` за флагом (provider/cache, shadow, fallback), контракт неизменён | ✅ Completed: Gate-1 + Gate-2 passed; flags default OFF | — |
| **TASK-CANONICAL-005** — freeze `stable_id` / output `snapshot_id` / anchor DTO | ✅ Completed; ADR-0003 Accepted | — |
| **TASK-CANONICAL-006** — TN VED search/code-card anchor bridge | ✅ Completed; optional soft-fail anchor | — |
| **TASK-CANONICAL-007** — leaf evidence в Parser, один DB snapshot, чистый Builder | ✅ Completed; Gate-2 18,049/18,049 | — |
| **TASK-CANONICAL-008** — snapshot-bound Guided semantic records | ✅ Completed; mutation regression + compact Gate-2 smoke | — |
| **TASK-CANONICAL-009** — terminal exact-rate L4 reachability | ✅ Completed; Gate-2 18,211/18,211, zero empty-root | — |
| **TASK-CANONICAL-010** — deep-freeze | ✅ Completed | — |
| **TASK-MVP-SEARCH-QUALITY-001** — hybrid поиск: ranking, typo recovery, explainable UI | ✅ Completed; embeddings remain separate | — |
| **TASK-MVP-PAYMENTS-001** — объяснимый расчёт платежей в карточке ТН ВЭД | ✅ Completed; calculation semantics unchanged | — |
| **TASK-MVP-RISK-001** — санкционный скрининг: scope, evidence, coverage, sources | ✅ Completed; semantics remain diagnostic | — |
| **TASK-MVP-ASSISTANT-001** — grounded assistant: серверные факты, цитаты, no-key fallback, guarded LLM | ✅ Completed | — |
| Full-data MVP acceptance | ✅ Completed: полная пользовательская БД, strict read-only, auth + 4/4, evidence сохранён | — |
| Official full NTM advisory rollout | ✅ Accepted Ivan 2026-08-15: default ON, explicit false kill switch, 9 families / 30 base sections, no broker impact | — |
| Full-catalog NTM audit on current code | ✅ Passed on temp read-only audit artifact rebuilt from 96 tracked official PDFs: exact 21/96/17 809, 17 774 described + 35 blank codes absent from pinned active ETT rate snapshot; pinned digests match; no production DB mutation | Повторять при source/parser revision |
| Official NTM enforcement | Not approved; every contour match remains advisory and outside missing-check | New Ivan decision required |
| Structured exact NTM applicability | ✅ Implemented under DM-0011: additive facts API/UI, exact advisory/exclusions, no default broker effect | Trusted registry/source adapters before rollout |
| Curated official NTM bridge | ✅ Implemented and tested in shadow; default OFF, two frozen exact rule IDs | Explicit rollout decision required to enable |
| Guided TN VED v1 | ✅ Completed locally: API/UI, 100% Canonical binding gate, safe fallback | — |
| Full-data guided acceptance (`0302/0303/5208/8517`) | ✅ Completed: 328/328 target codes, 100% Canonical coverage, hierarchy green | — |
| **TASK-SEMANTIC-003** — controlled nesting смысловых подгрупп | ✅ Completed: full-data hierarchy gate green | — |
| **TASK-SEMANTIC-004** — описание товара → ранжированные Canonical heading → Guided-вопросы | ✅ Completed: full Gate-2 API acceptance; flags OFF | — |
| **TASK-SEMANTIC-005** — whole-catalog Guided integrity/quality census | ✅ Completed: 1,228/1,228 headings, 16,708 source nodes / 13,254 declarable leaves; semantic baseline recorded | — |
| **TASK-SEMANTIC-006** — bounded official PDO interval for `2204` | ✅ Completed and accepted via DM-0005 Option A; implemented + verified on feature branch: exact 33-leaf allowlist, 18/14 → PDO 33/33, census 1,228/1,228 and golden 5/5; flags OFF | No merge/rollout/deploy in this docs update |
| TASK-SEMANTIC-007 | ✅ Completed; DM-0006 Option A | No rollout |
| TASK-SEMANTIC-008 | ✅ Completed; DM-0007 Option A, exact `0406` moisture chain, 16/15 and 21/47 | No merge/rollout/flag activation |
| TASK-SEMANTIC-009 | ✅ Completed; DM-0012 Option A, exact retained `2204` «прочие» boundaries, max 29/27, census 1,263/1,263 | No runtime rollout/flag activation |
| **TASK-MVP-FRONTEND-ACCEPTANCE-001** — поиск → Guided → реальный код → карточка | ✅ Completed: автоматический DOM-level acceptance; accessibility hardening | — |
| **TASK-MVP-FRONTEND-ACCEPTANCE-002** — карточка → платежи → документы → риск → assistant | ✅ Completed: verified/failure DOM-level paths; fail-safe evidence UI | — |
| **TASK-MVP-FRONTEND-ACCEPTANCE-003** — реальный card → assistant → grounded response | ✅ Completed: route bridge + deterministic/guarded-LLM UI contracts | — |
| **TASK-MVP-FRONTEND-PERFORMANCE-001** — route-level production bundles | ✅ Completed: initial JS −81.9%, loading/error boundary, all routes preserved | — |
| Optional LLM/embeddings readiness | Контракт и fallback ✅; векторы/provider не настроены, ingestion/search OFF | Отдельное решение |
| Interactive frontend acceptance | Search → Guided → card ✅; card → payments → requirements/risk → grounded assistant response ✅; live-browser QA ожидает достижимый URL | Высокий |
| DM-0004: nomenclature history / code transitions | Proposed; awaiting Ivan and official-source feasibility audit; no schema/runtime authorized | Decision |
| DM-0005: Guided `2204` PDO interval | ✅ Accepted — Option A (Ivan, 2026-08-05); TASK-SEMANTIC-006 completed on feature branch | No merge/rollout/deploy in this docs update |
| DM-0012: retained `2204` «прочие» boundaries | ✅ Accepted — Option A; TASK-SEMANTIC-009 completed and verified | No runtime rollout/flag activation |
| Fine-tune модели на `training_pairs.jsonl` | Вне репозитория | Низкий |
| Live-parсер ФТС предрешений (tks.ru JS) | Decision Memo #135 | Средний |
| Мульти-воркер ФСА (Redis-очередь) | Бэклог | Низкий |
| Полный аудит graduated-стран по ЕЭК №17 | Бэклог | Средний |
| Alembic для FTS5 virtual table | Архитектурная проблема | Низкий |
| Дополнительные регрессионные тесты дерева | Follow-up | Высокий |

---

## 6. Текущие ограничения

### Данные
- **ETT (пошлины):** 27 строк из TKS bulk-AI краулера (legacy), не от ЕЭК → `manual_review_required`
- **Anti-dumping:** 82.8% покрытие, 5 мер из 29 без официального источника
- **Special duties:** при отсутствии локальных данных Smart Payments намеренно не
  подтверждает финальный итог и показывает только известную частичную сумму
- **ФТС предрешения:** live-парсер не реализован (customs.gov.ru/folder/519 — статистика, не предрешения)
- **ТРОИС:** fuzzy-поиск может давать false positives на коротких запросах
- **NTM full-catalog evidence:** gate пройден на временном audit-only SQLite
  artifact, rebuilt из 96 tracked official PDFs и открытом read-only. Production
  DB не заменялась и не изменялась. Результат привязан к exact 21/96/17 809,
  pinned manifest/parser/ETT/code/code+description digests и должен
  пересчитываться при их обновлении. Partial/code-only отчёты supplementary
- **Semantic embeddings:** в доступных QA-БД нет готовых векторов и серверный ключ
  провайдера не настроен; умный поиск и ассистент используют детерминированный hybrid/evidence fallback

### Архитектура
- **SQLite** — ограничение параллельных записей; для production рекомендуется PostgreSQL (DATABASE_URL поддерживает)
- **FTS5** — вне Alembic, создаётся только при старте приложения
- **Official full NTM advisory** — default ON по решению Ivan от 2026-08-15;
  `NTM_V2_OFFICIAL_FULL_ADVISORY_ENABLED=false` является kill switch. Это не
  включает enforcement
- **Прочие NTM v2/enforcement flags** — не активируются решением advisory rollout;
  влияние на broker/missing-check требует отдельного одобрения Ivan
- **L6/L8 синтез** — производительность: на каждый запрос к дереву пересчитывается из БД (кэш не реализован)
- **Semantic Guided quality** — strict integrity доказана для supplied Gate-2
  snapshot по всем 1,263 heading. Semantic questions покрывают 6,949/13,254
  declarable leaves; остальные ветки сохраняют прямые code-choice маршруты.
  После bounded DM-0012 slice catalog-wide максимум равен 29/27 в `220429`;
  шагов более 30 нет. Дальнейшая оптимизация требует отдельных source-backed
  UX-задач; runtime rollout флагов не выполнен.

### Frontend
- **Тайпскрипт типы** — `openapi.generated.ts` требует ручной регенерации (`npm run gen:api-types`) при изменении схемы API
- **Acceptance coverage** — автоматизированы search → Guided → card и card →
  payments → requirements/risk → assistant route/grounded response;
  визуальная/live-network browser проверка ещё не выполнена из-за недоступности
  локального URL облачному браузеру
- **Tailwind CSS 3.4** (не 4.x) — конфигурация в `tailwind.config.cjs`

---

## 7. Версии технологий

| Технология | Версия |
|-----------|--------|
| Python | 3.13 |
| FastAPI | актуальная |
| SQLAlchemy | 2.x (Mapped columns) |
| Alembic | актуальная |
| React | 18.3.1 |
| TypeScript | 5.5.4 |
| Vite | 8.0.0 |
| Tailwind CSS | 3.4.4 |
| Node.js | актуальная LTS |

---

## 8. Architecture Debt (Canonical TNVED Model)

> Источник: Architecture Review TASK-CANONICAL-002 (Chief Architect, APPROVE WITH NOTES).
> `/children` может читать canonical только за default-OFF флагом. Долги должны быть
> закрыты до serving ON и расширения runtime-adoption.

### Critical
- ~~**Structural parity проверяет не весь контент.**~~ **Закрыто** (Canonical Model
  Materialization): добавлен `test_full_tree_content_parity_with_legacy` — сверяет
  полный контент узлов (name, `display_code`, `is_leaf`, `is_codeless`, `is_group`,
  `import_duty`, notes) рекурсивно против legacy `build_tree()`; проходит на всём дереве.
- ~~**`snapshot_id` не учитывает все входы модели.**~~ **Закрыто**
  (TASK-CANONICAL-005): `canonical-snapshot-v2` хеширует детерминированный output
  модели, включая структуру, имена, `import_duty`, notes и результирующие флаги;
  provider source revision остаётся отдельным rebuild-key.
- **Recovery-логика временно дублируется** в legacy `build_tree()` и в canonical
  (`StructureNormalizer` + Builder). Два источника одной логики до достижения parity —
  риск дрейфа.

### Important
- ~~**Формула `stable_id` не утверждена окончательно.**~~ **Закрыто**
  (ADR-0003 / TASK-CANONICAL-005): `stable-id-v1` — snapshot-independent versioned
  Canonical path hash; будущая смена требует ADR и alias/migration plan.
- **Документация отставала от кода** (001/002 были «Completed» по факту, но `.ai`
  отражал «не начато») — этим обновлением синхронизировано; держать в синхроне.
- ~~**Validator ещё не freeze-gate.**~~ **Закрыто** для `CanonicalModel`:
  `CanonicalModel.from_roots(...)` / `TreeBuilder.build_model(...)` прогоняют
  `TreeValidator` перед freeze; при ошибках модель не создаётся
  (`CanonicalModelValidationError`). Runtime по-прежнему использует legacy-путь.
- ~~**Builder читает БД для `leaf_flags`.**~~ **Закрыто** (TASK-CANONICAL-007):
  `TreeParser` собирает leaf-evidence вместе с остальными входами в одной DB session,
  `TreeParseResult.leaf_flags` делает зависимость явной, а `TreeBuilder` не импортирует
  SQLAlchemy/`SessionLocal`/`HsRate` и выполняет только детерминированное преобразование.
  Явный SQLite `BEGIN` защищает Parser от промежуточного конкурентного commit. Full и
  compact Gate-2 схемы покрыты тестами; parity 18,049/18,049 сохранён.
- ~~**Guided повторно читает Commodity после выбора Canonical snapshot.**~~
  **Закрыто** (TASK-CANONICAL-008): модель хранит frozen source-record projection
  exact Parser build; Guided runtime строит overlay только из неё и fail-safe
  возвращает `DEGRADED`, если projection отсутствует.
- ~~**Parity gate не замечает общий пропуск terminal L4.**~~ **Закрыто**
  (TASK-CANONICAL-009): Parser leaf evidence независимо добавляет exact-rate L4 без
  descendants в required reachability; Gate-2 18,211/18,211.
- ~~**Shared model deep immutability.**~~ **Закрыто** (TASK-CANONICAL-010):
  опубликованные `TreeNode` запрещают assignment/deletion, `children` и
  рекурсивные metadata immutable и detached от pre-publication aliases;
  snapshot и navigation indexes больше не могут разойтись через обычную
  ссылку на узел. Arbitrary custom mutable metadata objects не охватываются
  generic freeze; в production metadata таких объектов нет.
- **PostgreSQL snapshot portability.** SQLite Parser явно фиксирует read snapshot,
  но PostgreSQL default `READ COMMITTED` не гарантирует один snapshot для серии
  `SELECT`; нужен отдельный bounded read-only / repeatable-read design и regression
  до production PostgreSQL rollout.

### Nice to have
- **provenance / history / aliases / breadcrumb** — поля модели из ADR §3.2 ещё не
  реализованы (нужны для Search/RAG/Graph/версионности).
- **SQLite / PostgreSQL / FTS5 долг** — FTS5 вне Alembic; миграция на Postgres
  потребует аналога полнотекстового поиска (ROADMAP §7).
- **Удаление переходных `serializer`/`structure_fingerprint`** после завершения
  миграции (нужны только в переходный период для дифф-тестов).

---

## 9. Open Architecture Decisions

> Решения, которые нужно закрыть осознанно (а не молча) — по `ENGINEERING_PROTOCOL` и
> `agents/architect.md`. Полный контекст — в ADR-0001.

| Решение | Статус | Почему важно | Когда закрыть |
|---------|--------|--------------|---------------|
| **stable_id formula** | ✅ Closed: ADR-0003 `stable-id-v1`; TASK-CANONICAL-005 implemented | ID — первичный ключ для Search/RAG/AI-журнала/Graph; смена формулы позже = миграция всех ссылок | New ADR + alias/migration plan for any change |
| **snapshot_id inputs** | ✅ Closed: ADR-0003 `canonical-snapshot-v2`; TASK-CANONICAL-005 implemented | Snapshot идентифицирует построенный artifact, source revision отдельно управляет rebuild | Revisit only when Canonical output contract expands |
| **Materialized CanonicalModel** | Частично (in-memory `CanonicalModel` реализован; переживающий рестарт снапшот/кэш — Open) | Определяет переживаемость рестарта, память, путь к PostgreSQL | Перед runtime-adoption (кэш по `snapshot_id`) |
| **Feature flag strategy** | ✅ Closed (`CANONICAL_TREE_ENABLED` / `CANONICAL_TREE_SHADOW`, default OFF, request-time) — ADR-0002 Accepted with conditions | Управляет безопасным A/B old-vs-new и откатом | Gate-2 пройден; включение — отдельное решение Ivan |
| **Deadline for legacy `build_tree` removal** | Open (oracle до parity) | Двойная логика — долг; нужен критерий «parity достигнута → удаляем» | После content-parity + стабилизации flag (Этап 6) |
| **First production read-path** | ✅ Completed — `/children` структурный слой за default-OFF флагом; Gate-2 green | Какой эндпоинт первым читает CanonicalModel и как сверяется с legacy | Отдельное решение Ivan о rollout |
| **Nomenclature history / legal code transitions** | Proposed: DM-0004, current-only Canonical remains unchanged | Нужны official source, revision/effective dates, many-to-many split/merge semantics and provenance; нельзя смешивать с lexical synonyms/stable-ID aliases | Ivan decision after source-feasibility audit |
| **Official NTM advisory rollout** | ✅ Closed: DM-0008 Option A, Ivan 2026-08-15; default ON with explicit-false kill switch | Пользователь видит 9 семейств / 30 базовых разделов без broker-влияния | Revisit only for rollout rollback or a new enforcement decision |
| **Export-control family** | ✅ Closed: DM-0009 Option A; 1 087 raw / 1 085 effective candidates | Справочный код не заменяет параметрическую идентификацию | Any enforcement requires a new Ivan decision |
| **NTM legal/catalog completeness** | ✅ Boundary closed by DM-0010; full gate passed on rebuilt official-PDF temp read-only artifact with pinned digests; production DB unchanged | Code-only/partial scope по-прежнему нельзя выдавать за full; 35 blank catalog codes are absent from the pinned active ETT rate snapshot, без вывода о причине/статусе | Повторять gate при PDF/ETT/parser revision |
| **Structured exact NTM / curated bridge** | ✅ DM-0011 implementation boundary closed; exact rows remain advisory and bridge is default OFF | Caller-supplied facts are not a live registry lookup | New explicit rollout decision + trusted adapters before enabling |
| **Guided `2204` PDO interval** | ✅ Closed: DM-0005 Option A Accepted; bounded implementation completed + verified on feature branch | Exact user-visible PDO/PGI boundary accepted; flat/generic-parser options not selected | No merge/rollout/deploy in this docs update; flags OFF |
| Guided `0304` | ✅ DM-0006 Option A | Visible semantics | No rollout |

---

*Обновлять после каждого значимого изменения.*
