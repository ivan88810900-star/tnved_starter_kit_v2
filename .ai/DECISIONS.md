# DECISIONS.md — Журнал архитектурных решений (ADR Log)

> Реестр принятых архитектурных решений (Architecture Decision Records).
> Полные документы — в `.ai/decisions/`. Здесь — краткий индекс и статус.

---

## Индекс ADR

| ADR | Название | Статус | Принял | Дата | Документ |
|-----|----------|--------|--------|------|----------|
| ADR-0001 | Canonical TNVED Model | Accepted | Ivan | 2026-06-30 | [`decisions/ADR-0001-canonical-tnved-model.md`](decisions/ADR-0001-canonical-tnved-model.md) |

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
- ▶ Рекомендуемый следующий этап — **Derisking (остаток)**: расширение входов
  `snapshot_id` (hs_rates/leaf-флаги, import_duty, примечания), закрытие формулы
  `stable_id`, план read-path за флагом. См. `.ai/ROADMAP.md` и `.ai/CURRENT_STATE.md`
  §2b/§8/§9.

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

*Журнал обновляется при принятии каждого нового ADR.*
