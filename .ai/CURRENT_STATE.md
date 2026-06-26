# CURRENT_STATE.md — Текущее состояние проекта

> Дата: 2026-06-26
> Последний коммит: `f42d2d4` (fix: codeless L6 wrappers for lone subheadings)

---

## 1. Реализованные функции

### Ядро платформы

- **Справочник ТН ВЭД** — полное дерево (разделы → группы → позиции → субпозиции → коды), FTS5-поиск по всей номенклатуре (BM25), карточка товара
- **AI-классификация** — Gemini structured JSON (код, обоснование, confidence_score, атрибуты), Claude Vision для фото
- **Расчёт платежей** — пошлина, НДС (22%/10%), акциз, антидемпинг, спецпошлины, утильсбор (РОП), тарифные преференции (161 страна)
- **Нетарифные меры** — ТР ТС каталог (96+ глав), NTM v2 контур, noise-classifier (22K записей), структурированный UI без сырого TKS-текста
- **Инвойс / пакинг-лист** — загрузка XLSX/CSV, Vision-классификация, async-задачи, экспорт в Excel
- **ТРОИС** — opendata ФТС (CSV ~42MB), fuzzy-поиск, cron-синхронизация
- **ФСА/СС/ДС** — opendata (7Z-архивы), backfill истории, мгновенная проверка номера
- **AI-ассистент** — copilot pipeline, batch-режим, RAG (PDF/TXT/MD), журнал решений, semantic search (embeddings)
- **РОП / экосбор** — ставки ПП №1041/2414, 39 категорий ТС, audit 97 глав
- **Официальные данные** — ETT 99.8%, VAT 100%, Excise 100%, Anti-dumping 82.8%, Special Safeguard 100%, Countervailing 100%

### Инфраструктура

- Alembic: ~60 миграций, merge-голова восстановлена (PR #115)
- APScheduler: cron-задачи (курсы ЦБ, ФТС краулер, РОП, ТРОИС, ФСА)
- GitHub Actions: auto-merge, claude-pr-reviewer, cursor-task-agent, opendata-sync (05:00 UTC)
- Rate limit middleware, JWT auth, admin token
- Docker + nginx.conf для production

---

## 2. Активная задача

### Исправление структуры дерева ТН ВЭД под эталон ТКС

**Цель:** Структура дерева в приложении должна совпадать со структурой на tks.ru.

**Проблема:** Некоторые коды отображались как прямые листья там, где по эталону должны быть бескодовые заголовки с декларируемым листом под ними.

**Выполненные шаги:**
1. `732c1e7` — L8 синтез: одиночные L8-узлы без детей → codeless heading + synthetic leaf
2. `f42d2d4` — L6 синтез: одиночные L6-субпозиции без детей → codeless heading + synthetic leaf

**Статус:** Оба фикса применены. Текущая ветка — основная (`main`).

**Проверка:**
```bash
curl http://localhost:8001/api/v1/tnved/children/0302
# Ожидается: L6 узлы как codeless, под ними L8 codeless, под ними 10-digit листья
```

---

## 3. Последние архитектурные изменения

| Коммит | Дата | Описание |
|--------|------|---------|
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
- **ФТС предрешения:** live-парсер не реализован (customs.gov.ru/folder/519 — статистика, не предрешения)
- **ТРОИС:** fuzzy-поиск может давать false positives на коротких запросах

### Архитектура
- **SQLite** — ограничение параллельных записей; для production рекомендуется PostgreSQL (DATABASE_URL поддерживает)
- **FTS5** — вне Alembic, создаётся только при старте приложения
- **NTM v2 feature flags** — по умолчанию OFF, требует явного включения Иваном
- **L6/L8 синтез** — производительность: на каждый запрос к дереву пересчитывается из БД (кэш не реализован)

### Frontend
- **Тайпскрипт типы** — `openapi.generated.ts` требует ручной регенерации (`npm run gen:api-types`) при изменении схемы API
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

*Обновлять после каждого значимого изменения.*
