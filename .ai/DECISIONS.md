# DECISIONS.md — Журнал архитектурных решений (ADR Log)

> Реестр принятых архитектурных решений (Architecture Decision Records).
> Полные документы — в `.ai/decisions/`. Здесь — краткий индекс и статус.

---

## Индекс ADR

| ADR | Название | Статус | Принял | Дата | Документ |
|-----|----------|--------|--------|------|----------|
| ADR-0001 | Canonical TNVED Model | Accepted | Ivan | 2026-06-30 | [`decisions/ADR-0001-canonical-tnved-model.md`](decisions/ADR-0001-canonical-tnved-model.md) |
| ADR-0002 | First production read-path on CanonicalModel (`/children`) | **Proposed** | — (ждёт Ivan) | 2026-07-01 | [`decisions/ADR-0002-canonical-children-read-path.md`](decisions/ADR-0002-canonical-children-read-path.md) |

---

## ADR-0001 — Canonical TNVED Model

**Статус:** Accepted (Ivan, 2026-06-30)

**Суть решения:**

1. **Canonical TNVED Model — центральная source-of-truth модель продукта Tariff.**
   SQLite — это слой **хранения и ingestion**, а не истина. Дерево (`build_tree()`),
   parser, API — это **проекции и контракты доставки**, а не источник истины.
   Все слои (Semantic Navigation, API, AI, NTM, Duty Engine, Search, RAG, Knowledge
   Graph) читают Canonical Model или привязываются к ней по `stable_id` / `anchor`,
   а не перечитывают SQLite для структуры.

2. **Recovery — стадия внутри `tree_engine`**, а **не** отдельный top-level module.
   Логика восстановления неявной структуры (pad-имена, синтез бескодовых L6/L8,
   breadcrumb, очистка имён) выделяется в явную тестируемую стадию pipeline
   `Parser → Recovery → Builder → Validator → freeze()` внутри `tree_engine`.

3. **Semantic Navigation позже переводится на Canonical Model.**
   Экспериментальный overlay перестаёт сам читать БД (`_load_records`) и садится
   на узлы Canonical Model по `anchor_node_id`. Инварианты overlay (group-removal
   invariance, no virtual L5, max depth 2) сохраняются.

4. **Следующая engineering-задача — `TASK-CANONICAL-001`:**
   deterministic `stable_id` (замена `uuid4()` на детерминированный ID от снапшота)
   + recovery stage skeleton внутри `tree_engine`. Без подключения к API/frontend.

5. **Legacy `_build_tree` остаётся production и oracle до достижения parity.**
   Удаляется только после байт-в-байт / fingerprint-совпадения с Canonical Model
   на репрезентативном наборе heading'ов и стабилизации feature flag.

**Прогресс реализации:**
- ✅ **TASK-CANONICAL-001** (Completed) — deterministic `stable_id`, `snapshot_id`,
  recovery skeleton.
- ✅ **TASK-CANONICAL-002** (Completed, Architecture Review: APPROVE WITH NOTES) —
  recovery-логика → `StructureNormalizer`; Builder собирает напрямую (без делегирования
  в legacy); full-tree parity-тесты. Контур изолирован, к runtime не подключён.
- ✅ **Canonical Model Materialization** (Completed) — иммутабельный `CanonicalModel`
  (индексы достижимости + навигация parent/children/path/descendants), validator gate
  перед freeze, freeze/read-only на уровне интерфейса, full-tree content parity с legacy.
  Additive `TreeBuilder.build_model(...)`; `build(...)` без изменений. Не подключён к
  runtime/API/overlay; feature flag не вводился.
- 📝 **ADR-0002** (Proposed) — Decision Memo для первого production read-path `/children`
  на `CanonicalModel`. Меняет source of truth для API частично/временно → требует
  утверждения Ivan **до кода**. См. ниже §ADR-0002.
- 📋 **TASK-CANONICAL-004** (blocked-on-decision) — инженерная спецификация под ADR-0002:
  `/children` читает структуру из `CanonicalModel` за `CANONICAL_TREE_ENABLED`
  (default OFF, request-time) + отдельный `CANONICAL_TREE_SHADOW`; provider с build-once
  кэшем и validator gate; overlay через существующий `_serialize_tree_node` без изменений;
  legacy `build_tree()` остаётся oracle. Код — только после ADR-0002 Accepted.
  См. `.ai/tasks/TASK-CANONICAL-004.md`.
- ▶ Параллельный derisking-остаток — расширение входов `snapshot_id`/revision (hs_rates/
  leaf-флаги, import_duty, примечания) и закрытие формулы `stable_id`. См. `.ai/ROADMAP.md`
  и `.ai/CURRENT_STATE.md` §2b/§8/§9.

**Открытые Decision-точки** (полный список со статусами/сроками — `.ai/CURRENT_STATE.md`
§9 «Open Architecture Decisions»):
- Формула `stable_id` (черновой `node-<hex>`, окончательно не утверждена).
- Состав входов `snapshot_id` (сейчас только `db_codes`, не учитывает `hs_rates` и др.).
- Где материализуется модель: in-memory vs materialized-снапшот.
- Стратегия feature flag (`CANONICAL_TREE_ENABLED`).
- Дедлайн удаления legacy `build_tree` после parity.
- Первый production read-path.

**Архитектурные долги:** `.ai/CURRENT_STATE.md` §8 (Critical / Important / Nice to have).

**Инварианты (binding):** I1–I22 в полном ADR (no virtual L5, no fake codes,
stable ids, детерминизм, реальные коды достижимы, одна модель истины, semantic
overlay не меняет структуру, AI ничего не изменяет, snapshot-консистентность и др.).

---

## ADR-0002 — First production read-path on CanonicalModel (`/children`)

**Статус:** Proposed (ждёт утверждения Ivan; код не начинать до Accepted)

**Суть решения:**

Первым перевести на `CanonicalModel` **только** endpoint `GET /api/v1/tnved/children/{code}`
(+ compat), и **только его структурный слой**, за feature flag `CANONICAL_TREE_ENABLED`
(**default OFF**, читается **request-time**), с отдельным `CANONICAL_TREE_SHADOW`
(сравнивает legacy vs canonical, служит legacy). Overlay/enrichment (`_serialize_tree_node`:
ставки/НДС/меры/permit) **остаётся существующим legacy-путём**. Legacy `build_tree()` —
**oracle**. JSON-контракт **не меняется** (I20). Смена source of truth — **частичная и
временная**; откат — **одной переменной**; сбой canonical → **fallback на legacy без 500**.

**Ключевые обоснования:** `/children` — самый дорогой legacy-путь (до 2M строк/запрос) и уже
покрыт parity; flag OFF/request-time — обратимость и мгновенный откат; отдельный shadow —
ортогональность serving и наблюдения; cache build-once — иначе воспроизводится худшая
сторона legacy; overlay не мигрирует — свежесть данных + `source_kind`/enforcement.

**Риски (binding для реализации):** `snapshot_id`/revision обязан включать влияние
`hs_rates` (leaf-флаги) и `tnved_commodities` (иначе stale cache); латентность первого
запроса; усечённая dev-БД (ложные mismatch); shadow overhead; structural mismatch на
краевых кодах.

**Blocking gates (APPROVE WITH NOTES):** до первого `CANONICAL_TREE_ENABLED=1` в любом
окружении — **Gate-1**: revision/cache invalidation обязан учитывать `tnved_commodities` +
`hs_rates` (leaf_flags / `is_leaf_hs_code`); **Gate-2**: полный offline-обход всех
`/children` кодов на полной БД = 0 mismatch. **Тип кэша решён:** in-memory singleton;
persistent materialization в TASK-004 не делаем (blast radius / rollback).

**Decision-точки для Ivan:** утвердить `/children` как первый read-path; Gate-1 (состав
revision-маркера); Gate-2 (критерий serving ON); тип кэша (in-memory на этот этап).

**Реализация:** `.ai/tasks/TASK-CANONICAL-004.md` (blocked-on-decision). Полный документ:
`.ai/decisions/ADR-0002-canonical-children-read-path.md`.

---

*Журнал обновляется при принятии каждого нового ADR.*
