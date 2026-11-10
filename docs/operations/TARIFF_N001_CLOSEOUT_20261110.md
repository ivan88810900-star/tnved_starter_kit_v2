# N-001 — размещение неактивных отметок и путь

Продолжение PR270, [задание6763376082](https://github.com/ivan88810900-star/tnved_starter_kit_v2/issues/257#issuecomment-6763376082),
[ownership6763466332](https://github.com/ivan88810900-star/tnved_starter_kit_v2/issues/257#issuecomment-6763466332).
Baseline HEAD `7bfd7b5fd8607e3e9b472adf43d5b3acc43697de`,
tree `e3ea9180cf070a0b62e4aa0df1c1b2cb78eb487a`.
Конечный новый HEAD/tree/CI закрепляет итоговая квитанция257: без самоссылки
SHA документа внутрь того же коммита. Полный полученный аудит не повторялся.

## Полученная независимая проверка

REPORT SHA256 `58bd9644930b9a14b87c5bbc143ed0328eb96aeed7c0650a166ab1922ca5da38`;
ZIP SHA256 `f36f2744ab41d0aee23e9548b86886ffe065a96418cde60cd11b43544e8dc025`,
9091458байт. Отдельный REPORT равен ZIP-копии; CRC/path/symlink/encryption/duplicate
checks PASS. Оригиналы сохранены отдельно, аудиторские скрипты A0 не запускал.

По полученному отчёту Claude **сам наблюдал** SQLite5970 (hash до/после,
integrity/FK), SQL, собственный loopback HTTP и headless Chromium/DOM/Network.
Поэтому старый NOT_STARTED больше не описывает независимую проверку7bfd.
Заявлены21090физических строк/21207navigation nodes/37markers/65097GET основного
обхода/895фрагментов, сопоставленных с собственным PDF-render/271alias. Это
наблюдения в среде Claude, не просмотр Mac владельца и не визуальный просмотр
всех карточек. Найден один подтверждённый дефект N-001, остальные выводы имеют
границы отчёта. Предыдущая проверка R001=код+симуляция, R002=static сохранена;
R001/R002 не переоткрывались. F003 подтверждён как fallback, не rich-text или
интерпретация сносок;10spacing distinctions остаются open_limitation.

Комплектность: OUTPUT-MANIFEST77файлов,76присутствуют с верными SHA.
`http/children-edges.json` отсутствует, его заявленный SHA256:
`67b89027d43626cb47352f08a1a8cd6fe40b0ca7aaf8f155e669d2ab7b19c240`.
Этот недостающий артефакт ограничивает воспроизводимость полного аудиторского
HTTP-обхода; не считается новым дефектом продукта и не восстановлен фиктивно.
В точечном запросе запрошен **уже существующий** файл с прежним SHA, если он
сохранился у Claude, иначе отсутствие остаётся явно зафиксированным.

Sources ZIP тогда не был передан; Claude использовал96ранее полученных PDF с
теми же SHA. Это отдельное ограничение, не отсутствие children-edges. Указаны
headless Chromium153, Playwright1.63.0 вместо1.62.1 и незакреплённый
opentelemetry-api1.45.2. Google Fonts вызывает внешний запрос, auth/me даёт404
в изолированном профиле; полностью offline/no-network режим не заявляется.

## Общая причина и исправление

SQL уже сохранял правильные before_order/marker_order. Старый read adapter
подмешивал marks только к chapter и строил путь через chapter; caption терялся.
Новая логика использует навигационную строку **перед** before_order и её реальный
контейнер chapter/caption, проходя вверх через coded/codeless ancestors. Если
отметка стоит прямо перед новой caption, она остаётся в предшествующей открытой
подгруппе. До первой caption используется chapter; последовательные marks
сохраняют marker_order. Списка исключений по четырём кодам нет.

Один resolver используется для children, parent, path и breadcrumb. Только
назначенный контейнер получает отметку; контейнер с одними marks раскрывается.
Активная нормативная структура, исходные порядки и данные не перестраиваются.

| Отметка | Правильный контейнер | Прямые соседи в списке |
|---|---|---|
| [2838] | 28 / V | 2837 → [2838] → 2839 |
| [2848] | 28 / VI | 2847000000 → [2848] → 2849 |
| [2851] | 28 / VI | 285000 → [2851] → 2852 |
| [6908] | 69 / II | 6907 → [6908] → 6909 |

## Точные данные и авторские регрессии

SQLite **не менялась**: SHA256
`5970cdcf9a162417ea4264e3461accd64f1aeddf8e49ea137a3d8b29dedf5021`,130629632байта.
Работа выполнена с отдельной read-only копией. Старые SQLite/PDF/backup/пакеты
не перезаписывались. Frontend не пересобирался: index SHA256
`cee3488eadd6012d3eda69b6a85beea84afd94d11f5d1fc4becadc87a18171ac`;
digest канонического списка пяти path/bytes/SHA256
`6eba2526bcb15257c8a5d48fd5873b126085da757a70afddf2d8036c35e1edec`
(это не hash байтов frontend-manifest.json).

Замороженное ожидание Claude `auditor-expected-final.json`, SHA256
`25137a75a45f2ad2251d74b7146d21aab9b22e2757b928da8280cdee1a092aba`,
сопоставлено по идентичности37markers и предыдущим/следующим физическим строкам,
caption и последовательным marks. Новый SQL→HTTP targeted audit:
129списков chapter/caption,316запросов на прогон. До исправления — ровно4ошибки;
после —37/37 правильны, каждая встречается один раз. Карточки33marks полностью
равны исходным по всем полям JSON; в4меняются только path/breadcrumb. Все активные элементы
129списков равны до/после. Поиск37зарезервированных числовых позиций=0, числовой
lookup=404; code пустой, selectable/is_leaf/has_children=false. Проверены ближайшие
физические соседи и последовательные группы, а не только количество37.

Все895PNG BLOB сверены по SHA,37markerPNG дополнительно прочитаны по HTTP.
Весь файл SQLite совпал до/после;21207узлов,13294активных10-значных кода,271alias
сохранены. Parser/source-text/source/PDF-render/image/search механизмы неизменны;
R001 и R002 не затронуты. Frontend-source/build байты неизменны.

29unit tests PASS (26прежних+3общие topology/sequence/path regression), gate4/4,
0skipped. Проверены также границы перед первой/следующей caption и хвост,
deep coded/codeless ancestors, последовательные marks и контейнер только с mark.
Chrome1440/1280/125%-эквивалент:28 V/VI,69 II,контроль05 и14/41/80;
15marks×3конфигурации до и после. Проверены collapsed/expanded captions и chapter,
единственное появление после повторного раскрытия, соседство,неактивность и HTTP
breadcrumb. Сохранены screenshots/DOM/Network; это доказательства A0, не Claude.
Все37проверены машинно; UI не объявляется просмотренным для всех37.

## Команды

Из customs-clear/backend, HTTP_PY — существующий Python3.12 HTTPvenv. Все OUT
должны быть новыми; BASELINE — сохранённые **A0** replies до исправления, не
отсутствующий файл Claude. EXPECTED — преобразованные37ожиданий из frozen JSON.

```bash
"$HTTP_PY" -m unittest -v tests.test_tnved_fidelity tests.test_tnved_recovery_http \
  tests.test_tnved_catalog_api.HermeticTnvedCatalogApiTests tests.test_tnved_presentation
"$HTTP_PY" scripts/run_tnved_recovery_ci.py
"$HTTP_PY" scripts/audit_tnved_reserved_placement.py \
  --database "$COPY5970" --expected "$EXPECTED" --url http://127.0.0.1:18009 \
  --before "$BASELINE" --output "$OUT"
```

Browser из корня repo:
`node customs-clear/frontend/scripts/reserved-placement-browser-check.cjs URL EXPECTED OUT fixed`.
Режим before направляется на отдельный профиль точного7bfd, не на новый код.
Точные команды/логи/снимки сохранены локально; безопасный summary — рядом с этим
документом в evidence/20261110-n001/summary.json. CI привязывается итоговой квитанцией
к новому exact HEAD; старый CI не используется как проверка нового кода.

## Точечная независимая перепроверка

Новый пакет содержит только точный код/patch/tests/версию/инструкцию/проверку
идентичности. Новая SQLite/PDF/frontend выгрузка не требуется: в той же Claude
сессии уже есть5970и5файлов frontend, их SHA повторно проверяется. Launcher
использует их только чтением и не перезаписывает старый пакет/MANIFEST. Код
нового runtime лежит отдельно, сервер только127.0.0.1:18009. Внешняя передача
A0 не выполняется. Автоматических A6/provider calls нет.

Claude должен сопоставить все37markers со **своим** frozen PDF-ожиданием, а не
счётчиками A0; проверить parent/path/breadcrumb/соседей/неактивность и четыре
позиции в своём HTTP/браузере. Перечитывать1397страниц/повторять весь65097GET
не требуется: source/data/parser/frontend не менялись. Отдельно вернуть реальный
children-edges с прежним hash, если он существует; не генерировать замену под
видом старого доказательства. Новый код остаётся pending targeted recheck;
full PASS и приёмка до него не заявлены. После успешного recheck можно отдельно
предложить владельцу приёмку **локального структурного** справочника с F003
fallback и10ограничениями; merge/deploy/правовой допуск/ставки вне этого решения.

A0 один; DB HOLD/no merge/deploy/enforcement/permanent DB/new agents/chats/
schedules/automatic external transmission сохраняются.
