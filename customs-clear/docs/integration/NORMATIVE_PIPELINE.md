# Пайплайн: актуальный тариф, полный ТН ВЭД, примечания, нетарифка

Официальный сайт ЕЭК публикует ТН ВЭД и ЕТТ преимущественно в **PDF по группам** ([ТН ВЭД ЕАЭС и ЕТТ](https://eec.eaeunion.org/comission/department/catr/ett/)), без единого открытого API «все коды + все пояснения» в одном файле. Поэтому в приложении реализована **сводная локальная БД** и **контракт импорта**, который вы можете наполнять:

1. **Готовыми таблицами** (Excel TWS.BY — коды и пошлины, см. [tws_by.md](./tws_by.md)).
2. **Собственным ETL** (парсинг PDF, коммерческий датасет, интеграция партнёра) → выгрузка в **JSON-пакет**.
3. **Плановой синхронизацией** по URL (`NORMATIVE_BUNDLE_URL`, `NORMATIVE_FEED_URL`, `NORMATIVE_CSV_URL`, `POST /api/sources/sync`).

## Слои данных в БД

| Слой | Таблица | Назначение |
|------|---------|------------|
| Ставки ЕТТ, НДС-логика, акциз, антидемпинг | `hs_rates` | Расчёт платежей, поиск по коду |
| Наименования и пояснения позиций | `tnved_entries` | Справочник, калькулятор (`tnved_context`) |
| Примечания (ТН ВЭД / ЕТТ / нетариф / общие) | `normative_notes` | Привязка к коду, префиксу, главе или глобально |
| Нетарифные правила (ТР ТС, виды разрешений) | `non_tariff_rules` | Экран «Нетарифка», проверка разрешений |

## JSON-пакет (`customs_clear_normative_bundle`)

Файл-пример: `backend/data/normative_bundle.example.json`.

Секции (все опциональны, кроме распознавания формата):

- `format`: `"customs_clear_normative_bundle"` (или эвристика: есть массив `tnved`).
- `revision`: строка версии выгрузки.
- `tnved[]`: `hs_code`, `parent_hs`, `level`, `title`, `description`, `chapter`, `source_url`, `source_revision`.
- `rates[]` / `rows[]`: те же поля, что и для импорта ставок (совместимо с `NORMATIVE_FEED`).
- `non_tariff_rules[]`: `name`, `hs_prefix`, `tr_ts`, `required_permits`, **`tr_ts_edition`** (текст редакции ТР), **`exception_note`** (исключения), **`priority`** (число, больше — выше в списке), даты, источник.
- `notes[]`: `scope_type` (`global` | `chapter` | `prefix` | `hs_code`), `scope_value`, `category` (`tnved` | `ett` | `non_tariff` | `general`), `title`, `body`, `sort_order`.

### Загрузка

- `POST /api/sources/import` — если файл `.json` и распознан пакет, импортируются все секции.
- `POST /api/sources/import/bundle` — явный импорт только пакета.
- `GET /api/sources/template/bundle` — скачать пример.
- `NORMATIVE_BUNDLE_URL` + `POST /api/sources/sync` или `POST /api/sources/sync/bundle`.

## API справочника

- `GET /api/tnved/stats` — счётчики записей.
- `GET /api/tnved/search?q=` — код или текст наименования.
- `GET /api/tnved/lookup/{hs_code}` — карточка + иерархия + примечания.
- `GET /api/tnved/notes/{hs_code}?category=` — только примечания.

Калькулятор: в ответе `POST /api/calculator/compute` добавлено поле **`tnved_context`** (наименование, цепочка, примечания, ссылка на ЕЭК).

Нетарифка: в `notes` ответа подмешиваются строки из `normative_notes` с `category: "non_tariff"`.

## Рекомендуемый процесс обновления

1. Регулярно загружать **ставки** (Excel TWS или ваш CSV/JSON).
2. Раз в редакцию ТН ВЭД обновлять **номенклатуру и примечания** через пакет (свой конвейер или подрядчик).
3. Вести **нетарифные правила** в пакете или отдельным импортом строк в ту же схему.
4. Включить планировщик (`SCHEDULER_ENABLED`) для `sync` или вызывать `POST /api/sources/sync` по cron.

Юридически значимыми остаются **официальные тексты** на портале ЕЭК и акты; локальная БД — рабочая копия для декларанта с явной `revision` и журналом `sync_log`.
