# Cycle 285 checkpoint — first persistent raw-first staging ingest (2026-10-16 11:17 UTC)

- Owner-provided isolated Neon staging is live: project `red-meadow-53765518`, branch `br-weathered-frost-ba9jri3c`, database `tariff_staging`, private bucket `official-originals`; this is not production.
- Uploaded and read back the retained official EEC ETT chapter-29 PDF: 957,135 bytes, 49 pages, SHA-256 `418666f5fc61db171a9d0bbcf068753504cd29ff04f0f4ac62d4e1147980b51a`. The immutable object key is source/date/SHA-addressed.
- Created isolated `tariff_ingest` tables and atomically stored a bounded first 20 exact 10-digit rows as `COLLECTED_UNVERIFIED`. Reread: 1 source, 20 rows, 20 unique HS codes, 20 unverified, 0 normalized, 0 rejected; cursor `2902700000` / ordinal 20. An identical replay kept the counts unchanged.
- Independent A5 caught an initial UTF-8 serialization defect before checkpoint. It was corrected in-place with explicit UTF-8 extraction; reread proves 20/20 row-SHA matches and zero mojibake markers. Final independent reread is recorded in the cycle evidence.
- Draft PR #256 remains unchanged at `38a475d20f44e9624435ea0089def0b16b9e1bd5`, tree `a5ec80034901d5a6d4a12f4e978e495e72721b4c`; exact-head CI run 38884269859 / job 116918116968 remains successful.
- Status: `PERSISTENT_STAGING_INGESTED / COLLECTED_UNVERIFIED`. This is not legal/source admission, not a synchronized populated NTM snapshot, and not full #245/#256 acceptance. A6 unchanged/not sent; no protected action occurred.
- Durable evidence: `.ai/orchestration/evidence/cycle285_first_persistent_staging_ingest.json`; TASK_BOARD revision 819.
- Next: add explicit UTF-8 regression coverage to the reusable raw-first loader and continue resumable bounded collection; keep normalization and legal admission separate and fail closed.

# Cycle 284 checkpoint — staging dry-run safety and storage capability (2026-10-16 10:02 UTC)

- Draft PR #256 exact head `38a475d20f44e9624435ea0089def0b16b9e1bd5`, tree `a5ec80034901d5a6d4a12f4e978e495e72721b4c`.
- `run_full_data_refresh(dry_run=True)` is now read-only: no CBR updater/network fallback, no rate/provenance writes; database inspection failures return `partial_error`. Non-dry mode remains mutating by explicit call.
- Author: 56 passed, exit 0. Fresh independent A5 `/root/a5_cycle284`: PASS; 19 focused / 107 adjacent +31 subtests, including byte/logical sentinel no-mutation. Exact-head CI run 38884269859 / job 116918116968: success.
- Receipts: https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256#issuecomment-6213048689 and https://github.com/ivan88810900-star/tnved_starter_kit_v2/issues/257#issuecomment-6213054948
- Persistent staging is CAPABILITY_BLOCKED: no configured DB/object store, no durable volume, writable filesystem is transient overlay with `fsync=volatile`; already-checked connected Neon inventory is empty. Minimum: authorized non-production Postgres or durable-volume SQLite plus durable originals storage.
- Status: QA_PASSED / CI_PASSED / CAPABILITY_BLOCKED_PERSISTENT_STAGING. Full #245/#256 acceptance and legal/source completeness remain NOT PASS. A6 unchanged/not sent.
- Durable evidence: `.ai/orchestration/evidence/cycle284_staging_dry_run_safety.json`; TASK_BOARD revision 818.
- Next: connect durable non-production DB + originals storage, then bounded raw-first ingest; continue independent product work meanwhile.

# Cycle 283 checkpoint — PAY-8 fail-closed applicability quarantine (2026-10-16 09:15 UTC)

- Draft PR #256 exact head `af40f10f1e286adcde6914af67ef92b90d743c11`, tree `a867b3d5b6021fed775375ce74a05a352419b7a7`.
- Fifteen chapter-27 duplicate contours are reconciled only as a current official EEC snapshot. Mandatory chapter27/chapter29 applicability blockers prevent apply even after the remaining `8511100001` duplicate is removed.
- Primary Decision No. 6 verification established the unmodeled aniline 0% interval from 2026-02-07 through 2027-12-31.
- Author: 212 passed. Fresh independent A5: PASS, 78 targeted / 279 expanded, zero disposable DB writes. Exact-head CI run 38878463031 / job 116899123337: success.
- Receipt: https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256#issuecomment-6212133879
- Status: QA_PASSED / CI_PASSED / APPLICABILITY_QUARANTINED. Full #245/#256 acceptance, legal/source completeness and lawful populated synchronized NTM snapshot remain NOT PASS. A6 unchanged/not sent.
- Next: read-only inventory of the existing Neon boundary before any persistent staging; separately implement date-aware Decision 6 handling and verify chapter-27 history from primary acts.

# Cycle 281 CI closure checkpoint — 2026-10-16 06:52 UTC

- Draft PR #256 remains at exact head `cd41a21109a99aa23457f6d6a0ba7edddb536c08`, tree `2bc81fac43d83a3fea4ba41d1c03faac2cf26e1b`; no product file changed in this cycle.
- PAY-6 duplicate ETT admission fix remains bound to author **265 passed** and independent A5 `/root/a5_cycle280`: **PASS**, no findings; seeded no-mutation probe PASS.
- Exact-head GitHub Actions [run 38858876457 / job 116836388534](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38858876457/job/116836388534) completed **success** for the push event.
- Closure receipt: https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256#issuecomment-6209860846
- Status: QA_PASSED / CI_PASSED / PAY-6_CLOSED. Full #245/#256 acceptance, legal/source completeness and lawful populated synchronized NTM snapshot remain NOT PASS. A6 unchanged/not sent.

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

## Operating model normalization — 2026-09-29

- Active developer roles are now **A-CORE** on `integration/customs-core-v1` and **A-PRODUCT** on `integration/compliance-ai-v1`, coordinated by A0.
- A5 is ephemeral independent QA; A6 is an external high-risk audit gate. A6 is LIVE_VERIFIED, while subsequent audits still require protected PR #237.
- Persistent A1/A2/A3/A4 ownership is historical. Exact legacy ownership is archived at `.ai/orchestration/evidence/legacy-agent-ownership-archive-20260929-gen42.json`.
- Open PR classification and consolidation routing are authoritative in `.ai/orchestration/PR_INVENTORY_20260929.json`.
- Current main baseline: `08e030a6053ac9638957119373797e0fbf2b10c2`. No protected merge, deploy, production write, flag, permission, secret, destructive migration, force push, or branch deletion was performed during normalization.

## Cycle 277 checkpoint — PAY-5 VAT effective-period quarantine (2026-10-15)

- Main remains `e526dfbdb5a31b01bf6f743da0288b88f916de0c`; no protected action was performed.
- Draft PR #256 exact head `44c50df61747f09e4f876c0f751d7c23cbf56b30`, tree `43902a009e5949e4e37d2534411022a9c133530c`.
- Confirmed defect: `vat:2026-06-18` applies 22% from 2025-01-01 with no row validity windows, while FNS binds the 20% to 22% transition to 2026-01-01.
- The exact revision now fails closed at ingestion; persisted rows with this provenance withhold automatic VAT and final totals while keeping partial evidence. Manual VAT and later verified revisions remain eligible.
- Exact-head offline-safety CI run 38816928278 / job 116703956398 passed (120 required safety tests and 4 snapshot tests). All nine changed Python blobs parse.
- Product pytest and fresh independent A5 remain pending in this connector-only run. Status is IMPLEMENTED / SAFETY CI PASS / PRODUCT QA PENDING, not READY.
- No inline review threads exist on the active #244/#245/#255/#256/#258/#259 stack.
- Full #245/#256 acceptance and legal/source completeness remain NOT PASS; the lawful populated synchronized NTM snapshot remains unavailable.
- A6 request `core-s1-6415f443120f-r9-g106` is unchanged and not sent.
- Evidence: `.ai/orchestration/evidence/cycle277_checkpoint.json`; PR receipt: #256 comment 6203575372.
- Next safe step: execute focused VAT ingestion/payment engine/quote/profile tests on exact head, obtain fresh independent A5, and correct any findings before readiness.


## Cycle 279 checkpoint — PAY-5 exact-head CI closure (2026-10-16)

- Main remains `e526dfbdb5a31b01bf6f743da0288b88f916de0c`; no protected action was performed.
- Draft PR #256 exact head remains `486d407ec2628564a616302a96f52adb91149241`, tree `a7d4c3bd4a3b3b8573fa17c5353b336a737ddd20`; the reviewed product tree did not change.
- Cycle 278 author evidence remains **232 passed + 10 subtests**. Fresh independent A5 `/root/a5_cycle278` remains **PASS, no findings** on this exact tree.
- Exact-head offline-safety CI run 38820783123 / job 116716584278 completed successfully; every recorded step passed.
- PAY-5 is closed as a bounded verified repair. Full #245/#256 product acceptance and legal/source completeness remain NOT PASS; the lawful populated synchronized NTM snapshot remains unavailable.
- A6 request `core-s1-6415f443120f-r9-g106` is unchanged and not sent.
- Evidence: `.ai/orchestration/evidence/cycle279_pay5_ci_closure.json`; PR receipt: #256 comment 6207980737.
- TASK_BOARD revision 813 was not changed because its CAS write was rejected at the connector approval boundary; the write was not retried.
- Next safe step: reconcile the next unresolved stale payment bundle against primary sources while preserving fail-closed admission, applicability, provenance and final-total withholding.

