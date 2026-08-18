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
| DM-0005 | Guided `2204` PDO interval | Accepted — Option A | Ivan | 2026-08-05 | [`decisions/DM-0005-guided-2204-pdo-interval.md`](decisions/DM-0005-guided-2204-pdo-interval.md) |
| DM-0006 | Guided `0304` product-form chain | Accepted — Option A | Ivan | 2026-08-06 | [`decisions/DM-0006-guided-0304-product-form-chain.md`](decisions/DM-0006-guided-0304-product-form-chain.md) |
| DM-0007 | Guided `0406` fat/moisture chain | Accepted — Option A | Ivan | 2026-08-07 | [`decisions/DM-0007-guided-0406-moisture-chain.md`](decisions/DM-0007-guided-0406-moisture-chain.md) |
| DM-0008 | Rollout и enforcement официального NTM-контура | Accepted — Option A (advisory-only) | Ivan | 2026-08-15 | [`decisions/DM-0008-official-ntm-enforcement.md`](decisions/DM-0008-official-ntm-enforcement.md) |
| DM-0009 | Отдельное семейство экспортного контроля | Accepted — Option A (advisory-only) | Ivan | 2026-08-15 | [`decisions/DM-0009-export-control-family.md`](decisions/DM-0009-export-control-family.md) |
| DM-0010 | Правовые контуры NTM и fail-closed полнота каталога | Accepted boundary — full gate passed | Ivan | 2026-08-15 | [`decisions/DM-0010-ntm-legal-contours-catalog-fail-closed.md`](decisions/DM-0010-ntm-legal-contours-catalog-fail-closed.md) |
| DM-0011 | Структурированная применимость NTM и curated shadow enforcement | Accepted — implementation; activation deferred | Ivan | 2026-08-15 | [`decisions/DM-0011-structured-ntm-applicability-shadow-enforcement.md`](decisions/DM-0011-structured-ntm-applicability-shadow-enforcement.md) |
| DM-0012 | Guided `2204`: retained «прочие» boundaries | Accepted — Option A | Ivan | 2026-08-18 | [`decisions/DM-0012-guided-2204-retained-other-boundaries.md`](decisions/DM-0012-guided-2204-retained-other-boundaries.md) |

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

## DM-0005 — Guided 2204 PDO interval

**Статус:** Accepted — Option A (Ivan, 2026-08-05).

Ivan принял exact bounded interval только для `2204`: видимый пользователю
бескодовый PDO-вопрос, границу `(2204210900, 2204217800]` и следующий PGI code
choice с `2204217900`. Это navigation guidance, а не юридическое подтверждение PDO
для товара.

Приняты точные source markers, ordered allowlist из 33 Canonical sibling leaves и
fail-closed возврат к полному плоскому маршруту при любом drift. Option B и Option C
не выбраны; generic parser этим решением не разрешён. Глобальный лимит 30 не
меняется, одна noncritical `oversized_unsplit_group` warning не скрывается.
TASK-SEMANTIC-006 completed/accepted, но код остаётся только на feature branch:
этот docs-only update не выполняет merge, rollout или deployment. Флаги остаются
OFF; DB/API/LLM изменения не разрешены. Полный документ:
[`decisions/DM-0005-guided-2204-pdo-interval.md`](decisions/DM-0005-guided-2204-pdo-interval.md).

## DM-0006 — Guided 0304 product-form chain

**Статус:** Accepted — Option A (Ivan, 2026-08-06).

TASK-SEMANTIC-007 рассматривает одну exact five-chain проекцию для `0304`:
пять официальных product-form titles связываются с точными open/closed source
intervals, полными ordered code tuples, leaf roles и Canonical-parent topology.
Один drift подавляет весь bounded candidate и сохраняет полный pre-task route.

Ivan принял Option A — атомарную five-chain. Option B добавляет только две
отсутствующие границы «прочее» и смешивает exact/generic trust models; Option C
откладывает heading до generic packed-header parser; эти варианты не выбраны.

Технически проверенный candidate для `0304`: root 19/16 → 13/8, maximum step
19/17 → 13/9, semantic leaf coverage 82/100 → 92/100, при неизменных 117/117
source nodes и 100/100 declarable leaves. Whole census 1,228/1,228, golden 6/6,
Gate-2 18,211/18,211; QA не является продуктовым принятием. Exact official titles
меняют codeless guide IDs; реальные Canonical `stable_id` не меняются,
aliases/history вне scope.

DM не разрешает merge, rollout/deploy, включение флагов, DB/API/frontend изменения
или LLM/provider calls. Полный документ:
[`decisions/DM-0006-guided-0304-product-form-chain.md`](decisions/DM-0006-guided-0304-product-form-chain.md).

## DM-0007 — Guided 0406 fat/moisture chain

**Статус:** Accepted — Option A (Ivan, 2026-08-07).

TASK-SEMANTIC-008 реализует ограниченную exact-source цепочку для `0406`:
официальный вопрос по содержанию жира/влаги и два вложенных диапазона влажности
связываются с 17 точными Canonical leaves. Проверенная реализация снижает maximum
step 27/26 → 16/15 и повышает semantic coverage 10/47 → 21/47, сохраняя
54/54 source nodes и 47/47 leaves.

Ivan выбрал Option A. Option B с повторяющимися «прочие» и дополнительной
глубиной не авторизован. Whole census прошёл 1,228/1,228, golden 7/7, Gate-2 —
18,211/18,211. DM не разрешает merge, rollout/deploy, включение флагов или
DB/API/frontend/LLM изменения. Полный документ:
[`decisions/DM-0007-guided-0406-moisture-chain.md`](decisions/DM-0007-guided-0406-moisture-chain.md).

---

## DM-0008 — Rollout и enforcement официального NTM-контура

**Статус:** Accepted — Option A (Ivan, 2026-08-15).

Ivan одобрил default-ON показ полного официального NTM-контура только как
advisory. `NTM_V2_OFFICIAL_FULL_ADVISORY_ENABLED=false` является kill switch.
Все prefix/«из»/marker-совпадения остаются `needs_clarification` и
`used_for_missing_check=false`. **Enforcement не одобрен** и требует нового
отдельного решения. Полный документ:
[`decisions/DM-0008-official-ntm-enforcement.md`](decisions/DM-0008-official-ntm-enforcement.md).

## DM-0009 — Отдельное семейство экспортного контроля

**Статус:** Accepted — Option A (Ivan, 2026-08-15).

Экспортный контроль ПП РФ №1284–1288 и №1299 выделен в девятое семейство.
Source-faithful union содержит 1 087 raw HS-кандидатов; после исключения двух
versioned retired exact-кодов runtime использует 1 085 effective-кандидатов.
Совпадения требуют идентификации по техническим параметрам и не участвуют в
enforcement. Полный документ:
[`decisions/DM-0009-export-control-family.md`](decisions/DM-0009-export-control-family.md).

## DM-0010 — Правовые контуры NTM и fail-closed полнота каталога

**Статус:** Accepted boundary — full gate passed (Ivan, 2026-08-15).

Fail-closed граница запрещает повышать partial/code-only результат до полного.
После parser baseline fix временная DB, rebuilt из 96 tracked official PDFs,
прошла текущий gate: exact 21/96/17 809 unique, 0 duplicate/invalid и 17 774
непустых описания. Все 35 blank catalog codes absent from the pinned active ETT
rate snapshot; это нейтральная проверка множества, не вывод о причине или статусе
кодов. Все 13 290 кодов revision `ett:2026-06-18` присутствуют и описаны.
Pinned PDF-manifest, parser, ETT code-set, catalog code-set и code+description
digests совпали. Audit использовал временный read-only artifact и не изменял
production DB; отчёт имеет `full_commodity_catalog`, `catalog_complete=true` и
`ok=true`. Полный документ:
[`decisions/DM-0010-ntm-legal-contours-catalog-fail-closed.md`](decisions/DM-0010-ntm-legal-contours-catalog-fail-closed.md).

## DM-0011 — Структурированная применимость и shadow enforcement

**Статус:** Accepted — implementation boundary; production activation deferred
(Ivan, 2026-08-15).

API/UI принимают необязательные structured facts и показывают bounded exact
`definite`/`excluded` выводы отдельно от broker/missing-check. Запросы без facts
сохраняют broad-only контракт. Versioned curated bridge реализован, но
`NTM_V2_OFFICIAL_CURATED_ENFORCEMENT_ENABLED` по умолчанию выключен; включение
требует нового rollout-решения и доверенных source adapters. Полный документ:
[`decisions/DM-0011-structured-ntm-applicability-shadow-enforcement.md`](decisions/DM-0011-structured-ntm-applicability-shadow-enforcement.md).

## DM-0012 — Guided 2204 retained «прочие» boundaries

**Статус:** Accepted — Option A (Ivan, 2026-08-18).

Две точные retained source-boundary создают codeless «прочие» вопросы 16/16
внутри PDO `220421` и 7/7 под `220422`. Все 211 source codes и 170 leaves
сохранены; catalog maximum снижен до 29/27, full census остаётся 1,263/1,263,
Gate-2 — 18,246/18,246. Потерянный на page break заголовок «белые» не
синтезируется. Полный документ:
[`decisions/DM-0012-guided-2204-retained-other-boundaries.md`](decisions/DM-0012-guided-2204-retained-other-boundaries.md).

---

*Журнал обновляется при принятии каждого нового ADR.*
