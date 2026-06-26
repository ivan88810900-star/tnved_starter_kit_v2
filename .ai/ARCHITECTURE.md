# ARCHITECTURE.md — Архитектурная документация CustomsClear

> Составлен на основе анализа кода. Не копирует существующий ARCHITECTURE.md в корне.
> Фокус: модули, потоки данных, ключевые алгоритмы.

---

## 1. Модули и зависимости

```
customs-clear/backend/
├── app/main.py                    # Точка входа FastAPI
│   ├── lifespan()                 # startup: init_db, exchange_rates, APScheduler
│   ├── CORS middleware
│   ├── RateLimitMiddleware (опц.)
│   └── include_router × 25       # подключение всех роутеров
│
├── app/api/tnved_catalog.py       # ГЛАВНЫЙ ФАЙЛ: дерево ТН ВЭД
│   ├── _build_tree()              # плоский список → дерево 4→6→8→10
│   ├── _classify()                # классификация узлов (leaf/codeless/group)
│   ├── _wrap_in_sections()        # оборачивает дерево в разделы
│   ├── list_tnved_children()      # API: дочерние узлы
│   └── GET /hierarchy-tree        # полное дерево
│
├── app/services/normative_store.py # ЦЕНТРАЛЬНЫЙ СЕРВИС
│   ├── init_db()                  # seed + FTS-индекс
│   ├── find_rate_for_hs()         # ставка по коду
│   └── is_leaf_hs_code()          # проверка листа
│
├── app/services/tr_ts_catalog.py  # КАТАЛОГ ТР ТС
│   ├── get_full_ntm_requirements() # объединённые NTM требования
│   └── TR_TS_FULL_NAMES{}         # словарь полных названий
│
└── app/services/ntm_engine_v2.py  # NTM v2 ENGINE
    └── get_tr_ts_requirements_for_pipeline()
```

### Зависимости сервисов

```
tnved_catalog.py
    ├── normative_store.py (find_rate_for_hs, is_leaf_hs_code)
    ├── tr_ts_catalog.py (get_full_ntm_requirements, get_tr_ts_requirements)
    ├── ntm_engine_v2.py (get_tr_ts_requirements_for_pipeline)
    ├── non_tariff_measures_lookup.py (get_measures_for_code)
    └── tnved_code_card.py (find_preliminary_decisions_for_hs)

payment_engine.py
    ├── normative_store.py
    ├── exchange_rates.py
    └── rop_calculator.py

assistant_orchestrator.py
    ├── invoice_analyzer.py
    ├── payment_quote_service.py
    ├── non_tariff_service.py
    └── permits_service.py
```

---

## 2. Основные потоки данных

### 2.1 Invoice Pipeline (анализ инвойса / пакинг-листа)

```
POST /api/invoice/upload
    │
    ├── packing_list_parser.py
    │   └── автоопределение колонок (CN/EN/RU, фото)
    │
    ├── smart_classifier.py
    │   ├── batched CN → RU перевод
    │   ├── dedupe по (name_cn, material)
    │   ├── Claude Vision (если есть фото)
    │   └── web-search fallback (артикул)
    │
    ├── invoice_analyzer.py
    │   ├── suggest_hs_code_for_item() → Gemini structured JSON
    │   │   {hs_code, justification, confidence_score, ...}
    │   ├── _calculate_financials() → duty, VAT, ROP
    │   └── check_geopolitical_risks() → embargo / increased_duty
    │
    └── packing_list_export.py
        └── Excel report (колонки: ТН ВЭД, уверенность, обоснование)
```

### 2.2 Дерево ТН ВЭД (Tree Pipeline)

```
GET /api/v1/tnved/children/{code}
    │
    ├── list_tnved_children(db, code)
    │   │
    │   ├── _resolve_tree_node(db, code)
    │   │   ├── _build_wrapped_tree(db, prefix)
    │   │   │   ├── db.query(Commodity).filter(code LIKE prefix%)
    │   │   │   │   → до 2 000 000 строк
    │   │   │   ├── _collect_chapter_notes(db)
    │   │   │   ├── _build_tree(rows, chapter_notes)
    │   │   │   │   ├── Группировка по p4 (первые 4 цифры)
    │   │   │   │   ├── Обработка pad_code (XXXX000000)
    │   │   │   │   ├── Построение stack-based дерева
    │   │   │   │   ├── _classify() — рекурсивная классификация узлов
    │   │   │   │   │   ├── if children: → is_codeless=True
    │   │   │   │   │   ├── elif lvl==6: → L6 синтез (f42d2d4)
    │   │   │   │   │   ├── elif lvl==8: → L8 синтез (732c1e7)
    │   │   │   │   │   └── else: → is_leaf_hs_code()
    │   │   │   │   └── _sort()
    │   │   │   └── _wrap_in_sections(flat, db)
    │   │   │       └── Section → Chapter → Heading (4-digit)
    │   │   └── _find_node_in_tree(tree, code)
    │   │
    │   └── [_serialize_tree_node(db, ch) for ch in children]
    │       ├── _resolve_rates_for_code() → duty, vat_rate
    │       ├── _permit_flags_for_hs() → has_ds, has_ss
    │       └── _measures_for_api() → measure badges
    │
    └── Response: {status, code, depth, items[]}
```

### 2.3 Нетарифные меры (NTM Pipeline)

```
get_full_ntm_requirements(hs_code, description)  [tr_ts_catalog.py]
    │
    ├── Каталог ТР ТС (hardcoded rules + DB tr_ts_acts)
    │   └── prefix-matching: 6-digit → 4-digit → 2-digit
    │
    ├── ntm_engine_v2.py (если включён feature flag)
    │   ├── ntm_measures_v2 + ntm_applicability_rules_v2
    │   └── applicability: definite/possible/needs_clarification
    │
    └── ntm_layers.py (legacy layers, если включён)
        └── non_tariff_rules (legacy TKS)

Result: [{permit_type, tr_ts, description, short_description, ...}]
    │
    └── _convert_ntm_v2_to_display() → [{measure_type, document_required, ...}]
```

### 2.4 Расчёт платежей

```
POST /api/calculator/compute
    │
    ├── payment_engine.py
    │   ├── hs_rates → import_duty, vat_import_rate, excise
    │   ├── country_tariff_preferences → duty_coefficient
    │   ├── geo_special_duties → embargo / increased_duty
    │   ├── special_duties → anti-dumping
    │   ├── exchange_rates → USD/EUR → RUB
    │   └── rop_calculator.py → РОП / утильсбор
    │
    └── Response: {breakdown: {duty_rate, vat_rate, recycling_fee, ...}, total_payable}
```

---

## 3. Взаимодействие Frontend/Backend

### API Proxy (Vite)

```
Browser → :3000
    └── /api/* → Vite proxy → http://localhost:8001/api/*

vite.config.ts:
  server.proxy['/api'] = `http://${apiHost}:${apiPort}`  # default: localhost:8001
```

### Frontend API-слой

```typescript
// src/api/client.ts
const client = axios.create({ baseURL: '/' });

// src/api/tnvedCatalog.ts
export const fetchChildren = (code: string) =>
    client.get(`/api/v1/tnved/children/${code}`);

export const fetchNode = (code: string) =>
    client.get(`/api/v1/tnved/node/${code}`);
```

### Типы API

- `src/api/openapi.generated.ts` — автогенерируется из OpenAPI schema
- `src/types/api.types.ts` — дополнительные ручные типы
- Регенерация: `npm run gen:api-types` (требует запущенный backend на :8001)

---

## 4. Устройство дерева ТН ВЭД

### Иерархия уровней

```
Раздел (roman_number: "I" ... "XXI")         [is_group=True]
  └── Группа (2-digit: "01" ... "97")        [is_group=True]
        └── Позиция (4-digit: "0101")         [is_group=True]
              └── Субпозиция (6-digit: синт.) [is_codeless=True, display_code=6 цифр]
                    └── Подсубпозиция (8-digit: синт.) [is_codeless=True, display_code=8 цифр]
                          └── Код (10-digit)  [is_leaf=True]
```

### `_build_tree()` — ключевые шаги

1. **Сортировка по p4** — группировка 10-значных кодов по первым 4 цифрам
2. **Обработка pad_code** — `XXXX000000` извлекается, используется для `heading.name`
3. **stack-based построение** — обход кодов в порядке возрастания, stack хранит (level, node)
4. **_classify()** — постобработка: определяет is_leaf/is_codeless/is_group
5. **L6/L8 синтез** — одиночные узлы без детей оборачиваются синтетическим листом

### `_classify()` — логика

```python
def _classify(node):
    for ch in node["children"]:
        _classify(ch)  # сначала дети (post-order)
    
    if len(node["display_code"]) == 10:
        if node["children"]:
            # Уже имеет детей → бескодовый заголовок
            node["is_leaf"] = False
            node["is_codeless"] = True
        else:
            lvl = _node_level(node["code"])
            if lvl == 6:   # L6 синтез
            elif lvl == 8: # L8 синтез
            else:          # проверка is_leaf_hs_code()
```

### `_wrap_in_sections()` — финальная сборка

Принимает плоский список 4-значных узлов, строит полную иерархию:
- Загружает `Section` + `Chapter` из БД (один запрос с `selectinload`)
- Сортирует разделы по `_ROMAN_RANK` (порядок I, II, ..., XXI)
- Каждый Chapter-узел получает свои heading-узлы по `ch_prefix` (первые 2 цифры кода)

---

## 5. Нетарифные меры — архитектура слоёв

### Три контура (от приоритетного к устаревшему)

```
1. NTM v2 (целевой)
   └── ntm_measures_v2 + ntm_applicability_rules_v2
   └── applicability: definite → enforcement, possible → advisory

2. ТР ТС каталог (runtime)
   └── tr_ts_catalog.py — hardcoded + tr_ts_acts table
   └── 6-digit prefix matching

3. Legacy TKS (отключён)
   └── non_tariff_measures table
   └── USE_LEGACY_NTM = False
```

### Badge приоритет

```python
priority = {
    "ДС": 0, "СС": 1, "СГР": 2,
    "Фито": 3, "Вет": 4, "ФСС": 5, "ВС": 6,
    "Серт": 7, "ЛЗ": 8, "Марк": 9, "ФСТЭК": 10, "НФ": 11, "Рад": 12,
    "РУ": 13,
}
```

---

## 6. API — роуты, версии, middleware

### Версионирование

| Prefix | Статус | Описание |
|--------|--------|---------|
| `/api/v1/tnved` | Актуальный | Дерево ТН ВЭД (`tnved_catalog.py`) |
| `/api/v1/admin` | Актуальный | Административные функции |
| `/api/v1/finance` | Актуальный | Финансы |
| `/api/v1/documents` | Актуальный | Документы v1 |
| `/api/tnved/classify` | Compat-алиас | → `/api/classify` |
| `/api/assistant` | Актуальный + compat | chat-router дублируется |

### Middleware (порядок)

```python
app.add_middleware(CORSMiddleware, ...)     # CORS
app.add_middleware(RateLimitMiddleware, ...) # Rate limit (опц.)
```

### Health endpoints

| Endpoint | Назначение |
|----------|-----------|
| `GET /api/health` | Simple OK |
| `GET /api/health/ready` | DB + Redis + LLM |
| `GET /api/health/normative` | Статистика нормативной БД |
| `GET /api/health/data-pipeline` | Источники данных + sync log |
| `GET /api/health/pipeline` | CI validation |

---

## 7. Внешние интеграции

| Сервис | Использование | Файл |
|--------|--------------|------|
| Gemini (Google) | AI-классификация, invoice анализ | `gemini_genai_configure.py` |
| Anthropic (Claude) | Опциональный AI | `claude_service.py` |
| ЦБ РФ | Курсы валют | `cbrf.py`, `exchange_rates.py` |
| ФСА opendata | Сертификаты, свидетельства | `opendata_fsa.py` |
| ФТС opendata | ТРОИС | `opendata_trois.py` |
| opendata.gov.ru | Открытые реестры | `opendata_client.py` |
| Redis | Кэш (опц.) | `cache_layer.py` |

---

*Создан: 2026-06-26 на основе анализа кода репозитория.*
