# KNOWN_PITFALLS.md — Известные ловушки и особенности проекта

> Журнал реальных архитектурных ловушек, найденных в ходе работы с кодом.
> Каждая запись содержит: описание, механизм, последствия, решение.

---

## 1. Pad-коды (XXXX000000) — заголовки, не декларируемые коды

**Файл:** `tnved_catalog.py`, функция `_build_tree()`

**Суть:** В таблице `tnved_commodities` хранятся 10-значные коды вида `9401000000`, `8703000000` и т.п. Это **pad-коды** — технические записи, обозначающие заголовок 4-значной товарной позиции.

**Особенность:** `_node_level("9401000000") == 4` — уровень 4, несмотря на 10 символов.

**Логика обработки:**
```python
pad_code = p4 + "000000"  # например, "9401000000"
deeper = [c for c in codes if c != pad_code]
# pad_code исключается из дочерних узлов
# его description используется для заполнения heading["name"]
```

**Ловушка:** Если pad_code случайно попадёт в дерево как лист — будет отображаться как кликабельный код, хотя он не является декларируемым.

**Решение:** Pad-код всегда исключается из `codes` и используется только для заполнения `name` родительского узла.

---

## 2. L6 синтез — одиночная субпозиция без детей

**Файл:** `tnved_catalog.py`, функция `_classify()` (внутренняя в `_build_tree`)

**Коммит:** `f42d2d4` ("fix: codeless L6 wrappers for lone subheadings")

**Суть:** В базе данных некоторые 6-значные субпозиции (уровень L6, например `0302130000`) не имеют дочерних кодов. По эталонной структуре ТКС такой узел должен быть **бескодовым заголовком**, под которым находится декларируемый лист с тем же кодом.

**Механизм синтеза:**
```python
elif lvl == 6:
    leaf_child = {**node, "is_leaf": True, "is_codeless": False, "is_group": False, "children": []}
    node["children"] = [leaf_child]
    node["is_leaf"] = False
    node["is_codeless"] = True
    node["is_group"] = True
    node["display_code"] = node["code"][:6]  # отображается как "030213"
```

**Итог:**
- Узел `030213` (display_code = первые 6 цифр) — бескодовый заголовок
- Под ним синтетический лист `0302130000` — декларируемый код

**Ловушка:** Без этого синтеза L6-узлы отображались бы как прямые листья без структурного уровня, что противоречит эталону ТКС.

---

## 3. L8 синтез — одиночная подсубпозиция без детей

**Файл:** `tnved_catalog.py`, функция `_classify()`

**Коммит:** `732c1e7` ("fix(tree): synthesize L8 codeless headings in _classify()")

**Суть:** Аналогично L6 — 8-значные коды без дочерних узлов должны быть бескодовыми заголовками, не листьями.

**Пример из коммита:**
```
030211 (codeless) → 03021110 (codeless) → 0302111000 (leaf)
```

**Механизм (зеркалит L6):**
```python
elif lvl == 8:
    leaf_child = {**node, "is_leaf": True, "is_codeless": False, "is_group": False, "children": []}
    node["children"] = [leaf_child]
    node["is_leaf"] = False
    node["is_codeless"] = True
    node["is_group"] = True
    node["display_code"] = node["code"][:8]  # отображается как "03021110"
```

**Масштаб:** Затрагивает ~5872 L8-узла.

**Ловушка:** L8-узлы с уже существующими детьми обрабатываются ветвью `if node["children"]` (выше в `_classify`), а не этой. Не путать два случая.

---

## 4. `_node_level()` — правила определения уровня кода

**Файл:** `tnved_catalog.py`, функция `_node_level(code10: str) -> int`

Уровень определяется по «хвосту» из нулей:

```python
if code10[9] != "0":   return 10  # национальный код (8703211001)
if code10[8] != "0":   return 9   # национальная группа (8703211090)
if code10[6:8] != "00": return 8  # подсубпозиция (8703210000 → НЕТ, 8703211000 → L8)
if code10[4:6] != "00": return 6  # субпозиция (9401200000)
return 4                           # позиция / pad (9401000000)
```

**Ловушка:** Код `9401200000` → L6, а `9401000000` → L4. Не путать по визуальному виду.

---

## 5. `_is_direct_position_subheading()` — прямой потомок L6

**Файл:** `tnved_catalog.py`

```python
def _is_direct_position_subheading(code10: str) -> bool:
    if _node_level(code10) != 6:
        return False
    return code10[4] != "0" and code10[5] == "0"
```

Это субпозиции вида `XXXX30_____` / `XXXX90_____` (5-я цифра ненулевая, 6-я — ноль) — они являются **прямыми потомками 4-значной позиции**, в отличие от субпозиций `XXXX01____`.

Используется при формировании `subheading_group` для pad-sub узлов.

---

## 6. `subheading_group` — codeless-узел для mixed L6

**Файл:** `tnved_catalog.py`, функция `_build_tree()`

`subheading_group` создаётся **только** если:
- Есть pad_sub (подзаголовок из `XXXX000000.description`)
- И есть mix прямых L6 (`direct_l6`) и непрямых L6

```python
use_subheading_group = _needs_pad_subheading_group(pad_sub, level6_codes)
```

**Ловушка:** Если subheading_group создаётся без этого условия — получается лишний уровень в дереве, нарушающий структуру ТКС.

---

## 7. Legacy NTM отключён (`USE_LEGACY_NTM = False`)

**Файл:** `tnved_catalog.py`, строка 68

```python
USE_LEGACY_NTM = False
```

Это означает, что данные из таблицы `non_tariff_measures` (legacy TKS-импорт) **не используются** в badge-блоке карточки товара. Источник нетарифных мер — `get_full_ntm_requirements()` из `tr_ts_catalog.py` (NTM v2 + каталог ТР ТС).

**Ловушка:** Если случайно переключить на `True` — начнут показываться "шумные" legacy-меры (ранее помечены как noise, ~22K из 41K записей).

---

## 8. Особенности `ntm_measures_v2` и NTM v2 контура

**Файлы:** `app/models/ntm_v2.py`, `app/services/ntm_engine_v2.py`

- Таблицы: `ntm_measures_v2`, `ntm_applicability_rules_v2`
- Applicability: `definite` → может влиять на enforcement; `possible` / `needs_clarification` → только advisory
- **Feature flags** (`NTM_V2_*`, `NTM_V2_OFFICIAL_SGR_ADVISORY_ENABLED`): default OFF
- `source_kind` изоляция: `official_sgr_registry` не смешивается с `legacy_non_tariff_rules` без явного merge-policy

**Ловушка:** Не включать official SGR в enforcement без отдельного PR и разрешения Ivan.

---

## 9. FTS5 виртуальная таблица — вне Alembic

**Файл:** `app/services/tnved_fts.py`

FTS5 virtual table `tnved_fts` создаётся в runtime при старте (`normative_store.init_db()`), **не через Alembic**. Это ограничение SQLite FTS5 (Alembic не поддерживает создание virtual tables корректно).

**Ловушка:** При `alembic upgrade head` на свежей БД FTS-индекс не создаётся. Он появляется только после запуска приложения (`uvicorn`).

---

## 10. Дублирующий `revision_id` в Alembic (уже исправлено)

**Исправлено в:** PR #115, миграция `merge_heads_001_merge_payment_heads.py`

**Что было:** Ревизия `a1b2c3d4e5f6` использовалась дважды (`country_tariff_preferences` и `hs_duty_rules`). Алембик падал с ошибкой `Multiple heads`.

**Решение:** Конфликтующая миграция переименована в `a1b2c3d4e5f7`. Создана merge-миграция `merge_heads_001` для объединения трёх голов.

**Урок:** При создании новой миграции всегда проверять уникальность `revision_id`:
```bash
alembic heads  # должна быть одна голова
alembic upgrade head --sql | head  # не должно быть ошибок
```

---

## 11. Устаревшие/резервные описания в `tnved_commodities`

**Файл:** `tnved_catalog.py`, функции `_is_obsolete_reserved_description()`, `_exclude_obsolete_reserved()`

В базе есть ~35 записей с `description` вида `"Товарная позиция..."` — это упразднённые резервные позиции. Они фильтруются из всех запросов:

```python
def _is_obsolete_reserved_description(description):
    return (description or "").strip().startswith("Товарная позиция")
```

**Ловушка:** Если убрать этот фильтр — в дереве и поиске появятся «мусорные» узлы.

---

## 12. `_strip_leading_dashes()` — обязателен для description

Описания в БД содержат ведущие тире «–»/«—» для обозначения иерархии (как в исходном тексте ТН ВЭД). Перед отображением их нужно убирать.

```python
node["name"] = _strip_leading_dashes((r.description or "").strip())
```

**Ловушка:** Не вызывать `_strip_leading_dashes` → пользователь видит «– – молоко свежее» вместо «Молоко свежее».

---

## 13. Китай (CN) — не пользователь ЕСТП с 2021 года

**Исправлено в:** PR #130, fase S

**Что было:** CN числился в `country_tariff_preferences` с GSP-коэффициентом 0.75 (скидка 25% на пошлину). Это неверно — Китай исключён из ГСП с 12.10.2021 (Решение Совета ЕЭК № 17 от 05.03.2021).

**Последствия:** Пошлина для товаров из CN занижалась (8509400000: 6% вместо 8%).

**Решение:** CN переведён в группу `mfn_graduated` (коэффициент 1.0).

**Урок:** При добавлении новых стран в тарифные преференции — проверять актуальность по Решению Совета ЕЭК № 17/2021.

---

## 14. Несовместимость `_classify()` с уже-classified узлами

`_classify()` вызывается **рекурсивно** — сначала обрабатываются дочерние узлы, потом родительский. Если узел уже имеет `children` после первого прохода — он переходит в `is_codeless=True`.

**Ловушка:** Не вызывать `_classify()` дважды на одном дереве — повторный вызов превратит синтетические листья в codeless-узлы.

---

## 15. VAT-ставка 22% — значение по умолчанию с 2026 года

**Файл:** `tnved_catalog.py`, функция `_resolve_rates_for_code()`

```python
elif len(d) >= 4:
    vat_rate = 22.0  # fallback
```

С 01.01.2026 стандартная ставка НДС при импорте — 22% (было 20%). Коды с льготным НДС 10% получают ставку из `hs_rates.vat_import_rate` или `vat_preferences`.

**Ловушка:** Не хардкодить `20.0` в новых вычислениях — везде использовать данные из `hs_rates`.

---

*Журнал обновляется при обнаружении новых ловушек.*
*Создан: 2026-06-26.*
