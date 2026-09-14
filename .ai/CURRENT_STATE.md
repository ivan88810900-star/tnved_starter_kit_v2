# Autonomous orchestration status — 2026-09-12

Infrastructure: PR #190, `agent/orchestration-v1` -> `main`.
Verified code HEAD: `ad4935e318d947276178e2f269d4ffe1051ea6cb`.
Persistent runtime authority: `agent/orchestration-state` (state commits separate
from code/QA/CI candidate SHAs). Read this branch's board on every wake-up.

## Automation update — 2026-09-14

### Product source-bound recheck published — 2026-09-14 15:35 UTC

- Current product PR #187 remains at exact HEAD
  `5d3b0c1dc7dd8e396c4f812db2bf6f1fa6d293f9`; this run did not modify that
  branch. Two one-file evidence reports were developed from this exact base in
  isolated A1/A3 worktrees and published as draft PRs #200 and #201.
- Payment report PR #200 HEAD
  `dd56cc5357b30ae4cd448ae7a1608dbfa73e0da2`, tree
  `4a622a73b14de394c4e4f9238655432b9d947870`, is byte-identical to the local
  author tree. Fresh published-head A5 passed: 138 tests plus independent
  in-memory admission/FX/legacy-consumer probes. Exact-head CI run 34862392361
  completed successfully for backend, frontend, staging-build and workflow
  contract jobs. The separate ETT acquisition job was skipped and is not
  counted as passed. The docs-only medium-risk task is
  `READY_FOR_HUMAN_APPROVAL`; product gaps documented by it remain confirmed.
- Official-source/AD30 report PR #201 HEAD
  `a304ff9003be44e9ec1bf4c4e313b3993c634d46`, tree
  `0633120d6fc8dfead252101c8cf323084c04da6e`, is byte-identical to the local
  author tree. Fresh published-head A5 passed 442 tests and reproduced the
  three pinned evidence hashes, 24 facts / 3 producer rows, fail-closed gates,
  and monitor counts 49 registry / 49 policies / 72 default URLs / 11
  review-only targets. Exact-head CI run 34862395645 completed successfully for
  the same four required jobs; ETT acquisition was skipped. Because this task
  is high-risk and A6 is not yet live, it remains `QA_PASSED`, not ready.
- A0 confirmed four current product findings from independent reproduction:
  unbound HsRate/HsDutyRule inputs can yield a final `OK`; verified quote-bound
  CBR FX provenance has no path through `get_rates_map`; the bounded legacy
  diagnostic VAT override can change legacy totals without admission state;
  and AD30 still lacks a complete fresh amendment/final-report/producer/
  nomenclature evidence chain. These are technical/evidence gaps, not new legal
  applicability findings. No source was accepted and no product code, database,
  flag, deployment or production state changed.
- The A6 chain remains unchanged and ready for owner-authorized protected merge
  in order #190 -> #193 -> #194. No merge or provider request occurred. A6
  remains `BLOCKED_PENDING_DEFAULT_BRANCH_MERGE`; exact chain HEADs and CI are
  recorded in the checkpoint below.

### A6 chain ready for protected merge — 2026-09-14 14:12 UTC

- The reviewed chain is synchronized and all three PRs are open and ready for
  review in required order: PR #190 HEAD `0195a2b5eef30a96feaf866061ce2a706d1c08f3`,
  PR #193 HEAD `0126404cd78fd293f3634bd20c5fd09f937e83ba`, and
  PR #194 HEAD `47da2e4763261cddc638cc276573b3375508a9ac`.
- Exact-head CI succeeded: #190 run 34852286695, #193 push run 34852521668,
  #194 push run 34852829770. Independent exact-head A5 passed the combined
  #193 chain (92/92 verifier, 96/96 discovery, 32/32 audit) and #194 bridge
  (99/99 verifier, 103/103 discovery, 7/7 bridge). PR #190 alone is explicitly
  conditional: five non-audit review defects are fixed and resolved, while the
  sixth credential-scanner P1 is fixed only by stacked PR #193 and remains open
  on #190 until that dependent merge lands.
- A5 found and A0 fixed two final CI-admission defects before readiness: mandatory
  suites are now loaded from exact regular repository files, bridge artifacts
  require the bridge suite, and offline CI validates the committed state snapshot
  without acquiring controller authority. Scoped PR #199 was independently
  reviewed and integrated only into `agent/orchestration-v1`.
- PR #194 documentation now records the completed Environment migration solely as
  an uninspected owner assertion. No secret value or protected setting was read.
  A6 remains `BLOCKED_PENDING_DEFAULT_BRANCH_MERGE`; no provider request occurred.
- The only authorized next infrastructure action is an owner-approved protected
  merge sequence #190 -> #193 -> #194. After those reviewed changes are on `main`,
  A0 must run a commit-bound live smoke through `tariff-a6-trusted`; only a valid
  bound Anthropic response may change A6 to `LIVE_VERIFIED`.
- Product PR #187 remains independently queued at HEAD
  `5d3b0c1dc7dd8e396c4f812db2bf6f1fa6d293f9`; this infrastructure block did not
  modify it or inherit stale #191/#192 approvals.

### Trusted A6 bridge checkpoint — 2026-09-14 10:49 UTC

- Draft PR #194 publishes the separate four-file trusted A6 bridge at exact
  HEAD `ceec320e61070a96061f32096f61d92fc928415a`, tree
  `0d9b1be5deeb0591f114db3555e2c7bb80e69668`, stacked on PR #193. The
  published tree is byte-identical to the locally executed candidate. Exact-head
  offline Tariff agent safety run 34834783075 succeeded.
- Independent A5 first rejected the `workflow_dispatch` design with confirmed
  critical finding `A5-A6-BRIDGE-SECRET-BOUNDARY-001`: another same-repository
  branch could modify the dispatched workflow before repository-secret
  resolution. A4 replaced it with a narrow `repository_dispatch` default-branch
  workflow plus dedicated `tariff-a6-trusted` Environment boundary. A0 reproduced
  and resolved the finding; fresh A5 passed both the fixed local tree and exact
  published HEAD. Tests on the published tree: bridge 7/7, full orchestration
  76/76, verifier 69/69, compile/diff/scope clean.
- A6 is still `BLOCKED`, not `LIVE_VERIFIED`: no provider call was made and no
  secret value was read. Safe live use requires the owner to create/protect the
  `tariff-a6-trusted` Environment, restrict it to the protected default branch,
  migrate `ANTHROPIC_API_KEY` into that Environment, and remove the repository-
  level copy. PR #190, PR #193 and PR #194 must then pass protected review/merge
  before the first repository dispatch. The current GitHub connector can inspect
  runs and artifacts but cannot create `repository_dispatch`, so the first smoke
  also requires an owner-triggered dispatch (or a later connector capability).
- PR #193 exact HEAD `c39248672a6299b64bc2db5637e2027579a4624e`
  now has fresh independent A5 PASS: audit tests 23/23, orchestration verifier
  69/69, compile/diff clean, and a socket-blocked replay made no network calls.
  Exact-head offline CI run 34723187303 succeeded. This supersedes the older
  capability-limit note below; live A6 remains unavailable.
- Current product PR #187 HEAD is
  `5d3b0c1dc7dd8e396c4f812db2bf6f1fa6d293f9`; exact-head CI runs
  34830630369 (pull request) and 34830626784 (push) succeeded. Existing drift
  findings already invalidate PR #191/#192 evidence, so no duplicate was added.
- Hourly triage found no new source-monitor failure beyond the already recorded
  runs 34717159548/34716176823, no new deduplicated finding, and no stale active
  subagent session. PR #190 remains at `ad4935e3` with successful exact-head CI;
  its six unresolved review inputs are not treated as reproduced defects.

- PR #187 advanced 15 commits from the previously reviewed base `a9d15c74` to
  current product HEAD `dab1f8aae5a114a51505763bf9ea0a0d8161ed38`. Exact-head
  CI run 34825453006 succeeded, but the 22-file change set includes current
  product decisions, admission workflow, AD30 services/scripts/tests and
  evidence. A0 confirmed `A0-UPSTREAM-DRIFT-002` and
  `A0-UPSTREAM-DRIFT-003`: PR #191 and stacked PR #192 are stale, and both task
  records are now `CHANGES_REQUESTED` with prior QA/CI gates invalidated. The
  active product branch's separate AD30 executable review must be treated as the
  current implementation; old approvals are not transferred to it.
- Draft PR #192 publishes the bounded AD30 Decision 12 -> 4 -> 121 source-fact
  candidate at exact HEAD `5bff4523ec20f7a29fe6f7b997ffccfc479c9bff`.
  Fresh independent A5 and exact-head CI run 34722092821 passed that historical
  published HEAD, and Admission agent QA run 34722005000 completed successfully.
  Those results are retained as provenance only and no longer establish current
  readiness after the product-head drift above.
- Draft PR #193 publishes the separate orchestration-only adapter fix at exact
  HEAD `c39248672a6299b64bc2db5637e2027579a4624e`, tree
  `2c1f012c76b6eda13883f2d207c1d74ffc0d9c50`, stacked on PR #190. It does not
  modify PR #187 or PR #192. Tariff agent safety run 34723187303 succeeded.
- Before publication, independent A5 rejected the first adapter candidate for an
  unscanned contract-ref metadata path and incorrect deleted-line bounds. A4 fixed
  both; fresh A5 then passed the identical local tree with 23/23 audit tests and
  69/69 full orchestration tests. The required new A5 run bound to published SHA
  `c3924867` did not execute: the native subagent returned a platform usage-limit
  failure with a retry time of 2026-09-19 18:47 (timezone not supplied). This is
  `CAPABILITY_BLOCKED`, not QA evidence; task status remains `IMPLEMENTED` with
  no current QA/audit/CI gate recorded.
- The repaired adapter locally built the complete exact product packet
  `e0129b90ab1409133b6e8487752f651786e9cda5ae0e5fa0800abfe39ca42660`
  using immutable contract commit `ad4935e3`, and reported A6 `UNAVAILABLE` because
  `ANTHROPIC_API_KEY` and `TARIFF_ANTHROPIC_MODEL` are not configured. No provider
  request occurred and this is not an audit pass. The receipt is not promoted to
  task readiness until PR #193 receives fresh published-HEAD A5 verification.
- PR #190 remains open at `ad4935e3` with successful CI, but its 2026-09-12 Codex
  review contains unresolved P1/P2 inputs. They are untrusted review findings and
  require independent reproduction before any fix/readiness claim. No protected
  merge, production change, feature-flag activation, secret/permission change, or
  force push was performed.

- 60 offline tests passed including independent A5 cases; CI 34718310831 and
  34718309255 succeeded at the exact verified code HEAD.
- Real native Work children `/root/smoke_rates` and `/root/smoke_sources` executed
  isolated branches/worktrees. Independent `/root/a5_independent_qa` accepted both.
- Both smoke branches passed separate GitHub CI, then integrated on the agent
  infrastructure branch. No protected/main merge or production action occurred.
- Claude packet built/validated, but A6 is NOT_CONFIGURED: no Anthropic key/model.
  No request sent or external audit claimed. Native Work is the active runtime;
  optional Agents API adapter is SAFE_BOOTSTRAP_ONLY and not live verified.
- PR #187 advanced externally to a9d15c74699c8cd7842404580ff6fd7bd957e9eb.
  Its exact-head CI 34718655503/34718653080/34718400910 and Admission QA
  34718400932 passed. These are upstream observations, not this setup A5/A6 execution.
  PR #189 is unchanged/inactive. PR #191 is the separate A1 evidence report.
- PR #191 candidate 1c0272a34cbcbb3b99d6f32c86d86949bc0adc06 now rechecks
  current a9d15c74 and fixes the discovered CI branch matcher. Independent A5
  passed; Admission QA 34719777792 and full CI 34719777785 passed at exactHEAD.
  Backend: 5168 passed/2 skipped; Admission:1975 passed/1 skipped in44 files.
  These suites overlap. Task is READY_FOR_HUMAN_APPROVAL; no merge performed.
- A0-UPSTREAM-DRIFT-001 and A0-CI-BRANCH-SCOPE-001 are resolved with exact-head
  evidence. Real author/QA sessions repeated; no test was removed or weakened.
- Next queued A3 task: TARIFF-AD30-REVIEW-CANDIDATE-001, source-fact candidate
  for Decision 12 -> 4 -> 121 per current focus. It grants no legal applicability.
- Fresh native session /root/fresh_state_recovery recovered board revision 27 from
  separate Git common-dir snapshot c4d966e. See orchestration/FRESH_SESSION_RECOVERY.json.
- Existing hourly Automation 6a2a8a215240819197f0879e5d47c90d enabled for A0 triage.
  Scheduled background native development has not yet been verified; scheduling
  metadata alone does not prove execution. No self-written scheduler.
- GitHub reported main protected=false; no permissions/secrets were changed.
  Controller and coordinator guards are not external server branch protection.
- Existing accepted NTM advisory default ON preserved; enforcement/production flags
  not activated. Deployed values uninspected. Product source decisions live at the
  current product ref, not the historical main notes below.


---

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

## 2a. Принятые архитектурные решения

### ADR-0001 — Canonical TNVED Model (Accepted, Ivan, 2026-06-30)

**Source of Truth продукта Tariff — Canonical TNVED Model**, а не SQLite, не дерево
(`build_tree()`), не parser и не API. SQLite — слой хранения/ingestion; дерево,
семантика, AI, NTM, пошлины, поиск, RAG, граф знаний — проекции/overlay поверх
канонической модели (привязка по `stable_id` / `anchor`).

Зафиксировано:
1. Canonical TNVED Model — центральная source-of-truth модель.
2. **Recovery — стадия внутри `tree_engine`**, не отдельный top-level module.
3. **Semantic Navigation позже переводится на Canonical Model** (перестаёт читать БД сам).
4. Следующая задача — **`TASK-CANONICAL-001`**: deterministic `stable_id` + recovery
   stage skeleton (без подключения к API).
5. **Legacy `_build_tree` остаётся production и oracle до parity**; удаляется только после.

Полный документ: `.ai/decisions/ADR-0001-canonical-tnved-model.md`. Индекс: `.ai/DECISIONS.md`.

---

## 2b. Состояние Canonical Pipeline (после TASK-CANONICAL-001, 002 и Materialization)

**TASK-CANONICAL-001 — Completed.** Детерминированные `stable_id` (без `uuid4()`),
`snapshot_id`, skeleton стадии Recovery.

**TASK-CANONICAL-002 — Completed.** Recovery-логика перенесена в `StructureNormalizer`;
Builder собирает дерево напрямую из recovery-результата (без делегирования в legacy
`build_tree()`); добавлены full-tree parity-тесты против legacy-oracle.

**Canonical Model Materialization — Completed.** Добавлен иммутабельный `CanonicalModel`
поверх результата `TreeBuilder.build(...)` с индексами достижимости и навигацией;
freeze/read-only на уровне интерфейса; обязательный validator gate; content-parity с
legacy (сверх structural). Контур по-прежнему **не подключён** к runtime/API/overlay.

> **Прошло Architecture Review (Chief Architect): APPROVE WITH NOTES.** Контур
> изолирован, к runtime/API/overlay не подключён, прод-риска нет. Открытые замечания
> вынесены в разделы «Architecture Debt» и «Open Architecture Decisions» ниже.

### Реализовано (в `customs-clear/backend/app/services/tree_engine/`, изолированно)

- **Parser** (`parser.py`) — SQLite → плоская промежуточная модель `ParsedCommodityRecord`.
- **Recovery** (`recovery.py`, `StructureNormalizer`) — pad-имена, синтез бескодовых
  L6/L8, subheading-group, очистка имён, классификация типов; **чистая стадия** (без БД,
  без `uuid4`), leaf-флаги принимает аргументом.
- **Builder** (`builder.py`) — stack-сборка иерархии, материализация синтет-листьев,
  сортировка, восстановление имени группы, присвоение ID; **напрямую**, без legacy.
  Additive-метод `build_model(...)` → `CanonicalModel` (validator gate + freeze).
- **CanonicalModel** (`canonical_model.py`) — иммутабельный Source-of-Truth объект:
  `roots`/`snapshot_id`, индексы `node_by_stable_id` / `node_by_code` /
  `node_by_display_code` / `parent_by_stable_id` / `children_by_stable_id`; методы
  `get` / `get_by_code` / `get_by_display_code` / `parent` / `children` / `path` /
  `descendants`. Read-only на уровне интерфейса: `roots`/`children`/`path`/`descendants`
  → `tuple`, индексы → `MappingProxyType`, переустановка/удаление атрибутов запрещены.
- **Validator gate** — `CanonicalModel.from_roots(...)` прогоняет `TreeValidator` перед
  freeze; при ошибках модель не создаётся (`CanonicalModelValidationError`).
- **stable_id** — детерминированный (`node-<hex>`), воспроизводим между сборками.
- **snapshot_id** — вычисляется (`compute_snapshot_id(db_codes)`).
- **Parity tests** — `test_canonical_tnved_model.py`: full-tree **structural** parity
  (`structure_fingerprint`) и full-tree **content** parity (name / display_code /
  is_leaf / is_codeless / is_group / import_duty / notes) против legacy `build_tree()`.

### Чего ещё НЕТ (намеренно, по плану ADR-0001)

- **Deep-immutability узлов** — сами `TreeNode` (их `children`/`metadata`) физически не
  заморожены; иммутабельность обеспечена только на уровне интерфейса `CanonicalModel`
  (известное ограничение этапа).
- **Feature flag** — нет `CANONICAL_TREE_ENABLED`.
- **Runtime adoption** — контур не подключён к API / `lifespan` / роутерам.
- **Materialized snapshot** — модель строится in-memory на вызов `build_model(...)`; нет
  переживающего рестарт снапшота/кэша по `snapshot_id`.
- **Overlays** — Semantic Navigation / NTM / Duty / Notes / Search / RAG ещё не
  переведены на `anchor` (продолжают читать БД сами).

---

## 3. Последние архитектурные изменения

| Коммит | Дата | Описание |
|--------|------|---------|
| (uncommitted) | 2026-07-01 | Canonical Model Materialization: иммутабельный `CanonicalModel` (индексы + навигация), validator gate, freeze/read-only, full-tree content parity. Не подключён к runtime |
| (uncommitted) | 2026-06-30 | TASK-CANONICAL-002: recovery-логика → `StructureNormalizer`; Builder без делегирования в legacy; full-tree parity tests (APPROVE WITH NOTES) |
| `4a7eac2` | 2026-06-30 | TASK-CANONICAL-001: deterministic `stable_id`, `snapshot_id`, recovery skeleton |
| (docs) | 2026-06-30 | ADR-0001 Canonical TNVED Model принят (Ivan); зафиксированы DECISIONS.md, ROADMAP |
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
| **TASK-CANONICAL-001** — deterministic `stable_id` + recovery stage skeleton | ✅ Completed | — |
| **TASK-CANONICAL-002** — recovery-логика → `StructureNormalizer`, Builder без legacy, parity tests | ✅ Completed (APPROVE WITH NOTES) | — |
| **Canonical Model Materialization** — иммутабельный `CanonicalModel` (индексы+навигация), validator gate, content parity | ✅ Completed (не подключён к runtime) | — |
| Derisking (остаток): расширение входов `snapshot_id`, формула `stable_id`, план read-path за флагом | Рекомендован | Высокий |
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

## 8. Architecture Debt (Canonical TNVED Model)

> Источник: Architecture Review TASK-CANONICAL-002 (Chief Architect, APPROVE WITH NOTES).
> Долги контура изолированы (к runtime не подключено), но должны быть закрыты до
> перехода к runtime-adoption / Этапа 3 ADR-0001.

### Critical
- ~~**Structural parity проверяет не весь контент.**~~ **Закрыто** (Canonical Model
  Materialization): добавлен `test_full_tree_content_parity_with_legacy` — сверяет
  полный контент узлов (name, `display_code`, `is_leaf`, `is_codeless`, `is_group`,
  `import_duty`, notes) рекурсивно против legacy `build_tree()`; проходит на всём дереве.
- **`snapshot_id` не учитывает все входы модели.** Считается от `db_codes`, но не
  включает другие входы, влияющие на результат — в частности `hs_rates` (через leaf-флаги),
  `import_duty`, примечания глав. Кэш/инвалидация по такому `snapshot_id` ненадёжны.
- **Recovery-логика временно дублируется** в legacy `build_tree()` и в canonical
  (`StructureNormalizer` + Builder). Два источника одной логики до достижения parity —
  риск дрейфа.

### Important
- **Формула `stable_id` не утверждена окончательно** (см. Open Decisions). Сейчас
  `node-<hex>`; не зафиксировано отношение к ревизиям номенклатуры/истории.
- **Документация отставала от кода** (001/002 были «Completed» по факту, но `.ai`
  отражал «не начато») — этим обновлением синхронизировано; держать в синхроне.
- ~~**Validator ещё не freeze-gate.**~~ **Закрыто** для `CanonicalModel`:
  `CanonicalModel.from_roots(...)` / `TreeBuilder.build_model(...)` прогоняют
  `TreeValidator` перед freeze; при ошибках модель не создаётся
  (`CanonicalModelValidationError`). Runtime по-прежнему использует legacy-путь.
- **Builder читает БД для `leaf_flags`** (`SessionLocal`/`HsRate` в `builder.py`).
  Противоречит ADR §6.1 «единственный путь чтения — Parser» и переписывает предикат
  `is_leaf_hs_code`. Должно переехать в Parser.

### Nice to have
- **provenance / history / aliases / breadcrumb** — поля модели из ADR §3.2 ещё не
  реализованы (нужны для Search/RAG/Graph/версионности).
- **SQLite / PostgreSQL / FTS5 долг** — FTS5 вне Alembic; миграция на Postgres
  потребует аналога полнотекстового поиска (ROADMAP §7).
- **Удаление переходных `serializer`/`structure_fingerprint`** после завершения
  миграции (нужны только в переходный период для дифф-тестов).

---

## 9. Open Architecture Decisions

> Решения, которые нужно закрыть осознанно (а не молча) — по `ENGINEERING_PROTOCOL` и
> `agents/architect.md`. Полный контекст — в ADR-0001.

| Решение | Статус | Почему важно | Когда закрыть |
|---------|--------|--------------|---------------|
| **stable_id formula** | Open (черновой `node-<hex>`) | ID — первичный ключ для Search/RAG/AI-журнала/Graph; смена формулы позже = миграция всех ссылок | До runtime-adoption (Этап 3); прежде, чем кто-то начнёт хранить ссылки на узлы |
| **snapshot_id inputs** | Open (только `db_codes`) | От полноты входов зависит корректность кэша/инвалидации и «snapshot-консистентности» (I19) | До materialized CanonicalModel / включения кэша |
| **Materialized CanonicalModel** | Частично (in-memory `CanonicalModel` реализован; переживающий рестарт снапшот/кэш — Open) | Определяет переживаемость рестарта, память, путь к PostgreSQL | Перед runtime-adoption (кэш по `snapshot_id`) |
| **Feature flag strategy** | Open (нет `CANONICAL_TREE_ENABLED`) | Управляет безопасным A/B old-vs-new и откатом | До первого runtime read-path (Этап 3) |
| **Deadline for legacy `build_tree` removal** | Open (oracle до parity) | Двойная логика — долг; нужен критерий «parity достигнута → удаляем» | После content-parity + стабилизации flag (Этап 6) |
| **First production read-path** | Open | Какой эндпоинт первым читает CanonicalModel за флагом и как сверяется с legacy | До Этапа 3; зафиксировать план до реализации |

---

*Обновлять после каждого значимого изменения.*
