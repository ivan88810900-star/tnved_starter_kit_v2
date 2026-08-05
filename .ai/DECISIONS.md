# DECISIONS.md — Журнал архитектурных решений (ADR Log)

> Реестр принятых архитектурных решений (Architecture Decision Records).
> Полные документы — в `.ai/decisions/`. Здесь — краткий индекс и статус.

---

## Индекс ADR / DM

| ADR | Название | Статус | Принял | Дата | Документ |
|-----|----------|--------|--------|------|----------|
| ADR-0001 | Canonical TNVED Model | Accepted | Ivan | 2026-06-30 | [`decisions/ADR-0001-canonical-tnved-model.md`](decisions/ADR-0001-canonical-tnved-model.md) |
| ADR-0002 | First production read-path on CanonicalModel (`/children`) | Accepted with conditions | Ivan | 2026-07-10 | [`decisions/ADR-0002-canonical-children-read-path.md`](decisions/ADR-0002-canonical-children-read-path.md) |
| ADR-0003 | Canonical anchor identity and snapshot lifecycle | Accepted | Ivan | 2026-07-14 | [`decisions/ADR-0003-canonical-anchor-identity.md`](decisions/ADR-0003-canonical-anchor-identity.md) |
| DM-0004 | Canonical nomenclature history and code transitions | Proposed | Awaiting Ivan | 2026-08-05 | [`decisions/DM-0004-canonical-nomenclature-history.md`](decisions/DM-0004-canonical-nomenclature-history.md) |

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
  перед freeze, full-tree content parity с legacy. TASK-CANONICAL-010 дополнительно
  deep-freezes опубликованные nodes/parent/children и standard metadata containers
  без нового решения ADR.
  Additive `TreeBuilder.build_model(...)`; `build(...)` без изменений. Не подключён к
  runtime/API/overlay; feature flag не вводился.
- ✅ **TASK-CANONICAL-004** (Completed, 2026-07-14) — Этап 3 ADR: **структурный слой `/children`
  за feature flag** (`CANONICAL_TREE_ENABLED`, `CANONICAL_TREE_SHADOW`, оба default OFF,
  request-time). Provider с in-memory кэшем (build-once под локом; ревизия учитывает
  `tnved_commodities` + leaf-relevant `hs_rates`) + validator gate + fallback на legacy
  без 500. Bridge `TreeSerializer.to_legacy_dict` → существующий `_serialize_tree_node`
  (overlay не дублируется). Shadow-режим не влияет на ответ, логирует mismatch. Контракт
  JSON не изменён. Legacy `build_tree()` не тронут. Corrective закрывает stale-cache
  при in-place UPDATE и добавляет shadow metrics/sampling + Gate-2 auditor. Финальный
  Gate-2: 18 049/18 049 match, 0 mismatch/unresolved, `gate2_ok=true`, exit 0.
- ✅ **TASK-CANONICAL-010** (Completed, 2026-08-05) — corrective implementation
  ADR-0001 immutability invariant: опубликованный Canonical graph deep-frozen,
  Builder output до publication остаётся mutable; API/formulas/flags unchanged.

**Decision-точки** (полный список со статусами/сроками — `.ai/CURRENT_STATE.md`
§9 «Open Architecture Decisions»):
- ✅ Формула `stable_id` закрыта ADR-0003: snapshot-independent `stable-id-v1`.
- ✅ Состав `snapshot_id` закрыт ADR-0003: `canonical-snapshot-v2` хеширует
  детерминированный Canonical output; provider source revision остаётся отдельным
  cache-invalidation key.
- Где материализуется модель: in-memory (read-path использует in-memory кэш провайдера)
  vs materialized-снапшот, переживающий рестарт.
- ✅ Стратегия feature flag (`CANONICAL_TREE_ENABLED` / `CANONICAL_TREE_SHADOW`) —
  введена в TASK-CANONICAL-004 (default OFF). Gate-2 пройден; serving ON требует
  отдельного решения Ivan.
- Дедлайн удаления legacy `build_tree` после parity.
- ✅ Первый production read-path — `/children` (структурный слой) за флагом;
  TASK-CANONICAL-004 completed, overlay/остальные endpoints вне scope.

**Архитектурные долги:** `.ai/CURRENT_STATE.md` §8 (Critical / Important / Nice to have).

**Инварианты (binding):** I1–I22 в полном ADR (no virtual L5, no fake codes,
stable ids, детерминизм, реальные коды достижимы, одна модель истины, semantic
overlay не меняет структуру, AI ничего не изменяет, snapshot-консистентность и др.).

## ADR-0002 — First production read-path on CanonicalModel (`/children`)

**Статус:** Accepted with conditions (Ivan, 2026-07-10).

- Первый read-path — только структурный слой `/children`.
- Оба флага default OFF и читаются request-time.
- Legacy остаётся oracle и fail-safe fallback.
- Gate-1 и Gate-2 пройдены; Serving ON остаётся отдельным решением Ivan о rollout.

## DM-0003 / ADR-0003 — Next Canonical step and anchor identity

**DM-0003:** Option C accepted by Ivan, 2026-07-14. The next slice aligns Canonical
anchors with the TN VED search/code-card MVP; broad overlay migration and flag rollout
remain separate decisions.

**ADR-0003:** Accepted by Ivan, 2026-07-14, and implemented by TASK-CANONICAL-005.
Canonical anchors use snapshot-independent path identity (`stable-id-v1`), deterministic
output hashing (`canonical-snapshot-v2`), and the additive tuple
`(stable_id, snapshot_id, code, node_type)`. Formula changes now require a new ADR and
an explicit alias/migration plan.

## DM-0004 — Canonical nomenclature history and code transitions

**Статус:** Proposed — awaiting Ivan (2026-08-05).

Decision Memo разделяет три независимых контура: лексические синонимы поиска,
юридические переходы реальных кодов между редакциями номенклатуры и технические
миграции `stable_id`. Рекомендован отдельный versioned many-to-many history overlay с
провенансом, без изменения текущего `CanonicalModel` / `stable-id-v1`, без silent
redirect и без выдачи inferred-сходства за официальный переход.

До решения Ivan и успешного source-feasibility audit запрещены schema/runtime/UI
реализация и автоматическое сопоставление кодов. Полный документ:
[`decisions/DM-0004-canonical-nomenclature-history.md`](decisions/DM-0004-canonical-nomenclature-history.md).

---

*Журнал обновляется при принятии каждого нового ADR.*
