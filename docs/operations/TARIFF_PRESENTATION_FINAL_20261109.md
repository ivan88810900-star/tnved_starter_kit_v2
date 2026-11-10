# Конечное локальное представление — 2026-11-09

PR270/очередь257, scope [6739962487](https://github.com/ivan88810900-star/tnved_starter_kit_v2/issues/257#issuecomment-6739962487).
Учтена квитанция [6739362644](https://github.com/ivan88810900-star/tnved_starter_kit_v2/issues/257#issuecomment-6739362644).
R001 не открыт заново: код/независимая симуляция; R002: static на3eae7ee2.
Этот ограниченный PASS не переносится на изменённые файлы/новый runtime.

Baseline head3eae7ee2358c44ffe6cd91c337fc816705a8031c/tree6499c209aadb986f03725539d24ed0e83e92249d,
SQLite45ab63fa4b14fa4a9e1175f10685364249a2fb8eeb890ecf4a6701f53ba9ba2f.
Конечные head/tree/CI привязываются итоговой квитанцией257, без самоссылки SHA
документа внутрь того же коммита.

## Выбранный владельцем контракт

**F001:**37[NNNN] — отдельные неактивные отметки в официальной последовательности,
включая последовательные1402/1403,4108..4111,8004..8006. В той же новой SQLite
добавлена display projection; активная navigation не перестраивается. У отметки
code пустой/kind=reserved/selectable=false/has_children=false; в UI это не кнопка
выбора, нет копирования как HS. Numeric lookup/search/counts её не превращают
в активный код. Сохранены URL/SHA/page/baseline/порядок и оригинальный фрагмент,
в UI есть пояснение/фрагмент/ссылка на PDF. Правовой статус по скобкам не выводится.
17918кодовых строк/13294десятизначных/21207navigation nodes/271alias сохранены;
37отметок считаются отдельно.

**F003:** по PDF определены849узлов с малыми глифами; их набор ID точно совпал
с ранее переданным независимым перечнем. Подпись явно обозначена как упрощённая
поисковая. Для точного чтения показан raster оригинала, сохраняющий10^-6,
Al2O3,H2S,надстрочные ссылки и страничные продолжения. HTML-индексы/значение
или адресат сносок не угадываются. Это честный fallback, не semantic rich-text.
895PNG находятся BLOB в этой же SQLite и выдаются HTTP с проверкой hash; для
каждого — PDF SHA/page/bounds/PNG SHA.37PNG отметок+858фрагментов854активных строк
(849small-glyph и5других spacing rows;4дополнительных продолжения). При сбое
изображения UI явно сообщает, что точное оформление не подтверждено.

**10пробельных различий:** исходное/отображаемое написание, URL/SHA/page,
категория, оценка влияния A0 и статусopen_limitation сохранены в
`data/tnved_presentation_spacing.json`, SQLite и карточке.7относятся к тире в
диапазонах;3 —591132/7304220002/7304293002. «Смыслового изменения при чтении не
обнаружено» — оценка представления, не автоматическое согласование/правовой
вывод. Массовой нормализации и изменения старых имён/путей не было.

## Конечные данные, сборка и проверки

Новый отдельный кандидат SHA256
`5970cdcf9a162417ea4264e3461accd64f1aeddf8e49ea137a3d8b29dedf5021`,130629632байта.
Повторные сборки побайтно равны, включая полную границу последнего глифа.
Все старые таблицы/значения равны45ab; metadata дополнена двумя presentation
ключами. Старые SQLite/PDF/backups/audit packets не перезаписаны. PermanentDB,
Neon,ORM и provider startup не использовались.

Frontend index SHA256
`cee3488eadd6012d3eda69b6a85beea84afd94d11f5d1fc4becadc87a18171ac`;
digest отсортированного списка path/bytes/SHA256
`6eba2526bcb15257c8a5d48fd5873b126085da757a70afddf2d8036c35e1edec`.
Пять frozen файлов, точный список в frontend-manifest.json. Vite build PASS.
Typecheck — те же4TS2339 в PermitDocumentsBlock77/80, новых diagnostics нет;
typecheck PASS не заявляется.

26HTTP/fidelity/catalog/presentation tests PASS. Сквозной HTTP audit обходит
96групп,разделы,все активные узлы/parents/order/search/aliases,37отметок/895PNG.
Он выполнен также на отдельной папке runtime kit с её SQLite и frozen frontend,
без зависимости от working-tree assets. Chrome1440/1280/125%-эквивалент:
96названий,36карточек прежней навигации+18открытий source cases,37отметок в каждой
конфигурации,code clipboard,source links,codeless parent→child,pagination85,
failure/retry и явная ошибка оригинального изображения. Проверяются декодирование
и границы изображений. Авторские screenshot/DOM/Network не называются независимыми
наблюдениями Claude; все895изображений не выдаются за визуально просмотренные.
Точные результаты: [summary](evidence/20261109-presentation/summary.json).

## Воспроизведение

Изcustoms-clear/backend, SOURCE_PY имеет build-only pins, HTTP_PY — HTTPvenv;
выходные пути должны быть новыми:

```bash
"$SOURCE_PY" scripts/build_tnved_presentation.py \
  --base "$BASE45AB" --base-sha256 45ab63fa4b14fa4a9e1175f10685364249a2fb8eeb890ecf4a6701f53ba9ba2f \
  --sources "$OFFICIAL96" --manifest-sha256 baa2708f444176a493c2553972b20516bc6473d6e83348db4f9929e27dd2faa2 \
  --spacing data/tnved_presentation_spacing.json --pdftotext "$PDFTOTEXT" --output "$NEW_SQLITE"
"$HTTP_PY" -m unittest -v tests.test_tnved_fidelity tests.test_tnved_recovery_http \
  tests.test_tnved_catalog_api.HermeticTnvedCatalogApiTests tests.test_tnved_presentation
"$HTTP_PY" scripts/audit_tnved_presentation.py --base "$BASE45AB" --candidate "$NEW_SQLITE" \
  --url http://127.0.0.1:18008 --registry "$RETAINED_REGISTRIES" --glyph-findings "$RETAINED_F003" \
  --output "$NEW_EVIDENCE"
```

Browser: `frontend/scripts/presentation-browser-check.cjs BASE_URL EXPECTATIONS OUT`.
Ожидания сохраняют active frozen baseline/оригинальную физическую последовательность;
fakeSQLite или подмены успешных ответов нет. Ошибки проверяются отдельно.

## Подготовленный доступ Claude

Использованная Cloud-сессия по последнему отчёту не имела MacSQLite/localhost
доступа. Ссылка его не предоставляет. ЛокальныйCLI не найден; осмотр Desktop
недоступен из-за Computer Use permissions у Codex (не доказательство прав Claude).
Никакие права/ключи не менялись.

Автономный runtime kit содержит реальный5970SQLite,4точных Git-модуля HTTP,
frozen frontend,96оригинальных PDF,manifests,pinned dependencies,loopback start и
реальные access probes. Отдельная папка на Mac проверяется по цепочке
SQLite→HTTP→Chrome. Это неOSsandbox. После согласованной передачи **в ту же**
Cloud-сессию проверяется её копия и собственный127.0.0.1, не соединение к Mac.
CloudPython/browser до запуска не считаются доступными; README задаёт setup и
preflight, а инструкция требует собственные PDF/SQL/HTTP/UI, не отчёт автора.
Если browser недоступен, нужен точный capability gap, не UI PASS. Туннель,
publicURL,подменнаяБД,системные права/ключи запрещены.

Внешняя передача новой непубличной SQLite A0 **не выполнялась и ждёт scoped
согласования**. MANIFEST/DATABASE_CONTENTS раскрывают полный состав: catalog,
107исторических непроверенных source notes/68424связи,37markers,10differences,
895PNG; без клиентов/СГР-реестров/.env/ключей/cookies/Neon/private transcripts/
исходного backup. Прежнее согласование JSON не покрывает этот файл. Нужен один
owner handoff существующей сессии выбранного комплекта.

Новый code/data/build не объявляются независимо принятыми. Локальный контракт
F001/F003 реализован,10различий остаются ограничениями. Юридическая актуальность,
ставки и даты не подтверждены. PR draft; DB HOLD/no merge/deploy/enforcement;
A0 один, новых чатов/агентов/расписаний/автоматических model/A6/provider calls нет.
