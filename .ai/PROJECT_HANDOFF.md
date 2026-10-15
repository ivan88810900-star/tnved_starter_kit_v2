## 2026-10-14 — Packing-list async tests made dependency-independent on draft PR #259

- On exact PR #259 parent `092ce778585ef4adb48c987d844b9024877b43cd`, the clean tracked environment had no `pytest-asyncio`; `tests/test_packing_list_classify.py` therefore failed with `async def functions are not natively supported` instead of executing its scenario.
- Draft [PR #259](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/259) now publishes exact remote head `860b2098726a420af069492bdd32f8b23b619c19`, tree `2f8488f510648786c73fcc4e3b91e5f1ea00ea90`; local author head `ce490de24c66ded8f1b44e49839bb5f9760127a4` has the exact same tree. Only `customs-clear/backend/tests/test_packing_list_classify.py` and `customs-clear/backend/tests/test_packing_list_tasks.py` changed.
- The three async cases now run through stdlib `asyncio.run`; all original test names, 18 assert expressions and async calls are retained. The classified background-task scenario keeps creation, background execution and lookup on one event loop. No dependency, product, source, legal, data or workflow behavior changed.
- Author: focused **4 passed**; reverse order **4 passed**; adjacent packing tranche **10 passed**; compile and diff-check exit 0. Independent A5 `/root/a5_cycle237`: **PASS, no findings**; focused **4 passed** with no skip/xpass, adjacent tranche **10 passed** in both orders, AST preservation, same-loop instrumentation and exception-propagation probes PASS.
- Exact-head CI [run 38509036982 / job 115673056581](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38509036982/job/115673056581): **success** (`offline-safety`).
- A diagnostic broad command that kept `test_ntm_full_sync.py` and the three missing-workflow assertions explicitly outside the run advanced to **1,486 passed, 2 skipped, 3 deselected + 103 subtests**. It then reproduced the next independent defect: `tests/test_rate_display.py` uses ambient SQLite without `hs_rates`; standalone A5 reproduction was **3 failed**, exit 1, and created a 4,096-byte `customs.db`, moved recoverably to `/tmp`.
- NTM-3/full-sync remains blocked by the unavailable lawful populated synchronized snapshot, and the workflow assertions remain unresolved; neither gate was weakened or claimed as passed. Full #245 acceptance and legal/source completeness remain NOT PASS. A6 `core-s1-6415f443120f-r9-g106` is unchanged and undispatched. No merge, deploy, production write, enforcement/flag, secret/permission or destructive action was performed.

## 2026-10-14 — Normative-bundle order isolation published on draft PR #259

- On exact PR #259 parent `b889a16caa14d88f4fcbc427fc6c664c2f17ca6d`, `tests/test_normative_bundle.py` passed alone (**7 passed**) but failed after `tests/test_invoice_and_compare.py` (**1 failed, 3 passed**, exit 1): preloaded `rate_display.SessionLocal` still targeted ambient SQLite, which created a 4,096-byte `customs.db` and failed without `hs_rates`.
- Draft [PR #259](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/259) now publishes exact remote head `092ce778585ef4adb48c987d844b9024877b43cd`, tree `a2929499e8bd63e0a4bfd7e50a892f54ea73f54a`; local author head `5d11bf69c0b99f9a0eab8a522038fdda5b268bf6` has the exact same tree. Only `customs-clear/backend/tests/test_normative_bundle.py` changed; its seven original test methods/assertions are AST-identical.
- The module fixture now redirects `DATABASE_URL`, rebinds all preloaded database aliases by identity, restores aliases/modules imported during the fixture, protects ambient DB/WAL/SHM, and unlinks the disposable database even if `engine.dispose()` raises.
- Author: focused **7 passed**; invoice/normative both orders **9 passed**; payment/NTM adjacency both orders **69 passed**. Initial A5 `/root/a5_cycle236` rejected a dispose-failure cleanup gap; after correction fresh A5 `/root/a5_cycle236b`: **PASS, no findings**, focused **7 passed**, both orders **9 passed**, extended tranches **89 passed** each, setup/test/create-engine/dispose fault injection PASS.
- Exact-head CI [run 38503849272 / job 115656706829](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38503849272/job/115656706829): **success** (`offline-safety`).
- The broad command now reaches **659 passed + 103 subtests** and stops at `tests/test_ntm_full_sync.py`, which requires the unavailable populated synchronized NTM snapshot. This is the known NTM-3 gate; the test was not weakened and no snapshot/data was fabricated. The three absent scheduled-data-refresh workflow assertions remain explicitly deselected; no workflow/config change was made.
- Full #245 acceptance and legal/source completeness remain NOT PASS. A6 `core-s1-6415f443120f-r9-g106` is unchanged and undispatched. No merge, deploy, production write, enforcement/flag, secret/permission or destructive action was performed.

## 2026-10-14 — Invoice scenario comparison isolation published on draft PR #259

- Broad backend reproduction on exact PR #259 parent `8dd0e5f1432acdc3a1443ecaf0e3a82139afb79d` stopped in `ScenarioCompareTests.test_compare_two_countries` after **561 passed + 103 subtests**: the test opened an ambient 4,096-byte `customs.db`, failed because `exchange_rates` was absent, and tripped the classification-inventory teardown guard.
- Draft [PR #259](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/259) now publishes exact remote head `b889a16caa14d88f4fcbc427fc6c664c2f17ca6d`, tree `7f4608749948d819a6ce7babac4f75dcb1ba77f0`; local author head `4f224e50b4dc2826e5cc5db82555d99b51f5bb1c` has the exact same tree. Only `customs-clear/backend/tests/test_invoice_and_compare.py` changed.
- The test now uses migrated disposable SQLite, isolates already-loaded and late-loaded database aliases, restores environment/modules in `finally`, guards the ambient and pinned databases, and seeds deterministic FX, HS rate, DE preference and ROP data. It continues to exercise real scenario/payment/ROP behavior and now verifies RUB conversion, preference application, totals and the best scenario.
- A0 focused command: **2 passed**, exit 0. Author forward/reverse adjacent tranches: **20 passed** each. Independent A5 `/root/a5_cycle235`: **PASS, no findings**; focused **2 passed**, payment/ROP/preference tranches **71 passed** in both orders, adversarial teardown restoration PASS, no ambient DB/sidecars.
- Exact-head CI [run 38498877608 / job 115640826008](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38498877608/job/115640826008): **success** (`offline-safety`).
- The broad command now advances to the distinct `tests/test_normative_bundle.py::NormativeBundleTests::test_compute_includes_tnved_context` ambient-database isolation failure after **599 passed + 103 subtests**. The three assertions for absent `.github/workflows/scheduled-data-refresh.yml` remain explicitly deselected; no workflow/config change was made.
- NTM-3/full-sync remains blocked by the absence of a lawful populated synchronized snapshot; full #245 acceptance and legal/source completeness remain NOT PASS. A6 `core-s1-6415f443120f-r9-g106` is unchanged and undispatched. No merge, deploy, production write, enforcement/flag, secret/permission or destructive action was performed.

## 2026-10-14 — Data-refresh subprocess isolation published on draft PR #259

- Broad backend reproduction on exact PR #258 head `7f7f4938d6145979d45fddd5b04cdede83ca6e49` stopped after **254 passed + 47 subtests**: `test_script_check_only_mode` launched ambient `python3`, returned empty stdout after `ModuleNotFoundError: loguru`, created a 4,096-byte ambient `customs.db`, and caused the classification-inventory teardown guard to fail.
- Stacked draft [PR #259](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/259) publishes exact remote head `8dd0e5f1432acdc3a1443ecaf0e3a82139afb79d`, tree `1b5e40de4afb8847018eef5cd43e03506f5ff52e`; local author head `b7364510a5046c7da8f8aa600048e13aad6661e4` has the exact same tree. Only `customs-clear/backend/tests/test_data_refresh.py` changed.
- Direct freshness checks and the script subprocess now use disposable SQLite, the subprocess uses the exact pytest interpreter, valid freshness exit codes `0/1` remain bound to `all_fresh`, and empty/non-JSON output fails with captured exit/stdout/stderr diagnostics. Product code, source data and legal semantics are unchanged.
- A0 non-workflow module command: **15 passed, 3 deselected**, exit 0. Independent A5 `/root/a5_cycle234`: **PASS, no findings**; focused/adversarial, forward/reverse (**27 passed, 3 deselected** each), teardown/env restoration, AST preservation and no-ambient-DB checks passed.
- Exact-head CI [run 38494033356 / job 115625652725](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38494033356/job/115625652725): **success** (`offline-safety`).
- The broad command now advances to the distinct pre-existing missing `.github/workflows/scheduled-data-refresh.yml` assertion after **257 passed + 47 subtests**. No workflow/config change was made. NTM-3/full-sync remains blocked by the absence of a lawful populated synchronized snapshot; full #245 acceptance remains NOT PASS.
- A6 `core-s1-6415f443120f-r9-g106` is unchanged and undispatched. No merge, deploy, production write, enforcement/flag, secret/permission or destructive action was performed.

## 2026-10-14 — NSI-1995 immutable provenance published on draft PR #258

- Official read-only NSI API documentation and a live code-1995 element were checked before design. The element exposed `id`, `dateTimeFrom`, `dateTimeTo`, `dateTimeUpdated`, `DOC_NORM` and `DOC_USEAREA`; it did not expose `versionId`, so the implementation preserves that field as optional instead of inventing it.
- Draft [PR #258](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/258) now publishes exact head `7f7f4938d6145979d45fddd5b04cdede83ca6e49`, tree `91124ff54a054772168a84725845dd78659adcce`; local author exact-tree commit `5cdecd7b8041a8744f828418d04514166cf4dfed`. Parent was the verified NTM-1 head `60e097646aa1249b776df3ed018ad42d5986550d`.
- Each official NSI-1995 element is stored losslessly as deterministic canonical UTF-8 JSON plus SHA-256. Source id, optional version id and validity/update timestamps are retained; `DOC_NORM` and `DOC_USEAREA` are normalized onto the current SGR record, which links to the raw SHA. Re-import is idempotent and a changed raw element retains the previous revision.
- A0 focused provenance/pagination/status command: **40 passed**, exit 0. Author migration upgrade/downgrade and compile checks exited 0. Independent A5 `/root/a5_cycle233`: **PASS, no findings**, **160 passed**, live read-only NSI-1995 round-trip PASS, SQLite FK/migration and PostgreSQL SQL compilation PASS.
- Exact-head CI [run 38488698821 / job 115608493434](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38488698821/job/115608493434): **success** (`offline-safety`). NTM-3/full-sync remains blocked by the absence of a lawful populated synchronized snapshot; full #245 acceptance and legal/source completeness remain NOT PASS.
- A6 `core-s1-6415f443120f-r9-g106` is unchanged and undispatched. No merge, deploy, production DB write, enforcement/flag, secret/permission or destructive action was performed.

## 2026-10-13 — NSI SGR pagination fail-closed fix published as draft PR #258

- Confirmed parent defect on PR #256 head `3c24676a69b1d78d320bd5764fb04f5ac3f3430d`: official total 2998 with page sizes 1000/998/1000 returned only 1998 rows and stopped after offsets 0/1000; reproduction exit 0.
- Draft [PR #258](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/258) publishes exact head `60e097646aa1249b776df3ed018ad42d5986550d`, tree `6d562e11956fa5c76ba8f84776cc45919d98d38c`; local author exact-tree commit `5ea800e7d56c23b7f62067fc4ce6d9ea1c9c7522`.
- Short non-empty pages now continue to the official target; requests are capped at 1500 rows; malformed totals/pages, premature exhaustion and malformed rows fail before the first upsert. Explicit `max_rows` truncation is logged `partial`; a confirmed complete zero-row registry remains `ok`. `NSI_SGR_CODE=1995` and normative data are unchanged.
- Author/A0 focused and adjacent offline command: **157 passed**, exit 0; `py_compile` and `git diff --check` exit 0. Protected DB/cache fingerprints remained unchanged and no network was used.
- Initial independent A5 `/root/a5_cycle232` rejected the first candidate for incorrect SyncLog status, the missing 1500-row cap and row validation after a partial upsert. Fresh review of the repaired exact tree: **PASS, no findings**, independent **157 passed** plus adversarial probes, exit 0.
- Exact-head CI [run 38482169829 / job 115587083420](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38482169829/job/115587083420): **success** (`offline-safety`).
- Next: reconcile live PR #258/#256 heads, then continue the next bounded issue-257 or broad backend fixture defect. A lawful populated synchronized NTM snapshot is still unavailable; full #245 acceptance and legal/source completeness remain NOT PASS. A6 `core-s1-6415f443120f-r9-g106` is unchanged and undispatched. No merge, deploy, production write, flag or permission change was performed.

## 2026-10-13 — VAT-ingestion database isolation published on PR #256

- Exact candidate: `3c24676a69b1d78d320bd5764fb04f5ac3f3430d`, tree `a4e3cd52d0133698e5da905f0e48c52a087316b3`; parent `d309f36fd74af2015e689b87b360a874e754d733`; local author exact-tree commit `f23edbc2716823db4a647840fca7f902a435b5da`.
- Parent reproduction: `python -m pytest -q tests/test_vat_ingestion.py` exited 0 with **37 passed + 10 subtests** but created a 1,036,288-byte ambient `customs.db`; the DB/WAL/SHM probe artifacts were removed.
- The unchanged VAT-ingestion/API scenarios now use disposable SQLite and restore preloaded and dynamically imported `app.*` / `scripts.*` engine and session aliases. Cleanup is safe when either `create_engine` or `init_db` fails. No product algorithm, normative source or legal applicability changed.
- Author/A0: focused **37 passed + 10 subtests**; VAT/excise both orders **62 passed + 19 subtests**; VAT/import-duty both orders **95 passed + 10 subtests**; orchestration safety **124 passed + 175 subtests**; exact-remote focused **37 passed + 10 subtests**. All final commands exited 0; all 37 original test methods are AST-identical; protected fingerprints stayed unchanged; no final ambient SQLite.
- The first independent A5 `/root/a5_cycle230` rejected the initial tree because early `create_engine` failure caused a secondary cleanup `AttributeError`. The repaired exact tree received fresh independent A5 `/root/a5_cycle230b` **PASS without findings**, including both early-failure paths, alias restoration, execution-order controls, AST parity and cleanup.
- Exact-head CI [run 38476052793 / job 115566887191](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38476052793/job/115566887191): **success**.
- Next triage: eleven remaining API/payment/assistant/risk consumers were rechecked on the exact head and passed without creating ambient SQLite. The next bounded step is a clean broader backend fixture tranche to identify and reproduce the next real failure before any patch.
- The issue #257 bounded probe was not repeated because its receipt already exists. Full #245 acceptance and legal/source completeness remain NOT PASS; a lawful populated synchronized NTM snapshot is unavailable. A6 `core-s1-6415f443120f-r9-g106` remains unchanged and undispatched. No merge, deploy or production write was performed.

## 2026-10-13 — Excise-ingestion database isolation published on PR #256

- Exact candidate: `d309f36fd74af2015e689b87b360a874e754d733`, tree `e57cd2e9567ec7ad519381e878d75f2a9128a4f6`; parent `bb1951dbdf3b5b5136083d60b1896fdb620f05ab`; local author exact-tree commit `c1e22d9de3b424310cc6d692a644fcbe8ca1b154`.
- Parent reproduction: `python -m pytest -q tests/test_excise_ingestion.py` exited 0 with **25 passed + 9 subtests** but created a 1,036,288-byte ambient `customs.db`; the probe artifact was removed.
- The unchanged excise-ingestion/API scenarios now use disposable SQLite and restore preloaded and dynamically imported `app.*` / `scripts.*` engine and session aliases, including setup-failure cleanup. No product algorithm, normative source or legal applicability changed.
- Author/A0: focused **25 passed + 9 subtests**; excise/import-duty both orders **83 passed + 9 subtests**; excise/VAT both orders **62 passed + 19 subtests** under a process-scoped disposable database; orchestration safety **124 passed + 175 subtests**; exact-remote focused **25 passed + 9 subtests**. All final commands exited 0; pinned catalogue/revision fingerprints stayed unchanged; no final ambient SQLite.
- The first independent A5 `/root/a5_cycle229` correctly rejected the initial tree because a dynamically imported seed-module engine alias remained bound to the deleted temporary database. The repaired exact tree received fresh independent A5 `/root/a5_cycle229b` **PASS without findings**: focused, both execution orders, forced-init cleanup, AST parity, real endpoint assertions, protected fingerprints and clean worktree verified.
- Exact-head CI [run 38468419439 / job 115540961759](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38468419439/job/115540961759): **success**.
- Next reproduced target: on this exact HEAD, `test_vat_ingestion.py` exits 0 with **37 passed + 10 subtests** but creates a 1,036,288-byte ambient `customs.db`; the artifact was removed.
- The issue #257 bounded probe was not repeated because its receipt already exists. Full #245 acceptance and legal/source completeness remain NOT PASS; a lawful populated synchronized NTM snapshot is unavailable. A6 `core-s1-6415f443120f-r9-g106` remains unchanged and undispatched. No merge, deploy or production write was performed.

## 2026-10-13 — Normative source-import database isolation published on PR #256

- Exact candidate: `bb1951dbdf3b5b5136083d60b1896fdb620f05ab`, tree `c86766faa404a689b53fdadb0fc0b4cd901b10d8`; parent `3bee53f0ba15de9e860b5d6d926183b169862847`; local author exact-tree commit `9160168bf8c7ef5cc0fd524f06131dbfe5a4a674`.
- Parent reproduction: `python -m pytest -q tests/test_source_import.py` exited 0 with **3 passed** but created a 1,036,288-byte ambient `customs.db`; the probe artifact was removed.
- The unchanged source-import scenarios now use class-scoped disposable SQLite and restore all patched database/FTS state, including setup-failure cleanup. No product algorithm, normative source or legal applicability changed.
- Author/A0: focused **3 passed**; forward/reverse controls **7 passed** each; orchestration safety **124 passed + 175 subtests**; exact-remote focused **3 passed**. All final commands exited 0; pinned catalogue SHA-256 `53847cb00ebc53f6315042325bc416d13d65cf020a10530a4ce7dde848ed1ff2` stayed unchanged; no final ambient SQLite.
- Independent A5 `/root/a5_cycle228`: **PASS without findings**; focused **3 passed**, independent forward/reverse controls **61 passed** each, original three test-method ASTs, setup-failure cleanup, protected fingerprints and one-file scope verified.
- Exact-head CI [run 38460456175 / job 115513957704](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38460456175/job/115513957704): **success**.
- Next reproduced target: on this exact HEAD, `test_excise_ingestion.py` exits 0 with **25 passed + 9 subtests** but creates a 1,036,288-byte ambient `customs.db`; the artifact was removed. `test_payment_source_ingestion.py`, `test_import_restrictions.py`, `test_probe_fcs_sources.py`, and `test_normative_bundle.py` were rechecked clean.
- The issue #257 bounded probe was not repeated because its receipt already exists. Full #245 acceptance and legal/source completeness remain NOT PASS; a lawful populated synchronized NTM snapshot is unavailable. A6 `core-s1-6415f443120f-r9-g106` remains unchanged and undispatched. No merge, deploy or production write was performed.

## 2026-10-13 — VED-report PDF database isolation published on PR #256

- Exact candidate: `3bee53f0ba15de9e860b5d6d926183b169862847`, tree `b34b3ed7349d41dd095c6baa93983a661876304c`; parent `4d23c17e7971794737c41b03f47fa757c897013e`; local author exact-tree commit `312931e1c34dee6c3fc9ec5fa396c324096979fe`.
- Parent reproduction: `python -m pytest -q tests/test_ved_report_pdf_api.py` exited 0 with **1 passed** but created a 1,036,288-byte ambient `customs.db`; the probe artifact was removed.
- The unchanged VED-report PDF endpoint scenario now bootstraps disposable SQLite, redirects the preview-revision marker, rebinds loaded session/engine aliases, restores environment/modules and removes temporary DB sidecars. No product algorithm, normative source or legal applicability changed.
- Author/A0: focused **1 passed**; forward/reverse adjacent controls **4 passed** each; orchestration safety **124 passed + 175 subtests**; exact-remote focused **1 passed**. All final commands exited 0; pinned catalogue/revision hashes stayed unchanged; no final ambient SQLite.
- Independent A5 `/root/a5_cycle227`: **PASS without findings**; focused **1 passed**, independent forward/reverse controls **4 passed** each, original test-method AST, real endpoint/PDF assertions, protected fingerprints and cleanup verified.
- Exact-head CI [run 38450516833 / job 115479905765](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38450516833/job/115479905765): **success**.
- Next reproduced target: on this exact HEAD, `test_source_import.py` exits 0 with **3 passed** but creates a 1,036,288-byte ambient `customs.db`; the probe artifact was removed. Seven other scanned DB consumers passed cleanly.
- The issue #257 bounded probe was not repeated because its receipt already exists; the later Dot comment remains a coordination queue, not an authority change. Full #245 acceptance and legal/source completeness remain NOT PASS; a lawful populated synchronized NTM snapshot is unavailable. A6 `core-s1-6415f443120f-r9-g106` remains unchanged and undispatched. No merge, deploy or production write was performed.

## 2026-10-13 — VED-intel SSE database isolation published on PR #256

- Exact candidate: `4d23c17e7971794737c41b03f47fa757c897013e`, tree `0f1ef0af4d505ff50c26fd7fbe1e572e3b9ada6b`; parent `470d4122cda57c29eb0f83dabe7d381668d84e32`; local author exact-tree commit `a0caafae59965f24f5c0e9d68b4d74d496077845`.
- Parent reproduction: `python -m pytest -q tests/test_ved_intel_sse.py` exited 0 with **1 passed** but created a 1,036,288-byte ambient `customs.db`; the probe artifact was removed.
- The unchanged unknown-job SSE 404 scenario now bootstraps disposable SQLite, redirects the preview-revision marker, rebinds loaded session/engine aliases, restores environment/modules and removes temporary DB sidecars. No product algorithm, normative source or legal applicability changed.
- Author/A0: focused **1 passed**; forward/reverse VED-intel controls **4 passed** each; orchestration safety **124 passed + 175 subtests**; exact-remote focused **1 passed**. All final commands exited 0; pinned catalogue/revision hashes stayed unchanged; no final ambient SQLite.
- Independent A5 `/root/a5_cycle226`: **PASS without findings**; focused **1 passed**, independent forward/reverse controls **4 passed** each, original test-method AST, protected fingerprints and cleanup verified.
- Exact-head CI [run 38442816240 / job 115453461120](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38442816240/job/115453461120): **success**.
- Next reproduced target: on this exact HEAD, `test_ved_report_pdf_api.py` exits 0 with **1 passed** but creates a 1,036,288-byte ambient `customs.db`; the probe artifact was removed.
- The issue #257 bounded probe was not repeated because its receipt already exists; the later Dot comment remains a coordination queue, not an authority change. Full #245 acceptance and legal/source completeness remain NOT PASS; a lawful populated synchronized NTM snapshot is unavailable. A6 `core-s1-6415f443120f-r9-g106` remains unchanged and undispatched. No merge, deploy or production write was performed.

## 2026-10-13 — Async VED-intel API database isolation published on PR #256

- Exact candidate: `470d4122cda57c29eb0f83dabe7d381668d84e32`, tree `4f24207eb68bf7c04341978142da0d38feb4fc4b`; parent `293f2a2a156ae68bbaa5bb4a858a19eaa9d1ba6b`; local author exact-tree commit `7da2bc8211eda5eb4602ec2de867154b69939e6b`.
- Parent reproduction: `python -m pytest -q tests/test_ved_intel_async_api.py` exited 0 with **2 passed** but created a 1,036,288-byte ambient `customs.db`; the probe artifact was removed.
- The unchanged async job acceptance/polling and not-found scenarios now bootstrap disposable SQLite, redirect the preview-revision marker, rebind loaded session/engine aliases, restore environment/modules and remove temporary DB sidecars. No product algorithm, normative source or legal applicability changed.
- Author/A0: focused **2 passed**; forward/reverse adjacent controls **9 passed** each; orchestration safety **124 passed + 175 subtests**; exact-remote focused **2 passed**. All final commands exited 0; pinned catalogue/revision hashes stayed unchanged; no final ambient SQLite.
- Independent A5 `/root/a5_cycle225`: **PASS without findings**; focused **2 passed**, independent forward/reverse controls **9 passed** each, both original test-method ASTs, protected fingerprints and cleanup verified.
- Exact-head CI [run 38435329754 / job 115427691046](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38435329754/job/115427691046): **success**.
- Next reproduced target: on this exact HEAD, `test_ved_intel_sse.py` exits 0 with **1 passed** but creates a 1,036,288-byte ambient `customs.db`; the probe artifact was removed.
- The issue #257 bounded probe was not repeated because its receipt already exists; the later Dot comment remains a coordination queue, not an authority change. Full #245 acceptance and legal/source completeness remain NOT PASS; a lawful populated synchronized NTM snapshot is unavailable. A6 `core-s1-6415f443120f-r9-g106` remains unchanged and undispatched. No merge, deploy or production write was performed.

## 2026-10-13 — VED-intel API database isolation published on PR #256

- Exact candidate: `293f2a2a156ae68bbaa5bb4a858a19eaa9d1ba6b`, tree `be4a016338cd3ad7d98225c8fb66ce85751744a8`; parent `ed799f2d7c37dda719bfaef93a266c7ea495e63b`; local author exact-tree commit `d04485717545d1a8a163aa6b645b396dea855631`.
- Parent reproduction: `python -m pytest -q tests/test_ved_intel_api.py` exited 0 with **1 passed** but created a 1,036,288-byte ambient `customs.db`; the probe artifact was removed.
- The unchanged VED-intel endpoint scenario now bootstraps disposable SQLite, redirects the preview-revision marker, rebinds loaded session/engine aliases, restores environment/modules and removes temporary DB sidecars. No product algorithm, normative source or legal applicability changed.
- Author/A0: focused **1 passed**; forward/reverse adjacent controls **11 passed** each; orchestration safety **225 passed + 266 subtests**; exact-remote focused **1 passed**. All final commands exited 0; pinned catalogue/revision hashes stayed unchanged; no final ambient SQLite.
- Independent A5 `/root/a5_cycle224`: **PASS without findings**; focused **1 passed**, independent forward/reverse controls **11 passed** each, original test-method AST, protected fingerprints and cleanup verified.
- Exact-head CI [run 38427806072 / job 115401701528](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38427806072/job/115401701528): **success**.
- Next reproduced target: on this exact HEAD, `test_ved_intel_async_api.py` exits 0 with **2 passed** but creates a 1,036,288-byte ambient `customs.db`; the probe artifact was removed.
- The issue #257 bounded probe was not repeated because its receipt already exists; the later Dot comment remains a coordination queue, not an authority change. Full #245 acceptance and legal/source completeness remain NOT PASS; a lawful populated synchronized NTM snapshot is unavailable. A6 `core-s1-6415f443120f-r9-g106` remains unchanged and undispatched. No merge, deploy or production write was performed.

## 2026-10-13 — Decision-suggest database isolation published on PR #256

- Exact candidate: `ed799f2d7c37dda719bfaef93a266c7ea495e63b`, tree `a1cb51c669e4201a293cbc1cdefa1bbbceb79ab9`; parent `d41cf8dc270c448e7be4fdf1b3d29f2842807312`; local author exact-tree commit `efa7731a4f91ee2eac58be0e1466a1be50442511`.
- Parent reproduction: `python -m pytest -q tests/test_decision_suggest_hs.py` exited 0 with **4 passed** but created a 1,036,288-byte ambient `customs.db`.
- The unchanged four decision-history/hints scenarios now bootstrap disposable SQLite, redirect the preview-revision marker, rebind loaded session/engine aliases, restore environment/modules and remove temporary DB sidecars. No product algorithm, normative source or legal applicability changed.
- Author/A0: focused **4 passed**; forward/reverse adjacent controls **15 passed** each; orchestration safety **124 passed + 175 subtests**; exact-remote focused **4 passed**. All final commands exited 0; pinned catalogue/revision hashes stayed unchanged; no final ambient SQLite.
- Independent A5 `/root/a5_cycle223`: **PASS without findings**; focused **4 passed**, independent forward/reverse controls **9 passed** and **10 passed**, four test-method ASTs, import-order isolation, protected fingerprints and cleanup verified.
- Exact-head CI [run 38417501640 / job 115365736671](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38417501640/job/115365736671): **success**.
- Next reproduced target: on this exact HEAD, `test_ved_intel_api.py` exits 0 with **1 passed** but creates a 1,036,288-byte ambient `customs.db`; the probe artifact was removed. `test_safe_http_errors.py` and `test_upload_packing_list_api.py` were rechecked clean.
- The issue #257 comment `DOT-PILOT-SIX-TASKS-20261013` was read and remains a coordination/triage queue, not an authority change. Full #245 acceptance and legal/source completeness remain NOT PASS; a lawful populated synchronized NTM snapshot is unavailable. A6 `core-s1-6415f443120f-r9-g106` remains unchanged and undispatched. No merge, deploy or production write was performed.

## 2026-10-13 — Preview permit-badges database/revision isolation published on PR #256

- Exact candidate: `d41cf8dc270c448e7be4fdf1b3d29f2842807312`, tree `7d28cd861c8e742feb3f3475abdc82fa5a2f05fe`; parent `0ee5c48f8965995e2340d7ccd00bbf46e562bf8b`; local author exact-tree commit `19f14b5fdd3e96d79d250d41217f504838f0e427`.
- Parent reproduction: `python -m pytest -q tests/test_preview_permit_badges.py` exited 1 with **1 failed**, reported missing `tnved_commodities`, created a 4,096-byte ambient `customs.db`, and mutated the tracked preview revision marker.
- The unchanged 10-case endpoint regression now bootstraps a disposable classification inventory, redirects the preview marker, rebinds loaded database aliases, removes temporary files/sidecars and verifies protected fingerprints. No product algorithm, normative source or legal applicability changed.
- Author/A0: focused **1 passed**; forward/reverse controls **30 passed** each; bounded broad **182 passed + 3 subtests, 1 skipped**; orchestration safety **225 tests OK**; exact-remote focused **1 passed**. All commands exited 0; protected catalogue/marker hashes stayed unchanged; no final ambient SQLite.
- Independent A5 `/root/a5_cycle222`: **PASS without findings**; focused and three adversarial environment runs each passed **1**, forward/reverse controls each passed **30**, AST parity, sentinel fingerprints and teardown cleanup verified.
- Exact-head CI [run 38410104672 / job 115339853313](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38410104672/job/115339853313): **success**.
- Next reproduced target: on this exact HEAD, `test_decision_suggest_hs.py` exits 0 with **4 passed** but creates a 1,036,288-byte ambient `customs.db`; probe artifacts were removed.
- Full #245 acceptance and legal/source completeness remain NOT PASS; a lawful populated synchronized NTM snapshot is unavailable. A6 `core-s1-6415f443120f-r9-g106` remains unchanged and undispatched. No merge, deploy or production write was performed.

## 2026-10-13 — Permit-suggest database isolation published on PR #256

- Exact candidate: `0ee5c48f8965995e2340d7ccd00bbf46e562bf8b`, tree `31b5cf01d51bce39e207292e922ba9d171eb76f7`; parent `8557b12485295b02ef87aaa51bdb938a20a5ab7b`; local author exact-tree commit `1e26418fba810d74a598419282fb8ff8be0c5d5d`.
- Parent reproduction: `python -m pytest -q tests/test_permit_suggest.py` exited 0 with **6 passed** but created a 4,096-byte ambient `customs.db`.
- The unchanged six test methods now bind TROIS registry loading to disposable SQLite, restore patched aliases/state, remove sidecars and protect ambient/pinned fingerprints. No product algorithm, normative source or legal applicability changed.
- Author/A0: focused **6 passed**; forward/reverse controls **27 passed, 1 skipped** each; bounded broad **181 passed + 3 subtests, 1 skipped**; orchestration safety **124 tests OK**; exact-remote focused **6 passed**. All commands exited 0; no final ambient SQLite.
- Independent A5 `/root/a5_cycle221`: **PASS without findings**; focused **6 passed**, independent forward/reverse **15 passed, 1 skipped** each, adversarial ambient DB-variable run **6 passed** with no DB creation.
- Exact-head CI [run 38402241504 / job 115312530656](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38402241504/job/115312530656): **success**.
- Next reproduced target: `test_preview_permit_badges.py` fails **1/1** with missing `tnved_commodities`, creates a 4,096-byte ambient DB and mutates the tracked preview revision marker; those probe artifacts were removed/restored.
- Full #245 acceptance and legal/source completeness remain NOT PASS; a lawful populated synchronized NTM snapshot is unavailable. A6 `core-s1-6415f443120f-r9-g106` remains unchanged and undispatched.

## 2026-10-13 — Permits normalize/API database isolation published on PR #256

- Exact candidate: `8557b12485295b02ef87aaa51bdb938a20a5ab7b`, tree `64b96d301f73edabcabf6471b10998611449ab3e`; parent `6c1f3db6dc1da31683163fe9d5fb2966c77135e4`; local author exact-tree commit `b53cf41a3a5871a92d01d924c515218e2f3ece1b`.
- Parent reproduction: `python -m pytest -q tests/test_permits_normalize_and_api.py` exited 0 with **9 passed, 1 skipped** but created a 1,036,288-byte ambient `customs.db`.
- The unchanged 10 test methods now bootstrap disposable SQLite before `app.main`, redirect and restore loaded session/engine aliases and environment/modules, clean DB sidecars and protect ambient/pinned fingerprints. No product algorithm, normative source or legal applicability changed.
- Author/A0: focused **9 passed, 1 skipped**; forward/reverse five-module controls **55 passed, 1 skipped** each; bounded broad **188 passed + 3 subtests, 1 skipped**; orchestration safety **124 tests OK**; exact-remote focused **9 passed, 1 skipped**. All commands exited 0; no final ambient SQLite.
- Independent A5 `/root/a5_cycle220`: **PASS without findings**; focused **9 passed, 1 skipped**, independent forward/reverse controls **24 passed, 1 skipped** each, AST parity, bootstrap timing, restoration, cleanup and hashes verified.
- Exact-head CI [run 38394014237 / job 115284558655](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38394014237/job/115284558655): **success**.
- Next reproduced target: on exact HEAD, `test_permit_suggest.py` exits 0 with **6 passed** but creates a 4,096-byte ambient `customs.db`.
- Draft only. No merge, deploy, production write, enforcement/permissions/secrets change or external A6 call. Full #245 and legal/source completeness remain NOT PASS; lawful populated synchronized NTM snapshot remains unavailable.

## 2026-10-13 — ROP calculator database isolation published on PR #256

- Exact candidate: `6c1f3db6dc1da31683163fe9d5fb2966c77135e4`, tree `b3ca4b992f7d3d85a978778d2be97cc371629844`; parent `75b2a8e1fa9395bba1c88fac9f3a8255f347904f`; local author exact-tree commit `74ad6527f6f6f625af90812a3dbc2f959c3f6d12`.
- Parent reproduction: `python -m pytest -q tests/test_rop_calculator.py` exited 0 with **14 passed** but created a 1,089,536-byte ambient `customs.db`.
- The unchanged 14 calculator tests now load the tracked ROP goods and packaging bundles through the real importer into in-memory SQLite `StaticPool`; the importer session alias is restored and source/DB-sidecar fingerprints are protected. No product algorithm, normative source or legal applicability changed.
- Author: focused **14 passed**; forward/reverse seven-module controls **117 passed** each; bounded broad **383 passed + 47 subtests**; orchestration safety **124 tests OK**; exact-remote focused **14 passed**. All final commands exited 0; protected hashes stayed unchanged; no ambient SQLite.
- Independent A5 `/root/a5_cycle219`: **PASS without findings**; focused **14 passed**, independent forward/reverse controls **37 passed** each, one-file scope, AST parity, real importer population, hashes and cleanup verified.
- Exact-head CI [run 38387574926 / job 115263031228](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38387574926/job/115263031228): **success**.
- Fresh next-target triage: `test_recycling_fees.py` (14), `test_payment_engine.py` (37), `test_payment_quote.py` (9), and `test_import_duty_ingestion.py` (58) all pass on this exact HEAD and create no ambient database. Continue the read-only scan of remaining DB consumers before selecting another isolation edit.
- Draft only. No merge, deploy, production write, enforcement/permissions/secrets change or external A6 call. Full #245 and legal/source completeness remain NOT PASS; lawful populated synchronized NTM snapshot remains unavailable.

## 2026-10-13 — ROP coverage audit database isolation published on PR #256

- Exact candidate: `75b2a8e1fa9395bba1c88fac9f3a8255f347904f`, tree `517c2dc6d9fb1422b2b4f0242534b769dc70f320`; parent `09bd88e3085921733708578cce6e21a70430c0fd`; local author exact-tree commit `a63f22019632830ad6b8ffa645bb73f64c64a073`.
- Parent reproduction: `python -m pytest -q tests/test_rop_coverage_audit.py` exited 1 with **4 failed**, reported missing `rop_goods_rates`, and created a 4,096-byte ambient `customs.db`.
- The test now creates only `RopGoodsRate` and `Chapter` in in-memory SQLite and seeds exactly 16 tracked 2026 goods rows from `data/rop_rates_2024.json`. All four original test methods are AST-identical; no product algorithm, normative source or legal applicability changed.
- Author: focused **4 passed**; forward/reverse seven-module adjacency **117 passed** each; bounded broad **383 passed + 47 subtests**; orchestration safety **124 tests OK**; exact-remote focused **4 passed**. All final commands exited 0; protected hashes stayed unchanged; no focused ambient SQLite.
- Independent A5 `/root/a5_cycle217`: **PASS without findings**; focused **4 passed**, independent forward/reverse controls **32 passed** each, one-file scope, 16 tracked 2026 rows, AST parity, hashes and cleanup verified.
- Exact-head CI [run 38380603791 / job 115239756539](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38380603791/job/115239756539): **success**. The preceding trade-remedies HEAD also resolved to [run 38374382394 / job 115218983852](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38374382394/job/115218983852): **success**.
- Draft only. No merge, deploy, production write, enforcement/permissions/secrets change or external A6 call. Full #245 and legal/source completeness remain NOT PASS; lawful populated synchronized NTM snapshot remains unavailable.
- Next reproduced target: on clean exact HEAD, `test_rop_calculator.py` exits 0 with **14 passed** but creates a 1,089,536-byte ambient `customs.db`; isolate it next while preserving all calculator assertions.

## 2026-10-13 — Trade-remedies audit database isolation published on PR #256; exact-head CI pending

- Exact candidate: `09bd88e3085921733708578cce6e21a70430c0fd`, tree `5417a06e4a75ae4c7cba107be298a535f7df5b0e`; parent `024a4a631905e0081d1083fbf7c7bf6160942bd7`; local author exact-tree commit `85ff46a8cf406d664efa322314f4df9c4f3d4c7a`.
- Parent reproduction: `python -m pytest -q tests/test_trade_remedies_audit.py` exited 1 with **5 failed**, reported missing `special_duties`, and created a 4,096-byte ambient `customs.db`.
- The test now reconstructs the historical Issue #170 audit boundary in in-memory SQLite from the tracked 26 anti-dumping, 3 safeguard and 2 countervailing rows plus two explicitly labelled `EEC_AUDIT_RETAINED_TEST_ONLY` markers for the historical DB-only aggregate gap. These markers preserve only the historical count boundary and are not product/normative evidence.
- All five original test methods are AST-identical. Author: focused **5 passed**; forward/reverse adjacency **254 passed + 44 subtests** each; bounded broad **351 passed + 47 subtests**; orchestration safety **124 tests OK**; exact-remote focused **5 passed**. All listed final commands exited 0; protected source hashes stayed unchanged; no focused ambient SQLite.
- Independent A5 `/root/a5_cycle216`: **PASS, no blocking findings**; focused **5 passed**, independent adjacency **113 passed + 44 subtests**, one-file scope, AST parity, historical aggregate rationale, cleanup and hashes verified.
- Exact-head CI is **not yet registered/observable**: the authorized Actions lookup returned no run for the new SHA and, in the same check, no run for the previously known passing parent. No CI PASS or candidate acceptance is claimed.
- Draft only. No product/normative data, merge, deploy, production write, enforcement/permissions/secrets change or external A6 call. Full #245 and legal/source completeness remain NOT PASS; lawful populated synchronized NTM snapshot remains unavailable.
- Next: first verify successful exact-head CI for `09bd88e3085921733708578cce6e21a70430c0fd`. Then isolate `test_rop_coverage_audit.py`: clean exact-head reproduction exits 1 with **4 failed** because `rop_goods_rates` is absent and creates a 4,096-byte ambient `customs.db`.

## 2026-10-13 — PP908 VAT-coverage database isolation published on PR #256

- Exact candidate: `024a4a631905e0081d1083fbf7c7bf6160942bd7`, tree `634fe846c69ee758155868253e9ccdfd81e0c922`; parent checkpoint `b5c8f6938c4b20a06c6259ffa6eb1ae868a52a3c`; local author exact-tree commit `3fb9db9ebf75f9e02af0a27fbe959245992428b1`.
- Parent reproduction: `python -m pytest -q tests/test_pp908_vat_coverage.py` exited 1 with **3 failed, 2 passed** because the ambient database lacked `hs_rates` and `vat_preferences`, and created a 4,096-byte `customs.db`.
- `test_pp908_vat_coverage.py` now uses an in-memory SQLite fixture populated from 13,323 tracked VAT-rate rows and 10 tracked preference rows, patches the test/payment-engine/normative-store session aliases, restores them, and verifies protected fingerprints. All five original test methods are AST-identical and still exercise real PP908 coverage and no-overclaim assertions.
- Author exact-remote focused: **5 passed**. VAT/payment controls in both orders: **224 passed** each. Bounded 22-module control excluding the separately failing trade-remedies fixture: **455 passed + 73 subtests**. Safety: **124 tests OK**. All listed commands exited 0; diff-check clean; source hashes unchanged.
- Independent A5 `/root/a5_cycle215`: **FINAL PASS without findings**; focused **5 passed**, independent forward/reverse PP908/VAT/payment controls **46 passed** each, original-method AST parity, real 98.3% audit coverage (116/118), tracked rows, hashes, alias restoration and focused no-ambient-DB behavior verified.
- Exact-head CI [run 38366975672 / job 115194321234](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38366975672/job/115194321234): **success**.
- Draft PR only. No product code, normative/source data, merge, deploy, production write, legal applicability/enforcement/permissions/secrets change or external A6 call. Full #245 remains NOT PASS; lawful populated synchronized NTM snapshot remains unavailable.
- Next reproduced target: on the clean exact HEAD, `test_trade_remedies_audit.py` exits 1 with **5 failed** because `special_duties` is absent and creates a 4,096-byte ambient `customs.db`; isolate it next while preserving count, legacy-row, measure-type, official-source and `needs_verification` assertions.

## 2026-10-13 — VAT-preference audit database isolation published on PR #256

- Exact candidate: `b5c8f6938c4b20a06c6259ffa6eb1ae868a52a3c`, tree `41d49ab60d283a78deed100ff5b8e75fb9ebea75`; parent checkpoint `a8e5a9ce2f874d646859605bf48b67a38c5c7ddd`; local author exact-tree commit `634edd27377717a353ce1496fcf044b60ce9fd11`.
- Parent reproduction: `python -m pytest -q tests/test_vat_preferences_audit161.py` exited 1 with **4 failed** because the ambient database lacked `hs_rates` and `vat_preferences`, and created a 4,096-byte `customs.db`.
- `test_vat_preferences_audit161.py` now uses an in-memory SQLite fixture populated from tracked VAT-rate and preference bundles, patches the test/payment-engine/normative-store session aliases, restores them, and verifies all protected fingerprints. All four original test methods are AST-identical and still exercise the real engine lookup and audit assertions.
- Author exact-remote focused: **4 passed**. VAT-audit/payment/compliance controls in both orders: **223 passed** each. Broad 23-module command: **316 passed + 3 subtests**. Safety: **124 tests OK**. All final exits 0; diff-check clean; no ambient SQLite; pinned catalogue and both source bundles byte-identical.
- Independent A5 `/root/a5_cycle213`: **FINAL PASS without findings**; focused **4 passed**, independent forward/reverse VAT-audit/payment controls **50 passed** each, AST parity, real lookup, source hashes, restoration and no ambient DB verified.
- Exact-head CI [run 38359883714 / job 115171312790](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38359883714/job/115171312790): **success**.
- Draft PR only. No product code, normative/source data, merge, deploy, production write, legal applicability/enforcement/permissions/secrets change or external A6 call. Full #245 remains NOT PASS; lawful populated synchronized NTM snapshot remains unavailable.
- Next reproduced target: `test_pp908_vat_coverage.py` exits 1 with **3 failed, 2 passed**, reports missing `hs_rates`/`vat_preferences` and creates a 4,096-byte ambient `customs.db`; isolate it next while preserving PP908 coverage and no-overclaim assertions.


## 2026-10-13 — FSA registry-status database isolation published on PR #256

- Exact candidate: `a8e5a9ce2f874d646859605bf48b67a38c5c7ddd`, tree `cc589acea18a63680ebdce32eee4f6ced08b5155`; parent checkpoint `75c1f5f426a5d26094b9701fe29c00a75a2248ff`; local author exact-tree commit `6713f354d35334769749d01355a007631ff2cc6a`.
- Parent reproduction: `python -m pytest -q tests/test_fsa_registry_status_fail_closed.py` exited 0 with **20 passed** but created a 1,036,288-byte ambient `customs.db`.
- `test_fsa_registry_status_fail_closed.py` now bootstraps a disposable SQLite database, binds loaded database aliases, restores environment/module state, removes temporary SQLite files and verifies protected fingerprints. All three original test functions are AST-identical; the 18-case status matrix, expired-row rejection and UNKNOWN/manual-review lookup evidence are unchanged.
- Author exact-remote focused: **20 passed**. FSA/permits/auth/API/payment controls in both orders: **134 passed + 3 subtests** each. Broad 26-module command: **399 passed + 13 subtests**. Safety: **124 tests OK**. All exits 0; diff-check clean; no ambient DB/WAL/SHM; pinned catalogue SHA-256 unchanged.
- Independent A5 `/root/a5_cycle213`: **FINAL PASS without findings**; focused **20 passed**, independent forward/reverse FSA/permits controls **44 passed** each, fail-closed semantics, AST parity and cleanup verified.
- Exact-head CI [run 38354671784 / job 115154661235](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38354671784/job/115154661235): **success**.
- Draft PR only. No product code, normative/source data, merge, deploy, production write, legal applicability/enforcement/permissions/secrets change or external A6 call. Full #245 remains NOT PASS; lawful populated synchronized NTM snapshot remains unavailable.
- Next: on fresh PR #256 HEAD reproduce the ambient-database behavior of `test_vat_preferences_audit161.py` before editing and preserve its payment-preference audit assertions.


## 2026-10-13 — Permits verify-job ownership database isolation published on PR #256

- Exact candidate: `75c1f5f426a5d26094b9701fe29c00a75a2248ff`, tree `eb28a03be3944f09556ed4e4daab9c0ad6fb75cf`; parent checkpoint `0a830546181d2bb18f5805b202fe28a42a5f207c`; local author exact-tree commit `ddc50837c0c357cae8b8783564f134faf29e7947`.
- Parent reproduction: `python -m pytest -q tests/test_permits_verify_jobs_ownership.py` exited 0 with **4 passed** but created a 1,036,288-byte ambient `customs.db`.
- `test_permits_verify_jobs_ownership.py` now bootstraps a disposable SQLite database before importing the application surface, binds loaded database aliases, restores preloaded and late-import module state, removes the temporary database and sidecars, and verifies protected fingerprints. All four original test methods are AST-identical and still exercise real FastAPI requests, declarant/viewer/admin ownership, legacy ownerless handling, route-order protection and admin-token export.
- Author exact-remote focused: **4 passed**. Permits/sensitive/operational/documents/classify/assistant/API/payment controls in both orders: **114 passed + 3 subtests** each. Broad 25-module command: **379 passed + 13 subtests**. Safety: **124 tests OK**. All final exits 0; diff-check clean; no ambient DB/WAL/SHM; pinned catalogue SHA-256 unchanged.
- Independent A5 `/root/a5_cycle212`: **FINAL PASS without findings**; focused **4 passed**, independent five-module ordering control **22 passed**, AST parity, alias/environment/module restoration and temporary-file cleanup verified.
- Exact-head CI [run 38348649766 / job 115135780137](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38348649766/job/115135780137): **success**.
- Draft PR only. No product code, normative/source data, merge, deploy, production write, legal applicability/enforcement/permissions/secrets change or external A6 call. Full #245 remains NOT PASS; lawful populated synchronized NTM snapshot remains unavailable.
- Next: on fresh PR #256 HEAD reproduce the ambient-database behavior of `test_fsa_registry_status_fail_closed.py` before editing and preserve its fail-closed registry-status and lookup assertions.


## 2026-10-13 — Sensitive endpoints auth database isolation published on PR #256

- Exact candidate: `0a830546181d2bb18f5805b202fe28a42a5f207c`, tree `0741c481b6dcf0482890605bed79b8b26fc60f85`; parent checkpoint `b9ea7c465448cf65fda328fa55370f1e9f1c5e6b`; local author exact-tree commit `808aeab8976a9e1691a09838d33b2170cebdd4e6`.
- Parent reproduction: `python -m pytest -q tests/test_sensitive_endpoints_auth.py` exited 0 with **6 passed** but created a 1,036,288-byte ambient `customs.db`.
- `test_sensitive_endpoints_auth.py` now bootstraps a disposable SQLite database before importing the application surface, binds loaded database aliases, restores preloaded and late-import module state, removes the temporary database and sidecars, and verifies protected fingerprints. All seven original class methods, including `setUpClass`, are AST-identical and still exercise real FastAPI requests, declarant JWT login, anonymous/authenticated boundaries and missing/wrong/correct admin-token handling.
- Author exact-remote focused: **6 passed**. Sensitive/operational/documents/classify/assistant/API/payment controls in both orders: **110 passed + 3 subtests** each. Broad 24-module command: **375 passed + 13 subtests**. Safety: **124 tests OK**. All final exits 0; diff-check clean; no ambient DB/WAL/SHM; pinned catalogue SHA-256 unchanged.
- Independent A5 `/root/a5_cycle211`: **FINAL PASS without findings**; parent mutation reproduced, all candidate controls passed, real login/JWT/admin-token paths and AST parity verified, 38 SessionLocal + 6 engine aliases and environment/init_db restored, late imports and temporary SQLite cleaned up.
- Exact-head CI [run 38344097237 / job 115121400569](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38344097237/job/115121400569): **success**.
- Draft PR only. No product code, normative/source data, merge, deploy, production write, legal applicability/enforcement/permissions/secrets change or external A6 call. Full #245 remains NOT PASS; lawful populated synchronized NTM snapshot remains unavailable.
- Next: on fresh PR #256 HEAD reproduce the ambient-database behavior of `test_permits_verify_jobs_ownership.py` before editing and preserve its owner/admin authorization assertions.

## 2026-10-13 — Operational admin/auth database isolation published on PR #256

- Exact candidate: `b9ea7c465448cf65fda328fa55370f1e9f1c5e6b`, tree `5ff5abef82690e32bf10a9a052f7188a0bf0f088`; parent checkpoint `4c19b1848297e9b01264a08f5e411ecad9c98bc2`; local author exact-tree commit `bd24b4c764d44527486e6810bb27cac1b2fda411`.
- Parent reproduction: `python -m pytest -q tests/test_operational_admin_surface_auth.py` exited 0 with **7 passed** but created a 1,036,288-byte ambient `customs.db`.
- `test_operational_admin_surface_auth.py` now bootstraps a disposable SQLite database before importing the application surface, binds loaded database aliases, restores preloaded and late-import module state, removes the temporary database and sidecars, and verifies protected fingerprints. All seven original test methods are AST-identical and still exercise real FastAPI requests, `/api/auth/login`, JWT sessions, anonymous/authenticated boundaries and incorrect/correct `X-Admin-Token` handling.
- Author exact-remote focused: **7 passed**. Operational/documents/classify/assistant/API/payment controls in both orders: **104 passed + 3 subtests** each. Broad 23-module command: **369 passed + 13 subtests**. Safety: **124 tests OK**. All final exits 0; diff-check clean; no ambient DB/WAL/SHM; pinned catalogue SHA-256 unchanged.
- Independent A5 `/root/a5_cycle210`: **FINAL PASS without findings**; parent mutation reproduced, all candidate controls passed, real HTTP/auth/admin-token paths and AST parity verified, adversarial preload and alias/environment/init_db restoration confirmed, late imports and temporary SQLite cleaned up.
- Exact-head CI [run 38338909715 / job 115105248694](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38338909715/job/115105248694): **success**.
- Draft PR only. No product code, normative/source data, merge, deploy, production write, legal applicability/enforcement/permissions/secrets change or external A6 call. Full #245 remains NOT PASS; lawful populated synchronized NTM snapshot remains unavailable.
- Next: on fresh PR #256 HEAD reproduce the ambient-database behavior of `test_sensitive_endpoints_auth.py` before editing and preserve its authentication and authorization assertions.

## 2026-10-13 — Documents analyze security database isolation published on PR #256

- Exact candidate: `4c19b1848297e9b01264a08f5e411ecad9c98bc2`, tree `929a073e30da0ba2c85d6df9066671286f51b836`; parent checkpoint `03208ff9099236a5b1050a0df63c3f036f937e15`; local author exact-tree commit `0ea9e1a2d13ebecfb9053ff17aaf57084a18047a`.
- Parent reproduction: `python -m pytest -q tests/test_documents_v1_analyze_security.py` exited 0 with **2 passed** but created a 1,036,288-byte ambient `customs.db`.
- `test_documents_v1_analyze_security.py` now bootstraps a disposable SQLite database before importing the application surface, binds loaded database aliases, restores preloaded and late-import module state, removes the temporary database and sidecars, and verifies protected fingerprints. Both original security tests are AST-identical and still exercise real FastAPI requests, declarant login, HTTP 503/error-code handling and rejection of client-supplied API-key authority.
- Author exact-remote focused: **2 passed**. Documents/classify/assistant/API/payment controls in both orders: **97 passed + 3 subtests** each. Broad 22-module command: **362 passed + 13 subtests**. Safety: **124 tests OK**. All final exits 0; diff-check clean; no ambient DB/WAL/SHM; pinned catalogue SHA-256 unchanged.
- Independent A5 `/root/a5_cycle209`: **FINAL PASS without findings**; parent mutation reproduced, all candidate controls passed, real HTTP/auth paths and AST parity verified, adversarial preload and alias/environment/init_db restoration confirmed, late imports and temporary SQLite cleaned up.
- Exact-head CI [run 38335028326 / job 115093059027](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38335028326/job/115093059027): **success**.
- Draft PR only. No product code, normative/source data, merge, deploy, production write, legal applicability/enforcement/permissions/secrets change or external A6 call. Full #245 remains NOT PASS; lawful populated synchronized NTM snapshot remains unavailable.
- Next: on fresh PR #256 HEAD reproduce the ambient-database behavior of `test_operational_admin_surface_auth.py` before editing and preserve its admin-token and authenticated-session assertions.

## 2026-10-13 — Classify security API database isolation published on PR #256

- Exact candidate: `03208ff9099236a5b1050a0df63c3f036f937e15`, tree `87d4a434bce19c8d5df86ba4da648105eb0fd00b`; parent checkpoint `b0066faca700a469ff7e4b917d45bf1336168239`; local author exact-tree commit `d367c6c85b8e3afe9d12cad46d6c22cccfd0ff98`.
- Parent reproduction: `python -m pytest -q tests/test_classify_api_security.py` exited 0 with **3 passed** but created a 1,036,288-byte ambient `customs.db`.
- `test_classify_api_security.py` now bootstraps a disposable SQLite database before importing the application surface, binds loaded database aliases, restores preloaded and late-import module state, removes the temporary database and sidecars, and verifies protected fingerprints. All three original security tests are AST-identical and still exercise real FastAPI requests and declarant login.
- Author exact-remote focused: **3 passed**. Classify-security/assistant/API/payment controls in both orders: **95 passed + 3 subtests** each. Broad 21-module command: **360 passed + 13 subtests**. Safety: **124 tests OK**. All final exits 0; diff-check clean; no ambient DB/WAL/SHM; pinned catalogue SHA-256 unchanged.
- Independent A5 `/root/a5_cycle208`: **FINAL PASS without findings**; parent mutation reproduced, all candidate controls passed, real HTTP/auth paths and AST parity verified, aliases/environment restored, late imports and temporary SQLite cleaned up.
- Exact-head CI [run 38330048612 / job 115077516403](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38330048612/job/115077516403): **success**.
- Draft PR only. No product code, normative/source data, merge, deploy, production write, legal applicability/enforcement/permissions/secrets change or external A6 call. Full #245 remains NOT PASS; lawful populated synchronized NTM snapshot remains unavailable.
- Next: on fresh PR #256 HEAD reproduce the ambient-database behavior of `test_documents_v1_analyze_security.py` before editing and preserve its authorization assertions.

## 2026-10-13 — Assistant copilot database isolation published on PR #256

- Exact candidate: `b0066faca700a469ff7e4b917d45bf1336168239`, tree `2b42db6cdf6ffb49da4faace67773a1649eb3925`; parent checkpoint `8e181c074fcb271a9e51db36cb574117e1cfa016`; local author exact-tree commit `1c0653239df32500d5ef46905c46cff324736544`.
- Parent reproduction: `python -m pytest -q tests/test_assistant_copilot.py` exited 0 with **6 passed + 3 subtests** but created a 1,036,288-byte ambient `customs.db`.
- `test_assistant_copilot.py` now bootstraps a disposable SQLite database before importing the application surface, binds loaded database aliases, restores preloaded and late-import module state, removes the temporary database and sidecars, and verifies protected fingerprints. All six original test methods are AST-identical.
- Author exact-remote focused: **6 passed + 3 subtests**. Copilot/batch/decisions/journal/analytics/API/payment-engine/compliance in both orders: **92 passed + 3 subtests** each. Broad 20-module command: **357 passed + 13 subtests**. Safety: **124 tests OK**. All final exits 0; diff-check clean; no ambient DB/WAL/SHM; pinned catalogue SHA-256 unchanged.
- Independent A5 `/root/a5_cycle207`: **FINAL PASS without findings** on exact HEAD; parent mutation reproduced, candidate focused/adjacent/broad/safety controls passed, preloaded aliases and environment restored, late-import modules cleaned up, AST parity and one-file scope verified.
- Exact-head CI [run 38324992684 / job 115061487589](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38324992684/job/115061487589): **success**.
- Draft PR only. No product code, normative/source data, merge, deploy, production write, legal applicability/enforcement/permissions/secrets change or external A6 call. Full #245 remains NOT PASS; lawful populated synchronized NTM snapshot remains unavailable.
- Next: on fresh PR #256 HEAD reproduce the ambient-database behavior of `test_classify_api_security.py` before editing and preserve its authorization assertions.

## 2026-10-13 — Assistant batch API database isolation published on PR #256

- Exact candidate: `8e181c074fcb271a9e51db36cb574117e1cfa016`, tree `4d1b1027fad0acf6612f7d003c41848d302dd5ff`; parent checkpoint `40df46bbfd29027c64439b6c0c3819d823650b19`; local author exact-tree commit `417e5192034240944b8a3d0e56e170a059ad983d`.
- Parent reproduction: `python -m pytest -q tests/test_assistant_batch.py` exited 0 with **1 passed** but created a 1,036,288-byte ambient `customs.db` plus SQLite sidecars.
- `test_assistant_batch.py` now installs a disposable SQLite database before importing the authenticated application surface, binds already-loaded aliases, restores initially loaded and dynamically imported aliases, removes the temporary database and sidecars, and verifies protected fingerprints. Its original batch API test method is AST-identical.
- Author exact-remote focused: **1 passed**. Batch/decisions/journal/analytics/API/payment-engine/compliance in both orders: **86 passed** each. Broad 19-module command: **351 passed + 10 subtests**. Safety: **124 tests OK**. All final exits 0; diff-check clean; no ambient DB/WAL/SHM; pinned catalogue SHA-256 unchanged.
- Independent A5 `/root/a5_cycle206`: **FINAL PASS without findings** on exact HEAD; parent mutation reproduced, candidate focused/adjacent/broad controls passed, late-import restoration verified with **40 session + 6 engine aliases**, environment sentinels restored, AST parity and one-file scope verified.
- Exact-head CI [run 38320613262 / job 115047545846](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38320613262/job/115047545846): **success**.
- Draft PR only. No product code, normative/source data, merge, deploy, production write, legal applicability/enforcement/permissions/secrets change or external A6 call. Full #245 remains NOT PASS; lawful populated synchronized NTM snapshot remains unavailable.
- Next: on fresh PR #256 HEAD reproduce the ambient-database behavior of `test_assistant_copilot.py` before editing and preserve its orchestration and API assertions.

## 2026-10-13 — Assistant decisions API database isolation published on PR #256

- Exact candidate: `40df46bbfd29027c64439b6c0c3819d823650b19`, tree `cf1334ecc2078f0890f5f30eff78bea555171a4a`; parent checkpoint `a02575f05d697525274110f5dd8f99c059623019`; local author exact-tree commit `282b4721dc45f9dbd9e0fd36e447540c42d8f5cd`.
- Parent reproduction: `python -m pytest -q tests/test_assistant_decisions.py` exited 0 with **5 passed** but created a 1,036,288-byte ambient `customs.db`.
- `test_assistant_decisions.py` now installs a disposable SQLite database before importing the authenticated application surface, binds already-loaded application database aliases, restores all aliases and environment values, removes the temporary database and sidecars, and verifies protected file fingerprints. All five original API test methods are AST-identical.
- Author exact-remote focused: **5 passed**. Assistant-decisions/journal/analytics/API/payment-engine/compliance in both orders: **85 passed** each. Broad 18-module command: **350 passed + 10 subtests**. Safety: **124 tests OK**. All exits 0; diff-check clean; no ambient DB/WAL/SHM; pinned catalogue SHA-256 unchanged.
- Independent A5 `/root/a5_cycle205`: **FINAL PASS without findings** on exact HEAD; parent mutation reproduced, candidate focused/adjacent/broad controls passed, preloaded-app probe restored **44/44** database aliases plus environment sentinels, AST parity and one-file scope verified.
- Exact-head CI [run 38313997462 / job 115026180711](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38313997462/job/115026180711): **success**.
- Draft PR only. No product code, normative/source data, merge, deploy, production write, legal applicability/enforcement/permissions/secrets change or external A6 call. Full #245 remains NOT PASS; lawful populated synchronized NTM snapshot remains unavailable.
- Next: on fresh PR #256 HEAD reproduce the remaining ambient-database behavior of `test_assistant_batch.py` before editing and preserve its batch API assertion.

## 2026-10-12 — Journal statistics database isolation published on PR #256

- Exact candidate: `a02575f05d697525274110f5dd8f99c059623019`, tree `f79ea6706f4d530a2a72859b66f3c8603ee8a03a`; parent checkpoint `b91a90a859546ce61e5b9ebdd236dc3e6b7824b7`; local author exact-tree commit `f459fbd11549c1d4f0b3eaa4fc17238a58ef23a4`.
- Parent reproduction: `python -m pytest -q tests/test_journal_stats.py` exited 0 with **3 passed** but created a 1,036,288-byte ambient `customs.db`.
- `test_journal_stats.py` now bootstraps a disposable SQLite database, binds already-loaded application database aliases, restores all aliases and environment values, removes the temporary database and sidecars, and verifies protected file fingerprints. All three original test methods are AST-identical.
- Author exact-remote focused: **3 passed**. Journal/analytics/API/payment-engine/compliance in both orders: **80 passed** each. Broad 17-module command: **345 passed + 10 subtests**. Safety: **124 tests OK**. All exits 0; diff-check clean; no ambient DB/WAL/SHM; pinned catalogue SHA-256 unchanged.
- Independent A5 `/root/a5_cycle204`: **FINAL PASS without findings** on exact HEAD; parent mutation reproduced, candidate focused/adjacent/broad controls passed, preloaded-app probe restored **44/44** database aliases plus environment sentinels, AST parity and one-file scope verified.
- Exact-head CI [run 38308177875 / job 115007176323](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38308177875/job/115007176323): **success**.
- Draft PR only. No product code, normative/source data, merge, deploy, production write, legal applicability/enforcement/permissions/secrets change or external A6 call. Full #245 remains NOT PASS; lawful populated synchronized NTM snapshot remains unavailable.
- Next: on fresh PR #256 HEAD reproduce the remaining ambient-database behavior of `test_assistant_decisions.py` before editing and preserve its decision-history assertions.

## 2026-10-12 — Analytics overview database isolation published on PR #256

- Exact candidate: `b91a90a859546ce61e5b9ebdd236dc3e6b7824b7`, tree `5f80a650e65e6a5056889c6476346af6a0f1a23b`; parent checkpoint `641343937d9263aa3e5dfbf4481eda938c3551ed`; local author exact-tree commit `763ed6d8067c45c39d743b93aad72c50bc30b8db`.
- Parent reproduction: `python -m pytest -q tests/test_analytics_api.py` exited 1 because the overview request returned HTTP 401 without a test admin token and created a 1,036,288-byte ambient `customs.db`.
- `test_analytics_api.py` now bootstraps a disposable SQLite database, binds already-loaded application DB aliases, supplies a test-only admin token, restores all aliases and environment values, and removes the temporary database and sidecars. The existing overview test method is AST-identical; two real negative HTTP cases assert missing and invalid admin tokens return 401.
- Author exact-remote focused: **3 passed**. Analytics/API/payment-engine/compliance in both orders: **77 passed** each. Broad 16-module command: **342 passed + 10 subtests**. Safety: **124 tests OK**. All exits 0; diff-check clean; no ambient DB/WAL/SHM; pinned catalogue SHA-256 unchanged.
- Independent A5 `/root/a5_cycle203`: **FINAL PASS without findings** on exact HEAD; parent failure/mutation reproduced, candidate focused/adjacent/broad controls passed, 44 captured database aliases, both `init_db` bindings and the pre-existing admin-token value restored, AST parity and one-file scope verified.
- Exact-head CI [run 38301440084 / job 114985047144](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38301440084/job/114985047144): **success**.
- Draft PR only. No product code, normative/source data, merge, deploy, production write, legal applicability/enforcement/permissions/secrets change or external A6 call. Full #245 remains NOT PASS; lawful populated synchronized NTM snapshot remains unavailable.
- Next: on fresh PR #256 HEAD reproduce the ambient-database behavior of `test_journal_stats.py` before editing and preserve its statistics assertions.

## 2026-10-12 — API integration database isolation published on PR #256

- Exact candidate: `641343937d9263aa3e5dfbf4481eda938c3551ed`, tree `b68c5edafacce38b51b34cb3d02f26021b04682e`; parent checkpoint `6aa3e9943558b2037d1dd9e551fb8a331e7fe9ea`; local author exact-tree commit `70648d7de6bbe12c17637882c1eb6ada3fd3ccf7`.
- Parent reproduction: `python -m pytest -q tests/test_api_integration.py` exited 1 with **8 failed, 25 passed** and created a 1,056,768-byte ambient `customs.db`.
- `test_api_integration.py` now creates a disposable SQLite database, binds loaded application DB aliases to it, adds only minimum test rows, and restores all captured aliases. All 33 original test method bodies and HTTP assertions are AST-identical.
- Author exact-remote focused: **33 passed**. API/payment-engine/compliance in both orders: **74 passed** each. Broad 15-module command: **339 passed + 10 subtests**. Safety: **124 tests OK**. All exits 0; diff-check clean; no ambient DB/WAL/SHM; pinned catalogue SHA-256 unchanged.
- Independent A5 `/root/a5_cycle202`: **FINAL PASS without findings** on exact HEAD; parent failure/mutation reproduced, candidate focused/adjacent/broad controls passed, 44 captured aliases and both `init_db` bindings restored, AST parity and one-file scope verified.
- Exact-head CI [run 38295061892 / job 114964040454](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38295061892/job/114964040454): **success**.
- Draft PR only. No product code, normative/source data, merge, deploy, production write, legal applicability/enforcement/permissions/secrets change or external A6 call. Full #245 remains NOT PASS; lawful populated synchronized NTM snapshot remains unavailable.
- Next: on fresh PR #256 HEAD reproduce the ambient-database behavior of `test_analytics_api.py` before editing and preserve its API assertions.

## 2026-10-12 — Compliance database isolation published on PR #256

- Exact candidate: `6aa3e9943558b2037d1dd9e551fb8a331e7fe9ea`, tree `3d33d8c8291f27e48fc0aa71b9b730d1901a5515`; previous accepted checkpoint `86f09f07477553c07dd5c9860e3a83f533a8a44e`; local author exact-tree commit `288ea22547a0f51265c163328134cf0474029333`.
- Parent reproduction: `python -m pytest -q tests/test_compliance.py` exited 0 with **4 passed** but created an ambient 1,036,288-byte `customs.db`.
- `test_compliance.py` now uses an in-memory StaticPool database, minimum test-only payment rows, and explicit bindings for all captured payment, normative-store and rate-display database aliases. The four original test method bodies are AST-identical.
- Author focused: **4 passed**. Payment-engine adjacency in both orders: **41 passed** each. Broad 14-module payment/compliance command without `DATABASE_URL`: **306 passed + 10 subtests**. Safety: **124 tests OK**. All exits 0; diff-check clean; no ambient DB/WAL/SHM; pinned catalogue SHA-256 unchanged.
- Independent A5 `/root/a5_compliance_db_isolation_201`: **FINAL PASS without findings** on exact HEAD; parent mutation reproduced, candidate cleanup `PATCH_LEAKS=[]`, AST parity and one-file scope verified.
- Exact-head CI [run 38287007632 / job 114937679417](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38287007632/job/114937679417): **success**.
- Draft PR only. No product code, normative/source data, merge, deploy, production write, legal applicability/enforcement/permissions/secrets change or external A6 call. Full #245 remains NOT PASS; lawful populated synchronized NTM snapshot remains unavailable.
- Next: continue the fresh-head bounded inventory of integrated compliance/API tests, starting with `test_api_integration.py`; reproduce any database mutation before editing and preserve its HTTP assertions.

## 2026-10-12 — Remaining payment DB users isolated on PR #256

- Exact candidate: `86f09f07477553c07dd5c9860e3a83f533a8a44e`, tree `2b5d544ecaf158931b2f827ac41f8ae199e0fc03`; previous accepted checkpoint `d7db16b51d5d09c115d7fb0f9fff7e3ad9f27d4e`; local author exact-tree commit `d4aae4bdb8332383501a97dbc1dc25d99568315d`.
- Five backend test modules now bind all captured DB session aliases to disposable in-memory databases. All 181 original test method bodies and HTTP assertions remain unchanged.
- Author clean-checkout focused forward/reverse: **181 passed** each. Broad 13-module payment command without `DATABASE_URL`: **302 passed + 10 subtests**, exit 0. No `customs.db`, WAL or SHM was created; pinned catalogue stayed byte-identical.
- Independent A5 `/root/a5_payment_db_isolation_200` correctly rejected intermediate HEAD `4bbfc75adcaa2b1d3ee4bea78707c66498f6ee48` because `rate_display.SessionLocal` still reached ambient SQLite. Finding reproduced and fixed.
- Final A5: **PASS without findings** on exact HEAD; focused/reverse **181/181**, broad **302 + 10 subtests**, cleanup `PATCH_LEAKS=[]` and `AMBIENT_ARTIFACTS=[]`, safety **124/124**.
- Exact-head CI [run 38281892073 / job 114920887081](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38281892073/job/114920887081): **success**.
- Draft PR only. No product code, normative/source data, merge, deploy, production write, legal applicability/enforcement/permissions/secrets change or external A6 call. Full #245 remains NOT PASS; lawful populated synchronized NTM snapshot remains unavailable.
- Next: return to #245 with a fresh-head bounded NTM/classification fixture inventory and reproduce the first concrete remaining defect; do not substitute synthetic completeness for populated/full-sync evidence.

## 2026-10-12 — Hermetic broad payment regressions published on PR #256

- Exact candidate: `d7db16b51d5d09c115d7fb0f9fff7e3ad9f27d4e`, tree `18f80c48514220d2b627ff4799dc64acd4af63a8`; previous checkpoint `613cfe9a12aa1dbbc5582e7031217dd3d713c7f4`; local author exact-tree commit `b1be97f7ce8a5357b535c9470de47fef8272e4db`.
- Reproduced broad payment command: **18 failed, 284 passed + 10 subtests**, exit 1. Failures were classified as missing/stale shared-database fixture assumptions; no payment-algorithm defect was reproduced.
- Fixed four test modules with explicit disposable databases and minimum test-only rows. The calculator test retains HTTP `POST /api/calculator/compute` coverage; payment quote remains fail-closed with `total_payable_rub=None` when special duties are not configured.
- Author focused and reverse: **34 passed** each. Broad 13-file command with explicit disposable `DATABASE_URL`: **302 passed + 10 subtests**, exit 0. Configured `customs.db` remained byte-identical. Safety **124/124** and diff-check passed.
- Independent A5 `/root/a5_payment_fixture_isolation_198` correctly rejected two intermediate trees: direct-engine substitution for the HTTP calculator test, then ambient default-DB creation by the quote fixture. Both findings were reproduced and fixed.
- Final A5: **PASS without findings** on exact HEAD; focused/reverse **34/34**, broad **302 + 10 subtests**, cleanup `PATCH_LEAKS=[]`, safety **124/124**.
- Exact-head CI [run 38275697200 / job 114900495084](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38275697200/job/114900495084): **success**.
- Draft PR only. No product code, normative/source data, merge, deploy, production write, legal applicability/enforcement/permissions/secrets change or external A6 call. Full #245 remains NOT PASS; lawful populated synchronized NTM snapshot remains unavailable.
- Next: isolate remaining ambient-default DB users in unchanged `test_payment_engine.py` and API classes in payment coverage, normalization, source-ingestion and import-duty tests. Until then, run broad controls with an explicit disposable `DATABASE_URL`.

## 2026-10-12 — Assistant citation provenance published on PR #256

- Exact candidate: `613cfe9a12aa1dbbc5582e7031217dd3d713c7f4`, tree `2c863dd6f414a099d81ae7e3d1c553d9d9fd3aab`; previous checkpoint `bcb594ac8953d1c3be12c5b705ca1ba7e04340a6`.
- Reproduced: backend citations lost risk authority/legal provenance and frontend discarded it; backend and frontend focused regressions each failed **1**, exit 1.
- Fixed: signal and source-coverage provenance survives chat/copilot runtime projection; bounded authority/legal/status/excerpt is shown only for complete server-fact citations; unsafe URLs stay non-clickable. Optional destination/counterparty fields are present in the TypeScript chat contract.
- Author: backend **61 passed + 26 subtests**; frontend **109 passed**; typecheck, production build, safety **124/124** and diff-check passed; all exits 0.
- First A5 `/root/a5_assistant_citation_provenance_197` correctly failed intermediate HEAD `5089011937f51b826e1638266a16b3898a165dd2` on coverage provenance and chat trust gating; both findings were reproduced and fixed.
- Final A5 `/root/a5_assistant_citation_provenance_197_r2`: **PASS** on exact HEAD; backend expanded **64 + 29 subtests**, frontend **109**, edge probe, typecheck/build and safety **124/124** passed; no findings.
- Exact-head CI [run 38268374091 / job 114876230022](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38268374091/job/114876230022): **success**.
- Draft PR only. No merge, deploy, production/source data write, legal applicability change, enforcement/permissions/secrets change or external A6 call. Full #245 remains NOT PASS; lawful populated synchronized NTM snapshot remains unavailable.
- Next: reproduce inherited broad calculator/special-duty fixture failures on current PR #256 and classify the first concrete defect versus stale/missing fixture assumptions before editing.

## 2026-10-12 — AI sanctions/risk grounding and provenance published on PR #256

- Exact candidate: `bcb594ac8953d1c3be12c5b705ca1ba7e04340a6`, tree `4cd6220223d80b3137fe849168a37a7c53bbfa63`; previous HEAD `d0fce3527c92026a4dc687ba3bb79854d16af75f`.
- Reproduced: chat context accepted destination/counterparty fields but grounding forwarded only origin country; focused regression failed **1**, exit 1.
- Fixed: origin/destination/counterparty now flow through chat → NTM → sanctions risk; grounded risk facts retain source label, authority and legal reference; missing scope is not inferred and incomplete coverage remains fail-closed.
- Author: assistant/NTM/sanctions/API **145 passed + 29 subtests**; agent safety **124 passed**; all exits 0.
- Independent A5 `/root/a5_assistant_risk_grounding_196`: **FINAL PASS**; focused **39 + 26 subtests**, expanded **65 + 26 subtests**, independent edge probe and safety **124/124** passed; no findings.
- Exact-head CI [run 38260763805 / job 114850353328](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38260763805/job/114850353328): **success**.
- Draft PR only. No merge, deploy, production/source data write, legal applicability change, enforcement/permissions/secrets change or external A6 call. Full #245 remains NOT PASS; lawful populated synchronized NTM snapshot remains unavailable.
- Next: audit the frontend/client assistant risk-scope and citation-provenance contract end-to-end; reproduce before editing.

## 2026-10-12 — Destination-country sanctions/risk fix published on PR #256

- Exact candidate: `d0fce3527c92026a4dc687ba3bb79854d16af75f`, tree `4c81fe078de7230493a454b88b4d27a8a356f608`; previous HEAD `e7f141a145e1475e8d1c51f25c51789a084b4541`.
- Reproduced: `destination_country` was present in the public contract but discarded by the product service; disposable test failed **1**, exit 1.
- Fixed: destination country/embargo signals are evaluated separately without repeating HS/entity scopes; wording identifies destination scope; duplicate OFAC signals from one counterparty were removed.
- Author: sanctions/compliance/grounded **38 passed + 26 subtests**; agent safety **124 passed**; all exits 0.
- First A5 rejected the intermediate tree for duplicate OFAC signals. Corrected independent A5 `/root/a5_sanctions_destination_195`: **FINAL PASS**; focused sanctions **9 passed**; related normative/NTM/regulatory/grounded **122 passed + 29 subtests**; independent fail-closed/dedup/scope probe passed.
- Exact-head CI [run 38253458871 / job 114825377967](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38253458871/job/114825377967): **success**.
- Draft PR only. No merge, deploy, production/source data write, legal applicability change, enforcement/permissions/secrets change or external A6 call. Full #245 remains NOT PASS; lawful populated synchronized NTM snapshot remains unavailable.
- Next: bounded audit of AI-assistant sanctions/risk grounding and provenance; reproduce before editing.

## 2026-10-12 — Smart-payment explanations published on PR #255

- Exact candidate: `9659b6509d82f6077dfe0f6917af0dc532f6277e`, tree `73e5c9abb08e3cb1c9d4110661412e41ae4333e8`, parent `7c12f21787b1d557630d8b0737c769b326ab112d`.
- Reproduced with an executable disposable UI audit: the quote API supplied line reasons/sources, warnings, assumptions and legal bases, but Smart Payments hid them (**1 failed**, exit 1).
- The UI now displays those server-returned explanations as plain React text. Calculation and applicability are unchanged; manual-review amounts stay `—`, the final total stays “не определено”, and only the partial sum is informational.
- Author: disposable UI **1 passed** after the fix; frontend typecheck/build exit 0; focused backend quote/payment slice **78 passed + 14 subtests**, exit 0; safety **120 + 4 passed**, snapshot valid.
- Independent A5 `/root/a5_smart_payment_explanations_194`: **FINAL PASS**, hostile-text UI probe **2 passed**, typecheck/build passed, disposable backend **78 + 14 passed**, no findings; worktree clean.
- Exact-head CI [run 38247429977](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38247429977): offline-safety job `114804735216` and payment-regression job `114804735533` both succeeded.
- Draft PR only. No merge, deploy, production write, source/legal-completeness claim or external A6 call. Full #244 remains NOT PASS; full #245 still requires a lawful populated synchronized NTM snapshot.
- Next: fresh-head bounded audit of the sanctions/risk-management product slice; reproduce a concrete defect before editing.

## 2026-10-12 — ProductDetails decisions-tab integration audited on unchanged PR #256 HEAD

- Exact candidate: `e7f141a145e1475e8d1c51f25c51789a084b4541`, tree `def0f10bc2dc35376dcdff6f453ee91f390f0607` (unchanged).
- A0 disposable integration audit passed **4 tests**. Full frontend with probe passed **112**, typecheck/build passed; after removal baseline passed **108** and worktree was clean.
- Verified loading/error, unavailable and confirmed-empty data, badge/navigation, both embedded decision kinds, separate classification-rulings block, stale count fail-safe rendering, and selected-code request cancellation.
- Independent A5 `/root/a5_product_details_193`: **FINAL PASS**, corrected disposable audit **5 passed**, full frontend with probe **113 passed**, typecheck/build passed, baseline **108 passed** after deletion.
- The first A5 disposable draft had assertion-harness mismatches only; no product failure. Low-severity defensive note remains: the badge trusts embedded `total_count` and does not aggregate the separate rulings endpoint, while current backend preserves its count invariant.
- Safety **120 + 4 passed**, snapshot valid. Exact-head CI [run 38216078694 / job 114701012450](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38216078694/job/114701012450) succeeded.
- No product/test code, data, merge, deploy, production write or external A6 call changed. Full #245 and lawful populated NTM snapshot remain blocked/not accepted.
- Next per active focus: reread fresh PR #255 and audit the smart-payment explanation slice end-to-end before any edit.

## 2026-10-12 — #245 preliminary-decisions frontend audited on unchanged HEAD

- Exact candidate: PR #256 `e7f141a145e1475e8d1c51f25c51789a084b4541`, tree `def0f10bc2dc35376dcdff6f453ee91f390f0607` (unchanged).
- A0 executable frontend: `npm test -- --run` passed 108 tests; `npm run typecheck` and `npm run build` exited 0. A disposable UI audit passed 3 tests and was removed.
- Verified loading/null/custom-empty and populated classification/preliminary rendering, stale `total_count`, code formatting, 280-character truncation, hostile source escaping, and exactly one fixed FTS link.
- Independent A5 `/root/a5_preliminary_ui_192`: FINAL PASS; full 108-test suite, typecheck/build, and disposable 2-test edge audit all passed.
- Nonblocking observation: the ProductDetails tab badge trusts `total_count`; current backend derives it from arrays, so no present defect was reproduced.
- Safety: tariff-agent verify 120 passed; CLI snapshot 4 passed; committed snapshot valid; exact-head CI [run 38216078694 / job 114701012450](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38216078694/job/114701012450) succeeded.
- No product/test code, normative data, sources, flags, merges, deploys or external A6 calls changed. Full #245 and lawful populated NTM snapshot remain blocked/not accepted.
- Next: audit ProductDetails decisions-tab integration (embedded block, badge, navigation, loading and empty/error states) before any edit.

# Tariff / A0 — единая точка передачи проекта

## 0aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa. #245 — TN VED code-card executable audit on unchanged HEAD

**Checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `e7f141a145e1475e8d1c51f25c51789a084b4541`, tree `def0f10bc2dc35376dcdff6f453ee91f390f0607` (unchanged).

No defect was reproduced in `test_tnved_code_card.py`; therefore no product or test commit was created. The executable audit retained exact/6/4-prefix priority, duplicate suppression, bounded limits, empty states, trimmed fields and source serialization while exercising the real catalogue API and FCS preliminary-sync paths in both collection orders.

Evidence bound to the exact unchanged candidate:

- root focused absent-input and populated-sentinel controls: **3 passed** each, exit 0;
- root adjacent code-card/catalogue API/FCS sync controls: **36 passed** in forward and reverse order for both absent and populated sentinels, all exit 0;
- disposable edge probe passed prefix order/dedupe, limit clamps, short/empty boundaries and blank-source fallback;
- configured/source databases and preview marker stayed absent or byte-identical; no WAL/SHM/default `customs.db`; pinned catalogue SHA-256 unchanged;
- independent executable A5 `/root/a5_tnved_code_card_191`: **FINAL PASS without blocking findings**; repeated **3 + 3** focused and four **36-pass** adjacent runs plus edge probes;
- local safety: `verify` **120 passed**, CLI snapshot **4 passed**, committed snapshot valid;
- exact-head CI: [run 38216078694](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38216078694), offline-safety job `114701012450`, **success**.

A5 recorded an informational low-level resolver wording ambiguity for 6/8/longer inputs. The public API remains strict at 4 or 10 digits, so no current product regression was reproduced and no semantic change was made.

This is executable verification, not full #245 product/legal/source acceptance. A lawful populated synchronized NTM snapshot remains unavailable. A6 `core-s1-6415f443120f-r9-g106` remains prepared but not authorized or sent. No merge, deploy, production write, enforcement/permissions/secrets change, destructive migration, force push or branch deletion occurred. Next safe block is fresh-HEAD frontend audit of `PreliminaryDecisionsBlock`, its API contract, empty state and source rendering; reproduce a concrete defect before any edit.

## 0aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa. #245 — smart TN VED search executable audit on unchanged HEAD

**Checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `e7f141a145e1475e8d1c51f25c51789a084b4541`, tree `def0f10bc2dc35376dcdff6f453ee91f390f0607` (unchanged).

No defect was reproduced in `test_smart_tnved_search.py`; therefore no product or test commit was created. The executable audit retained exact-code ranking, typo correction only after an empty initial query, safe handling of special FTS syntax, explicit unavailable-FTS caching/rebuild semantics and restoration of `tnved_fts.engine` / `_fts_ready`.

Evidence bound to the exact unchanged candidate:

- root focused absent-input and populated-sentinel controls: **6 passed** each, exit 0;
- root adjacent smart-search/FTS/semantic controls: **21 passed** in both absent-input orders; with catalogue API and populated sentinels: **44 passed** in both orders, all exit 0;
- configured/source databases and preview marker stayed absent or byte-identical; no WAL/SHM/default `customs.db`; pinned catalogue SHA-256 unchanged;
- independent executable A5 `/root/a5_smart_search_190`: **FINAL PASS, no findings**; repeated **6 + 6** focused and **44 + 44** adjacent tests, then verified exact-code ranking, typo timing, special syntax, unavailable-FTS caching and globals restoration;
- local safety: `verify` **120 passed**, CLI snapshot **4 passed**, committed snapshot valid;
- exact-head CI: [run 38216078694](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38216078694), offline-safety job `114701012450`, **success**.

This is executable verification, not full #245 product/legal/source acceptance. A lawful populated synchronized NTM snapshot remains unavailable. A6 `core-s1-6415f443120f-r9-g106` remains prepared but not authorized or sent. No merge, deploy, production write, enforcement/permissions/secrets change, destructive migration, force push or branch deletion occurred. Next safe block is fresh-HEAD execution of `test_tnved_code_card.py` with classification inventory and configured/source/marker absent and sentinel controls plus adjacent API ordering; reproduce a concrete defect before any edit.

## 0aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa. #245 — HS leaf calculator fixture isolated from configured DB

**Checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `e7f141a145e1475e8d1c51f25c51789a084b4541`, tree `def0f10bc2dc35376dcdff6f453ee91f390f0607`, parent `7462f2959735f7aad51f53047ef6d9ddeefd04a3`.

A collection-order defect was reproduced before editing: the parent adjacent contour returned **3 failed, 30 passed**, and the already-imported `rate_display.SessionLocal` queried a missing `hs_rates` table through configured SQLite, creating a 4096-byte file. The test fixture now binds that captured alias to the same disposable classification inventory used by the calculator/payment fixtures. All 9 original test methods and 23 assertions remain AST-identical; product code and normative data were not changed.

Evidence bound to the exact candidate:

- root focused hostile-absent and populated-sentinel runs: **9 passed** each, exit 0;
- root adjacent catalogue/measures/calculator forward and reverse runs: **33 passed** each on absent inputs and **33 passed** each on populated sentinels, all exit 0;
- configured/source/marker stayed absent or byte-identical; no WAL/SHM/default `customs.db`; pinned catalogue hash unchanged;
- independent executable A5 `/root/a5_hs_leaf_isolation_189`: **FINAL PASS, no findings**; parent defect independently reproduced and candidate invariance repeated;
- local safety: `verify` **120 passed**, CLI snapshot **4 passed**, committed snapshot valid;
- exact-head CI: [run 38216078694](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38216078694), offline-safety job `114701012450`, **success**.

This is a bounded fixture-isolation fix only. Lawful populated synchronized NTM data remains unavailable and full #245 remains **NOT PASS**. A6 `core-s1-6415f443120f-r9-g106` remains prepared but not authorized or sent. No merge, deploy, production write, enforcement/permissions/secrets change, destructive migration, force push or branch deletion occurred. Next safe block is fresh-HEAD execution of `test_smart_tnved_search.py` with engine/cache ordering and external DB/marker invariance controls.

## 0aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa. #245 — TN VED catalog API изолирован от configured/source DB и preview marker

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `5bb7dbf69e61c0999e3b0971fc79f86198296560`, tree `bb9120b69a980fdc0d4e401e0f67f89fb4d60e29`, parent `42ac7665990111d45d9038be807f8ba61c354e11`. Локальный author commit `277cd9d1a85b8c0e690e9eb5e4d7747c41c691b5` имеет тот же exact tree.

Воспроизведён fixture defect в `test_tnved_catalog_api.py`: все **23 tests** проходили, но отсутствующая configured SQLite создавалась размером 1 036 288 bytes; существующая 8192-byte sentinel DB разрасталась до 1 040 384 bytes и меняла SHA, а внешний preview revision marker перезаписывался. Module-autouse fixture теперь создаёт disposable classification inventory через существующий bootstrap, направляет test/application/normative-store/catalog/payment/rate-display DB aliases в него и выносит preview revision в disposable marker. Configured/source/repository DB, исходный marker и SQLite sidecars остаются неизменными. Все 23 test methods и исходные assertions AST-identical; production code, нормативные данные, source claims, flags, skips/xfails и правовая интерпретация не менялись.

Проверки:

- root: focused **23 passed** на absent и populated sentinel inputs; configured/source DB и внешний marker не созданы либо byte-identical;
- вместе с TN VED measures API, regulatory mass-seed safety, regulatory-source completeness и FCS preliminary sync в прямом и обратном порядке — по **49 passed + 3 subtests**, все exit 0, DB/marker/WAL/SHM drift отсутствует;
- root local agent-safety: **120 + 4 passed**, committed snapshot valid, exit 0;
- независимый A5 `/root/a5_tnved_catalog_api_185`: **FINAL PASS без findings**; parent DB/marker mutation независимо воспроизведена, candidate aliases, cleanup, focused/adjacent invariants и AST parity подтверждены;
- exact-head CI: [run 38202590035](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38202590035), offline-safety job `114659007873`, attempt 1, **success**.

Это test-isolation evidence, не подтверждение полноты источников или юридической применимости. Lawful populated synchronized NTM snapshot недоступен; полный #245 остаётся **NOT PASS**. Merge, deploy, production write, enforcement/permissions/secrets change, destructive migration, force push, branch deletion и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий отдельный блок — на свежем HEAD выполнить bounded inventory оставшихся TN VED/source-backed fixtures, начиная с `test_tnved_fts.py` и `test_semantic_navigation_v1.py`; populated/full-sync ожидания не подменять синтетическими данными.

## 0aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa. #245 — TN VED measures API изолирован от configured DB

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `42ac7665990111d45d9038be807f8ba61c354e11`, tree `8743cc676c19edb030d858c4698271acbec7ac20`, parent `dcb32489bf5f4526a6ee6b761e171d3114909f2d`. Локальный author commit `d9a3f1446077a79cd548080a4abc220dc3294111` имеет тот же exact tree.

Воспроизведён fixture defect в `test_tnved_measures_api.py`: тест проходил **1 passed**, но создавал отсутствующую configured SQLite размером 1 044 480 bytes; существующая 8192-byte sentinel DB меняла SHA и разрасталась до 1 048 576 bytes. Autouse fixture теперь создаёт disposable classification inventory через существующий bootstrap, направляет test/application/normative-store/TN VED endpoint DB aliases в него и проверяет byte-level неизменность configured, source и repository DB. Реальный endpoint, все 7 кодов, тело product test и 4 assertions AST-identical; production code, нормативные данные, source claims, flags, skips/xfails и правовая интерпретация не менялись.

Проверки:

- root: focused **1 passed** на absent и sentinel DB; отсутствующая configured DB не создана, sentinel SHA/marker byte-identical;
- вместе с regulatory mass-seed safety, regulatory-source completeness и FCS preliminary sync в прямом и обратном порядке — по **26 passed + 3 subtests**, sentinel SHA byte-identical; все exit 0;
- `py_compile`, `git diff --check` и AST parity — exit 0 / PASS;
- независимый A5 `/root/a5_tnved_measures_api_184`: **FINAL PASS без findings**; parent 1 044 480-byte creation и sentinel mutation воспроизведены, candidate absent/source/sentinel invariants и cleanup подтверждены;
- exact-head CI: [run 38197947110](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38197947110), offline-safety job `114644739948`, attempt 1, **success**.

Это test-isolation evidence, не подтверждение полноты источников или юридической применимости. Lawful populated synchronized NTM snapshot недоступен; полный #245 остаётся **NOT PASS**. Merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий отдельный блок — на свежем HEAD выполнить bounded inventory следующего воспроизводимого configured/source fixture, начиная с `test_tnved_catalog_api.py` на disposable DB и вынесенном preview marker; full-catalog и populated-snapshot ожидания не подменять синтетическими данными.

## 0aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa. #245 — synthetic regulatory mass-seed safety изолирован от configured DB

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `dcb32489bf5f4526a6ee6b761e171d3114909f2d`, tree `157ee2556971c8db25ce98669c1f7fb059430257`, parent `075df086af14458d0c856ef817e3456160b2e514`. Локальный author commit `f8396cff7f85ad41056343eec13158029ba08156` имеет тот же exact tree.

Воспроизведён fixture defect в `test_regulatory_mass_seed_safety.py`: на отсутствующей configured SQLite оба synthetic-safety теста падали с missing-table errors, создавая 4096-byte DB; существующая sentinel DB менялась по SHA из-за раннего connection pragma. Autouse fixture теперь создаёт disposable SQLite только с реальными `RegulatoryDocument` и `RegulatoryDocHsMapping` таблицами и перепривязывает четыре захваченных `SessionLocal`. Реальные `seed_regulatory_mass.run`, `get_regulatory_documents_for_hs` и `_count_db_probe` продолжают выполняться. Два test functions и 15 assertions AST-identical; production code, нормативные данные, source claims, flags, skips/xfails и правовая интерпретация не менялись.

Проверки:

- root: focused **2 passed** на absent и sentinel DB; отсутствующие configured/source DB не созданы, обе sentinel DB и marker rows byte-identical;
- вместе с regulatory-source completeness и FCS preliminary sync в прямом и обратном порядке — по **25 passed + 3 subtests**, external DB отсутствует, все exit 0;
- root local agent-safety: **120 + 4 passed**, committed snapshot valid, exit 0;
- независимый A5 `/root/a5_reg_mass_seed_isolation_183`: **FINAL PASS без findings**; parent failure/4096-byte creation и sentinel mutation воспроизведены, candidate invariants, реальные callable и AST parity подтверждены;
- exact-head CI: [run 38194012583](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38194012583), offline-safety job `114632627303`, attempt 1, **success**.

Это test-isolation evidence, не подтверждение полноты источников или юридической применимости. Lawful populated synchronized NTM snapshot недоступен; полный #245 остаётся **NOT PASS**. Merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий отдельный блок — на свежем HEAD воспроизвести и изолировать уже обнаруженное создание configured SQLite размером 1 044 480 bytes в `test_tnved_measures_api.py`; populated-snapshot `test_ntm_full_sync.py` и `test_regulatory_mass_seed.py` не подменять синтетическими данными.

## 0aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa. #245 — NTM v2 layers matrix изолирована от configured DB

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `075df086af14458d0c856ef817e3456160b2e514`, tree `e9d1a7ccb0bd3b9629954f73038342ae64c07e41`, parent `7d96291c6bd43e77d0a80b7513c375004b2dc847`. Локальный author commit `b41f782fdf8b0731547eb4e0084a548ee95aa92a` имеет тот же exact tree.

Воспроизведён отдельный fixture defect в `test_ntm_v2_layers.py`: 72-case layers/TR-TS matrix обращалась к нерелевантным persistent sources, давала **72 failed / 18 passed** на отсутствующей configured SQLite и создавала 4096-byte DB. Fixture теперь изолирует только DB/legacy advisory/official SGR/risk/enrichment sources и enforcement gates. Реальные `import_ntm_layers_to_ntm_v2`, `import_tr_ts_catalog_to_ntm_v2`, `ntm_engine_v2`, canonical layers/TR-TS catalog и description triggers продолжают выполняться. 15 test functions и 26 assertions AST-identical; production code, нормативные данные, source claims, flags, skips/xfails и правовая интерпретация не менялись.

Проверки:

- root: полный модуль **90 passed** на absent и sentinel DB; отсутствующий файл не создан, sentinel SHA/marker/table count byte-identical;
- пять смежных модулей в прямом и обратном порядке — по **262 passed, 1 skipped**, external DB отсутствует, все exit 0;
- root local agent-safety: **120 + 4 passed**, committed snapshot valid, exit 0;
- независимый A5 `/root/a5_ntm_layers_isolation_181`: **FINAL PASS без findings**; parent failure/4096-byte mutation воспроизведены, test bodies/assertions и реальные v2/catalog/layer/trigger paths подтверждены;
- exact-head CI: [run 38190299249](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38190299249), offline-safety job `114621413278`, attempt 1, **success**.

Это test-isolation evidence, не подтверждение полноты источников или юридической применимости. Lawful populated synchronized NTM snapshot недоступен; полный #245 остаётся **NOT PASS**. Merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий отдельный блок — на свежем HEAD продолжить bounded поиск следующего воспроизводимого configured-DB/source fixture; ожидаемый blocker полного sync test не подменять тестовыми данными.

## 0aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa. #245 — pipeline flag tests изолированы от configured DB

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `7d96291c6bd43e77d0a80b7513c375004b2dc847`, tree `b5b345144e26d365c1dafe5f20672f444c39d7dc`, parent `cdf28f1287394391c94375fce20c97116f112ae2`. Локальный author commit `ae3e085659c6f8f286a25b8e03a00fda3c9bfd09` имеет тот же exact tree.

Воспроизведены два связанных test-fixture дефекта в `test_ntm_v2_pipeline_flag.py`: отдельный logger-тест выполнял Alembic против configured SQLite и менял её, а 72-case matrix скрыто зависела от этой миграции и порядка тестов. Logger-тест теперь выполняет реальный Alembic на disposable SQLite, включая перенаправление captured seed engine/session. Fixture matrix явно изолирует нерелевантные DB/source ветви, сохраняя реальный NTM v2 adapter/import, canonical TR TS catalog, layers и description triggers. Production code, нормативные данные, source claims, flags, skips/xfails и правовая интерпретация не менялись.

Проверки:

- root: полный модуль **85 passed** с отсутствующим и существующим sentinel configured DB; отсутствующий файл не создан, sentinel SHA/marker/table-count byte-identical; четыре смежных модуля в прямом и обратном порядке — по **172 passed, 1 skipped**, все exit 0;
- отдельный logger-тест сохранил исходную проверку logger и создал disposable Alembic schema из 63 таблиц с актуальной version, NTM v2 и declaration documents;
- root local agent-safety: **120 + 4 passed**, committed snapshot valid, exit 0;
- независимый A5 `/root/a5_ntm_pipeline_isolation_180`: **FINAL PASS без findings** на exact commit/tree, повторены focused/sentinel/оба порядка и подтверждены реальные adapter/import/catalog/triggers;
- exact-head CI: [run 38187004142](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38187004142), offline-safety job `114611375970`, attempt 1, **success**.

Это test-isolation evidence, не подтверждение полноты источников или юридической применимости. Lawful populated synchronized NTM snapshot недоступен; полный #245 остаётся **NOT PASS**. Merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий отдельный блок — на свежем HEAD найти следующий воспроизводимый configured-DB/source fixture, не подменяя ожидаемый blocker полного sync test тестовыми данными.

## 0aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa. #245 — legacy smoke не создаёт configured SQLite

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `cdf28f1287394391c94375fce20c97116f112ae2`, tree `be55d5c157d2f228e2d411d76480b61fae672d37`, parent `24a670d1e2629f4c6cf1bc1f8e14a39c4f3ab297`. Локальный author commit `b50508b1cf9e991286f919d743f9b1129b723bc4` имеет тот же exact tree.

Воспроизведён test-side effect: `test_ntm_v2_legacy_measures_import.py` проходил **10 tests, 1 skipped**, но smoke-проверка dev-БД создавала отсутствующий configured SQLite размером 4096 байт, а существующий marker-SQLite без нужных таблиц меняла по SHA из-за connection pragma. Smoke теперь до SQLAlchemy connection проверяет существующий SQLite через immutable read-only URI и пропускается, если отсутствует файл или любая из двух обязательных таблиц. Non-SQLite и populated SQLite flow не менялись; product code, нормативные данные, source claims, flags, xfails и правовая интерпретация не менялись.

Проверки:

- root: focused **10 passed, 1 skipped**; отсутствующая DB не создана, sentinel SHA byte-identical; соседние legacy import/diagnostics, combined-runtime и source-isolation в обоих порядках — по **25 passed, 1 skipped**, configured DB не создана; все test commands exit 0;
- независимый A5 `/root/a5_legacy_smoke_isolation_179`: **PASS без findings**; parent создаёт 4096-byte DB и меняет sentinel SHA, candidate сохраняет absent/sentinel invariants; отдельная read-only URI проверка запретила INSERT;
- exact-head CI: [run 38182336448](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38182336448), offline-safety job `114597337917`, attempt 1, **success**.

Это test-isolation evidence, не подтверждение полноты источников или юридической применимости. Lawful populated synchronized NTM snapshot недоступен; полный #245 остаётся **NOT PASS**. Merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий отдельный блок — на свежем HEAD изолировать следующий воспроизводимый empty-DB/source-backed fixture cluster; `test_ntm_full_sync.py` остаётся ожидаемо заблокирован отсутствием lawful populated synchronized snapshot.

## 0aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa. #245 — NTM v2 source isolation не пишет в configured DB

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `24a670d1e2629f4c6cf1bc1f8e14a39c4f3ab297`, tree `5d51da4d66f31f2fc962fb57139c5a7e8a8e2792`, parent `cebf36cdff378deb18aa0d7730d4c0e4fcff73d7`. Локальный author commit `a33c376331437acb9eaf4c2899e050d89a29c383` имеет тот же exact tree.

Воспроизведён collection-order fixture defect: `test_ntm_v2_source_isolation.py` отдельно проходил **4 tests** без residue, но совместная collection с regulatory-source completeness в любом порядке проходила **17 tests + 3 subtests** и создавала пустую configured SQLite размером 4 KiB. Причина — ранний импорт `sanctions_risk_block` сохранял исходный `SessionLocal`, который четыре раза использовался combined runtime comparison. Fixture теперь явно перепривязывает этот alias к in-memory database и проверяет binding. Production code, нормативные данные, source claims, flags, skips/xfails и правовая интерпретация не менялись.

Проверки:

- root: focused **4 passed**; оба порядка с regulatory completeness — **17 passed + 3 subtests**; расширенный source/combined/sanctions/regulatory tranche — **29 passed + 3 subtests**; populated configured и `TNVED_SOURCE_DB` sentinel hashes byte-identical, все exit 0;
- независимый A5 `/root/a5_ntm_source_isolation_178`: **FINAL PASS без findings**; на parent дефект воспроизведён в обоих порядках, на candidate absent paths не создаются и populated sentinels сохраняют SHA/rows;
- exact-head CI: [run 38178722631](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38178722631), offline-safety job `114586522253`, attempt 1, **success**.

Это test-isolation evidence, не подтверждение полноты источников или юридической применимости. Lawful populated synchronized NTM snapshot недоступен; полный #245 остаётся **NOT PASS**. Merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий отдельный блок — на свежем HEAD найти и изолировать следующий воспроизводимый empty-DB/source-backed fixture cluster, сохраняя test evidence отдельно от legal/source completeness.

## 0aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa. #245 — FCS preliminary sync изолирован от configured DB

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `cebf36cdff378deb18aa0d7730d4c0e4fcff73d7`, tree `24f4e077c4e766c3f4c56f474ca44ecf584e43c8`, parent `02215630f69b81ec300490e0da3b3b88a2b1fccf`. Локальный author commit `12a053e8b947d30cf01428403b68300b18a9035c` имеет тот же exact tree.

Воспроизведён fixture defect: `test_fcs_preliminary_sync.py` проходил **10 tests**, но создавал configured SQLite размером 1 036 288 байт. Модуль теперь создаёт disposable classification DB, очищает только её FCS decision/sync/status rows для fresh-DB семантики, перепривязывает захваченные application/normative-store/FCS-sync/completeness DB aliases и удаляет временную DB вместе с sidecars. Все 10 исходных test methods, 24 `unittest` assertions и 2 Python assertions AST-identical; production code, нормативные данные, source claims, flags, skips/xfails и правовая интерпретация не менялись.

Проверки:

- A2 `/root/a2_fcs_preliminary_177` и root: focused **10 passed**; absent configured и `TNVED_SOURCE_DB` paths не создаются, валидные SQLite-sentinels и marker rows byte-identical;
- adjacent с regulatory-source completeness в обоих порядках: **23 passed + 3 subtests**, hostile DB/WAL/SHM residue отсутствует;
- независимый A5 `/root/a5_fcs_preliminary_177`: **FINAL PASS без findings**; instrumented реальные sync/count/completeness/code-card calls и disposable FCS rows подтверждены;
- root local agent-safety: **120 + 4 passed**, snapshot valid; все exit 0;
- exact-head CI: [run 38174846284](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38174846284), offline-safety job `114574963218`, attempt 1, **success**.

Это test-isolation evidence, не подтверждение полноты источников или юридической применимости. Lawful populated synchronized NTM snapshot недоступен; полный #245 остаётся **NOT PASS**. Merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий отдельный блок — независимо воспроизвести и изолировать ранее обнаруженную configured-DB mutation в `test_ntm_v2_source_isolation.py`.

## 0aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa. #245 — regulatory source completeness изолирован от configured DB

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `02215630f69b81ec300490e0da3b3b88a2b1fccf`, tree `f750f4f1b8e9df55bd7043254e1607b5522a276d`, parent `1f4d1f0631ed09dfdc5395cb88dfab8a5070b0b1`. Локальный author commit `d15cc084d3ddf887d30ea09f12c87bcee43ce989` имеет тот же exact tree.

Воспроизведён fixture defect: `test_regulatory_source_completeness.py` проходил **13 tests + 3 subtests**, но создавал configured SQLite размером 1 036 288 байт и записывал тестовую строку ALTA mirror. Модуль теперь создаёт disposable classification DB, перепривязывает захваченные `SessionLocal` aliases и удаляет временную DB вместе с SQLite sidecars. Все 13 исходных test methods и 33 `unittest` assertion calls AST-identical; production code, нормативные данные, source claims, flags, skips/xfails и правовая интерпретация не менялись.

Проверки:

- A2 `/root/a2_regulatory_source_176` и root: focused **13 passed + 3 subtests**; absent configured и `TNVED_SOURCE_DB` paths не создаются, pre-existing sentinels byte-identical;
- clean adjacent source-diagnostics/probe tranche: **28 passed + 3 subtests**, configured DB не создана;
- root local agent-safety: **120 + 4 passed**, snapshot valid; все exit 0;
- независимый A5 `/root/a5_regulatory_source_176`: **FINAL PASS без findings**; AST parity, absent/sentinel invariance и clean adjacent orders подтверждены;
- exact-head CI: [run 38170562392](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38170562392), offline-safety job `114562103876`, attempt 1, **success**.

Отдельный существовавший ранее configured-DB mutation воспроизведён в `test_fcs_preliminary_sync.py`; это следующий изолированный блок. Lawful populated synchronized NTM snapshot недоступен; полный #245 остаётся **NOT PASS**. Merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` не отправлялся.

## 0aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa. #245 — legacy/combined diagnostics изолированы от configured DB

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `1f4d1f0631ed09dfdc5395cb88dfab8a5070b0b1`, tree `810fce451087981b2ab369e27352b43f05cb69f5`, parent `648b0e06141192d339e10a65142dd4e863574d05`. Локальный author tip `0526717bc3d748719570a8d5a373f8dd5e4a7719` имеет тот же exact tree.

Воспроизведён order-dependent fixture defect: `test_ntm_v2_legacy_measures_diagnostics.py` проходил **7 tests**, но создавал 4 KiB configured SQLite; совместная collection с combined-runtime модулем делала оба порядка тестов зависимыми от configured DB. Обе in-memory fixtures теперь явно перепривязывают захваченный `app.services.sanctions_risk_block.SessionLocal`. Изменено ровно по одной fixture-строке в двух test files; 11 test functions и 27 assertions AST-identical. Production code, нормативные данные, flags, skips/xfails и правовая интерпретация не менялись.

Проверки:

- A2 `/root/a2_ntm_legacy_measures_175` и root: focused **7 + 4 passed**, оба порядка **11 passed**, со source diagnostics **17 passed**; absent configured DB не создаётся;
- root local agent-safety: **120 + 4 passed**, snapshot valid; все exit 0;
- независимый A5 `/root/a5_ntm_legacy_measures_175`: **FINAL PASS без findings**; оба порядка и adjacent оба порядка PASS, pre-existing sentinel SHA/row сохранены, AST parity подтверждён;
- exact-head CI: [run 38166485840](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38166485840), offline-safety job `114550000909`, attempt 1, **success**.

Это test-isolation evidence, не подтверждение полноты источников или юридической применимости. Lawful populated synchronized NTM snapshot недоступен; полный #245 остаётся **NOT PASS**. Merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий отдельный блок — следующий воспроизводимый empty-DB/source-backed fixture cluster на disposable данных, без подмены legal/source completeness тестовым evidence.

## 0aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa. #245 — NTM source diagnostics изолированы от configured DB

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `648b0e06141192d339e10a65142dd4e863574d05`, tree `3f5a4202520a7bd94aabbcd98677856f08ea70c0`, parent `3cc66695d26ce807718afa9494a799dc76a3bb9e`. Локальный author commit `3389f7a8a11f2466ba2d58746763e8465c3e7e8a` имеет тот же exact tree.

Воспроизведён fixture defect: `test_ntm_source_diagnostics.py` на пустой configured SQLite давал **3 failed / 3 passed**, читал отсутствующие v2/legacy таблицы и создавал 4 KiB DB. Test-only fixture теперь подставляет пустые configured-DB rule/measure inputs и собирает полный broker source set из реальных canonical TR TS и `ntm_layers` функций модуля. Сравнение источников, matrix aggregation и `_build_broker_required_permits` dedupe продолжают выполняться. Все 6 исходных тестов и 12 assertions AST-identical; production code, нормативные данные, flags, skips/xfails и правовая интерпретация не менялись.

Проверки:

- A2 `/root/a2_ntm_source_diag_174`: focused **6 + 6 passed**, absent DB не создана, sentinel byte-identical; adjacent оба порядка **17 passed**; compile/diff-check exit 0;
- root control: focused **6 + 6 passed**, adjacent **17 passed**, DB invariance подтверждена; local agent-safety **120 + 4 passed**, snapshot valid; все exit 0;
- независимый A5 `/root/a5_ntm_source_diag_174`: **FINAL PASS без findings**; reverse adjacent PASS, DB/WAL/SHM residue отсутствует, instrumented canonical catalog/layers/comparison/matrix/broker calls подтверждены;
- exact-head CI: [run 38162233357](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38162233357), offline-safety job `114537380203`, attempt 1, **success**.

Это test-isolation evidence, не подтверждение полноты источников или юридической применимости. Lawful populated synchronized NTM snapshot недоступен; полный #245 остаётся **NOT PASS**. Merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий отдельный блок — следующий воспроизводимый empty-DB/source-backed fixture cluster на disposable данных, без подмены legal/source completeness тестовым evidence.

## 0aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa. #245 — NTM broker matrix изолирован от configured DB

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `3cc66695d26ce807718afa9494a799dc76a3bb9e`, tree `705ce207eab76df149f38dd9a41183590ee6fbb2`, parent `e6f501be22e844b12d4e48e8046c8c9aaf98ef8d`. Локальный author commit `e6d89b340ee59cd3790c94d70e3df1b56625d39b` имеет тот же exact tree.

Неполный checkpoint `e6f501be…` воспроизведён как реальный fixture defect: при включённых NTM v2 source switches все **73** broker-matrix сценария падали на пустой configured SQLite с `no such table: ntm_applicability_rules_v2`, создавая файл БД. Test-only autouse fixture теперь фиксирует только v2 TR TS/layers switches на legacy in-process paths. Production `check_position_non_tariff`, canonical TR TS catalog, `ntm_layers` и реальные description triggers продолжают выполняться. Оба исходных test functions и 4 assertions сохранены AST-identical; production code, нормативные данные, продуктовые flags, skips/xfails и правовая интерпретация не менялись.

Проверки:

- A2 `/root/a2_ntm_pipeline_fix_173`: focused **73 passed**, absent DB не создана; valid sentinel **73 passed**, byte-identical; adjacent NTM **271 passed**; compile/diff-check exit 0;
- root control: focused **73 + 73 passed**, absent DB не создана, sentinel byte-identical; local agent-safety **120 + 4 passed**, snapshot valid; все exit 0;
- независимый A5 `/root/a5_ntm_pipeline_173`: **FINAL PASS без findings**; focused **73 + 73 passed**, нулевой DB/WAL/SHM residue, instrumented production/catalog/layers/triggers calls подтверждены; bounded adjacent **36 passed**;
- exact-head CI: [run 38158116384](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38158116384), offline-safety job `114525186732`, attempt 1, **success**.

Это доказательство тестовой изоляции, не актуальности или юридической полноты NTM. Lawful populated synchronized NTM snapshot недоступен. Полный #245 product/legal/source completeness остаётся **NOT PASS**. Merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий отдельный блок — следующий воспроизводимый source-diagnostics/empty-DB fixture cluster на disposable данных без ослабления assertions и без подмены legal/source completeness тестовым inventory.

**Снимок:** 2026-10-11 (UTC). **Единственный репозиторий:** [ivan88810900-star/tnved_starter_kit_v2](https://github.com/ivan88810900-star/tnved_starter_kit_v2).
**Авторитетное состояние:** ветка `agent/orchestration-state`, файлы `.ai/TASK_BOARD.json`, `.ai/COORDINATOR_LEASE.json`, `.ai/orchestration/A6_LIVE_STATUS.json`. Этот документ — указатель и контрольная точка, **не** право на запись/merge/A6. Перед действием заново читать текущие HEAD и state. Не полагаться на Business-чат.

## 0aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa. #245 — effective-requirements debug test изолирован от configured DB

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `477074fb554c865cc55ebb740cc68eb0c371977b`, tree `621a5894d12b87a9a4275bb69927f755195e3c2a`, parent `171a393eb907ec663a8b4a9d95b740abf275458a`.

Воспроизведён следующий fixture defect: `test_ntm_effective_requirements.py` на пустой configured SQLite давал **6 passed, 1 failed** (`ntm_applicability_rules_v2` отсутствует) и создавал 4 KiB файл; валидный pre-existing sentinel также менял SHA. Debug-invariance test теперь получает детерминированные test-only source results с реальной broker-shaped строкой `ДС / 004/2011 / 8471`, продолжая вызывать production `check_position_non_tariff` и реальную сборку effective requirements. Все 7 исходных test methods и 19 assertion nodes сохранены AST-identical; production code, нормативные данные, конфигурация продукта и правовая интерпретация не менялись.

Проверки:

- A2 `/root/a2_ntm_effective_171`: focused **7 passed**; совместный normative run в обоих порядках **18 passed**; absent hostile DB не создаётся, pre-existing sentinel byte-identical; compile/diff-check exit 0;
- root control: focused + bounded adjacent **53 passed**; hostile present/absent preservation PASS; local agent-safety **120 + 4 passed**, snapshot valid, exit 0;
- независимый A5 `/root/a5_ntm_effective_171`: **FINAL PASS без findings**; focused **7 passed**, оба adjacent order **9 passed**, production-call invariance и meaningful broker row подтверждены, DB/WAL/SHM residue отсутствует;
- exact-head CI: [run 38153464780](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38153464780), offline-safety job `114511728747`, **success** на attempt 2. Attempt 1 встретил только временную Python 3.12 cleanup-гонку Git pack directory; неизменный HEAD прошёл повтор.

Это доказательство тестовой изоляции, а не свежести или юридической действительности NTM. Lawful populated synchronized NTM snapshot недоступен. Полный #245 product/legal/source completeness остаётся **NOT PASS**. Merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий отдельный блок — изолировать следующий воспроизводимый `test_ntm_pipeline` / source-diagnostics empty-DB fixture cluster на disposable данных, не ослабляя assertions и не выдавая test inventory за нормативный источник.

## 0aaaaaaaaaaaaaaaaaaaaaaaaaaaaa. #245 — normative bundle/requirements tests используют hermetic databases

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `171a393eb907ec663a8b4a9d95b740abf275458a`, tree `648f07e4ff24ccacd5d5b269eabd0243d5cf73a3`, parent `c58878f5064ec49419c39944f5da70b35944652e`.

Воспроизведён следующий broad-suite fixture defect: `test_normative_bundle.py` и `test_normative_requirements_block.py` проходили **18 tests**, но создавали или изменяли сконфигурированный hostile SQLite. При absent DB создавался файл 1 036 288 байт; валидный pre-existing sentinel изменял SHA и вырастал до 1 040 384 байт. Bundle/API tests теперь используют отдельную временную SQLite через существующий pinned classification bootstrap и перепривязывают test/application/normative-store/payment/FTS consumers; requirements-block fixture направляет sanctions lookup в существующую in-memory session. Все 13 test methods и 53 assertion nodes сохранены AST-identical; production code, нормативные данные, конфигурация продукта и правовая интерпретация не менялись.

Проверки:

- A2 `/root/a2_normative_db_isolation_170`: focused **7 + 11 passed**, оба совместных порядка **18 passed**; absent hostile/source paths не создаются, pre-existing hashes byte-identical; bounded adjacent **52 passed**, diff-check exit 0;
- root control: focused + adjacent **46 passed**; local agent-safety **120 + 4 passed**, snapshot valid, exit 0;
- независимый A5 `/root/a5_normative_db_isolation_170`: **FINAL PASS без findings**; 13 methods/53 assertions AST-identical, оба порядка **18 passed**, bounded adjacent NTM **33 passed**, pinned catalogue неизменён, временные DB/WAL/SHM удалены;
- exact-head CI: [run 38149897850](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38149897850), offline-safety job `114500978594`, **success**.

Это доказательство тестовой изоляции, а не свежести/юридической действительности NTM. Lawful populated synchronized NTM snapshot недоступен. Полный #245 product/legal/source completeness остаётся **NOT PASS**. Merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий воспроизводимый fixture-дефект: `test_ntm_effective_requirements.py` на пустой configured DB даёт **6 passed, 1 failed** и создаёт 4 KiB SQLite; разбирать отдельным блоком, не смешивая с этим checkpoint.

## 0aaaaaaaaaaaaaaaaaaaaaaaaaaaa. #245 — FSA registry tests используют hermetic databases

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `c58878f5064ec49419c39944f5da70b35944652e`, tree `a4cf25fbf7a8cfc5ced58fc91e603fd93e7d085b`, parent `720f882b8aa379c8daeb2baafc26ab4caa74a549`.

Воспроизведён следующий broad-suite fixture defect: пять FSA opendata/upsert и certificate-normalization тестов проходили, но создавали и изменяли сконфигурированный hostile SQLite-файл размером 1 036 288 байт. Оба модуля теперь создают отдельные временные SQLite через существующий pinned classification bootstrap и перепривязывают захваченные test/application/normative-store/FSA-import/registry-lookup DB consumers к временному engine. Все 5 исходных test methods и 19 assertions сохранены AST-identical; production code, registry data, product configuration и правовая интерпретация не менялись.

Проверки:

- A4 `/root/a4_fsa_test_isolation_169`: focused **5 passed** в обоих порядках; hostile/source hashes неизменны, absent sentinels не создаются; смежный шестимодульный набор в обоих порядках **44 passed, 1 skipped**; cleanup/diff-check exit 0;
- root control: те же focused и adjacent результаты; local agent-safety **120 + 4 passed**, snapshot valid, exit 0;
- независимый A5 `/root/a5_fsa_test_isolation_169`: **FINAL PASS без findings**; все 5 методов и 19 assertions AST-identical, FSA test rows не выходят за disposable storage, pinned catalogue неизменён, временные DB/WAL/SHM удалены;
- exact-head CI: [run 38145633639](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38145633639), offline-safety job `114488252775`, **success**.

Это доказательство тестовой изоляции, а не свежести/юридической действительности реестра. Lawful populated synchronized NTM snapshot недоступен. Полный #245 product/legal/source completeness остаётся **NOT PASS**. Merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий шаг — изолировать следующий реальный broad-suite data/DB side-effect или fixture defect на disposable данных, не превращая тестовый inventory в нормативное доказательство.

## 0aaaaaaaaaaaaaaaaaaaaaaaaaaa. #245 — commodity-group documents используют hermetic seed fixture

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `720f882b8aa379c8daeb2baafc26ab4caa74a549`, tree `b1eaab03b291592aa720f119a13482ef203944aa`, parent `70beb6d124a4062b4f4cc57ff8f20e10f4171062`.

Воспроизведён следующий broad-suite fixture defect: `test_commodity_group_docs.py` на пустой/hostile SQLite давал **8 failed** из-за отсутствующей `regulatory_documents`. Модуль теперь создаёт отдельную временную SQLite через существующий pinned classification bootstrap, перепривязывает захваченные test/seed/application DB consumers к одному временному engine и дважды загружает существующий `seed_commodity_group_docs` для явной проверки идемпотентности. Все 8 исходных test methods и assertions сохранены AST-identical; production code, seed-данные, конфигурация продукта и правовая интерпретация не менялись.

Проверки:

- A4 `/root/a4_commodity_docs_168`: hostile focused **8 passed**; смежный семимодульный набор в обоих порядках **80 passed**; seed idempotence **115 документов / 284 mappings → 0 / 0**, totals **321 / 489**; hashes/cleanup/diff-check exit 0;
- root control: hostile focused **8 passed**; оба смежных порядка **80 passed**; local agent-safety **120 + 4 passed**, snapshot valid, exit 0;
- независимый A5 `/root/a5_commodity_docs_168`: **FINAL PASS без findings**; исходные тесты/assertions AST-identical, hostile DB/source sentinels отсутствуют, pinned catalogue неизменён, временные DB/WAL/SHM удалены;
- exact-head CI: [run 38141335175](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38141335175), offline-safety job `114475658546`, **success**.

Seeded commodity-group inventory является только test evidence, не доказательством актуальной нормативной или source completeness. Lawful populated synchronized NTM snapshot недоступен. Полный #245 product/legal/source completeness остаётся **NOT PASS**. Merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий шаг — изолировать следующий seed-backed broad-suite fixture/data cluster на disposable данных без ослабления assertions; не выдавать тестовый inventory за актуальный нормативный источник.

## 0aaaaaaaaaaaaaaaaaaaaaaaaaa. #245 — recycling fees используют hermetic seed fixture

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `70beb6d124a4062b4f4cc57ff8f20e10f4171062`, tree `8f8ddebc4adaa77ade8b44449aaa44bffde5a04a`, parent `6b449c7ba981e45c43c01f30bc75f80071d1202e`.

Воспроизведён следующий broad-suite fixture defect: `test_recycling_fees.py` на пустой/hostile SQLite давал **13 failed / 1 passed** из-за отсутствующих `recycling_fees` и зависимых payment-таблиц. Модуль теперь создаёт отдельную временную SQLite через существующий pinned classification bootstrap, перепривязывает захваченные test/application/normative-store/payment-engine/rate-display/seed consumers к одному временному engine и загружает существующий `seed_recycling_fees`. Все 14 исходных test methods и 25 исходных assertions сохранены; production code, ставки, seed-данные и правовая интерпретация не менялись.

Проверки:

- A4 `/root/a4_recycling_fees_fixture_167`: hostile focused **14 passed**; смежный набор в обоих порядках **72 passed**; seed idempotence **40 → 40**, второй insert 0; hashes/cleanup/compile/diff-check exit 0;
- root control: hostile focused **14 passed**; оба смежных порядка **72 passed**; local agent-safety **120 + 4 passed**, snapshot valid, exit 0;
- независимый A5 `/root/a5_recycling_fees_fixture_167`: **FINAL PASS без findings**; hostile focused **14 passed**, оба смежных порядка **72 passed**; исходные тесты/assertions AST-identical, hostile DB/source sentinels и pinned catalogue неизменны, временные DB/WAL/SHM удалены;
- exact-head CI: [run 38137757823](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38137757823), offline-safety job `114465033700`, **success**.

Seeded recycling-fee inventory является только test evidence, не доказательством актуальности ставок, нормативной или source completeness. Lawful populated synchronized NTM snapshot недоступен. Полный #245 product/legal/source completeness остаётся **NOT PASS**. Merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий шаг — изолировать следующий seed-backed broad-suite fixture/data cluster на disposable данных без ослабления assertions; не выдавать тестовый inventory за актуальный нормативный источник.

## 0aaaaaaaaaaaaaaaaaaaaaaaaa. #245 — declaration documents используют hermetic seed fixture

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `6b449c7ba981e45c43c01f30bc75f80071d1202e`, tree `917b418ee5a69c3b75188cb08129a0e79de15e0f`, parent `776e5bdb67c8ac1b6c630196b6e00691d3fa5ec1`.

Воспроизведён следующий broad-suite fixture defect: `test_declaration_documents.py` захватывал default `SessionLocal` и на пустой/hostile SQLite давал **13 failed** из-за отсутствующей `declaration_documents`. Модуль теперь создаёт отдельную временную SQLite через существующий pinned classification bootstrap, перепривязывает захваченные test/application/normative-store/seed consumers к одному временному engine и загружает существующий `seed_declaration_documents`. Все 13 исходных test methods и 16 исходных assertions сохранены; production code, seed-данные, ставки и правовая интерпретация не менялись.

Проверки:

- A4 `/root/a4_declaration_documents_fixture_166`: hostile focused **13 passed**; смежный набор в обоих порядках **58 passed**; seed idempotence **87 → 87**, второй insert 0; hashes/cleanup/compile/diff-check exit 0;
- root control: hostile focused **13 passed**; оба смежных порядка **58 passed**; local agent-safety **120 + 4 passed**, snapshot valid, exit 0;
- независимый A5 `/root/a5_declaration_documents_fixture_166`: **FINAL PASS без findings**; hostile focused **13 passed**, оба смежных порядка **58 passed**; исходные тесты/assertions AST-equivalent, hostile DB/source sentinels и pinned catalogue неизменны, временные DB/WAL/SHM удалены;
- exact-head CI: [run 38133961473](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38133961473), offline-safety job `114453881715`, **success**.

Seeded declaration-documents inventory является только test evidence, не доказательством актуальной нормативной или source completeness. Lawful populated synchronized NTM snapshot недоступен. Полный #245 product/legal/source completeness остаётся **NOT PASS**. Merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий шаг — изолировать следующий seed-backed broad-suite fixture/data cluster на disposable данных без ослабления assertions; не выдавать тестовый inventory за актуальный нормативный источник.

## 0aaaaaaaaaaaaaaaaaaaaaaaa. #245 — import restrictions используют hermetic seed fixture

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `776e5bdb67c8ac1b6c630196b6e00691d3fa5ec1`, tree `3906bb199996c590bb77eaa9e79777c5b08614a9`, parent `6d95f61986f71e89a390b77256dfed55c2c80f39`.

Воспроизведён следующий broad-suite fixture defect: `test_import_restrictions.py` захватывал default `SessionLocal` и на пустой/hostile SQLite давал **15 failed** из-за отсутствующей `import_restrictions`. Модуль теперь создаёт отдельную временную SQLite через существующий pinned classification bootstrap, перепривязывает захваченные test/application/normative-store/seed consumers к одному временному engine и загружает существующий `seed_import_restrictions`. Все 15 исходных test methods и 19 assertions сохранены; production code, seed-данные, ставки и правовая интерпретация не менялись.

Проверки:

- A4 `/root/a4_import_restrictions_fixture_165`: hostile focused **15 passed**; смежный набор в обоих порядках **45 passed**; seed idempotence **76 → 76**, второй insert 0; hashes/cleanup/compile/diff-check exit 0;
- root control: hostile focused **15 passed**; оба смежных порядка **45 passed**; local agent-safety **120 + 4 passed**, snapshot valid, exit 0;
- независимый A5 `/root/a5_import_restrictions_fixture_165`: **FINAL PASS без findings**; hostile focused **15 passed**, оба смежных порядка **45 passed**; исходные тесты/assertions AST-equivalent, hostile DB/source sentinels и pinned catalogue неизменны, временные DB/WAL/SHM удалены;
- exact-head CI: [run 38130084244](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38130084244), offline-safety job `114442413336`, **success**.

Seeded import-restrictions inventory является только test evidence, не доказательством актуальной нормативной или source completeness. Lawful populated synchronized NTM snapshot недоступен. Полный #245 product/legal/source completeness остаётся **NOT PASS**. Merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий шаг — изолировать следующий seed-backed broad-suite fixture/data cluster на disposable данных без ослабления assertions; не выдавать тестовый inventory за актуальный нормативный источник.

## 0aaaaaaaaaaaaaaaaaaaaaaa. #245 — Honest Mark использует hermetic seed fixture

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `6d95f61986f71e89a390b77256dfed55c2c80f39`, tree `983e705370281ea2367db721ee22b40d7256c07c`, parent `d1240389b62f13ba38c442ce64a011e99e8a3d8c`.

Воспроизведён следующий broad-suite fixture defect: `test_honest_mark.py` захватывал default `SessionLocal` и на пустой/hostile SQLite давал **13 failed** из-за отсутствующей `non_tariff_measures`. Модуль теперь создаёт отдельную временную SQLite из существующего pinned classification bootstrap, перепривязывает захваченные test/application/seed session factories к одному временному engine и загружает существующий Honest Mark inventory. Все 13 исходных assertions сохранены; production code, данные продукта, ставки и правовая интерпретация не менялись.

Проверки:

- A4 `/root/a4_honest_mark_fixture_164`: hostile focused **13 passed**; bootstrap safety в обоих порядках **18 passed**; seed idempotence **644 → 644**; hashes/cleanup/compile/diff-check exit 0;
- root control: hostile focused **13 passed**; оба порядка bootstrap safety **18 passed**; local agent-safety **120 + 4 passed**, snapshot valid, exit 0;
- независимый A5 `/root/a5_honest_mark_fixture_164`: **FINAL PASS без findings**; hostile focused **13 passed**, adjacent customs-procedure suites в обоих порядках **25 passed**; все 13 исходных test methods/assertions AST-equivalent, sentinel/pinned files неизменны, временные DB/WAL/SHM удалены;
- exact-head CI: [run 38126432552](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38126432552), offline-safety job `114431647861`, **success**.

Disposable Honest Mark inventory является только test evidence, не доказательством нормативной или source completeness. Lawful populated synchronized NTM snapshot недоступен. Полный #245 product/legal/source completeness остаётся **NOT PASS**. Merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий шаг — изолировать следующий seed-backed broad-suite fixture/data cluster на disposable данных без ослабления assertions; не выдавать тестовый inventory за актуальный нормативный источник.

## 0aaaaaaaaaaaaaaaaaaaaaa. #245 — customs procedures используют hermetic seed fixture

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `d1240389b62f13ba38c442ce64a011e99e8a3d8c`, tree `751c1d516314107082b38d5a18685b2fab4b6389`, parent `ec00c3dad4be46ae9c8efb47103fff4650df4761`.

Воспроизведён следующий broad-suite fixture defect: `test_customs_procedures.py` захватывал default `SessionLocal` и на пустой/hostile SQLite давал **12 failed** из-за отсутствующей таблицы `customs_procedures`. Модуль теперь создаёт отдельную временную SQLite для каждого теста, перепривязывает захваченный session factory вместе с application/seed consumers и загружает существующий `scripts.seed_customs_procedures` inventory. Все 12 исходных assertions сохранены; production code, данные продукта, ставки и правовая интерпретация не менялись.

Проверки:

- A4 `/root/a4_customs_procedures_fixture_163`: hostile focused **12 passed**, обратный порядок **12 passed**, compile/diff-check exit 0;
- root control: hostile focused **12 passed**; local agent-safety **120 + 4 passed**, exit 0;
- независимый A5 `/root/a5_customs_procedures_fixture_163`: **FINAL PASS без findings**; hostile sentinel **12 passed**, обратный порядок **12 passed**, sentinel hash неизменён; dry-run/real/idempotent seed audit PASS;
- exact-head CI: [run 38123022463](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38123022463), offline-safety job `114421482867`, **success**.

Disposable procedure inventory является только test evidence, не доказательством нормативной или source completeness. Lawful populated synchronized NTM snapshot недоступен. Полный #245 product/legal/source completeness остаётся **NOT PASS**. Merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий шаг — изолировать следующий seed-backed broad-suite fixture/data cluster на disposable данных без ослабления assertions; не выдавать тестовый inventory за актуальный нормативный источник.

## 0aaaaaaaaaaaaaaaaaaaaa. #245 — HS leaf clarification использует hermetic fixture

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `ec00c3dad4be46ae9c8efb47103fff4650df4761`, tree `0db14cfa88af89469108e92e230f7dfeac8ae0ad`, parent `20459b52510efbbea7785b914dcd0d27fb0f59a9`.

Воспроизведён следующий broad-suite fixture defect: `test_hs_leaf_clarification.py` читал пустую унаследованную SQLite и давал **8 failed / 1 passed** из-за отсутствующей `hs_rates`. Модуль теперь использует существующий disposable pinned classification inventory и добавляет только во временную БД три явные test-only ставки. Захваченные `SessionLocal` для calculator path подменены той же фабрикой. Общий fixture сохраняет оба допустимых состояния optional `customs.db`: файл остаётся побайтово неизменным, если существовал, и отсутствующим, если его не было.

Проверки:

- A4 `/root/a4_hs_leaf_fixture_162`: focused **9 passed**; семимодульный hermetic classification suite **86 passed**, exit 0;
- root control: focused **9 passed**; local agent-safety **120 + 4 passed**, exit 0;
- независимый A5 `/root/a5_hs_leaf_fixture_162`: **FINAL PASS без findings**; focused **9 passed**, adjacent **77 passed**; present/absent `customs.db` preservation подтверждён;
- exact-head CI: [run 38120143563](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38120143563), offline-safety job `114413135616`, **success** на attempt 2. Первый attempt упал только на гонке cleanup временного Git pack; локальный exact-tree safety и повтор CI прошли.

Изменены только два test-файла; production code, нормативные данные, ставки и legal interpretation не менялись. Disposable inventory не является правовым или source-completeness evidence. Lawful populated synchronized NTM snapshot недоступен. Полный #245 product/legal/source completeness остаётся **NOT PASS**. Merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий шаг — изолировать следующий кластер broad-suite fixture/data failures на disposable данных, не ослабляя assertions и не выдавая test inventory за нормативную полноту.

## 0aaaaaaaaaaaaaaaaaaaa. #245 — ROP importer изолирован от argv тестового раннера

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `20459b52510efbbea7785b914dcd0d27fb0f59a9`, tree `e1546df9dbc5e1d576cc2601a2a254ed3a7fbba0`, parent `6f3a832244c7f9c48cca4c97ffb8a681867c3f52`.

Широкий backend-прогон воспроизвёл отдельный broad-suite defect: программный вызов ROP importer разбирал аргументы самого pytest, поэтому `-q tests/test_rop_calculator.py` завершал setup через `SystemExit` и блокировал все 13 расчётных проверок. Importer теперь принимает явную последовательность `argv`, сохраняя обычную CLI-семантику при её отсутствии; тестовый setup передаёт пустой список. Добавлен regression с hostile outer `sys.argv`.

Проверки:

- до исправления: focused ROP **13 setup errors**, exit 1;
- A4 `/root/a4_rop_importer_argv_161`: **14 passed**, CLI `--help`/dry-run exit 0;
- root control на disposable SQLite: focused + adjacent ROP/child-marker **53 passed**, compileall/diff-check exit 0;
- независимый A5 `/root/a5_rop_importer_argv_161`: **FINAL PASS без findings**; focused **14 passed**, adjacent **18 passed**, hostile outer argv изолирован, hash dry-run DB неизменён;
- exact-head CI: [run 38116681245](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38116681245), offline-safety job `114402828401`, **success**.

Формулы, ставки, нормативные данные и production DB не менялись. Широкий baseline остаётся красным по другим fixture/data-контрам и не является полным product PASS. Lawful populated synchronized NTM snapshot недоступен. Merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий шаг — изолировать следующий кластер broad-suite failures на disposable данных, начиная с актуального product/data fixture contour, не скрывая failures и не выдавая тестовый inventory за нормативную полноту.

## 0aaaaaaaaaaaaaaaaaaa. #245 — canonical model использует disposable full-catalog fixture

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `6f3a832244c7f9c48cca4c97ffb8a681867c3f52`, tree `f23cd21eed59d9df588eb2075526ae555472726d`, parent `b65516018df18646a3a1b2f1bcaa88fa66d0aeec`.

Закрыт следующий full-catalog fixture-контур. До исправления 17-модульный classification/search regression давал **10 failed / 137 passed + 7 subtests**: `test_canonical_tnved_model.py` создавал и читал пустую default DB, поэтому не находил реальные headings `0101`, `0302` и другие. Теперь canonical model использует существующую session-scoped disposable DB из pinned bootstrap; прямые DB-сеансы также проходят через patchable `app_db.SessionLocal`. Assertions, skip/xfail, production code и product data не менялись.

Проверки:

- root: canonical **32 passed**, hostile `DATABASE_URL` **32 passed**, exact 17-module regression **147 passed + 7 subtests**, exit 0;
- независимый A5 `/root/a5_canonical_fixture_160`: **FINAL PASS без findings**; normal **32 passed**, hostile **32 passed**, exact 17-module regression **147 passed + 7 subtests**, exit 0;
- exact-head CI: [run 38113322643](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38113322643), offline-safety job `114393202247`, **success**.

Полный #245 product/legal/source completeness остаётся **NOT PASS**. Lawful populated synchronized NTM snapshot недоступен. Merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий шаг — воспроизвести следующий remaining full-catalog fixture failure либо bounded #245 search/classification defect; disposable inventory не считать нормативной полнотой.

## 0aaaaaaaaaaaaaaaaaa. #245 — Tree Model v2 использует изолированный каталог

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `b65516018df18646a3a1b2f1bcaa88fa66d0aeec`, tree `9b60048309b8ce4dcb74a7a3775fbfa8f207f182`, parent `6cba001e44812391be363a3e2bdd5ecdf86b11a9`.

Закрыт следующий full-catalog fixture-контур. До исправления совместный запуск TN VED catalog API и Tree Model v2 давал **2 failed / 25 passed**: оба tree-теста не находили реальные heading-коды вроде `0101`, потому что читали пустую default DB. Tree Model v2 теперь использует существующую session-scoped disposable DB из pinned bootstrap. Общий fixture дополнительно подменяет захваченный на уровне модуля `tree_engine.builder.SessionLocal`, поэтому внутренний расчёт leaf flags не уходит в унаследованный `DATABASE_URL`.

Первый candidate независимый A5 отклонил: hostile `DATABASE_URL` выявил этот скрытый обход fixture. После исправления свежий A5 `/root/a5_tree_fixture_157` — **PASS без findings** на точном дереве: hostile run **4 passed**, обратный порядок **4 passed**, совместный пяти-модульный regression **63 passed**. Root повторил hostile **4 passed** и общий **63 passed**; exit 0. Assertions, skip/xfail, production code и product data не менялись; SHA-256 default и pinned DB сохранились.

Exact-head CI: [run 38022682658](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38022682658), offline-safety job `114126853141`, **success**.

Полный #245 product/legal/source completeness остаётся **NOT PASS**. Lawful populated synchronized NTM snapshot недоступен. Merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий шаг — воспроизвести следующий remaining full-catalog/fixture failure либо bounded #245 search/classification defect; disposable inventory не считать нормативной полнотой.

## 0aaaaaaaaaaaaaaaaa. #245 — classification fixture больше не зависит от пустой default DB

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `6cba001e44812391be363a3e2bdd5ecdf86b11a9`, tree `0e5a147fcdd3a2eb93ab3057f65c41500035f19f`, parent `8ca94203a04c131f2f7181a3e66b5ab71fdf59a6`.

Закрыт воспроизводимый fixture-контур classification/search. До исправления classification rulings + FTS letters давали **19 failed / 8 passed**, а соседний semantic navigation — ещё **9 failed**, потому что тесты читали пустую default DB. Теперь все три набора используют одну session-scoped disposable DB, создаваемую существующим pinned bootstrap. Пороговые и содержательные assertions не менялись; skip/xfail не добавлялись.

Default `customs.db`, pinned catalogue и заранее заданный hostile `DATABASE_URL` остаются побайтово неизменными. Временная DB и WAL/SHM удаляются после teardown. Шесть parser-boundary описаний добавляются только во временную DB на существующие точные коды каталога и не являются правовым или source-completeness evidence.

Проверки:

- A4 author `/root/a4_classification_fixture_156`: exact six-module **54 passed + 15 subtests**, exit 0; DB hashes и cleanup подтверждены;
- root: exact six-module **54 passed + 15 subtests**, exit 0; SHA-256 default/source DB неизменны, sidecars отсутствуют;
- независимый A5 `/root/a5_classification_fixture_156`: **PASS без findings**; exact six-module **54 passed + 15 subtests**, отдельные модули и hostile-environment проверки — PASS;
- exact-head CI: [run 38019455741](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38019455741), offline-safety job `114116972462`, **success**.

Изменены только test fixture и три test-модуля; production code/data, API, расчёты, applicability и enforcement не менялись. Полный #245 product/legal/source completeness остаётся **NOT PASS**: lawful populated synchronized NTM snapshot недоступен.

Следующий шаг — продолжить оставшиеся full-catalog fixture failures или следующий воспроизводимый bounded #245 search/classification defect, не подменяя test inventory нормативной полнотой.

## 0aaaaaaaaaaaaaaaa. #245 — оставшиеся registry/source URL в UI теперь fail-closed

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `8ca94203a04c131f2f7181a3e66b5ab71fdf59a6`, tree `26ff4dbb3e56440ea5ffa48a6c037720a828478a`, parent `d9d0be7da22904689aa4e5af1f62d7ca58072a8f`.

Закрыт связный frontend-блок из семи оставшихся API-derived внешних ссылок на пяти поверхностях: Calculator, PermitPicker, NonTariff, DocumentCheck и PermitDocumentsBlock. Все они теперь используют общий строгий `getSafeExternalUrl`: допустимый absolute HTTP(S) сохраняется byte-for-byte; credentials, non-HTTP, control/bidi, backslash и malformed host не становятся anchor, но остаются ограниченным экранированным plain-text evidence. Небезопасный `manual_check_url` больше не скрывает безопасный fallback `registry_link`; отклонённое evidence при этом сохраняется.

Проверки:

- A4 author `/root/a4_remaining_external_urls_155`: focused **16 passed**, полный frontend **108 passed**, typecheck/build/diff-check — exit 0;
- root: focused **57 passed**, полный frontend **108 passed**, typecheck/build — exit 0;
- независимый A5 `/root/a5_remaining_external_urls_155`: **PASS без findings**; focused **53 passed**, full frontend **108 passed**, typecheck/diff-check — exit 0;
- exact-head CI: [run 38015394005](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38015394005), offline-safety job `114104399311`, **success**.

Это только URL transport/rendering boundary, не подтверждение официальности, legal applicability или source completeness. Полный #245 product/legal/source completeness остаётся **NOT PASS**: lawful populated synchronized NTM snapshot недоступен. Merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` неизменён и не отправлялся.

Следующий шаг — воспроизвести следующий bounded #245 search/classification/grounding defect либо разобрать fixture contour; NTM full-sync сохранять заблокированным до законно доступного populated synchronized snapshot.

## 0aaaaaaaaaaaaaaa. #245 — официальный URL в Copilot bundle теперь fail-closed

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `d9d0be7da22904689aa4e5af1f62d7ca58072a8f`, tree `74e8517315d6977a3c2170783c619cd56ce604c8`, parent `7ab810dbae2a7caf9f3caebc03014c6f7dbc8cb6`.

Воспроизведён frontend-дефект: `bundle.tnved_context.official_ett_url` в Copilot/Batch напрямую попадал в `href`. Все 11 adversarial значений — credentials, leading whitespace, literal C1/bidi, encoded/double/deep controls, backslash authority confusion и malformed host — становились кликабельными.

Теперь URL проходит общий `getSafeExternalUrl`. Допустимый absolute HTTP(S) сохраняется byte-for-byte; отклонённый адрес остаётся ограниченным экранированным некликабельным evidence. Это только transport/rendering boundary, не подтверждение официальности или юридической полноты.

Проверки:

- pre-fix reproduction: 11 опасных ссылок, exit 1;
- root focused: **61 passed**, полный frontend: **96 passed**, typecheck/build — PASS, общая команда exit 0;
- bounded A5 `/root/a5_bundle_source_url_154`: **PASS без findings** exact staged tree; focused **61 passed**, full frontend **96 passed**, typecheck/build/diff-check — exit 0;
- exact-head CI: [run 38011169587](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38011169587), offline-safety job `114091271018`, **success**.

Полный #245 product/legal/source completeness остаётся **NOT PASS**: lawful populated synchronized NTM snapshot недоступен. Merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` неизменён и не отправлялся.

Следующий шаг — следующий воспроизводимый bounded #245 URL/source или search/classification defect; NTM full-sync сохранять заблокированным до законно доступного populated synchronized snapshot.

## 0aaaaaaaaaaaaaa. #245 — URL цитат Copilot теперь используют общий fail-closed boundary

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `7ab810dbae2a7caf9f3caebc03014c6f7dbc8cb6`, tree `a483ba9bfaeaa855fbc3280473c884bc7bf84c2b`, parent `f982f48490e5be5fae12e2f49a9d106401e60c37`.

Воспроизведён frontend-дефект: Copilot/Batch использовал локальный `new URL` boundary, который нормализовал допустимые ссылки и пропускал credential, управляющие и malformed-host формы, уже отклоняемые общим валидатором. Теперь цитаты Copilot используют `getSafeExternalUrl`: корректный absolute HTTP(S) URL сохраняется byte-for-byte, а credentials, leading whitespace, literal C1/bidi, encoded/double/6-deep controls, backslash confusion и malformed hostname остаются видимым, но некликабельным текстом.

Проверки:

- до исправления focused reproduction: **6 passed / 2 failed**, exit 1;
- root focused: **49 passed**, полный frontend: **84 passed**, typecheck/build — PASS, общая команда exit 0;
- bounded A5 `/root/a5_copilot_url_exec_153`: **PASS** exact staged tree; focused **49 passed**, full frontend **84 passed**, typecheck/build/diff-check — exit 0;
- exact-head CI: [run 38007178245](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38007178245), offline-safety job `114078535987`, **success**.

Полный #245 product/legal/source completeness остаётся **NOT PASS**: lawful populated synchronized NTM snapshot недоступен. Merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` неизменён и не отправлялся.

Следующий шаг — следующий воспроизводимый bounded #245 search/classification/grounding defect; NTM full-sync сохранять заблокированным до законно доступного populated synchronized snapshot.

## 0aaaaaaaaaaaaa. #245 — executable gate для строгих URL цитат чата закрыт

**Кодовый checkpoint не изменён:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `f982f48490e5be5fae12e2f49a9d106401e60c37`, tree `2616d6df4c4e5e611aea55f298d9fbfc56eebbb1`, parent chain `a556cb073482a957fa5fff09ab59ddd2b9194ba5` → `06a540ad6e9fcbd7003a224cc68a3dd5a779598f`.

Ранее chat citation URL boundary был реализован, но свежий focused/full frontend и исполнимый независимый review оставались неподтверждёнными из-за недоступных зависимостей в той среде. На точном неизменном HEAD эти gates теперь реально выполнены:

- root focused: `DeclarantChatThread.test.tsx` + `externalUrl.test.ts` — **54 passed**, exit 0;
- root full frontend: **82 passed**, typecheck/build — PASS, общая команда exit 0;
- свежий независимый A5 `/root/a5_chat_url_exec_151`: **FINAL PASS** exact HEAD/tree; focused **54 passed**, full **82 passed**, typecheck/build/diff-check — exit 0;
- A5 adversarial probe: **24 unsafe URL rejected**, **7 safe HTTP(S) URL preserved byte-for-byte**, включая literal C1/bidi и encoded/double/deep controls, exit 0;
- exact-head CI: [run 37998614667](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37998614667), job `114050947337`, **success**.

Предыдущая `FRONTEND_EXECUTION_PENDING` блокировка закрыта. Полный #245 product/legal/source completeness остаётся **NOT PASS**: lawful populated synchronized NTM snapshot недоступен. Merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись.

Следующий шаг — следующий воспроизводимый bounded #245 search/classification/grounding defect; full-sync audit сохранять заблокированным до законно доступного populated synchronized snapshot.

## 0aaaaaaaaaaaa. #245 — импортированные source URL теперь fail-closed

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `a556cb073482a957fa5fff09ab59ddd2b9194ba5`, tree `e225b7df42488301bd3f12be6e7841a14ba44f31`, parent `9319a1b925a4c7fe04e45431e2805becc61499be`.

Воспроизведён frontend-дефект: импортированные `source_url` в TN VED notes, official ETT и classification rulings напрямую попадали в `href`, поэтому `javascript:`/`data:` значения становились кликабельными. Теперь anchor допускается только для absolute credential-free HTTP(S) URL с синтаксически корректным hostname. Relative/non-HTTP(S), malformed host, credential confusion, literal/encoded control, bidi и backslash fail closed. Отклонённое значение остаётся видимым как ограниченное escaped non-clickable evidence; это не подтверждение валидности источника или юридической полноты.

Проверки:

- pre-fix component reproduction: unsafe `javascript:`/`data:` values были anchors, exit 1;
- author focused: **43 passed**, полный frontend: **76 passed**, typecheck/build/diff-check — exit 0;
- независимый A5 дважды отклонил промежуточные trees: credential/control/host/evidence gaps, затем encoded C1/bidi bypass;
- repaired exact tree: A5 **PASS**, focused **43 passed**, full frontend **76 passed**, adversarial URL matrix **32 cases**, typecheck/build/diff-check — exit 0;
- remote tree побайтово совпадает с reviewed tree;
- exact-head CI: [run 37996837003](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37996837003), job `114044951892`, **success**.

Полный #245 product/legal/source completeness остаётся **NOT PASS**. Lawful populated synchronized NTM snapshot недоступен. Protected merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` неизменён и не отправлялся.

Следующий шаг — продолжить следующий воспроизводимый bounded #245 search/classification/grounding defect; full-sync audit сохранять заблокированным до законно доступного populated synchronized snapshot.

## 0aaaaaaaaaaa. #245 — semantic search больше не выдаёт непохожие векторы как кандидатов

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `9319a1b925a4c7fe04e45431e2805becc61499be`, tree `daadba714208c413c249599dcbf40a0e83b6d733`, parent `28e226a0b1fd33530e4a46786ce0eb5c3f392085`.

Воспроизведён search/classification defect: ортогональные и противоположные эмбеддинги со score `0.0` и `-1.0` попадали в semantic TN VED results как совпадения. До исправления direct probe напечатал оба результата и завершился exit 1.

Теперь `semantic_search_tnved` исключает cosine score `<= 0`. Это минимальная математическая граница: более сильный доменный или юридический порог без калиброванных данных не вводился, положительные кандидаты сохраняют ранжирование. UI явно помечает результаты как кандидатов векторного поиска, а не подтверждённую классификацию, и требует ручной сверки по описанию, примечаниям и классификационным решениям.

Проверки:

- author focused backend: **10 passed + 15 subtests**, frontend: **1 passed**, typecheck/diff-check — exit 0;
- независимый A5 `/root/a5_semantic_candidate_boundary`: **PASS** exact tree; backend **10 passed + 15 subtests**, adjacent API **7 passed**, полный frontend **33 passed**, typecheck и adversarial boundary probe — exit 0;
- root full frontend/typecheck/build: **33 passed**, exit 0;
- root bounded backend selection: **50 passed + 15 subtests**; ещё **19 fixture-dependent failures** из-за пустых таблиц classification rulings/letters, поэтому полный backend PASS не заявляется;
- remote commit tree побайтово совпадает с independently reviewed tree;
- exact-head CI: [run 37991127094](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37991127094), job `114025259019`, **success**.

Полный #245 product/legal/source completeness остаётся **NOT PASS**. Lawful populated synchronized NTM snapshot недоступен. Protected merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` неизменён и не отправлялся.

Следующий шаг — продолжить следующий воспроизводимый bounded #245 search/classification integration defect; отдельно разобрать fixture contour, не подменяя lawful populated snapshot.

## 0aaaaaaaaaa. #245 — классификатор больше не выдаёт LLM-догадку за web grounding

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `28e226a0b1fd33530e4a46786ce0eb5c3f392085`, tree `197f264af9220cd255d5116ffe25ada449514062`, parent `dd7ac413dc2f7698ffe1ce80375557afcbac2da5`.

Воспроизведён fail-open дефект: если реальный web-search не возвращал результат, `SmartClassifier` просил LLM восстановить «наиболее вероятные» характеристики и затем публиковал догадку как `web_context` с `web_search_used=true`. До исправления проверка ожидала пустой контекст, получила модельное предположение и завершилась exit 1.

Теперь web evidence допускается только при фактическом `web_search_result` с непустым корректным HTTP(S) URL и hostname. Text-only, tool error, отсутствующий/пустой URL, `ftp:`, `javascript:`, hostless и malformed URL fail closed. Если поиск был нужен, но подтверждённых данных нет, direct/grouped paths возвращают `MANUAL_REVIEW`, `manual_review_required=true`, `web_search_status=unavailable`, не отдают `web_context` и принудительно снимают `recommended`. UI показывает границу ручной проверки и скрывает «Рекомендуется».

Проверки:

- author backend: **33 passed + 7 subtests**, полный frontend: **32 passed**, typecheck/build/compileall/diff-check — exit 0;
- независимый A5 сначала отклонил candidate из-за type-only/blank-URL proof; repaired exact tree — **PASS**;
- A5 backend/API/parser: **20 passed + 7 subtests**, frontend: **32 passed**, typecheck и adversarial URL matrix — exit 0;
- remote tree побайтово совпадает с reviewed tree;
- exact-head CI: [run 37984824462](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37984824462), job `114004071500`, **success**.

Это не полный #245 product/legal/source completeness PASS. Lawful populated synchronized NTM snapshot по-прежнему недоступен. Protected merge, deploy, production write, enforcement/permissions/secrets change, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` неизменён и не отправлялся.

Следующий шаг — следующий воспроизводимый bounded #245 search/classification integration defect; full-sync запускать только при законно доступном populated synchronized snapshot.

## 0aaaaaaaaa. #245 — Copilot/Batch показывает server grounding и fail-closed provenance

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `dd7ac413dc2f7698ffe1ce80375557afcbac2da5`, tree `48c43f8e00a4091c56425975cb28c63fcc235ab5`, parent `e452d967d86436fda4b49cf344b026b639eb7c5c`.

Воспроизведён frontend-дефект: `/assistant/copilot` и `/assistant/copilot/batch` уже возвращали server-owned `ai.grounding` и `ai.citations`, но типы и общий экран сводки полностью их отбрасывали. Пользователь видел «экспертную сводку» без режима, покрытия и источников.

Исправление показывает coverage, mode, использованные fact-блоки, limitations и citations в single/batch представлении. Положительные `grounded` / `llm_grounded` допускаются только при `generated_from_server_facts=true`, полной citation identity (`id/source_id/title/kind`) и непустом полностью allowlisted `facts_used`. Missing, incomplete и mixed metadata обозначается неподтверждённой; `javascript:` и другие небезопасные URL не становятся ссылками. UI прямо сообщает, что статус не является юридической проверкой и не подтверждает полноту НТМ.

Проверки:

- author focused: **6 passed**, полный frontend: **31 passed**, typecheck/build/diff-check — exit 0;
- независимый A5 дважды отклонил промежуточные trees: неполная citation + произвольный fact; затем valid citation без `facts_used` с положительным badge;
- финальный A5: **PASS без findings**, focused/adversarial **15 passed**, полный frontend **31 passed**, typecheck/build/diff-check — exit 0;
- exact-head CI: [run 37978226897](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37978226897), job `113981820756`, **success**.

Изменены только frontend type/view/focused test. Backend, БД, applicability, source admission, enforcement и feature flags не менялись. Полный #245 product/legal/source completeness остаётся **NOT PASS**; lawful populated synchronized NTM snapshot всё ещё недоступен. A6 `core-s1-6415f443120f-r9-g106` неизменён и не отправлялся.

Следующий шаг — следующий воспроизводимый bounded #245 assistant/search integration defect с теми же fail-closed source boundaries; full-sync audit запускать только при законно доступном populated synchronized snapshot.

## 0aaaaaaaa. #245 — UI чата показывает grounding и fail-closed проверяет metadata

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `e452d967d86436fda4b49cf344b026b639eb7c5c`, tree `e5252a9f45b717215dabf7d5ded1b297480f4435`, parent `43803039d7ce50bf88c3d9c08af2f638462767a2`.

Воспроизведён frontend-дефект контракта: текущий `/v1/assistant/chat` возвращает вложенный объект `answer`, но UI ожидал строку и вызывал `.trim()` на объекте. Одновременно coverage, citations и limitations полностью скрывались от пользователя.

Исправление поддерживает текущий и legacy envelope, показывает ограниченные coverage/mode/limitations/citations и превращает в ссылки только HTTP(S). Утвердительные `grounded` / `llm_grounded` labels допускаются лишь при `generated_from_server_facts=true` и минимум одной runtime-валидной цитате; иначе metadata обозначается неподтверждённой. UI прямо предупреждает, что покрытие данных не подтверждает юридическую полноту. Grounding metadata не попадает в историю; API получает только последние 40 текстовых сообщений, видимая история не обрезается.

Проверки:

- до исправления: **2 failed, 1 passed**, `.trim is not a function`, exit 1;
- author focused: **7 passed**, полный frontend: **25 passed**, typecheck/build — exit 0;
- независимый A5 сначала отклонил первый candidate из-за недоказанных affirmative labels; исправленный exact tree — **PASS без findings**;
- A5 adversarial matrix: **8 passed**, exit 0;
- root repeat focused/typecheck/build — exit 0;
- exact-head CI: [run 37971284152](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37971284152), job `113958262264`, success; [run 37971430723](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37971430723), job `113958761517`, success.

Изменены только frontend type/component/focused test. API, applicability, enforcement, source admission, БД и feature flags не менялись. Полный #245 product/legal/source completeness остаётся **NOT PASS**; populated synchronized NTM snapshot по-прежнему отсутствует. Внешний A6 `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий шаг — следующий bounded #245 assistant/search/frontend integration slice с сохранением fail-closed citations и source boundaries.

## 0aaaaaaa. #245 — assistant grounding больше не считает пустую карточку доказательством

**Новый checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `43803039d7ce50bf88c3d9c08af2f638462767a2`, tree `efbbfb1764c40392b4ecc988f8f929d59fbb4bf6`, parent `321b4ac72b13ec40a0dc3e2b05f8079f39fb6ee7`.

Воспроизведён fail-open metadata defect: синтаксически корректного HS-кода было достаточно для `coverage="grounded"`, даже когда TNVED и NTM providers завершались ошибкой. Первый candidate A5 отклонил: штатно возвращённая пустая TNVED-карточка с одной generic EEC URL всё ещё создавала факт/цитату и могла допустить configured LLM selector.

Финальное исправление требует usable local evidence: непустые title/description/breadcrumb/notes/source revision или resolver-validated canonical anchor. При provider failure либо пустой карточке coverage становится `partial`, citations/facts остаются пустыми, LLM selector не вызывается. Содержательная карточка и canonical anchor сохраняют `grounded`. Пользовательский deterministic fail-closed ответ сохранён; legal applicability, source-of-truth и enforcement не менялись.

Проверки:

- regression до исправления: expected `partial`, получен `grounded`, exit 1;
- author focused: **25 passed + 26 subtests**, exit 0;
- author 12-module assistant/search/grounded/RAG tranche: **87 passed + 29 subtests**, exit 0;
- независимый A5: первый candidate **REJECT MEDIUM**, repaired tree **PASS без findings**; adversarial empty-card/canonical-only/provider-error/candidates/no-context matrix exit 0;
- remote commit tree побайтово совпадает с independently reviewed tree;
- exact-head CI: [run 37963680241](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37963680241), job `113932566080`, **success**.

Тесты выполнялись на новой disposable classification DB с пустыми provider keys, deny proxies и preview marker вне репозитория. `integrity_check=ok`, foreign key violations 0, source WAL/SHM отсутствуют.

Полный #245 product/legal/source completeness остаётся **NOT PASS**. NTM full-sync по-прежнему требует законно доступный populated synchronized snapshot. Внешний A6 `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий шаг — следующий bounded #245 assistant/search API и frontend grounding tranche, не расширяя legal/enforcement semantics.

## 0aaaaaa. #245 — NTM и mass-seed fixtures подтверждены в раздельных disposable-контурах

**Кодовый checkpoint не изменён:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `321b4ac72b13ec40a0dc3e2b05f8079f39fb6ee7`, tree `ef6fd5680b6c006be5c836643a0ab1cbceef111a`.

Расширенный выборочный запуск 35 NTM/non-tariff/regulatory/compliance/permits модулей сначала воспроизвёл **8 failures**: семь mass-seed assertions ожидали более 5 000 документов, а mass-seed-safety ошибочно выполнялся на classification inventory. Это конфликт двух fixture-контуров, а не runtime-дефект продукта. Контуры разделены без изменения кода и порогов:

- classification/NTM contour на каноническом bootstrap: 33 модуля, **790 passed, 2 skipped, 3 subtests**, exit 0;
- отдельный regulatory mass-seed contour: **5 057 документов / 5 481 mapping**, три audit-модуля, **24 passed, 3 subtests**, exit 0;
- суммарно: **814 passed, 2 skipped, 6 subtests**, обе команды exit 0.

Независимый A5 `/root/a5_ntm_fallback` повторил exact unchanged HEAD в свежем detached worktree: **790 passed, 2 skipped, 3 subtests** и **24 passed, 3 subtests**, обе команды exit 0. Worktree чистый, обе SQLite БД дают `integrity_check=ok`, catalogue WAL/SHM отсутствуют, synthetic admitted documents = 0. Новых findings нет.

Exact-head CI остаётся действующим для того же SHA: [run 37941232220](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37941232220) и [run 37941931512](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37941931512), оба `success`. Новый кодовый commit и новый CI run не требуются, потому что проверенный HEAD не изменился.

Полный broad/full-suite PASS и юридическая/source completeness не заявляются. `test_ntm_full_sync.py` всё ещё требует законно доступный populated synchronized NTM snapshot; существующий disposable classification bootstrap его не заменяет. Внешний A6 `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий шаг — следующий bounded offline #245 assistant/search/grounded tranche с сохранением раздельных fixture-контуров и без тестов, требующих неразрешённую внешнюю сеть.

## 0aaaaa. #245 — bootstrap подтверждён расширенным offline-срезом и exact-head CI

**Текущий кодовый checkpoint не изменён:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `321b4ac72b13ec40a0dc3e2b05f8079f39fb6ee7`, tree `ef6fd5680b6c006be5c836643a0ab1cbceef111a`.

На новой disposable DB выполнен следующий bounded offline #245 tranche: bootstrap плюс 12 модулей TN VED/classification/normative/API — **137 passed**, exit 0. Независимый A5 `/root/a5_ntm_fallback` повторил exact clean detached запуск с запретом исходящей сети и вынесенным `TNVED_PREVIEW_CACHE_REVISION_FILE`: **137 passed, 1 warning**, exit 0; tracked/untracked mutation и source WAL/SHM отсутствуют. Existing `test_tnved_catalog_api.py` без перенаправления marker обновляет tracked preview-revision файл, поэтому дальнейшие disposable прогоны обязаны выносить marker из репозитория.

Exact-head Actions подтверждены на alias ref, который свежим `ls-remote` связан с тем же SHA: [run 37941232220](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37941232220), job `113855829425`, success; [run 37941931512](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37941931512), job `113858391699`, success. Старый статус CI pending снят.

Полный broad/full-suite PASS не заявляется: ранее unrelated тест попытался обратиться к `api.proxyapi.ru`, и обход запрета не выполнялся. Lawful populated synchronized NTM snapshot по-прежнему отсутствует, поэтому NTM full-sync и legal/source completeness остаются **NOT PASS**. Внешний A6 `core-s1-6415f443120f-r9-g106` не отправлялся.

Следующий шаг — продолжить следующий ограниченный offline #245 fixture tranche на этом bootstrap с вынесенным preview marker; full-sync ждать только законно доступный populated synchronized snapshot.

## 0aaaa. #245 — канонический disposable bootstrap закрыл FTS classification fixture gap

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `321b4ac72b13ec40a0dc3e2b05f8079f39fb6ee7`, tree `ef6fd5680b6c006be5c836643a0ab1cbceef111a`, parent `a89904e335aa7cb3ae906b094031c0155254000e`; base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

Воспроизведён fixture gap: свежий `init_db()` оставлял 0 писем ФТС и 0 classification rulings, поэтому broad #245 останавливался на inventory assertions. Добавлен отдельный bootstrap, который создаёт только новую SQLite БД, проверяет SHA-256 committed TN VED каталога, открывает источник immutable/read-only, детерминированно оставляет `MIN(id)` для 39 legacy duplicate-code групп и загружает тестовый classification inventory. Существующий target отклоняется; запуск после уже загруженного `app.db` fail-closed, чтобы cached `engine`/`SessionLocal` не записал в ранее привязанную БД. Результат явно помечен как disposable test inventory, не legal/source-completeness snapshot.

Проверки exact final tree:
- reproduction до исправления: 0 FTS letters, первые 3 inventory assertions failed, exit 1;
- author safety tests: **5 passed**, exit 0; bootstrap + исходные FTS/classification suites: **32 passed**, exit 0;
- создано 13 979 уникальных кодов, 206 писем, 205 classification decisions, 50 formal и 520 reference rulings; `integrity_check=ok`;
- независимый A5 `/root/a5_ntm_fallback`: первый candidate **REJECT HIGH/MEDIUM** из-за cached-DB mutation и WAL sidecars; исправленный exact tree **PASS**. Pre-bound DB осталась 0/0/0/0, новый target не создан; hash источника неизменён, WAL/SHM отсутствуют, для всех 39 duplicate groups 0 расхождений с `MIN(id)`;
- remote tree побайтово совпадает с reviewed tree;
- полный backend run остановлен runtime security policy при попытке unrelated теста обратиться к `api.proxyapi.ru`; обход не выполнялся, full-suite PASS не заявляется;
- exact-head GitHub Actions: **PENDING_NO_RUN_OBSERVED**. После push основной ветки и fast-forward CI alias `agent/product-ntm-bootstrap-ci-v1` workflow runs и combined statuses остаются пустыми. Candidate не считается окончательно принятым.

Полный #245 product/legal/source-completeness **NOT PASS**. Lawful populated synchronized NTM snapshot всё ещё недоступен; этот bootstrap его не заменяет. Protected merge, production/DB writes, enforcement flags, secrets/permissions, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` неизменён и не отправлен.

Следующий шаг — повторно проверить mandatory exact-head CI, затем использовать bootstrap для следующего bounded offline fixture tranche #245. NTM full-sync completeness остаётся заблокированной до законно доступного populated synchronized snapshot.

## 0aaa. #245 — official SGR NTM v2 scope и runtime admission теперь fail-closed

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `a89904e335aa7cb3ae906b094031c0155254000e`, tree `641a1acf45728729c683bef2728521cff6e26604`, parent `d5dd222f108399eac82a5d8001d7615a00953d08`; base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

Воспроизведены четыре product defect: DB runtime расширял `exact` HS scope на потомков, допускал inactive measure и export-only rule в import evaluation, а importer принимал неизвестный `hs_scope_mode`. Первый candidate независимый A5 отклонил из-за более серьёзного fail-open: пустой или exclusion-only `description_only` мог совпасть с любым товаром. Финальное исправление требует positive contains/requires marker в importer и dataset validator, блокирует ранее сохранённые некорректные строки в DB runtime, объединяет seed/DB semantics и сохраняет неподтверждённую применимость вне автоматического вывода. Новая юридическая интерпретация и definite applicability не добавлялись.

Проверки exact final tree:
- direct reproduction до исправления: seed matcher `False`, DB runtime `True` для descendant exact scope; четыре targeted regression — **4 failed**, exit 1;
- author disposable-DB NTM v2 runtime/layer slice: **210 passed**, exit 0; focused importer/validator/pipeline после A5 repair: **189 passed**, exit 0; `compileall` и `git diff --check` — exit 0;
- broader #245 probe: **507 passed, 1 skipped, 26 subtests**, затем 10 fixture-inventory failures из-за отсутствующих в disposable DB FTS letters/classification seeds; это зафиксированный fixture/setup gap, не green broad-suite claim;
- независимый A5 `/root/a5_ntm_fallback`: первый candidate **REJECT HIGH**, финальный exact reviewed tree **PASS**; fresh-SQLite adversarial matrix `OFFICIAL_SGR_FAIL_CLOSED_MATRIX_OK`, focused **189 passed**, exit 0; вручную сохранённые empty/exclusions-only строки также не допускаются runtime;
- remote blobs пяти изменённых файлов побайтово совпали с reviewed tree; PR перечитан на exact remote HEAD;
- exact-head GitHub Actions: **PENDING_NO_RUN_OBSERVED** для `a89904e335aa7cb3ae906b094031c0155254000e`; workflow runs и combined status пусты после повторных проверок. Candidate не считается окончательно принятым.

Полный #245 product/legal/source-completeness **NOT PASS**. Protected merge, production/DB writes, enforcement flags, secrets/permissions, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` неизменён и не отправлен.

Следующий шаг — повторно проверить обязательный exact-head CI, затем подготовить canonical disposable fixture bootstrap для FTS classification inventory и продолжить fixture-backed broad/full-sync #245 проверки.

## 0aa. #244 — устаревшее или несвязанное evidence спецпошлины больше не попадает в автоматическую сумму

**Новый текущий checkpoint:** [draft PR #255](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/255), `agent/core-payment-regressions-v1` @ `7c12f21787b1d557630d8b0737c769b326ab112d`, tree `9ebd8fb4f9a11d066f1b538fb50d67861e249604`, parent `6f1f5522cfe304030d1be474e3f074e85a739835`; base #244 неизменён `14e0ee8f034d94ffc5831d87e076f4d693a5a524`.

Воспроизведён product defect: строка trade remedy с `SourceStatus.is_stale=true` всё ещё добавляла 7 000 RUB к публичному расчёту. Исправление связывает каждую anti-dumping, safeguard и countervailing строку с exact current `SourceStatus.revision` и единым 90-дневным budget свежести. Отсутствующий, stale, mismatched или future status, а также revision старше 90 дней, оставляет evidence и переводит расчёт в manual review: special-duty amount и итог удерживаются. Exact 90-day boundary остаётся допустимым. Новая юридическая применимость не выводилась и нормативные источники не переинтерпретировались.

Проверки exact final tree:
- direct reproduction до исправления: `test_public_path_rejects_stale_trade_remedy_source_status` — **FAIL**, получено 7 000 вместо 0, exit 1;
- author focused `tests/test_special_duties.py`: **18 passed + 9 subtests**, exit 0;
- author workflow-equivalent payment slice на disposable SQLite: **274 passed + 23 subtests**, exit 0;
- author broad source/ingestion slice: **254 passed + 63 subtests**, exit 0; `compileall` и `git diff --check` — exit 0;
- независимый A5 `/root/a5_special_scope`: **PASS exact reviewed tree**; focused **37 passed + 9 subtests**, broad **182 passed + 68 subtests**, public-API adversarial matrix **15/15** и future-row matrix **6/6**, все exit 0;
- exact-head GitHub Actions: **PASS** — [run 37921716308](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37921716308), [offline-safety job 113790958532](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37921716308/job/113790958532), [payment-regression job 113790958895](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37921716308/job/113790958895), все steps success.

Все шесть committed payment bundles остаются старше допустимого порога и требуют source-by-source refresh из удержанных первичных snapshots; это исправление делает trade-remedy расчёт fail-closed, но не обновляет и не переутверждает источники. Полный #244 product/legal/source-completeness **NOT PASS**; полный #245 также **NOT PASS**. Protected merge, production/DB writes, enforcement flags, secrets/permissions, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` неизменён и не отправлен.

Следующий шаг — продолжить текущий #245 source/applicability block и подготовить canonical disposable NTM v2 fixtures для воспроизводимых broad/full-sync проверок; неподтверждённую применимость сохранять как manual review.

## 0z. #245 — HTML fallback ФСА больше не принимает неоднозначную таблицу за действующую запись

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `d5dd222f108399eac82a5d8001d7615a00953d08`, tree `9a81a7381d327061050a4616aba3f7988e0bc210`, parent `ad111df595f323b25e9cef1e7e250a6df1a0bad9`; base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

Воспроизведён source/identity defect HTML fallback ФСА: таблица с любой строкой могла стать `VALID` без сопоставления номера, статуса и срока действия. Теперь разбираются все result tables; `VALID` требует точного canonical identity, явного active status и разбираемой непросроченной даты. Пропущенные колонки/ячейки, rowspan/colspan, неоднозначные заголовки, пустые номера, неизвестные даты и конфликтующие дубликаты остаются `UNKNOWN`/manual review; revoked/expired evidence остаётся `NOT_FOUND`. Query/search/organization metadata не считается реестровой записью, но неоднозначная registry-looking таблица блокирует положительный вывод. Справочная фраза «не найдено» не перекрывает точную полную запись и не удаляет evidence. Applicability/advisory/enforcement и правовая интерпретация не расширялись.

Три промежуточных candidate независимый A5 отклонил: из-за missing expiry/rowspan/multiple-table false `VALID`, затем из-за ambiguous header/organization/unparseable expiry, затем из-за ошибочного downgrade корректной active записи служебной metadata-таблицей. Они не публиковались.

Проверки exact final tree:
- author focused FSA/opendata/permits: **75 passed, 1 skipped, 6 subtests**, exit 0; `compileall` и `git diff --check` — exit 0;
- author broad #245 backend slice: **959 passed, 11 skipped, 38 subtests**, exit 0;
- независимый A5 `/root/a5_pravo_probe`: **PASS exact reviewed tree**; adversarial HTML matrix **28/28**, metadata + exact-active **3/3**, focused **20 passed +6 subtests**, related disposable-DB **71 passed, 1 skipped +6 subtests**, все exit 0; import-order probes и diff-check exit 0;
- connector remote tree побайтово совпадает с reviewed local tree; PR перечитан на exact remote HEAD;
- exact-head GitHub Actions: **PENDING_NO_RUN_OBSERVED** для `d5dd222f108399eac82a5d8001d7615a00953d08`.

Полный #245 product/legal/source-completeness **NOT PASS**. NTM full-sync audit всё ещё требует законно доступного populated synchronized snapshot. Protected merge, production/DB writes, enforcement flags, secrets/permissions, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` неизменён и не отправлен.

Следующий шаг — повторно проверить exact-head CI, затем продолжить следующий воспроизводимый #245 source/applicability defect, сохраняя неподтверждённые результаты в manual review.

## 0y. #245 — FSA JSON API больше не принимает чужую или неподтверждённую запись за действующую

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `ad111df595f323b25e9cef1e7e250a6df1a0bad9`, tree `961b8d8c1995900284d54f5143f7ae1db7633b47`, parent `af1f6301f871b5156fabe774505aa9184e452217`; base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

Воспроизведён source/identity defect: любой непустой JSON-ответ API ФСА становился `VALID`, даже если API вернул другой номер, аннулированную/неизвестную запись либо только положительный счётчик без строки. Теперь `VALID` требует точного canonical match по специальному полю номера сертификата/декларации и явного active status. Generic `number` не считается доказательством личности записи, потому что может быть внутренним ID API. Все точные дубликаты агрегируются независимо от порядка: revoked/expired не позволяют `VALID`, active+unknown остаётся `UNKNOWN`. `NOT_FOUND` для несовпадения допустим только когда каждая строка имеет доверенное поле номера; смешанные/ненумерованные ответы и positive count без строк остаются `UNKNOWN` для manual review. Evidence номера, статуса, count и ТН ВЭД сохраняется; applicability/advisory/enforcement и правовая интерпретация не расширялись.

Два промежуточных local candidate независимый A5 отклонил: первый был order-dependent на duplicate active/revoked и ошибочно считал mixed numbered/unnumbered ответ доказанным отсутствием; второй ещё доверял generic string `number` как номеру сертификата. Эти варианты не публиковались.

Проверки exact final tree:
- author focused FSA/opendata/permits: **58 passed, 1 skipped**, exit 0; `compileall` и `git diff --check` — exit 0;
- author broad #245 backend slice: **942 passed, 11 skipped, 32 subtests**, exit 0;
- независимый A5 `/root/a5_pravo_probe`: **PASS exact candidate**; adversarial identity/status matrix exit 0; focused **17 passed**; related FSA/opendata/permits **51 passed, 1 skipped**, exit 0; оба порядка imports exit 0, circular import отсутствует; false `VALID` не найден;
- connector создал remote tree, побайтово совпадающий с reviewed local tree; PR после публикации перечитан и показывает exact remote HEAD;
- exact-head GitHub Actions: **PENDING_NO_RUN_OBSERVED** для `ad111df595f323b25e9cef1e7e250a6df1a0bad9`; workflow runs пусты при проверке.

Полный #245 product/legal/source-completeness **NOT PASS**. NTM full-sync audit всё ещё требует законно доступного populated synchronized snapshot. Protected merge, production/DB writes, enforcement flags, secrets/permissions, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` неизменён и не отправлен.

Следующий шаг — повторно проверить exact-head CI, затем исследовать HTML-table fallback ФСА и следующий #245 source/applicability defect; неподтверждённые результаты оставлять `UNKNOWN`, не расширять definite rules.

## 0x. #245 — локальный FSA opendata статус fail-closed

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `af1f6301f871b5156fabe774505aa9184e452217`, tree `fd3d214ce25a01286f3110e2a42849f4ff31f7a6`, parent `758797f56b00ceb5fd78362a0dce80683dc1e96d`; base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

Воспроизведён source/applicability defect: любая непустая неизвестная строка статуса локальной FSA opendata записи (например, «Ожидает проверки» или «Архив») ошибочно становилась `VALID`. Исправление fail-closed сохраняет номер, держателя и исходный status как evidence: только явный active/valid считается `VALID`, inactive/revoked/expired — `NOT_FOUND`, неизвестный/архивный/неподтверждённый — `UNKNOWN`. Русские и английские отрицания проверяются раньше положительных слов; `invalid`, `unregistered`, `validated`, `reactivated` не дают substring false positive. Lookup scope, SQL matching, NTM applicability, advisory/enforcement и правовая интерпретация не расширялись.

Первый local candidate `98e92e236ff8f0a49a46fab997506f2a882231e9` независимый A5 отклонил: «Не зарегистрирован», «незарегистрирован» и `not registered` ещё попадали в positive marker. Этот вариант не публиковался. Финальный reviewed local tree опубликован как один remote commit и побайтово совпадает.

Проверки exact final tree:
- author focused FSA/permits: **34 passed, 1 skipped**, exit 0; explicit negation matrix, `py_compile`, `git diff --check` — exit 0;
- author broad #245 backend slice: **925 passed, 11 skipped, 32 subtests**, exit 0;
- независимый A5 `/root/a5_pravo_probe`: **PASS exact remote HEAD**; 23-case adversarial matrix exit 0; focused **20 passed**, related FSA **25 passed**, broader FSA/permits **34 passed, 1 skipped**, exit 0; unknown/archive evidence retained, active valid, inactive/expired fail closed; local reviewed tree и remote tree byte-identical;
- exact-head GitHub Actions: **PENDING_NO_RUN_OBSERVED** для `af1f6301f871b5156fabe774505aa9184e452217`; workflow runs пусты при повторной проверке.

Tracked `customs-clear/backend/customs.db.backup_before_pdf_import` проверен как возможный snapshot, но в нём отсутствуют таблицы `non_tariff_measures`/NTM v2; он не пригоден для full-sync audit. Полный #245 product/legal/source-completeness **NOT PASS**. Protected merge, production/DB writes, enforcement flags, secrets/permissions, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` неизменён и не отправлен.

Следующий шаг — повторно проверить exact-head CI; затем выполнить NTM full-sync audit на lawful populated synchronized snapshot, если он появится, либо продолжить следующий воспроизводимый #245 source/applicability defect без расширения definite rules.

## 0w. #245 — статус СГР fail-closed: неподтверждённая запись остаётся evidence, но не считается действующей

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `758797f56b00ceb5fd78362a0dce80683dc1e96d`, tree `b478bbdd8bc1552acda622d5f9c1453f8beb8148`, parent `afab417d008bc6e386091544ac6589884eb758e5`; base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

Воспроизведён product defect: fuzzy-match локального реестра СГР мог вернуть строку со статусом `Аннулировано` и одновременно рекомендовать «Найдено действующее СГР». Исправлено fail-closed без удаления evidence: номер и исходный статус сохраняются, но revoked/negated/unknown возвращают «Найдено совпадение, статус требует проверки» и явное требование сверки в официальном реестре. Положительные английские статусы распознаются только как отдельные слова, поэтому `invalid` и `unregistered` не становятся active по подстроке. Действующие exact/fuzzy сценарии сохранены. HS activation, SQL matching, applicability, advisory/enforcement и правовая интерпретация не расширялись.

Проверки exact remote tree:
- author focused: **19 passed**, exit 0; adversarial status matrix, `git diff --check`, `py_compile` — exit 0;
- author broad #245 backend slice: **917 passed, 11 skipped, 32 subtests**, exit 0;
- независимый A5 `/root/a5_pravo_probe`: первые два exact local commits отклонены из-за `Не действует/not active` и `invalid/unregistered`; финальный exact remote HEAD **PASS**. Focused **19 passed**, related fresh disposable SGR/NTM/normative **154 passed**, lookup/status matrices exit 0; remote tree побайтово совпадает с reviewed tree;
- exact-head GitHub Actions: **PASS** — [run 37897546292](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37897546292), job `offline-safety` `113712246088`, все steps success.

NTM full-sync audit по-прежнему требует законно доступного populated synchronized snapshot. Полный #245 product/legal/source-completeness **NOT PASS**. Protected merge, production/DB writes, enforcement flags, secrets/permissions, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` неизменён и не отправлен.

Следующий шаг — выполнить NTM full-sync audit на lawful populated synchronized snapshot, если он доступен, либо продолжить следующий воспроизводимый #245 source/applicability defect без расширения definite rules.

## 0v. #245 — официальный PRAVO probe больше не принимает synthetic/reference-only как покрытие

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `afab417d008bc6e386091544ac6589884eb758e5`, tree `a1c7cc38118d879135e2eba9ed1aa79f4c2e0b1e`, parent `ec4c3fc67fbb7ca90ec28e2ee89ff232711b2eac`; base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

Воспроизведён source-completeness дефект: одна `PRAVO_GOV` строка со статусом `reference_only` и quality `synthetic_seed` давала общий regulatory probe `0`, но отдельный `regulatory_documents_pravo` probe ошибочно возвращал `1`. Из-за этого synthetic/reference-only данные могли скрыть реальный gap официального правового источника.

Исправление: product retrieval, общий regulatory probe и PRAVO probe используют один fail-closed admission predicate. Допускаются active normal/NULL/verified; исключаются noise, synthetic_seed, reference_only и inactive. Applicability, advisory/enforcement, source status и правовая интерпретация не расширялись.

Проверки exact remote tree:
- author direct reproduction: общий probe `0`, PRAVO probe `1`, exit 0;
- author focused source/regulatory: **22 passed +3 subtests**, exit 0;
- author fixture-isolation с заранее существующей unrelated PRAVO строкой: **1 passed**, exit 0;
- author populated synthetic mass-seed: **5 057 документов / 5 481 mapping**, аудит **24 passed +3 subtests**, seed/tests exit 0;
- author broad #245 backend slice: **898 passed, 11 skipped, 32 subtests**, exit 0;
- независимый A5 `/root/a5_pravo_probe`: первый review отклонил абсолютный fixture-count; финальный exact remote HEAD **PASS** после baseline+delta. Focused **22 passed +3 subtests**, admission matrix exit 0, broader source/advisory/enforcement **80 passed +3 subtests**, exit 0; unrelated row сохранена;
- `git diff --check` и `py_compile`: exit 0;
- exact-head GitHub Actions: **PASS** — [run 37892321961](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37892321961), job `offline-safety` `113695775268`, все steps success.

Synthetic mass-seed dataset-аудит теперь выполнен на disposable БД; это не доказательство официальной полноты. NTM full-sync audit по-прежнему требует законно доступного populated synchronized snapshot. Полный #245 product/legal/source-completeness **NOT PASS**. Protected merge, production/DB writes, enforcement flags, secrets/permissions, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` неизменён и не отправлен.

Следующий шаг — выполнить NTM full-sync audit на lawful populated synchronized snapshot, если он доступен, либо продолжить следующий воспроизводимый #245 source/applicability defect без расширения definite rules.

## 0u. #245 — оставшиеся broad-suite fixtures изолированы без ослабления dataset-порогов

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `ec4c3fc67fbb7ca90ec28e2ee89ff232711b2eac`, tree `93571a51fdd03806693be76920163312edb24d68`, parent `b4fef2b9952a5b58f4bc2545523daf92a3bfd518`; полный двухкоммитный блок начинается от `4333061a162225f0efbbf0e971585a428ce78f82`, base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

Расширенный офлайн-срез сначала воспроизвёл **8 failures / 898 passed / 2 skipped / 32 subtests**: семь assertions массового regulatory seed ошибочно считали пустую disposable DB провалом импорта, а API measures ожидал существование кодов без собственных persisted fixtures. Теперь `test_regulatory_mass_seed.py` пропускается только при отсутствующем/пустом dataset; любой непустой partial snapshot исполняет исходные пороги. `test_tnved_measures_api.py` создаёт exact HsRate evidence для своих кодов и удаляет только ID, вставленные этим fixture-run.

Промежуточный HEAD `b4fef2b9952a5b58f4bc2545523daf92a3bfd518` не принят как финальный: author/A5 увидели, что cleanup по общему `source_revision` мог удалить чужие строки. Финальный HEAD хранит точные inserted IDs; A5 подтвердил, что case-code с тем же marker, official case-code и unrelated same-marker row сохраняются.

Проверки exact head/tree:
- author broad #245 backend slice: **897 passed, 11 skipped, 32 subtests**, exit 0;
- author focused: **3 passed, 9 skipped**, exit 0; отдельный pre-existing-row probe **2 passed**, exit 0;
- author one-row partial regulatory dataset: ожидаемый **1 failed**, exit 1; threshold 5000 не скрыт;
- независимый A5 `/root/a5_ntm_fallback`: **PASS exact remote HEAD**; empty DB **1 passed, 9 skipped**; partial dataset threshold exit 1; cleanup adversarial lifecycle PASS; relevant slice **111 passed, 9 skipped, 3 subtests**, exit 0;
- `git diff --check`: exit 0;
- exact-head GitHub Actions: **PASS** — [run 37886387124](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37886387124), job `offline-safety` `113677226792`, completed `2026-10-09T04:59:15Z`, все steps success.

Изменены только два test-файла; runtime/legal/source-admission/applicability/calculation semantics не менялись. Полный #245 product/legal/source-completeness **NOT PASS**. Mass-seed и full-sync coverage всё ещё требуют законно доступных заполненных synchronized snapshots. Protected merge, production/DB writes, enforcement flags, secrets/permissions, destructive migration и внешний A6 не выполнялись; `core-s1-6415f443120f-r9-g106` неизменён и не отправлен.

Следующий шаг — выполнить оба явных dataset-аудита на populated snapshots либо продолжить следующий воспроизводимый #245 source/applicability defect без расширения definite rules.

## 0t. #256 — exact-head GitHub Actions подтверждён

Для неизменённого HEAD `4333061a162225f0efbbf0e971585a428ce78f82` GitHub Actions run [37881930775](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37881930775) завершён успешно: job `offline-safety` и все его steps — `success` (completed `2026-10-09T04:01:43Z`). Review threads и submitted reviews отсутствуют. Это закрывает только прежний CI-polling blocker; полный #245 product/legal/source-completeness остаётся **NOT PASS**, а populated full-sync dataset audit всё ещё не выполнен. A6 `core-s1-6415f443120f-r9-g106` не отправлялся и не изменялся.

## 0s. #245 — broad fixtures изолированы, full-sync audit не скрывает partial snapshots

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `4333061a162225f0efbbf0e971585a428ce78f82`, tree `f14b0542d0fb8d730b4312c4db58b70b89e2674e`, parent `f1d3a5d451c8325a6c766bd6dce4f7368a2d790c`, base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

Разобраны оставшиеся 12 failures одинакового 20-file product slice. Шесть были зависимостью от произвольно заполненной developer DB: legacy NTM lookup теперь сам создаёт in-memory exact/prefix fixture; tree API сам создаёт и удаляет изолированную иерархию `99xx` и exact HsRate. Ещё девять assertions в `test_ntm_full_sync.py` явно являются аудитом заполненного full-sync snapshot: они пропускаются только при полностью пустой disposable DB, а любой непустой/частичный snapshot обязан исполнять исходные thresholds.

Промежуточный gate `count < 42000` независимый A5 отклонил: он делал порог строк недостижимым и скрывал regression на 41,999 строках. Этот вариант не принят. Финальный exact head использует только `count == 0`.

Проверки exact head/tree:
- author changed lookup/catalog: **25 passed**, exit 0;
- author exact 20-file backend/NTM slice: **322 passed, 10 skipped, 3 subtests**, exit 0;
- author 41,999-row probe: expected total-count failure, exit 1; audit не skipped;
- независимый A5 `/root/a5_ntm_fallback`: **PASS exact remote HEAD**; empty disposable **25 passed, 9 skipped**; сбалансированные 41,999 строк дали ровно **1 failed + 8 passed**; намеренно неправильные 42,000 строк дали **3 expected structural failures + 6 passed**;
- `git diff --check`: exit 0;
- exact-head GitHub Actions: **PENDING_NO_RUN_OBSERVED**; workflow run и commit status для `4333061a162225f0efbbf0e971585a428ce78f82` connector не показывает.

Изменения этого блока только в тестовых contracts/fixtures; legal/applicability/runtime calculation не менялись. Полный #245 product/legal/source-completeness **NOT PASS**. Девять full-sync assertions ещё нужно прогнать на законно доступном заполненном synchronized snapshot. Protected merge, production/DB writes, enforcement flags, secrets/permissions, destructive migration и внешний A6 не выполнялись. A6 `core-s1-6415f443120f-r9-g106` неизменён и не отправлен.

Следующий шаг — получить populated full-sync snapshot для явного dataset audit либо продолжить независимый #245 applicability/source block; не расширять definite rules без подтверждённых характеристик/источника.

## 0r. #245 — карточка отсутствующего кода требует exact persisted evidence

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `5717db24b7833d15182d1da231222559301b8e6f`, tree `97e493374c18b82f5472417bfad74716ec1cbee7`, parent `04979b50bf2926751dad92468e9beb4e2fa7b539`, base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

Воспроизведён product/API defect: произвольный отсутствующий 10-значный код получал успешную карточку только из-за соседнего названия или вычисляемых NTM. Теперь fallback закрыт по умолчанию: код подтверждает только точная сохранённая строка `HsRate.hs_code` или `HsRate.hs_prefix`; широкая prefix-ставка, derived NTM и соседний `Commodity` сами по себе код не легитимизируют. Exact rate-only карточка берёт пошлину из этой строки; обычный exact `Commodity` path не менялся. Тест 8401300000 теперь сам создаёт rate fixture и не зависит от общей developer DB.

Проверки exact head/tree:
- author targeted fallback: **4 passed**, exit 0; related code-card/preliminary tests: **13 passed**, exit 0; compileall и `git diff --check` PASS;
- полный `test_tnved_catalog_api.py` на fresh SQLite: **18 passed, 5 failed**, exit 1; остались только прежние tree/full-catalog fixture ожидания;
- frontend: **18 passed**, typecheck и build PASS, exit 0;
- независимый A5 `/root/a5_ntm_fallback`: **PASS exact remote HEAD**; targeted **6 passed**, adversarial matrix PASS; одинаковый 20-file slice улучшился с parent **14 failed, 315 passed, 1 skipped** до candidate **12 failed, 319 passed, 1 skipped**, новых failures нет;
- exact-head GitHub Actions: **PENDING_NO_RUN_OBSERVED** для `5717db24b7833d15182d1da231222559301b8e6f`; workflow run и commit status connector не показывает.

Доступны полная exact-tree копия, Git, Python, Node и реальное выполнение команд. Публикация выполнена только в существующую draft-ветку под coordinator lease generation 129. Protected merge, production/DB writes, flags, secrets/permissions, destructive migration и A6 не выполнялись. A6 request `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся.

Остаётся: 12 broad-slice failures зависят от полного каталога/seed fixtures; full #245 product/legal/source-completeness **NOT PASS**; exact-head CI не подтверждён. Следующий шаг — сделать канонический disposable full-catalog fixture для tree/lookup tests либо изолировать эти dataset contracts, не расширяя legal/applicability semantics.

## 0q. #245 — synthetic legacy NTM seed исключён из product evidence

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `04979b50bf2926751dad92468e9beb4e2fa7b539`, tree `051d77ca61ef1d70e28beee46d28fa977ef8b75c`, parent `a1984575e6c58360847a54ee8618944dbfb996b0`, base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

Воспроизведён source-safety defect: `seed_ntm_full_sync.py` создавал шаблонные legacy NTM строки как `quality=normal`; runtime, RAG, invoice enrichment, SGR trigger, catalog/completeness и legacy-to-v2 import могли признать их product evidence. Новые строки теперь `synthetic_seed` и fail-closed исключаются всеми этими read paths. Ремонт старых строк ограничен deterministic representative commodity code, полным generated payload и только прежним `quality=normal`.

Первый repair-вариант независимый A5 отклонил: text-only match мог relabel курируемую строку на never-selected code. Этот вариант не принят; финальный exact head сохраняет такую `verified` строку и меняет только точную старую generated запись.

Проверки exact head/tree:
- author focused: `25 passed, 1 skipped, 3 subtests`, exit 0; compileall и `git diff --check` PASS;
- author fresh disposable SQLite + init/migrations + полный NTM v2 import + безопасный backend/NTM срез: `867 passed, 2 skipped, 32 subtests`, exit 0;
- frontend: `18 passed`, typecheck и build PASS, exit 0;
- независимый A5 `/root/a5_ntm_fallback`: **PASS exact remote HEAD**; exact repair/adversarial quality matrix exit 0; focused `25 passed, 1 skipped, 3 subtests`; 20-file candidate/parent comparison одинаков: `14 failed, 315 passed, 1 skipped`, failure-name diff пустой, failures fixture-bound;
- exact-head GitHub Actions: **PENDING_NO_RUN_OBSERVED** для `04979b50bf2926751dad92468e9beb4e2fa7b539`. Connector не показывает run; обычный local push завершился exit 128 (`could not read Username`). Credentials/UI workaround не предпринимался, CI PASS не заявляется.

Доступны полная exact-tree копия, Git, Python, Node и реальное выполнение команд. Публикация выполнена только в существующую draft-ветку под coordinator lease generation 128. Protected merge, production/DB writes, flags, secrets/permissions, destructive migration и A6 не выполнялись. A6 request `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся.

Остаётся: exact-head CI не подтверждён; полный #245 product/legal/source-completeness **NOT PASS**; production remediation уже развёрнутых legacy rows не выполнялся. Следующий шаг — получить/проверить exact-head CI штатным авторизованным каналом, затем продолжить #245 applicability/source failures без расширения definite rules.

## 0p. #245 — permit job detail больше не перехватывается legacy verify route

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `9d4ffb38d7479f6f9a6983728612e01e0c28018e`, tree `824f644beec6a8ef219f737aede05a634fe9297f`, parent `9a8493e196202fdb752abc79302c02f6b1303b79`, base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

Воспроизведён product/API defect: ранний legacy catch-all `GET /api/permits/verify/{number:path}` перехватывал `GET /api/permits/verify/jobs/{job_id}`. Вместо job detail и ownership policy API возвращал permit-verification payload `200`, передавал `jobs/{id}` во внешний permit check и не закрывался для non-owner/ownerless jobs. Catch-all перемещён после всех статических `/verify/*` маршрутов; production-style auth добавлен в устаревшие API-тесты; негативные ownership тесты теперь требуют `404` и отсутствие вызова `check_permits`.

Проверки exact head/tree:
- author focused на свежей disposable SQLite: `python -m pytest -q -p no:cacheprovider tests/test_permits_normalize_and_api.py tests/test_permits_verify_jobs_ownership.py --tb=short` — **13 passed, 1 skipped**, exit 0;
- author широкий permit/auth/API/NTM срез после `init_db()` и полного NTM v2 import: **308 passed, 1 skipped**, exit 0; frontend: **18 passed**, typecheck/build PASS, exit 0; compileall и `git diff --check` PASS;
- независимый A5 `/root/a5_ntm_fallback`: **PASS exact remote HEAD**; focused **20 passed, 1 skipped**, extended **222 passed, 1 skipped**, exit 0; owner `200`, non-owner/ownerless `404`, admin foreign/ownerless `200`, anonymous protected endpoints `401`, негативные job detail/export без внешнего permit check, legacy path со slash сохранён;
- exact-head CI: **PASS** — [run 37872398938](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37872398938), job `offline-safety` `113633224151`, success на точном HEAD `9d4ffb38d7479f6f9a6983728612e01e0c28018e`.

Полный `test_api_integration.py` остаётся диагностически **NOT PASS**: 8 calculator failures / 246 passed / 1 skipped; независимый A5 воспроизвёл те же 8 failures на parent, поэтому это не регрессия текущего diff. Live FSA намеренно не вызывался. Порядок регистрации остаётся важным инвариантом: будущие статические `/verify/*` маршруты должны быть выше legacy catch-all.

Доступны полная exact-tree копия, Git, Python, Node и реальное выполнение команд. Публикация выполнена только в существующую draft-ветку под coordinator lease generation 127. Protected merge, production/DB writes, flags, secrets/permissions, destructive migration и A6 не выполнялись. A6 request `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся.

Остаётся: full #245 product/legal/source-completeness **NOT PASS**; PostgreSQL, payment/calculator fixtures и безопасный remediation уже развёрнутых synthetic rows не закрыты. Следующий шаг — продолжить #245 backend/frontend applicability и source failures без расширения definite rules.

## 0o. #245 — synthetic regulatory seed больше не считается официальным evidence

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `9a8493e196202fdb752abc79302c02f6b1303b79`, tree `19d2f245e7b851b98347fb20a5852fd6b03b5c6f`, parent `5a535d00056c5c46c2ca614eaa3194325647fe1b`, base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

Воспроизведён source-safety defect: `seed_regulatory_mass` создавал 5,057 шаблонных документов с построенными URL как `active/verified`, после чего они выдавались пользователю и считались в official-source completeness. Исправлено fail-closed: synthetic rows теперь `reference_only/synthetic_seed`, их mappings — `reference`, confidence 0, unapproved; runtime evidence и completeness принимают только active non-noise/non-synthetic документы. Повторный явный запуск seed ремонтирует ранее созданные небезопасные labels. Реальные `active/verified` и `active/quality=NULL` документы продолжают выдаваться и учитываться.

Проверки exact head/tree:
- author targeted regulatory safety: **21 passed +3 subtests**, exit 0; свежий полный mass seed: **5,057 documents / 5,481 mappings**, **10 passed**, surfaced 0, admitted completeness 0, exit 0;
- author fresh disposable SQLite + `init_db()` + полный NTM v2 import + широкий канонический NTM/regulatory срез: **808 passed, 1 skipped, 3 subtests**, exit 0; frontend: **18 passed**, typecheck/build PASS, exit 0;
- независимый A5 `/root/a5_ntm_fallback`: **PASS exact remote HEAD**; targeted **258 passed +3 subtests**, mass-seed **9 passed**, fresh-seed, forced legacy repair и adversarial real-document preservation PASS, exit 0;
- exact-head CI: **PASS** — [run 37867410107](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37867410107), job `offline-safety` `113617338713`, success на точном HEAD `9a8493e196202fdb752abc79302c02f6b1303b79`;
- `git diff --check` и compile checks PASS; remote tree совпадает с проверенным tree.

Доступны полная exact-tree копия, Git, Python, Node и реальное выполнение команд. Публикация выполнена только в существующую draft-ветку под coordinator lease generation 126. Protected merge, production/DB writes, flags, secrets/permissions, destructive migration и A6 не выполнялись. A6 request `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся.

Остаётся: full #245 product/legal/source-completeness **NOT PASS**. Уже развёрнутые legacy synthetic rows требуют отдельного безопасного remediation/reseed плана; production backfill не выполнялся. PostgreSQL и оставшиеся dataset-dependent legacy tests не закрыты. Следующий шаг — продолжить #245 applicability/source triage без расширения definite rules и без признания synthetic данных нормативным источником.

## 0n. #245 — startup schema-check больше не отключает fail-closed NTM diagnostics

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `5a535d00056c5c46c2ca614eaa3194325647fe1b`, tree `768e5143cae4f1d168d90acc1361188524543f9c`, parent `0650526aed724322fbe0842f1a8e22d91dfb6b90`, base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

Расширенный канонический NTM/normative/regulatory прогон воспроизвёл order-dependent observability defect: in-process `init_db()`/Alembic `fileConfig` отключал уже созданные application loggers, поэтому предупреждения `NTM_V2_TR_TS` и `NTM_V2_LAYERS` пропадали после schema-check. `alembic/env.py` теперь вызывает `fileConfig(..., disable_existing_loggers=False)`. Applicability, advisory/enforcement, схема и данные не менялись.

Проверки exact head/tree:
- author fresh disposable SQLite + `init_db()` + полный NTM v2 import + 40 backend modules: **819 passed, 1 skipped, 3 subtests**, exit 0; focused startup/warning sequence **3 passed**, exit 0;
- независимый A5 `/root/a5_ntm_fallback`: **PASS exact remote HEAD**; parent доказан как `target_disabled=True/sentinel_captured=False`, candidate как `target_disabled=False/sentinel_captured=True`; Alembic logger остался INFO и выдал 59 migration lines; independent regression **269 passed**, exact-remote focused **1 passed**;
- remote tree byte-identical прошедшему A5 tree; только `customs-clear/backend/alembic/env.py` и `tests/test_ntm_v2_pipeline_flag.py` изменены;
- exact-head CI: **PENDING_NO_RUN_OBSERVED** для `5a535d00056c5c46c2ca614eaa3194325647fe1b`; readiness/полный #245 PASS не заявляются.

Код и команды доступны в полной exact-tree копии; публикация выполнена только в существующую draft-ветку под coordinator lease generation 125. Protected merge, production/DB writes, flags, secrets/permissions, destructive migration и A6 не выполнялись. A6 request `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся.

Остаётся: дождаться exact-head CI; затем продолжить #245 backend/frontend applicability/source failures. Дополнительные definite rules без подтверждённой подкатегории/характеристик не добавлять; юридическая и источниковая полнота **NOT PASS**.

## 0m. #245 — канонический NTM v2 pipeline: исправлены definite over-claim каталога

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `0650526aed724322fbe0842f1a8e22d91dfb6b90`, tree `dad9ba0b58ab7b1815182a2bfc25a19ca033bb8b`, parent `4fdb291b254c8ebff4b9fa65e52cbd7f1ce13126`, base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

На свежей disposable SQLite штатные `init_db()` и `scripts/import_tr_ts_catalog_to_ntm_v2.py` отделили отсутствие fixture от реальных применимостных дефектов. Исправлено: игрушки `9503` больше не получают лишнюю ДС по ТР ТС 008 (только СС); обычная мебель `9401`–`9403` больше не получает ТР ТС 016 о газовых аппаратах; смартфон переведён на текущий код `851713` и definite 020/037 сужен до этого подзаголовка. ТР ТС 004 без подтверждённого напряжения не ставится. Части `851771`/`851779` не попадают в mandatory/document-check; широкий fallback `8517` остаётся только `possible`/manual review. Marking scope не расширен.

Проверки exact head/tree:
- author: `DATABASE_URL=sqlite:////tmp/... python -m pytest -q` для 15 NTM/backend suites после `init_db` и полного NTM v2 import — **504 passed**, exit 0;
- независимый A5 `/root/a5_ntm_fallback`: **PASS exact remote HEAD**; свежая БД/import и `267 passed`, затем exact-remote smoke `104 passed`; промежуточные over-claim 004 и широкого 020 были отклонены A5 и не опубликованы;
- remote tree совпадает с прошедшим A5 tree; локальный `git diff --exit-code` — exit 0;
- exact-head CI: **PENDING_NO_RUN_OBSERVED** для `0650526aed724322fbe0842f1a8e22d91dfb6b90`; readiness/полный #245 PASS не заявляются.

Код и команды доступны в полной exact-tree копии; публикация выполнена только в существующую draft-ветку под coordinator lease generation 124. Protected merge, production/DB writes, flags, secrets/permissions, destructive migration и A6 не выполнялись. A6 request `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся.

Остаётся: дождаться exact-head CI; затем продолжить #245 по следующим backend/frontend applicability/source failures. Дополнительные аппараты 8517 можно добавлять только на подтверждённой подкатегории/характеристиках; юридическая и источниковая полнота **NOT PASS**.

## 0l. #245 — TR TS noise classifier сохраняет product fallback без юридического over-claim

**Новый текущий checkpoint:** [draft PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256), `agent/product-ntm-regressions-v1` @ `4fdb291b254c8ebff4b9fa65e52cbd7f1ce13126`, tree `58ea5b5f13c21ec505ed1b4a7f198aa0842dee02`, base #245 неизменён `e39e19787bd913baeb6f85577a13e1116458e633`.

Воспроизведён старый продуктовый дефект: `8517120000 + tr_ts` ошибочно удалялся как crawler noise, потому что классификатор читал только неполный legacy-каталог и игнорировал уже используемый product fallback. Общий fallback вынесен в отдельный DB-free модуль и используется для консервативного сохранения generic `tr_ts`; конкретный регламент не назначается. Граница `marking` не расширена. Первый вариант независимый A5 отклонил из-за ORM/DB import dependency; он не публиковался. Исправленный вариант не загружает `app.db`, ORM или SQLAlchemy.

Проверки exact head/tree:
- author #245/backend slice на disposable SQLite: `367 passed +44 subtests`, exit 0;
- отдельный focused: `115 passed`, compileall и diff-check PASS;
- независимый A5 `/root/a5_ntm_fallback`: **PASS exact remote HEAD**; `83 passed` и совместно с HS matching `99 passed`, DB/model-blocked import probe PASS, exhaustive `marking` parent/candidate hash identical;
- exact-head CI: **PASS** — [run 37851053652](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37851053652), job `offline-safety` [113563946657](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37851053652/job/113563946657), завершён успешно на точном HEAD `4fdb291b254c8ebff4b9fa65e52cbd7f1ce13126`; это инфраструктурная проверка, не полный DB-backed NTM acceptance.

Диагностический широкий NTM прогон на пустой SQLite не является PASS: pipeline требует инициализированных `ntm_applicability_rules_v2`/`ntm_measures_v2` и импортированных datasets. Это fixture/environment gap, который ещё надо закрыть и затем повторить полный backend/frontend блок. Доступ к полной копии, Git/Python/pytest и законная публикация draft-ветки подтверждены. Protected merge, production/DB writes, flags, secrets/permissions, destructive migration и A6 не выполнялись. A6 request `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся.

Следующий шаг: инициализировать канонические disposable NTM v2 fixtures и разобрать реальные pipeline/applicability failures отдельно от отсутствующих данных; не расширять legal/applicability semantics и не запускать A6. Полный #245, юридическая и источниковая полнота **NOT PASS**.

## 0k. Оставшиеся payment-fixtures из широкого среза закрыты и закреплены в CI

**Текущий checkpoint #255:** [draft PR #255](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/255), `agent/core-payment-regressions-v1` @ `6f1f5522cfe304030d1be474e3f074e85a739835`, tree `a7f640b4fb42320bb77f2c0bd70017a40b367075`, base #244 неизменён `14e0ee8f034d94ffc5831d87e076f4d693a5a524`.

Закрыт следующий воспроизведённый класс fixture/broad-suite failures: ROP importer больше не поглощает аргументы pytest; duty backfill сам поднимает pure-specific fixture и явный EUR/RUB test FX; normative bundle и VAT/PP908 проверки используют идемпотентный disposable seed и сохраняют fail-closed `REVIEW_REQUIRED`/withheld totals. Четыре фиктивных ETT-кода из старого snapshot отфильтровываются единым `is_ett_test_hs()` и покрыты двойным вызовом seed. Exact-head payment CI теперь включает `test_duty_rules_backfill.py`, `test_normative_bundle.py`, `test_rop_calculator.py`, `test_vat_preferences_audit161.py`; bootstrap использует тот же проверенный helper, а не собственный небезопасный загрузчик.

Проверки exact tree:
- author explicit offline-safe payment broad slice: `470 passed +370 subtests`, exit 0;
- author exact workflow-equivalent после исправления bootstrap: `265 passed +23 subtests`, exit 0; focused forward/reverse-order: по `45 passed`, exit 0;
- независимый A5 `/root/a5_special_scope`: **PASS** exact tree; `265 passed +23 subtests`, exit 0; четыре запрещённых fake-кода отсутствуют, permissions/actions не ослаблены;
- exact-head GitHub Actions [run 37844312369](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37844312369): `offline-safety` **SUCCESS** (job 113541234912), `payment-regression` **SUCCESS** (job 113541235424);
- `git diff --check`: PASS.

Доступ к коду подтверждён полной exact-tree копией; Git/Python/pytest и команды реально выполнялись. Законная публикация сделана только в существующую draft-ветку через connector под lease generation 121. Неограниченный root `pytest -q` не повторялся после platform security stop на unrelated outbound `api.proxyapi.ru`; поэтому full-suite PASS не заявляется. Checkpoint записывается CAS и должен быть перечитан. Protected merge, production/DB writes, flags, secrets/permissions, destructive migration и A6 не выполнялись. A6 request `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся.

Остаётся: этот ограниченный payment-broad блок PASS, но полный #244 и юридическая/источниковая полнота **NOT PASS**; шесть committed payment bundles stale. Следующий технический шаг — перейти к #245: воспроизвести текущие backend/frontend NTM failures, начиная с применимости требований по коду/характеристикам/источнику и без выдумывания source completeness.

## 0j. Самодостаточные payment-fixtures и fail-closed broad-suite

**Текущий checkpoint #255:** [draft PR #255](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/255), `agent/core-payment-regressions-v1` @ `26fac3bf5585284afac77734f7888a2fac64e991`, tree `6c7ce0fcdfe726c8803696f4f0fad428874933bd`, base #244 неизменён `14e0ee8f034d94ffc5831d87e076f4d693a5a524`.

Устранён воспроизведённый fixture-класс broad-suite падений: calculator/leaf/recycling/tariff-preference тесты больше не зависят от заранее наполненной чужой `customs.db`. Добавлен идемпотентный disposable test seed для восьми точных кодов и штатный bootstrap существующих test-справочников. Test-only строки остаются явно недоверенными: автоматические результаты обязаны быть `REVIEW_REQUIRED`, финальные VAT/total withheld, provisional-арифметика сохраняется только для диагностики. Четыре исправленных модуля добавлены в exact-head payment-regression CI.

Проверки exact tree:
- author disposable workflow-equivalent: `238 passed +23 subtests`, exit 0; изменённые модули `74 passed`, повторный прогон на общей БД `74 passed`, exit 0;
- orchestration verifier: `120 passed`; snapshot `4 passed`, exit 0;
- независимый A5 `/root/a5_special_scope`: **PASS**; свежий workflow-equivalent `238 passed +23 subtests`, normal/repeat/reverse-order по `74 passed`; все восемь fixture-кодов сохранили `REVIEW_REQUIRED`, `total_payable=null`, `withheld` и `hs_rate_source_binding_unverified`;
- exact-head GitHub Actions [run 37836111451](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37836111451): `offline-safety` **SUCCESS** (job 113513449756), `payment-regression` **SUCCESS** (job 113513450175);
- `git diff --check`: PASS.

Доступ к коду подтверждён полным checkout точного tree; Git/Python/pytest реально выполнялись. Законная публикация сделана только в существующую draft-ветку под lease generation 120. Checkpoint записывается CAS и будет перечитан. Protected merge, production/DB writes, flags, secrets/permissions, destructive migration и A6 не выполнялись. A6 request `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся.

Остаётся: это bounded fixture-cleanup, а не полный broad-suite или #244 PASS. Другие payment/source fixtures и актуальность шести committed bundles ещё требуют разбор; юридическая/источниковая полнота не подтверждена. Следующий технический шаг — продолжить triage оставшихся broad-suite fixture failures без ослабления fail-closed, затем перейти к #245.

## 0i. PP908 — типизированный признак для 30 неоднозначных animal-кодов

**Текущий checkpoint #255:** [draft PR #255](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/255), `agent/core-payment-regressions-v1` @ `ba8097d18d3512479df21cd9c15b768f3d835c93`, tree `648865448fa7576163fbc2549a5f34b39627d22d`, base #244 неизменён `14e0ee8f034d94ffc5831d87e076f4d693a5a524`.

Для 30 листьев `0102`–`0105`, где код не доказывает племенное назначение, добавлен типизированный вход `breeding | non_breeding | unknown` в Calculator, Payment Quote, Smart Payments UI и compare. `unknown` удерживает НДС и итог для ручной проверки; явно подтверждённое документами `non_breeding` выбирает 10%, `breeding` — 22%. Свободный текст не интерпретируется. Конфликт входа с 5 точными убойными или 10 точными племенными кодами также fail-closed. Отсутствующая/повреждённая карта удерживает результат. Compare теперь передаёт новый признак и ранее объявленные `net_weight_kg`, `extra_quantity`, `apply_reduced_vat` во все сценарии.

Проверки exact tree:
- author disposable CI-equivalent: `176 passed +23 subtests`, exit 0; focused `79 passed +14 subtests`, exit 0;
- frontend `npm run typecheck` и `npm run build`: PASS, exit 0;
- первый независимый A5 обнаружил потерю признака в compare; исправление вошло до публикации;
- финальный независимый A5 `/root/a5_special_scope`: **PASS** exact tree; все 30 исходов unknown/non-breeding/breeding, 15 конфликтов, 45 mapping-missing симуляций и API quote/compute/compare проверены;
- exact-head GitHub Actions [run 37829007811](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37829007811): `offline-safety` **SUCCESS** (job 113489177769), `payment-regression` **SUCCESS** (job 113489178130);
- `git diff --check`: PASS.

Доступ к коду и командам подтверждён: полный checkout, Git/Python/pytest/Node доступны; публикация выполнена в существующую draft-ветку через connector под lease generation 119. Checkpoint сохраняется в state и должен быть перечитан после CAS. Protected merge, production/DB writes, flags, secrets/permissions, destructive migration и A6 не выполнялись. A6 request `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся.

Остаётся: typed-признак является входным фактом декларанта и требует подтверждающих документов; source freshness и fixture/broad-suite failures не закрыты; полный #244 и юридическая/источниковая полнота **не PASS**. Следующий технический шаг — разобрать fixture/broad-suite failures, затем продолжить #245.

## 0h. PP908 — retained map живых животных без over-claim

**Текущий checkpoint #255:** [draft PR #255](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/255), `agent/core-payment-regressions-v1` @ `5092e99642387233ebbed6ada2fef8687b629a7a`, tree `392388557d2f7cbe8724de4a12bb45a0a998dd28`, base #244 неизменён `14e0ee8f034d94ffc5831d87e076f4d693a5a524`.

Добавлена сохранённая карта 45 десятизначных листьев `0102`–`0105`, сверенная с официальным PDF группы 01 ЕТТ ЕАЭС (`sha256 7942d2176d8c728dde35f55cc4871ba230fdef721b30d5c191fd444cd55537c9`, 168285 bytes). Автоматические 10% допускаются только для пяти кодов, прямо названных «убойными»; десять племенных кодов исключены; остальные 30 кодов остаются `product_characteristic_required`. Слово «прочие» не используется как доказательство пищевого/неплеменного назначения. Широкие `0102`/`0103`/`0104`/`0105` по-прежнему fail-closed.

Проверки exact tree:
- author disposable SQLite CI-equivalent slice: `157 passed +21 subtests`, exit 0;
- read-only audit: 119/119 безопасных targets покрыты, но ожидаемый exit 1 — `MANUAL_REVIEW_REQUIRED: product_characteristic_required`, auto 5 / breeding excluded 10 / characteristic-required 30;
- независимый A5 `/root/a5_special_scope`: **PASS**; `60 passed +12 subtests`, 45 листьев образуют точное непересекающееся разбиение, stale broad rows не дали ни одной утечки для 40 blocked-кодов;
- exact-head GitHub Actions [run 37822334976](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37822334976): `offline-safety` **SUCCESS** (job 113466271370), `payment-regression` **SUCCESS** (job 113466271764);
- `git diff --check`: PASS.

Полный #244, юридическая полнота и актуальность всех payment sources **не PASS**. A6 request `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся; merge/production/flags/secrets/permissions/destructive действия не выполнялись.

Следующий безопасный шаг: добавить в quote/input проверяемые характеристики товара для 30 неоднозначных animal-кодов, сохраняя withheld totals и manual review при отсутствии/неподтверждённой характеристике; затем продолжить source freshness и #245.

## 0g. PP908 VAT scope — broad over-claim закрыт, animal map остаётся fail-closed

**Текущий checkpoint #255:** [draft PR #255](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/255), `agent/core-payment-regressions-v1` @ `02573a121e3de7ccfab079eb436bce5e85917fc9`, tree `428752c8f8e61c40f239c91e9f6237a818672c3a`, base #244 неизменён `14e0ee8f034d94ffc5831d87e076f4d693a5a524`.

Устранён подтверждённый legal/product over-claim: широкие 10%-преференции `0102`, `0103`, `0104`, `0105` и `8715` удалены из committed seed и отфильтровываются на чтении даже при наличии старых строк в БД. Один и тот же fail-closed guard применяется к payment resolver и catalog UI. AI/reference trigger для колясок сужен до точного `8715001000`; sibling `8715009000` не наследует 10%. Для четырёх животноводческих заголовков точная карта включённых/исключённых десятизначных кодов не выдумывалась: audit сохраняет `MANUAL_REVIEW_REQUIRED: source_mapping_required`.

Проверки exact head/tree:
- author CI-equivalent disposable SQLite: `154 passed +21 subtests`, exit 0;
- audit: 114/114 безопасно суженных targets покрыты, но ожидаемый exit 1 из-за четырёх отсутствующих source mappings;
- первоначальный независимый A5 нашёл два обходных read path (catalog и AI reference); они исправлены до публикации;
- финальный независимый A5 `/root/a5_special_scope`: **PASS** exact remote HEAD/tree; stale broad rows дают 22%/пустой catalog/нет AI trigger, точный `8715001000` даёт 10%, sibling остаётся 22%;
- exact-head GitHub Actions [run 37814127865](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37814127865): `offline-safety` **SUCCESS** (job 113438242529), `payment-regression` **SUCCESS** (job 113438242162);
- `git diff --check`: PASS.

Среда разработки подтверждена: полный checkout exact parent/HEAD, Git/Python/pytest выполняются, draft branch опубликована законно под lease generation 117. Protected merge, production/DB write, flags, destructive migration, secrets/permissions и A6 не выполнялись. A6 request `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся.

Следующий безопасный шаг: получить retained primary-source mapping для включённых/исключённых десятизначных кодов `0102`–`0105`; до этого не снимать manual review. После этого продолжить source-by-source freshness и #245. Полный #244 и юридическая/источниковая полнота **не PASS**.

## 0f. PP908 fail-closed audit и payment regression CI

**Текущий checkpoint #255:** [draft PR #255](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/255), `agent/core-payment-regressions-v1` @ `942d0da1520081666ce3620708f1a692b80af0a2`, base #244 неизменён `14e0ee8f034d94ffc5831d87e076f4d693a5a524`.

PP908 audit больше не возвращает ложный `OK`: при VAT gaps или отсутствии representative code он возвращает `MANUAL_REVIEW_REQUIRED`, а CLI завершает работу с code 1. Герметичные тесты покрывают оба fail-closed случая, полный fixture и JSON CLI. Реальный committed fixture проверяется через миграции и committed snapshots; он явно фиксирует 118 проверенных headings, 113 covered и пять 22% gaps: `0102`, `0103`, `0104`, `0105`, `8715`. Это evidence о пробелах, не юридическое решение и не claim полноты.

Проверки exact head:
- GitHub Actions run [37809890335](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37809890335): `offline-safety` **SUCCESS**, `payment-regression` **SUCCESS**;
- payment regression выполняет полный `test_pp908_vat_coverage.py` и import-duty / bundle / payment-engine / special-duty slices;
- независимый A5 review exact head: **PASS**, предыдущие blockers (circular fixture assertion, отсутствие CLI exit test и DB bootstrap) закрыты;
- provider/network/A6 не вызывались; immutable request `core-s1-6415f443120f-r9-g106` не менялся.

Следующий безопасный шаг: source-backed разбор пяти PP908 gaps без broad heading over-claim; до этого audit обязан оставаться fail-closed. Merge, production, flags, secrets/permissions и destructive операции не выполнялись.

## 0e. Продолжение продуктового цикла — retained ETT source snapshot

**Новый текущий checkpoint #255:** [draft PR #255](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/255), `agent/core-payment-regressions-v1` @ `2751be626775964130af01874cded669427d452b`, tree `6de62435b74e55e195593248cb19dec491314ed1`, base #244 неизменён `14e0ee8f034d94ffc5831d87e076f4d693a5a524`.

ЕТТ import-duty теперь fail-closed без соседнего provenance manifest и сохранённого первичного snapshot. Manifest криптографически связывает точные bytes bundle и source snapshot, revision, официальный HTTPS EEC URL, число нормализованных строк, время захвата и transform id. Отсутствие/mismatch, traversal, symlink и future revision блокируют dry-run/apply; legal completeness не заявляется. Committed ETT bundle по-прежнему не содержит такого snapshot и теперь явно возвращает `manual_review_required: source_snapshot_manifest_missing`; данные не выдумывались и не обновлялись.

Проверки exact tree:
- author import-duty: **71 passed**, exit 0;
- author expanded source suite: **219 passed**, exit 0;
- independent A5 `/root/a5_special_scope`: **PASS**, **264 passed +73 subtests**, exit 0;
- independent adversarial traversal / external symlink / `ett:2099-01-01`: все blocked, `db_mutated=false`, HsRate/SourceStatus/SyncLog unchanged;
- compileall и `git diff --check`: PASS;
- exact-head GitHub CI: **ещё не наблюдался**.

Полный #244, юридическая полнота и актуальность источников **не PASS**. Следующий шаг — получить и проверить реальный immutable EEC snapshot/manifest для ЕТТ, затем интегрировать тот же контракт source-by-source для остальных payment domains; PP908 fixture и #245 остаются после этого. A6 `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся; merge/production/secrets/permissions не выполнялись.

## 0d. Продолжение продуктового цикла — fail-closed provenance builders

**Новый текущий checkpoint #255:** [draft PR #255](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/255), `agent/core-payment-regressions-v1` @ `fd48ed6d82cf0448e8e90469be8b0105eda1c7ee`, tree `e66ff8f046461b3115eb1b88a2d58109a74cdd62`, base #244 неизменён `14e0ee8f034d94ffc5831d87e076f4d693a5a524`.

Обнаружен и закрыт опасный путь source lineage: `build_official_bundles.py` копировал строки operational DB или placeholder-меры и маркировал их текущей датой как официальный revision; `build_vat_excise_official.py` аналогично мог маркировать broad 4-digit PP908 inference и константы акцизов 2025 как текущие. Оба legacy builder теперь fail-closed до DB/file access, import-time mkdir удалён. Для продолжения требуется retained immutable snapshot первичного источника с явным revision; изменение только даты запрещено.

Проверки exact tree:
- author guard: `python -m pytest -q tests/test_official_bundle_builder_safety.py` — **10 passed**, exit 0;
- оба CLI — ожидаемый exit 2, stdout пуст, DB/output не изменены;
- source suite с guard: **316 passed +76 subtests, 1 известный PP908 FAIL**, exit 1; `no_sample_code=118` остаётся видимым;
- независимый A5 `/root/a5_special_scope`: **PASS** exact tree; related suite **256 passed +73 subtests**, exit 0; AST/static и SHA256 bundle-файлов подтверждают отсутствие обхода/записи;
- compileall и `git diff --check`: PASS;
- exact-head GitHub CI: **ещё не наблюдался**.

Все 6 committed payment bundles остаются stale и не обновлялись. Полный #244, юридическая полнота и PP908 coverage **не PASS**. Следующий шаг — построить безопасный source-by-source importer из сохранённых первичных snapshots (сначала ЕТТ/акциз/меры), затем герметичный PP908 fixture. A6 `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся; merge/production/secrets/permissions не выполнялись.

## 0c. Продолжение продуктового цикла — source-refresh broad-suite

**Новый текущий checkpoint #255:** [draft PR #255](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/255), `agent/core-payment-regressions-v1` @ `f0e499e5e97ae83a63d9117e043420e52cb99da6`, tree `ec606fc15f76c73ad461f0ee84d8764b83f7644e`, base #244 неизменён `14e0ee8f034d94ffc5831d87e076f4d693a5a524`.

Восстановлен отсутствовавший `.github/workflows/scheduled-data-refresh.yml` на текущих интерфейсах: read-only `contents: read`, actions закреплены полными SHA, checkout credentials не сохраняются, production write/issue creation/secrets отсутствуют. Committed bundle freshness отделена от live CBR: CBR выполняется с `always()`, поэтому stale bundles не скрывают проверку источника валют.

Проверки exact tree:
- author payment/API/quote/invoice/Copilot/VED: `130 passed +358 subtests`, exit 0;
- source suite: `306 passed +76 subtests, 1 известный FAIL`, exit 1;
- workflow profile: `18 passed`, exit 0;
- независимый A5 `/root/a5_special_scope`: **PASS** на exact tree; чистый venv/pip-check PASS, bundle gate дал валидный JSON и ожидаемый exit 1 при `stale_count=6`, live CBR exit 0 / 54 валюты, safety assertions PASS;
- `git diff --check`: PASS;
- exact-head GitHub CI для этого HEAD пока не наблюдался; readiness не заявляется.

Незакрытые подтверждённые риски: все 6 committed payment bundles старше настроенного 90-дневного порога; PP908 audit на чистой инициализированной БД не находит 118 representative codes (`coverage_pct=0`) и не может доказать нормативное покрытие. Failure не skipped/xfail и не замаскирован фиктивным seed. Следующий шаг — источник-за-источником обновить/проверить payment bundles и сделать PP908 audit герметичным на подтверждённом полном TNVED/rates dataset без новой юридической интерпретации. Полный #244, юридическая полнота и exact-head CI **не PASS**.

A6 `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся. Merge/production/secrets/permissions не выполнялись.

## 0b. Продолжение продуктового цикла — special-duty scope

**Новый текущий checkpoint #255:** [draft PR #255](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/255), `agent/core-payment-regressions-v1` @ `fe7ce2da9cbcf776911f4b27a44ddb40e7e48cc9`, tree `17e1672b5ee98515a1e51e559961d5d7337be0e1`, base #244 неизменён `14e0ee8f034d94ffc5831d87e076f4d693a5a524`.

Исправлен воспроизведённый дефект: строки специальных пошлин с ограничением по изготовителю/экспортёру или описанию товара больше не применяются только по коду/стране. Для каждого непустого persisted scope требуется точное совпадение после NFKC, casefold и нормализации пробелов. Отсутствие, несовпадение, пунктуационное отличие или substring-only совпадение дают `special_duty_scope_unresolved`, нулевую сумму меры, `REVIEW_REQUIRED` и withheld totals. Fuzzy matching и новая правовая интерпретация не добавлены. Scope-поля передаются через Calculator, Payment Quote, Compliance, invoice, Copilot single/batch и VED Intel.

Проверки exact tree:
- author disposable SQLite: `130 passed, 358 subtests`, exit 0;
- точная команда: `python -m pytest tests/test_special_duties.py tests/test_payment_engine.py tests/test_payment_quote.py tests/test_payment_source_admission.py tests/test_automatic_duty_operand_validation.py tests/test_antidumping_fixed_unit_fail_closed.py tests/test_payment_fx_provenance_fail_closed.py tests/test_invoice_and_compare.py tests/test_assistant_copilot.py tests/test_orchestrator_batch_parallel.py tests/test_ved_intel_api.py -q --tb=short`;
- независимый A5 `/root/a5_special_scope`: **PASS**, `65 passed +21 subtests`, exit 0; отдельная adversarial matrix `8/8 PASS`, exit 0;
- exact-head CI: **PASS**, [run 37781116016 / job 113324157002](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37781116016/job/113324157002), `offline-safety`;
- `git diff --check` и compileall: PASS.

Возможности среды подтверждены: полный clone main `e526dfbdb5a31b01bf6f743da0288b88f916de0c`, Git/Python/pytest выполняются, draft-ветка опубликована законно через connector под lease generation 112. Этот checkpoint сохранён в state-ветке и будет перечитан после CAS. Protected merge, production, secrets/permissions и A6 не выполнялись. A6 request `core-s1-6415f443120f-r9-g106` не менялся и не отправлялся.

Остаётся: canonical fixture/broad-suite разбор, затем продолжение #245. Полный #244, юридическая применимость и источниковая полнота **не PASS**.

## 0a. Продолжение продуктового цикла — persisted duty fallback

**Текущий checkpoint заменяет старый HEAD #255 ниже:** [draft PR #255](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/255), `agent/core-payment-regressions-v1` @ `a356f5302a2bb4388504c213b8c767ba1de0a786`, tree `c653cb79db95f82a0b943c1ec445c79038d6a1a8`, base #244 `14e0ee8f034d94ffc5831d87e076f4d693a5a524`.

Исправлено: fallback из persisted `HsRate.duty_rate` теперь сохраняет чистую специфическую часть, MAX и ADD; допускает фактические формы источника `EUR за 1 кг`/`EUR/кг` и русские эквиваленты; строка с валютой без знаменателя, отсутствующие FX/вес и переполнение завершаются fail-closed. Единицы и FX не выдумываются.

Проверки на byte-identical exact tree:
- author: `116 passed, 355 subtests`, exit 0; команда — семь payment/backend файлов на отдельной disposable SQLite;
- lineage scan: 1171/1171 persisted EUR/kg строк из `eec_ett_normative_bundle.json` приняты, 0 отклонено, exit 0;
- независимый A5 `/root/a5_payment_fallback`: **PASS** для опубликованного exact HEAD через совпадающий tree и `git diff --exit-code`; 288 passed +349 subtests, edge harness PASS;
- GitHub exact-head CI: **PASS**, [run 37774959207 / job 113303383038](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37774959207/job/113303383038), `offline-safety` на точном `a356f5302a2bb4388504c213b8c767ba1de0a786`. Это инфраструктурная проверка, не полный product CI.
- Контрольное воспроизведение опубликованного SHA в рабочем чате: `116 passed, 355 subtests`, exit 0 за 4.71s на отдельной новой SQLite; повторены семь payment-модулей через `offline_pytest.py`, JUnit `replay-a356.xml`. Это проверка исполнителя, не новый независимый A5. Worktree после запуска clean.

Доступ к коду: полная копия main `e526dfbdb5a31b01bf6f743da0288b88f916de0c` и candidate worktree доступны. Git/Python/pytest выполняются. Обычная публикация draft-ветки выполнена законно через GitHub connector под lease generation 110; protected merge/production/A6 не выполнялись. A6 request `core-s1-6415f443120f-r9-g106` не отправлялся и не пересоздавался.

Остаётся: продолжить manufacturer/product applicability и fixture/broad-suite разбор; exact-head CI этого исправления подтверждён. Полный #244 и юридическая/источниковая полнота **не PASS**.

### Плановый исполнитель — фактически проверен, 2026-10-08

После завершённого входа в интерфейсе прочитан фактический результат асинхронного пробного запуска задачи «Tariff — разработка» `6ac775d0feac8191abc1e60865ce1461`. Результат сверён с live GitHub: новый commit `a356f5302a2bb4388504c213b8c767ba1de0a786`, checkpoint `7926a5cba641dc74f049c73f570e24c04f456711`, release generation110. API фиксирует `last_run_time=2026-10-08T12:16:33.532805Z`. Исполнитель реально располагал полной копией, Git/Python, выполнил продуктовый тест и опубликовал исправление; ранее неизвестный исход trial установлен. Публикация, локальный повтор тестов и exact-head CI проверены отдельно.

**Существующее часовое расписание возобновлено 12:21:34Z:** `is_enabled=true`, `RRULE:FREQ=HOURLY;INTERVAL=1`, прежняя cadence с DTSTART 10:52Z, timezone Europe/Moscow. Новых расписаний нет. Старый «Tariff — фоновая разработка» и остальные дублирующие developer-задачи выключены; включённый «контроль остановок» остаётся read-only. Prompt обновлён: fallback уже завершён, следующая работа — ограничения производителя/товара и далее broad-suite/#245. Сохраняются единый live lease, запрет защищённых действий/A6 и явная остановка при недоступности полноценного исполнения.

Проверен **один асинхронный запуск того же расписания через run_now**, не обещана безусловная успешность всех будущих часовых запусков. API `next_run_time=null` не интерпретируется как доказанный будущий старт. Итог запуска виден в разговоре самой задачи; доставка в прежний управляющий чат не подтверждена. Для фиксации проверки использован штатный lease generation111; после checkpoint он освобождается.

## 0. Реальный продуктовый цикл — 2026-10-08, рабочий исполнитель

**Результат сохранён:** [draft PR #255](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/255), ветка `agent/core-payment-regressions-v1`, точный HEAD `7ce87f4eb3550f10a285dd04e38e9c6b60508e79`, tree `bb910341be886b587cff8eabc5cba478e5552bea`. Base — неизменный #244 `14e0ee8f034d94ffc5831d87e076f4d693a5a524`. Один общий исправляющий PR, три файла; merge не выполнен. Контроллер допускает рабочие ветки `agent/*`; исходные #244/#245 сохранены.

Исправлено и покрыто регрессиями:
- Некорректные/перевёрнутые даты специальной пошлины больше не превращают её в `not_applicable`: требуется ручная проверка, сумма строки/итог отсутствуют.
- Чисто процентная спецпошлина не требует курс валюты для нулевой фиксированной части; `fx_rate=null`, frontend тип приведён к `number | null`.
- Отрицательные, неконечные и иные недопустимые ставки специальных пошлин не попадают в предварительную арифметику.

### Среда и воспроизводимость

Полный Git checkout, 1590 tracked paths в исходном #244, история не shallow, missing objects не обнаружены. Отдельные полные worktrees для main, state, #244, его базы `08e030a6053ac9638957119373797e0fbf2b10c2` и #245. Python 3.12.14 / Git 2.51.1 / Node 24.19.0. Изолированный venv: `pip install -r customs-clear/backend/requirements.txt pytest-subtests pytest-asyncio`; `pip check` PASS. Frontend: штатный `npm ci --no-audit --no-fund` по lockfile каждой ветки. `PATH` должен начинаться с venv/bin — один тест запускает `python3` в subprocess.

Команды запускаются из `customs-clear/backend`, `PYTHONPATH=.`; **каждый прогон использует отдельный временный файл SQLite через абсолютный `DATABASE_URL=sqlite:////.../run.sqlite`**. Production DB не использовалась. Штатный `init_db()` выполнял Alembic/seed только на этой временной БД. Tests могут менять tracked `data/tnved_preview_cache_revision.txt`; побочный timestamp восстановлен, в PR не включён.

| Проверка | Фактический результат |
|---|---|
| Исходный #244: payment_engine, payment_quote, source_admission, automatic operands, antidumping fixed unit, FX provenance, special duties, tariff preferences, duty parser, normalization, invoice/compare, unavailable exports | 142 passed +348 subtests; 12 failures — отсутствует seed стран |
| Те же 18 тестов `test_tariff_preferences.py` после штатного `python -m scripts.seed_tariff_preferences` в тестовой БД | 18 passed; все 12 исходных failures воспроизведены и на базе #244. Seed не является доказательством актуальности правовых данных |
| #244 источники: ingestion/payment coverage/import duty/VAT/excise/PP908/regulatory completeness/source sync/sync diagnostics/data refresh | После исправления окружения: 303 passed +76 subtests, 4 failures. Не хватает полной TNVED fixture для PP908 coverage; 3 проверки отсутствующего scheduled-data-refresh.yml. Эти failures воспроизведены на базе |
| Полный #244: `python offline_pytest.py tests -q --tb=short --junitxml=full.xml` | 1402 passed, 181 failed, 13 errors, 2 skipped, +478 subtests; **NOT PASS** |
| Полная база #244, та же среда и отдельная новая БД | 1169 passed, 158 failed, 166 errors, 2 skipped, +73 subtests; **NOT PASS** |
| Сравнение full suite | 191 общий failing/error test ID. 3 дополнительных у #244: calculator_compare/recycling non_vehicle ждут старый `OK`; quantity_affects_excise ждёт расчёт unitless fixed excise. Требуется обновить контрактные проверки с сохранением строгих утверждений, а не ослаблять их. Общие сбои включают fixtures/shared DB/data dependencies; это не 191 доказанный дефект кандидата |
| Новые регрессии до fix | 7 failures, 12 passed, 2 subtests passed |
| Исправленный **опубликованный SHA #255**: 7 платёжных модулей | 114 passed +352 subtests, exit 0 |
| Независимый native A5 `/root/a5_core244_review`, опубликованный SHA #255 | 65 passed +343 subtests; scoped PASS. На идентичном backend дополнительно 23 boundary assertions: даты включительно/истёкшие/будущие, страны, missing bounds, FX и invalid operands |
| HTTP smoke исправления | uvicorn на loopback, lifespan off, одноразовые локальные auth values; реальные curl POST compute и payments/quote: 2/2 PASS, unknown code удерживает итог. Первоначальный код 8509400000 на минимальной БД возвращал CLARIFICATION_NEEDED — корректная проверка leaf, не дефект расчёта |
| Frontend #244 и исправление #255 | TypeScript/build PASS. У исходного #244 нет Vitest набора; frontend unit PASS для него не заявляется |
| #245 `e39e19787bd913baeb6f85577a13e1116458e633`: все 13 изменённых backend test-модулей | 268 passed +44 subtests |
| #245 frontend | 18 tests passed; TypeScript/build PASS |
| Полный #245 | 1537 passed, 181 failed, 13 errors, 2 skipped, +120 subtests; **NOT PASS** |

Точная команда повторной проверки исправления #255:
```sh
python -m pytest tests/test_special_duties.py tests/test_payment_engine.py tests/test_payment_quote.py tests/test_payment_source_admission.py tests/test_automatic_duty_operand_validation.py tests/test_antidumping_fixed_unit_fail_closed.py tests/test_payment_fx_provenance_fail_closed.py -q --tb=short --junitxml=published.xml
```

Дополнительные точные команды завершённых прогонов (те же disposable SQLite / venv / PYTHONPATH):
```sh
# #244 sources, exit 1: 303 passed +76 subtests, 4 failures
python -m pytest tests/test_data_refresh.py tests/test_excise_ingestion.py tests/test_import_duty_ingestion.py tests/test_official_payment_coverage_audit.py tests/test_payment_data_coverage.py tests/test_payment_source_ingestion.py tests/test_pp908_vat_coverage.py tests/test_regulatory_source_completeness.py tests/test_source_sync_index_currentness.py tests/test_sync_status_diagnostics.py tests/test_vat_ingestion.py -q --tb=short
# #245 focused backend, exit 0: 268 passed +44 subtests
python -m pytest tests/test_assistant_copilot.py tests/test_assistant_payment_review.py tests/test_compliance_permit_parser.py tests/test_embedding_service_safety.py tests/test_grounded_assistant.py tests/test_non_tariff_data_freshness.py tests/test_normative_requirements_block.py tests/test_ntm_child_product_markers.py tests/test_ntm_sgr_bad_token_boundary.py tests/test_ntm_trigger_food_contact.py tests/test_regulatory_ai_classifier.py tests/test_regulatory_keyword_token_boundaries.py tests/test_smart_tnved_search.py -q --tb=short
# Из customs-clear/frontend каждой ветки; exit 0
npm ci --no-audit --no-fund
npm run typecheck
npm run build
# Только #245, где существует штатный Vitest script; exit 0, 18 passed
npm test
```

Полный диагностический runner `offline_pytest.py` не менял тесты: удалял из окружения ANTHROPIC_API_KEY/OPENAI_API_KEY/GEMINI_API_KEY/GOOGLE_API_KEY, ставил Python audit hook на `socket.connect` (разрешал только localhost/127.0.0.1/::1, иначе RuntimeError OFFLINE_TEST_GUARD) и вызывал `pytest.main(sys.argv[1:])`. Ограничение времени 240 секунд; все три full-прогона завершились самостоятельно за 73–104 секунды. Это локальная диагностика; сетевые/живые провайдерные проверки не подтверждены.

CI #255: [offline-safety PASS, run 37771953943](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37771953943), job 113293439909. Это инфраструктурный CI и **не** замена продуктовым тестам выше. Full product CI на GitHub пока отсутствует.

### Незакрытые выводы / следующий конкретный шаг

1. Исправить подтверждённый **унаследованный** legacy fallback: `_parse_duty_rate` отдаёт `specific_eur`/`rule`, а `_find_duty_rule_for_hs` читает `specific_amount`/currency/uom. Для `2 евро/кг` возвращается 0; MAX/ADD теряют специфическую часть. Нужны persisted-row регрессии с подтверждёнными FX/единицами; не выводить единицы из предположений.
2. Производитель/описание товара в строках спецмер не сопоставляются со входом. Пока нет подтверждения совпадения, нельзя выдавать автоматическую применимость. Сначала воспроизводитель и существующий источник/контракт, без новой юридической интерпретации.
3. Разобрать isolated fixtures/full-suite failures и три устаревших контрактных теста; сохранить исходные выводы, не скрывать failures через skip/deselect.
4. Проверки #245 подтверждают технические ограничения AI/UI и тестовый набор, **не** полноту нетарифки или юридическую применимость.
5. Существующий A6 request `core-s1-6415f443120f-r9-g106` не пересоздан, не отправлен и не повторён. Его прежние результаты не переносятся на #255.

Удалённый Git transport не имеет write credentials (`could not read Username`), это **не security refusal**. Публикация выполнена существующим GitHub connector: 3 blobs -> tree с проверкой полного совпадения -> commit -> agent branch -> draft PR. Ни ключей, ни токенов у владельца не запрашивалось.

Состояние сохранялось под штатно приобретённым CAS lease generation 108, holder `/root/tariff_product_cycle_20261008`; перед продолжением перечитать live lease. Основной чат владельца не менялся; канал доставки туда не установлен.

### Проверка расписания — история до подтверждённого результата выше

На 2026-10-08T11:54Z обнаружено существующее часовое расписание разработчика `6ac775d0feac8191abc1e60865ce1461` («Tariff — разработка»), **disabled**, last_run 10:55:48Z. Точный результат того запуска через доступное чтение не получен. Существующий включённый «Tariff — контроль остановок» `6ac775fd994c8191aea0165bc66b38b1` — read-only наблюдатель, не исполнитель и не координатор; он не заменяет разработку. Дублирующие задачи не созданы.

**Фактическая проверка:** после release generation108 в 11:55:59Z существующая задача была возобновлена с обязательным capability gate; единственный `automations.run_now` принят в 11:56Z. К 12:00Z новый результат не получен: `last_run_time` остался 10:55:48Z, `next_run_time=null`, нового checkpoint/lease исполнителя нет. Это **UNKNOWN / не подтверждённый запуск**, не доказанный CAPABILITY_BLOCKED и не успешная автономная разработка. API Automations не предоставляет чтение журнала запуска; Personal Context не нашёл этот разговор. Прямое открытие возвращённого conversation_id в ChatGPT показало sign-in wall. Требуется безопасный вход для чтения результата, без передачи паролей/токенов в чат.

В 12:00:12Z **повторения явно приостановлены** (`is_enabled=false`) до проверки результата; пользователю причина сообщена. Это не доказательство отмены уже принятого асинхронного запуска. Задача контроля остановок не менялась; новых задач/мониторов не создано. Дальнейшее включение допускается только после подтверждения полноценной среды исполнения и фактического тестового checkpoint. Обычная интерактивная разработка в текущей среде работоспособна и этой проверкой не заблокирована.

Продуктовый checkpoint сохранён commit `3a118f2bc37862673858f6285f6fb600ce861893`, затем дополнен записью о расписании; release108 commit `76fb75fed24c86cbd962ed99e6c3e01d009a59c9`, [state safety PASS run37773352840](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37773352840). Для сохранения результата проверки расписания штатно получен lease generation109, который освобождается сразу после записи. Перед продолжением читать live lease.

## 1. Восстановление инфраструктуры — PR #254

- [PR #254](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/254) — `fix(agents): verified recovery and preflight`; **MERGED 2026-10-08T10:45:47Z**; рабочая ветка `review/tariff-recovery-20261008`.
- Проверенный final candidate HEAD: `957702311efd8d29c0ff18c58bcd3b523b7fcd77`, base `main` `c29015e9c25232e07d06bc3869abc45db3b066a2`. Текущий live `main`: `e526dfbdb5a31b01bf6f743da0288b88f916de0c` — подтверждённый merge #254. Старые записи draft/ожидания разрешения ниже относятся только к истории.
- 14 инфраструктурных файлов: восстановление preflight, A6 structured-safety/receipts, recovery-status, CLI, required verifier, CI, runbook и тесты. В `test_audit_bridge.py` в двух disposable Git-fixtures отключены `maintenance.auto` и `gc.auto` — устранён race `tearDown` на Git 2.55; строгая очистка не подавлена.
- Независимый **whole-PR** Codex review на прежнем SHA `6031c4a8...` подтвердил P2: default `publication_policy=unknown` скрывал существующий A6 owner gate в `task_owner_action_required`. См. [finding](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/254#discussion_r4217405436).
- На текущем SHA `957702311e...` `recovery_status` теперь учитывает `observed["owner_action_required"]`; отдельный регрессионный тест внесён в `test_operations.py`. Новый [независимый Codex re-review](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/254#issuecomment-6057912061) завершён **без major issues** именно на `957702311e...`. Исторический P2 review thread закрыт после независимой воспроизводимости и проверки исправления. Не представлять это как формальное GitHub `APPROVED` от человека: Codex оставил advisory review.
- [Exact-head GitHub CI PASS, run 37763266913](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37763266913), job `113264825797`: `offline-safety`, проверка тестов и committed snapshot PASS. Независимый локальный replay A0 восстановил Git blobs текущих `operations.py`, `test_operations.py`, `test_audit_bridge.py` и запустил required verifier **225/225 PASS** и полный orchestration **225/225 PASS** с socket guard, **0 network attempts**; Python 3.13 / Git 2.47 локально, Git 2.55 на Actions. Это не product-suite и не запуск A6.
- Merge #254 уже выполнен владельцем; не повторять разработку, merge или запрос разрешения. В этой сессии защищённых действий не было.

## 2. Product candidates — НЕ приняты окончательно

| Приоритет | PR, candidate SHA | Зафиксированные доказательства и открытые ограничения |
|---|---|---|
| Ставки, преференции, специальные пошлины, расчёт и источники | [#244](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/244), `14e0ee8f034d94ffc5831d87e076f4d693a5a524` | draft; base `integration/customs-core-v1` `08e030a...`, 34 файла. Ранее заявлен A5 PASS; расчётный semantic harness 47/47. Exact-head [run 36853205641](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/36853205641) PASS, но это **Tariff agent safety**, не полный product/backend CI. Полная backend регрессия, обязательные официальные данные и юридическая применимость не доказаны; A6 LIVE PASS отсутствует. |
| NTM, документы, код ТН ВЭД, поиск, AI | [#245](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/245), `e39e19787bd913baeb6f85577a13e1116458e633` | draft; base `integration/compliance-ai-v1` `08e030a...`, 43 файла. Ранее заявлен A5 PASS после child-negation fix; focused backend 268 + 44 subtests, frontend 18/18 и build (см. тело PR). Exact-head [run 36853210034](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/36853210034) PASS, но workflow тоже только **Tariff agent safety**. Полная broad backend и end-to-end нормативная/юридическая приёмка не подтверждены; A6 LIVE PASS отсутствует. |

До работы над #244/#245: сверить HEAD/base/состав файлов/required checks, внимательно прочитать их текущие PR body и source-task lineage; не наследовать review/CI после изменения SHA. Проверить реальные сценарии, API/DB схемы, даты действия и версии нормативных источников. Эвристики и AI-подсказки — advisory, не юридический факт.

## 3. A6 — отдельный запрещённый пока внешний шаг

- Авторитетный файл: `.ai/orchestration/A6_LIVE_STATUS.json` **только** на `agent/orchestration-state`.
- Уже подготовлен, **не отправлен/не израсходован** immutable request `core-s1-6415f443120f-r9-g106`; packet SHA256 `e2a0d35aaae76d4a8fa0c74d4fe7d83d609371d75b7ef7eced1484890d1f22b8`; canonical serialization SHA256 `349339f5393176b83d02fea8965783b6237b0259110d835fff5bd55ec1886f89`; 8 tracked paths, 392515 bytes, 0 official URLs; lease generation **106** binds its request identity. Не пересоздавать и не делать retry.
- Для внешней передачи приватного кода Anthropic/A6 требуется **отдельное точное согласие владельца** на этот request/packet через предусмотренный trusted bridge. Разрешение merge PR #254 **не** разрешает A6. Даже live ответ A6 не заменяет проверку A0.

## 4. Следующие технические шаги

1. Продолжить платёжный блок от live draft [#255](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/255) `7c12f21787b1d557630d8b0737c769b326ab112d`: legacy specific/combined fallback и fail-closed manufacturer/product scope уже исправлены; exact-head [CI 37921716308](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37921716308) успешен. Следующая задача — source-by-source refresh шести stale payment bundles из retained primary-source snapshots, immutable ETT binding и оставшаяся broad-fixture/source-completeness evidence. Не фабриковать snapshots, не запускать/не пересобирать A6.
2. Main уже обновлён merge #254. Перед следующей удалённой записью приобрести coordinator lease через **current trusted main** `tools/tariff_agents/lease.py` и GitHub CAS; перечитать holder/token/TTL. На реальных непроизводственных сценариях проверять: recovery state/board, создание -> allocation -> implementation -> independent QA -> CI, зависание и освобождение, корректную диагностику и доказанную видимость уведомления. Не имитировать child session IDs, A5/A6, delivery receipts. Нет доступа к native Work executor — пометить unavailable.
3. #244: воспроизвести полный backend/CI по ставкам, FX, НДС, акцизам, спецпошлинам и преференциям с реальными source versions/effective dates, unknown/fail-closed, сформировать и протестировать payment quote end-to-end без production writes; независимый A5 текущего SHA.
4. #245: проверка применимости ТР, СС/ДС/СГР, лицензий, нотификаций, маркировки и исключений по кодам и свойствам, source/provenance и confidence; самостоятельная полнота нормативного набора и full backend+frontend; independent A5. Не включать SGR enforcement без отдельного решения.
5. Далее A3: реестр **официальных** документов, версии, даты вступления, полнота и обновления; A4: классификация/семантика/AI grounded-only; интеграция пользовательского сценария описание -> код -> ставки/платежи -> документы/доказательства.
6. По каждому готовому блоку: commit-bound A5 -> обязательные CI -> A6 **только когда разрешено и требуется** -> owner decision. Любой новый HEAD обнуляет прежнее «готово» для этого exact SHA.

## 5. Сроки / риски

Предыдущие ориентиры: **9 октября** — платёжный кандидат; **23 октября** — NTM; **30 октября** — официальные источники; **10 ноября** — RC1; **17 ноября** — целевая v1.0. На 8 октября платёжный draft уже существует, но **его окончательная приёмка к 9 октября под риском**: нет полного подтверждённого product backend/источников/A6-gate. Отсутствует подтверждение для обещания v1.0 по нормативной полноте. Перепланировать только по новой фактической evidence и явно отмечать gate.

## 6. Authority, безопасность, продолжение из другого чата

- A0 — один координатор; не порождать второй A0, не дублировать executor/automations. Рабочее состояние в GitHub, не в чате. Подтверждён один реальный асинхронный цикл разработчика; существующее часовое расписание возобновлено. Включённый read-only контроль остановок не является вторым координатором. См. точные доказательства и ограничения проверки расписания выше.
- **Перед любым remote write:** `main` `AGENTS.md`, `.ai/orchestration/CONTRACT.md`; state `.ai/orchestration/RUNBOOK.md`, `.ai/TASK_PROTOCOL.md`, `.ai/TASK_BOARD.json`, `.ai/COORDINATOR_LEASE.json`, `.ai/orchestration/A6_LIVE_STATUS.json`. Запрашивать lease актуальным helper; CAS на текущем blob SHA; reread holder/token; каждый существенный write проверять. Не обходить платформенный security refusal. Отдельно в журнале: предыдущая блокировка записи lease была устранена **только для штатного CAS acquisition generation 107 2026-10-08**; это не доказывает общий доступ без ограничений. При потере lease прекратить write.
- Во время перепроверки внешний сеанс внёс 2 коммита в PR #254 с исправлением P2; A0 здесь **не отправлял дублирующий патч**. При новом внешнем движении branch немедленно reconcile HEAD и избежать пересекающихся записей. Все дополнительные findings проверять самостоятельно, не признавать review автоматически.
- Никогда без Ivan: merge защищённых веток, production deploy/DB/migrations, enforcement flags, изменение credentials/permissions/secrets, удаление/force push, A6 export. Никакой доставки в основной пользовательский чат не подтверждено.
- Статус блоков честно разделять: **сделано / сейчас / осталось / что нужно от владельца**. Прогресс доказан конкретным SHA, CI job, A5 и diff, не «агент запущен».
## 2026-10-14 — Rate-display database isolation completed on draft PR #259

- Cycle 238 published an initial isolated `test_rate_display.py` fixture but lacked executable author/A5 evidence. Fresh independent A5 `/root/a5_cycle239` rejected that exact head because table-create/seed failures leaked the engine and a cleanup failure could mask the primary test error.
- Draft [PR #259](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/259) now publishes exact head `17636c0a78936d6d06cb19b97cc684b6c39ffdc9`, tree `7c182ff9bcac2ba453be16b4b39e3c3877e50296`; local author commit `f3125852e0fa9b68108b70fe3ef39841fa71774d` has the exact same tree. Only `customs-clear/backend/tests/test_rate_display.py` changed; its three original test functions are AST-identical.
- The fixture now guarantees cleanup during table creation, seed, body and teardown failures, attempts every cleanup step, restores both `SessionLocal` bindings even when patch undo fails, and preserves the original primary exception while annotating cleanup failures.
- Author/A0: focused **3 passed**, adjacent rate/payment/normative suite **56 passed** in both orders, all exit 0. Fresh A5 `/root/a5_cycle239b`: **PASS, no findings**; all setup/body/undo/close/dispose fault injections, AST parity and no-ambient-DB checks passed.
- Exact-head CI [run 38514368199 / job 115689724755](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38514368199/job/115689724755): **success** (`offline-safety`).
- A diagnostic broad command excluding only the lawful-snapshot NTM test and three absent-workflow assertions advanced to **1,884 passed, 11 skipped, 3 deselected + 133 subtests**. It then found the next independent ambient-DB defect at teardown after `tests/test_vision_integration.py::test_xlsx_conflict_text_vs_photo_prioritizes_visual`; the DB/WAL/SHM artifacts were moved recoverably to `/tmp`.
- NTM-3/full-sync remains blocked by the unavailable lawful populated synchronized snapshot; full #245 acceptance and legal/source completeness remain NOT PASS. A6 `core-s1-6415f443120f-r9-g106` remains unchanged and undispatched. No merge, deploy, production write, enforcement/flag, secret/permission or destructive action was performed.

## 2026-10-14 — NTM v2 advisory database isolation completed on draft PR #259

- Fresh broad instrumentation showed that the prior teardown observation after `test_vision_integration.py` was not the writer. The first exact writer was `tests/test_ntm_v2_advisory_requirements.py::test_advisory_present_for_matrix_cases[8517120000-…]` after 309 preceding assertions passed.
- Root cause was import-order dependent: `sanctions_risk_block` copies `SessionLocal` at module import. The advisory fixture patched `app.db.SessionLocal` but not that already imported alias, so the test opened ambient `customs.db`; a standalone run hid the defect because the module imported after the in-memory patch.
- Draft [PR #259](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/259) now publishes exact head `363fc1b14e1ee4e98092360be8c2772173e21b9b`, tree `9a3d58959114dc261812581661b43d594f5cee80`; local author commit `71cba6052b0d03c8e1e082b11676509a67fa948a` has the exact same tree. Only `customs-clear/backend/tests/test_ntm_v2_advisory_requirements.py` changed; product and normative data did not.
- The fixture binds `sanctions_risk_block.SessionLocal` to the same in-memory factory, asserts the alias identity, and disposes the engine in `finally`.
- Author/A0: focused **11 passed**, ordered predecessor/advisory tranche **319 passed**, all exit 0; `customs.db`, WAL and SHM were absent before and after. Fresh independent A5 `/root/a5_240`: **PASS, no findings**; focused **11 passed** and preimport-order control **23 passed**, exit 0.
- Exact-head CI [run 38520191329 / job 115707884776](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38520191329/job/115707884776): **success** (`offline-safety`).
- Next: rerun the broader backend diagnostic on this exact head and separate the three earlier dependency-sensitive failures from the next actual ambient writer. NTM full-sync remains blocked without a lawful populated synchronized snapshot; full #245 and legal/source completeness remain NOT PASS. A6 is unchanged and undispatched; no protected action was performed.
## 2026-10-14 — NTM v2 measures-enforcement database isolation completed on draft PR #259

- The guarded broad run on exact PR #259 parent `363fc1b14e1ee4e98092360be8c2772173e21b9b` reached `tests/test_ntm_v2_measures_enforcement.py::test_enforcement_adds_vs` at 55% and found a 4,096-byte ambient `customs.db` plus WAL/SHM. Fresh A5 confirmed the parent order could pass **22 tests** yet still create the database: `sanctions_risk_block.SessionLocal` retained the default copied alias.
- Draft [PR #259](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/259) now publishes exact head `0a234073ca8d46f48a0889df6e9ee0721c77c431`, tree `e07d4d733c7a794366d2dedd25f9aa6db87f403c`; local author commit `4c2e79d67c3ef065759d606746921a8cac2069c2` has the exact same tree. Only `customs-clear/backend/tests/test_ntm_v2_measures_enforcement.py` changed; product code and normative data did not.
- The fixture now rebinds the pre-imported sanctions alias to the in-memory sessionmaker, disposes the engine in `finally`, and includes an explicit alias regression assertion. Author: focused **12 passed** and advisory→enforcement **23 passed**, exit 0. Independent A5 `/root/a5_241`: **PASS, no findings**; focused **12 passed**, both module orders **23 passed** each, parent reproduction and absent DB/WAL/SHM verified.
- Exact-head CI [run 38526371444 / job 115727571845](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38526371444/job/115727571845): **success** (`offline-safety`).
- The repaired guarded broad run advanced past measures enforcement and reproduced the next distinct leak at `tests/test_ntm_v2_official_sgr_advisory.py::test_official_advisory_flag_off_no_official_source`; the ambient files were moved recoverably to `/tmp`. This remains the next bounded repair.
- NTM-3/full-sync remains blocked by the unavailable lawful populated synchronized snapshot. Full #245 acceptance and legal/source completeness remain NOT PASS. A6 `core-s1-6415f443120f-r9-g106` is unchanged and undispatched. No merge, deploy, production write, enforcement/flag, secret/permission or destructive action was performed.

## 2026-10-14 — Official SGR advisory database isolation completed on draft PR #259

- Exact parent `0a234073ca8d46f48a0889df6e9ee0721c77c431` passed the two adjacent modules (**24 passed**) but created a 4,096-byte ambient `customs.db`; the copied `sanctions_risk_block.SessionLocal` alias was not rebound by the in-memory fixture.
- Draft [PR #259](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/259) now publishes exact head `09b883d78ad3e269587e35c1d95dfef7f4cd6c7c`, tree `f328588388cf48416af9e5cbd5b056ff304e3ee8`; local author commit `b5a9e730532cd192211333f75f154490ece85291` has the exact same tree. Only `customs-clear/backend/tests/test_ntm_v2_official_sgr_advisory.py` changed; product code and normative data did not.
- The fixture now binds the pre-imported sanctions alias to the in-memory sessionmaker, asserts that identity and disposes its engine in `finally`. Author: focused **14 passed** and both adjacent module orders **25 passed** each, all exit 0, with no DB/WAL/SHM.
- Fresh independent A5 `/root/a5_242`: **PASS, no findings**; exact tree, one-file scope, diff check, focused **14 passed**, both orders **25 passed** and absent DB/WAL/SHM verified.
- Exact-head CI [run 38532176582 / job 115746378297](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38532176582/job/115746378297): **success** (`offline-safety`).
- The guarded broad run advanced to 59% and reproduced the next independent leak at `tests/test_ntm_v2_official_sgr_import.py::test_official_not_in_production_broker`; ambient DB/WAL/SHM were moved recoverably to `/tmp`. This is the next bounded repair.
- NTM full-sync remains blocked without a lawful populated synchronized snapshot; full #245 acceptance and legal/source completeness remain NOT PASS. A6 `core-s1-6415f443120f-r9-g106` is unchanged and undispatched. No protected action was performed.

## 2026-10-14 — Official SGR import database isolation completed on draft PR #259

- Exact parent `09b883d78ad3e269587e35c1d95dfef7f4cd6c7c` passed the advisory→import order (**38 passed**) but created a 4,096-byte ambient `customs.db`; the import fixture did not rebind the copied `sanctions_risk_block.SessionLocal` alias.
- Draft [PR #259](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/259) now publishes exact head `29ea26fda41e241da495435bba03c74a1dd57c80`, tree `fa00d093ef709a06113f65bde84691970c436b52`; local author commit `1cf4bb5a6eb5631db685df57309a2ba895f2ab35` has the exact same tree. Only `customs-clear/backend/tests/test_ntm_v2_official_sgr_import.py` changed.
- The fixture now binds the pre-imported sanctions alias to the in-memory sessionmaker, asserts alias identity and disposes its engine in `finally`. Author: focused **25 passed** and both adjacent module orders **39 passed** each, all exit 0, with no DB/WAL/SHM.
- Fresh independent A5 `/root/a5_243`: **PASS, no findings**; exact tree, one-file scope, diff check, alias/teardown review, focused **25 passed**, both orders **39 passed** and absent DB/WAL/SHM verified.
- Exact-head CI [run 38538222812 / job 115766255270](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38538222812/job/115766255270): **success** (`offline-safety`).
- The guarded broad run advanced to 62% and reproduced the next independent leak at `tests/test_ntm_v2_rules_enforcement.py::test_enforcement_off_unchanged_baseline`; ambient DB/WAL/SHM were moved recoverably to `/tmp`. This is the next bounded repair.
- NTM full-sync remains blocked without a lawful populated synchronized snapshot; full #245 acceptance and legal/source completeness remain NOT PASS. A6 `core-s1-6415f443120f-r9-g106` is unchanged and undispatched. No protected action was performed.

## 2026-10-14 — NTM v2 rules-enforcement database isolation completed on draft PR #259

- Exact parent `29ea26fda41e241da495435bba03c74a1dd57c80` passed the pipeline-flag→rules-enforcement order (**86 passed**) but created a 4,096-byte ambient `customs.db`; the rules fixture did not rebind the copied `sanctions_risk_block.SessionLocal` alias.
- Draft [PR #259](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/259) now publishes exact head `146c7efe9c8a7832da9a60e6d834d05fff35a54a`, tree `263388053892c31ffd5dff8e631e78bf8c7a5e91`; local author commit `8a099fe85164ceea3f918b0ca31330db22acf839` has the exact same tree. Only `customs-clear/backend/tests/test_ntm_v2_rules_enforcement.py` changed.
- The fixture now binds the pre-imported sanctions alias to the in-memory sessionmaker, asserts alias identity and disposes its engine in `finally`. Author: focused **14 passed**, isolated baseline **1 passed**, predecessor-first **86 passed**, all exit 0, with no DB/WAL/SHM.
- Fresh independent A5 `/root/a5_244`: **PASS, no findings**; exact tree, one-file scope, diff check, alias/teardown review, the same **14/1/86** executions and absent DB/WAL/SHM verified.
- Exact-head CI [run 38546658998 / job 115794263031](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38546658998/job/115794263031): **success** (`offline-safety`).
- The guarded broad run advanced to 81% and reproduced the next independent writer at `tests/test_regulatory_mass_seed.py::TestMassRegulatoryDocuments::test_total_documents_exceeds_5000`; exact ambient DB/WAL/SHM were moved recoverably to `/tmp`. This is the next bounded repair.
- NTM full-sync remains blocked without a lawful populated synchronized snapshot; full #245 acceptance and legal/source completeness remain NOT PASS. A6 `core-s1-6415f443120f-r9-g106` is unchanged and undispatched. No merge, deploy, production write, enforcement/flag, secret/permission or destructive action was performed.

## 2026-10-14 — Source-import callable isolation completed on draft PR #259

- The guarded full backend order on parent `8b1f5be35756a5eac7e2bc953727b7d8b16e5e8f` reached `SourceImportTests.test_import_xlsx_with_headers` at 88%; assertions passed, but teardown found ambient `customs.db`/WAL/SHM and the guard exited 1. Standalone execution hid the collection-order defect.
- Root cause: earlier API fixtures can unload and re-import application modules while pytest retains collection-time source-import callables. Patching named modules therefore missed the database globals of copied functions.
- Draft [PR #259](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/259) now publishes exact head `45222b38c334f4cb08b5b666206897d950552f03`, tree `edbaf0ee7b6410bbddaee468a994e780d81d3065`; local author commit `4a526da2776d907feec6bf5a438b331f1211e249` has the exact same tree. Only `customs-clear/backend/tests/test_source_import.py` changed; all three original test methods are AST-equivalent.
- The fixture patches the exact collected callables' `SessionLocal`/`engine` globals and creates only `HsRate`/`SourceStatus` tables required by the unchanged scenarios instead of invoking broad `init_db`.
- Author: focused **3 passed**, exit 0; exact guarded backend **1,889 passed, 11 skipped, 3 deselected + 133 subtests**, exit 0, without ambient DB/WAL/SHM. Fresh independent A5 `/root/a5_cycle247`: **PASS, no findings**; stale/re-import identity, setup-failure cleanup, AST parity and no-ambient controls passed.
- Exact-head CI [run 38562659003 / job 115847344018](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38562659003/job/115847344018): **success** (`offline-safety`).
- The ambient-database guarded contour now completes. Next: recover current PR #256/#245 exact head and resume bounded backend/frontend NTM applicability and grounded AI/UI acceptance. NTM full-sync remains blocked without a lawful populated synchronized snapshot; full #245 and legal/source completeness remain NOT PASS. A6 is unchanged and undispatched; no protected action was performed.

## 2026-10-14 — Regulatory mass-seed absent-database isolation completed on draft PR #259

- Cycle245 had already published a bounded 12-addition candidate but explicitly lacked executable backend and independent A5 evidence. Cycle246 recovered and validated that unchanged exact candidate rather than duplicating or replacing it.
- Draft [PR #259](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/259) remains at exact head `8b1f5be35756a5eac7e2bc953727b7d8b16e5e8f`, tree `3603d4f521068effd448744962a3ebda8dd86c26`. Only `customs-clear/backend/tests/test_regulatory_mass_seed.py` changed.
- The module now skips before SQLAlchemy inspection only when the configured file-backed SQLite path is absent. This prevents creating ambient `customs.db`; existing empty, partial and populated databases still reach the original table/count/coverage checks.
- Native author validation `/root/author246`: focused absent-default **9 skipped**, predecessor-first **14 passed + 9 skipped**, all exit 0, no DB/WAL/SHM. Nonexistent absolute and relative SQLite files were not created. A partial schema produced expected **7 failed + 2 passed**, exit 1, proving the coverage thresholds were not hidden.
- Fresh independent A5 `/root/a5_246`: **PASS, no findings** on exact tree, including the same absent/empty/partial path controls and no-test-weakening review.
- Exact-head CI [run 38549024897 / job 115802136715](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38549024897/job/115802136715): **success** (`offline-safety`).
- The guarded broad run advanced to 88% and reproduced the next independent writer at `tests/test_source_import.py::SourceImportTests::test_import_xlsx_with_headers`; exact ambient DB/WAL/SHM were moved recoverably to `/tmp`. This is the next bounded repair.
- NTM full-sync remains blocked without a lawful populated synchronized snapshot; full #245 acceptance and legal/source completeness remain NOT PASS. A6 `core-s1-6415f443120f-r9-g106` is unchanged and undispatched. No merge, deploy, production write, enforcement/flag, secret/permission or destructive action was performed.

## 2026-10-14 — PR #256 grounded assistant, search and NTM UI bounded acceptance

- Recovered current draft [PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256) at unchanged exact head `3c24676a69b1d78d320bd5764fb04f5ac3f3430d`, tree `a4e3cd52d0133698e5da905f0e48c52a087316b3`. The worktree remained clean; no product or test files changed.
- A0 backend acceptance command covered grounded assistant, assistant API flows, NTM applicability, normative requirements, TN VED search/catalog/FTS and SGR status: **220 passed + 51 subtests**, exit 0.
- A0 frontend full suite: `npm test && npm run typecheck && npm run build` — **109 passed**, typecheck PASS and production build PASS, exit 0. Non-blocking build warnings remain for Browserslist age, a large bundle and a legacy print selector.
- Fresh independent A5 `/root/a5_cycle248`: **PASS, no findings**. Independent backend selection passed **276 + 44 subtests**; frontend again passed **109**, typecheck and build. It confirmed executable coverage for citation allowlisting/fallback, no-grounding without usable evidence, manual-review/advisory boundaries, freshness and safe source-link surfaces.
- Existing exact-head CI [run 38476052793](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38476052793) is **success** for this unchanged HEAD (`offline-safety` only). Executable A0/A5 runs provide the product-test evidence.
- This closes only the bounded technical acceptance slice. Full #245 acceptance and legal/source completeness remain NOT PASS. NTM full-sync is still blocked without a lawful populated synchronized snapshot. A6 `core-s1-6415f443120f-r9-g106` remains unchanged and undispatched; no protected action was performed.
- Next: select the next real PR256/#245 search/classification or assistant integration defect from executable behavior, preserving fail-closed provenance and manual review for unsupported applicability.

## 2026-10-14 — Smart-classifier remote-image boundary hardened on draft PR #256

- On exact parent `3c24676a69b1d78d320bd5764fb04f5ac3f3430d`, a private loopback image URL reached the HTTP client; failed raw image URLs could also enter the model prompt. This was a reproducible SSRF/provenance boundary defect, not a legal interpretation.
- Draft [PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256) now publishes exact head `b30a81f6ea878b8cabfc78639b7c9bcf203ea2f9`, tree `917cbeece299b5b7058056d90d66026bf94f60d4`; local author commit `0e482110c2d2bf50afb927038bd449e2e2e8f3f4` has the same tree. Only `smart_classifier.py` and `test_smart_classifier.py` changed.
- Remote image fetching now accepts only public http(s) destinations, validates every DNS answer and redirect, pins the validated address while preserving Host/SNI, limits redirects and streamed bytes to 10 MiB, requires image content, keeps raw URLs out of prompts and never substitutes text-only model guesses for visual evidence. Unavailable image-only input returns deterministic `ERROR`; text plus unavailable image requires manual review and withholds recommendations.
- A0 exact command passed **41 tests + 23 subtests**, exit 0; compileall and diff check also exited 0. Fresh independent A5 `/root/a5_cycle249`: **PASS, no findings** after focused, adjacent, packing, parser/chain and 22-check no-network adversarial executions, all exit 0.
- Exact-head CI [run 38570657548 / job 115874683335](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38570657548/job/115874683335): **success** (`offline-safety`). PR receipt comment id `6169318937` records the candidate and checks.
- Full PR #245 product acceptance and legal/source completeness remain NOT PASS. NTM full-sync remains blocked without a lawful populated synchronized snapshot. A parent-existing mixed collection/import mock failure remains separate. A6 `core-s1-6415f443120f-r9-g106` is unchanged and undispatched; no protected action was performed.

## 2026-10-14 — Smart-classifier image-byte validation completed on draft PR #256

- Exact parent `b30a81f6ea878b8cabfc78639b7c9bcf203ea2f9` accepted local HTML/SVG/invalid base64 as image evidence, allowed grouped packing to lose the failed-image signal, and forwarded remote HTML bytes declared as `image/png` to the vision provider.
- Draft [PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256) now publishes exact head `d68b1f848ef7c1de24c208f4ad5e5f96ee9a0083`, tree `20a12b23180cd19d8c0e4ffa2988ffb2f0b749ae`; local author commit `517df5e6ad1a3ee3348f2ae84fa6583a0d5b6b9f` has the same tree. Only `smart_classifier.py` and `test_smart_classifier.py` changed.
- Local and remote images now require decoded JPEG/PNG/GIF/WebP byte signatures. Bare base64 type is detected from bytes; declared MIME must match. Malformed, empty, non-raster, mismatched and oversized images fail before provider use. Grouped packing keeps fresh/cached results at manual review with `recommended=false` when image evidence is unavailable.
- A0 exact adjacent command passed **55 tests + 53 subtests**, exit 0; adversarial local/group control, compileall and diff-check also exited 0.
- Fresh independent A5 `/root/a5_cycle249` rejected two earlier candidates, then returned **PASS, no findings** on the final tree. Focused **47 + 53 subtests**, adjacent **55 + 53 subtests**, parser/direct packing and local/remote adversarial matrices all exited 0.
- Exact-head CI [run 38578532619 / job 115901949956](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38578532619/job/115901949956): **success** (`offline-safety`). PR receipt comment id `6170414985` records the candidate and checks.
- Full PR #245 product/legal/source acceptance remains NOT PASS. NTM full-sync remains blocked without a lawful populated synchronized snapshot. A6 `core-s1-6415f443120f-r9-g106` is unchanged and undispatched; no protected action was performed.

## 2026-10-14 — Smart-classifier complete raster integrity enforced on draft PR #256

- Exact parent `d68b1f848ef7c1de24c208f4ad5e5f96ee9a0083` accepted signature-only JPEG, PNG, GIF and WebP garbage as image evidence.
- Draft [PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256) now publishes exact head `4a53e88108a03b5002aa28887154bbc10a2b3d8e`, tree `1be6787e834e4ca17f08e947f49f42eab8a40304`; local author commit `1cad369d88206b132b09f250687eb74d6da5978b` has the exact same tree. Only `smart_classifier.py` and `test_smart_classifier.py` changed.
- Local and remote images now require canonical JPEG/PNG/GIF/WebP boundaries, matching decoded format, valid PNG/APNG chunk CRCs, Pillow structural verification and decoding of every reported frame. Truncation, duplicate-terminator polyglots, corrupted later frames, decompression bombs and excessive frame counts fail before provider use. Manual-review, `recommended=false` and SSRF behavior remain fail closed.
- A0 exact adjacent command passed **64 tests + 71 subtests**, exit 0; progressive/EXIF/static compatibility and appended-payload probe passed 10 checks; compileall and diff-check exited 0.
- Fresh independent A5 `/root/a5_cycle251` rejected two earlier candidates (`fd9241b`, `d8c1326`) for confirmed integrity gaps, then returned **PASS, no findings** on the final tree. Fresh adjacent execution passed **64 + 71 subtests**; independent adversarial matrix passed **35 checks**; scope, tree and clean worktree were verified.
- Exact-head CI [run 38587572055 / job 115933542721](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38587572055/job/115933542721): **success** (`offline-safety`). PR receipt comment id `6171665986` records the candidate and checks.
- Full PR #245 product/legal/source acceptance remains NOT PASS. NTM full-sync remains blocked without a lawful populated synchronized snapshot. A6 `core-s1-6415f443120f-r9-g106` remains unchanged and undispatched; no protected action was performed.

## 2026-10-14 — Smart-classifier image-evidence cache integrity completed on draft PR #256

- Exact parent `4a53e88108a03b5002aa28887154bbc10a2b3d8e` reused the first image's visual analysis and derived classification when a later valid but different image had the same packing-group key.
- Draft [PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256) now publishes exact head `af5dc3c09294aa4223205ee01aebc008fa0a396f`, tree `946dc680d0cc35d04a26bb2d684bcda65a5f6366`; local author commit `18927166a2a841046e8e4f26c77313ff77f96f81` has the exact same tree. Only `smart_classifier.py` and `test_smart_classifier.py` changed.
- Vision and classification caches are now bound to canonical validated image evidence and all classification inputs. Failed-image identity survives delayed, concurrent and same-task interleavings, so invalid evidence remains `MANUAL_REVIEW` with `recommended=false` even if a sibling valid request succeeds.
- A0 exact adjacent command passed **70 tests + 71 subtests**, exit 0; py_compile, diff-check and exact scope exited 0.
- Fresh independent A5 `/root/a5_cycle252` rejected three intermediate candidates after reproducing separate stale-cache/fail-open races, then returned **PASS, no findings** on the final tree. Final adjacent execution passed **70 + 71 subtests**; independent adversarial matrix passed **11/11** and packing-list controls passed **4/4**, all exit 0.
- Exact-head CI [run 38596656746 / job 115965012426](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38596656746/job/115965012426): **success** (`offline-safety`). PR receipt comment id `6172924322` records the candidate and checks.
- Full PR #245 product/legal/source acceptance remains NOT PASS. NTM full-sync remains blocked without a lawful populated synchronized snapshot. A6 `core-s1-6415f443120f-r9-g106` remains unchanged and undispatched; no protected action was performed.

## 2026-10-14 — Smart-classifier transient error cache recovery completed on draft PR #256

- Exact parent `af5dc3c09294aa4223205ee01aebc008fa0a396f` cached a transient group-classification provider failure as a permanent `ERROR`; an identical later request never retried after provider recovery.
- Draft [PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256) now publishes exact head `7cab94dd9481888a8946a2177132b8e1927a3670`, tree `edd6f5907c3185e7e175bfc75cb5cb9c5ab3f92a`; local author commit `e1979c51c3f21676762d965650bb62baad9d5ca7` has the exact same tree. Only `smart_classifier.py` and `test_smart_classifier.py` changed.
- The failing request still returns fail-closed `ERROR`, but error responses no longer poison the group cache. An identical later request retries; a recovered `OK` is cached normally. Image-fingerprint isolation and unavailable-image `MANUAL_REVIEW` / `recommended=false` behavior are preserved.
- A0 exact adjacent command passed **71 tests + 71 subtests**, exit 0; py_compile, diff-check and exact scope exited 0.
- Fresh independent A5 `/root/a5_cycle253`: **PASS, no findings**. Its adjacent suite passed **71 + 71 subtests** and independent cache/fail-closed adversarial matrix passed **5/5**, all exit 0.
- Exact-head CI [run 38602133386 / job 115983741821](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38602133386/job/115983741821): **success** (`offline-safety`). PR receipt comment id `6173662185` records the candidate and checks.
- Full PR #245 product/legal/source acceptance remains NOT PASS. NTM full-sync remains blocked without a lawful populated synchronized snapshot. A6 `core-s1-6415f443120f-r9-g106` remains unchanged and undispatched; no protected action was performed.

## 2026-10-14 — Smart-classifier cached-result snapshot isolation completed on draft PR #256

- Exact parent `7cab94dd9481888a8946a2177132b8e1927a3670` cached a successful mutable `ClassifyResult` by reference. A caller could mutate `hs_code`, rationale or nested metadata, and the next identical request received that corrupted state without another provider call.
- Draft [PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256) now publishes exact head `797cd548b1b83f5b15fa26bbcf23ae9352a15b0b`, tree `805eceeae02bf903e54435a0b012934949d2ccd4`; local author commit `898eb448a7046a74d9df22f93241937d50c538e3` has the exact same tree. Only `smart_classifier.py` and `test_smart_classifier.py` changed.
- The cache now retains a private deep snapshot and every cache hit returns a fresh deep snapshot. Nested `results`, `extra` and `web_context` are isolated, while the string-compatible vision-analysis wrapper, transient ERROR retry, image fingerprint isolation and failed-image manual review behavior remain intact.
- A0 exact adjacent command passed **72 tests + 71 subtests**, exit 0; `py_compile`, diff-check, exact two-file scope, tree and clean-worktree checks exited 0.
- Fresh independent A5 `/root/a5_cycle254`: **PASS, no findings**. Its adjacent run passed **72 + 71 subtests**; its adversarial matrix passed first-return isolation, cached-hit isolation, nested deep isolation, provider call count=1, transient ERROR retry, image fingerprint isolation and failed-image manual review.
- Exact-head CI [run 38611383191 / job 116015341403](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38611383191/job/116015341403): **success** (`offline-safety`). PR receipt comment id `6174899050` records the candidate and checks.
- Full PR #245 product/legal/source acceptance remains NOT PASS. NTM full-sync remains blocked without a lawful populated synchronized snapshot. A6 `core-s1-6415f443120f-r9-g106` is unchanged and undispatched; no merge, deploy, production write, enforcement/flag, secret/permission, destructive migration, force-push or external A6 action was performed.

## 2026-10-14 — Smart-classifier concurrent group singleflight completed on draft PR #256

- Exact parent `797cd548b1b83f5b15fa26bbcf23ae9352a15b0b` started three provider classifications for three simultaneous identical cold-cache requests before any result was released.
- Draft [PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256) now publishes exact head `e5e75915ec1957f172b30284dd1633cf0c4c1915`, tree `76d8c0717b88342b11be28a18d20202e2f5a13de`; local author commit `75d61bf74fb46548ae86945ceab1eca08d51f060` has the exact same tree. Only `smart_classifier.py` and `test_smart_classifier.py` changed.
- Exact-key concurrent calls now share one event-loop-local producer task; every waiter and cache hit receives an independent deep snapshot. Cancelling a waiter cannot cancel the producer. Concurrent ERROR remains fail-closed and uncached so a later request retries; a generation fence prevents a late producer from repopulating a cleared cache.
- A0 exact adjacent command passed **75 tests + 71 subtests**, exit 0; `py_compile`, diff-check, exact two-file scope, tree and clean-worktree checks exited 0.
- Fresh independent A5 `/root/a5_cycle255`: **PASS, 0 code findings**. Its adjacent run passed **75 + 71 subtests**; independent adversarial matrix passed **46 assertions** covering singleflight, deep isolation, ERROR retry, cancellation, generation fence, distinct fingerprints and separate event loops. One direct async pytest invocation lacked `pytest-asyncio`; the same coroutine passed via `asyncio.run`.
- Exact-head CI [run 38620208681 / job 116045462121](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38620208681/job/116045462121): **success** (`offline-safety`). PR receipt comment id `6176072359` records the candidate and checks.
- Full PR #245 product/legal/source acceptance remains NOT PASS. NTM full-sync remains blocked without a lawful populated synchronized snapshot. A6 `core-s1-6415f443120f-r9-g106` is unchanged and undispatched; no merge, deploy, production write, enforcement/flag, secret/permission, destructive migration, force-push or external A6 action was performed.

## 2026-10-14 — Smart-classifier translation fallback cache recovery completed on draft PR #256

- Exact parent `e5e75915ec1957f172b30284dd1633cf0c4c1915` cached the original foreign text after a transient translation-provider exception or empty answer, so an identical later request did not retry after provider recovery.
- Draft [PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256) now publishes exact head `162cd8c03d0365fbc57b3172201fb3981b40c89a`, tree `f87d4ec51bd053ff7e688b9dc51ad96863e2077e`; local author commit `eb5d14b36920b0334ad143a9ad89f5716f2826e4` has the exact same tree. Only `smart_classifier.py` and `test_smart_classifier.py` changed.
- Failed or empty translation fallbacks are returned only to the current caller and are not cached. Successful translations and the Russian fast path remain cached; batch results retain only requested nonempty mappings. Concurrent identical cold translations share one loop-local provider task, waiter cancellation is shielded, and cache clear fences late completion.
- A0 exact adjacent command passed **81 tests + 71 subtests**, exit 0; `py_compile`, diff-check, exact two-file scope, tree and clean-worktree checks exited 0.
- Fresh independent A5 `/root/a5_cycle256`: **PASS, no findings**. Its adjacent run passed **81 + 71 subtests**; independent probes covered exception/empty retry, partial/malformed batch recovery, successful/Russian caching, concurrent deduplication, cancellation shielding, clear generation fence, distinct keys and separate event loops.
- Exact-head CI [run 38627869101 / job 116071549278](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38627869101/job/116071549278): **success** (`offline-safety`). PR receipt comment id `6177113723` records the candidate and checks.
- Full PR #245 product/legal/source acceptance remains NOT PASS. NTM full-sync remains blocked without a lawful populated synchronized snapshot. A6 `core-s1-6415f443120f-r9-g106` is unchanged and undispatched; no merge, deploy, production write, enforcement/flag, secret/permission, destructive migration, force-push or external A6 action was performed.

## 2026-10-14 — Smart-classifier concurrent translation-batch singleflight completed on draft PR #256

- Exact parent `162cd8c03d0365fbc57b3172201fb3981b40c89a` made two provider calls for two simultaneous identical cold translation batches. Equivalent 90-row sets in reverse order produced four calls because chunk boundaries depended on input order.
- Draft [PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256) now publishes exact head `3e54a6abe467138071e775b6820f58a381e06060`, tree `1e32538978ac23faa5df700db227ffb07269bb02`; local author commit `8d1dcc85ccfa1c1f9878a0d624dfd54e30c36359` has the exact same tree. Only `smart_classifier.py` and `test_smart_classifier.py` changed.
- Pending translations are canonically ordered before chunking. Identical loop-local chunks share one shielded producer; cancelling one waiter does not cancel it. Cache clear detaches old batches, and generation checks before every fallback prevent late old work from repopulating the new cache.
- A0 exact adjacent command passed **86 tests + 71 subtests**, exit 0; `py_compile`, diff-check, exact two-file scope, tree and clean-worktree checks exited 0.
- Independent A5 `/root/a5_cycle257` rejected two intermediate candidates for order-dependent chunking above 45 rows and a clear-during-fallback race. Fresh final review: **PASS, no findings**; focused **19 passed**, adjacent **86 + 71 subtests**, independent adversarial matrix **45 assertions PASS**.
- Exact-head CI [run 38636236869 / job 116100003588](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38636236869/job/116100003588): **success** (`offline-safety`). PR receipt comment id `6178312499` records the candidate and checks.
- Full PR #245 product/legal/source acceptance remains NOT PASS. NTM full-sync remains blocked without a lawful populated synchronized snapshot. A6 `core-s1-6415f443120f-r9-g106` is unchanged and undispatched; no merge, deploy, production write, enforcement/flag, secret/permission, destructive migration, force-push or external A6 action was performed.

## 2026-10-14 — Smart-classifier concurrent vision singleflight completed on draft PR #256

- Exact parent `3e54a6abe467138071e775b6820f58a381e06060` made two vision-provider calls for two simultaneous identical cold group-image requests.
- Draft [PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256) now publishes exact head `8a1ff90112f5fb6f7b766bbd55510dfd8af105c4`, tree `e3bf55bdc4b015ed90152e337ab700ed658f8a8a`; local author commit `639feb1893a50066d9665b38e646bafb1ab1fb92` has the exact same tree. Only `smart_classifier.py` and `test_smart_classifier.py` changed.
- Identical loop-local validated images share one shielded producer. Failures remain retryable; cache clear detaches old producers; a newest-image fingerprint fence prevents late old success or failure from replacing or erasing newer evidence. Manual review and fail-closed image-unavailable behavior are preserved.
- A0 exact adjacent command passed **92 tests + 71 subtests**, exit 0; focused race suite passed **6**; `py_compile` and diff-check exited 0.
- Independent A5 `/root/a5_cycle258` rejected the first candidate for a reproduced late changed-image cache race, then returned **PASS, no findings** on the repaired exact tree. Fresh probes covered late success/failure, invalid-newer, A/B/A, cancellation, retry, fail-closed recovery and separate event loops.
- Exact-head CI [run 38645370088 / job 116130776149](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38645370088/job/116130776149): **success** (`offline-safety`). PR receipt comment id `6179555513` records the candidate and checks.
- Full PR #245 product/legal/source acceptance remains NOT PASS. NTM full-sync remains blocked without a lawful populated synchronized snapshot. A6 `core-s1-6415f443120f-r9-g106` is unchanged and undispatched; no merge, deploy, production write, enforcement/flag, secret/permission, destructive migration, force-push or external A6 action was performed.

## 2026-10-14 — Smart-classifier transient web-search recovery validated on draft PR #256

- Cycle 259 published the production repair at `f05df522155b3fadaeddd1da6f9a830d31f152cc` but explicitly left focused backend execution and independent A5 pending. Exact execution reproduced a defect in the new test: successful normalized results intentionally omit `recommended=true`, while fail-closed results explicitly carry `recommended=false`.
- Draft [PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256) now publishes exact head `a5e952f1ea847500b65bdc76b18514ddfd97f01d`, tree `f1b269e40ee3b5fa72770a8d75ec6ed2d80ce9d5`; local exact-tree commit `369b12e4ce84c18dd1c8197d4d370bf33284b465`. Cycle 260 changed only the assertion; the production repair remains unchanged.
- A required-but-unavailable web search remains fail-closed `MANUAL_REVIEW` and uncached. The next identical request retries, and only confirmed recovery is cached.
- A0 exact adjacent command first exited 1 with **1 failed, 92 passed + 71 subtests**, then after the assertion repair exited 0 with **93 passed + 71 subtests**.
- Independent A5 `/root/a5_cycle260`: **PASS, no findings**. It repeated focused/adjacent/parser suites, compilation and independent concurrent-retry plus cache-generation-fence probes.
- Exact-head CI [run 38651533970 / job 116151241312](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38651533970/job/116151241312): **success**. PR receipt comment id `6180447989` records the exact candidate and checks.
- Full PR #245 product/legal/source acceptance remains NOT PASS. NTM full-sync remains blocked without a lawful populated synchronized snapshot. A6 `core-s1-6415f443120f-r9-g106` is unchanged and undispatched; no merge, deploy, production write, enforcement/flag, secret/permission, destructive migration, force-push or external A6 action was performed.

## 2026-10-14 — Data-refresh check-only filesystem mutation removed on draft PR #256

- Exact parent `a5e952f1ea847500b65bdc76b18514ddfd97f01d` opened a missing file-backed SQLite database during `--check-only`, creating `customs.db`; the subprocess regression also used literal `python3` rather than the active isolated interpreter.
- Draft [PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256) now publishes exact head `863011a250c4713d0a867b03f0ca1d8c79197274`, tree `a3be986ffffd53f220a8fe1df0e05816f47c4cf8`; local author commit `777fb6d5922bcc8fd0ed95df93e2d37f587bc840` has the same tree. Only `data_refresh_service.py` and `test_data_refresh.py` changed.
- Missing SQLite now returns stale reason `db_missing` before opening a connection and leaves DB/WAL/SHM absent. Existing, in-memory and non-SQLite behavior is preserved; the test uses `sys.executable` and an isolated temporary `DATABASE_URL`.
- A0 final bounded command passed **106 tests + 71 subtests**, with 3 parent-existing workflow-presence tests deselected, exit 0; no database artifact was created; `py_compile` and diff-check exited 0.
- Independent A5 `/root/a5_cycle261`: **PASS, no findings**. Its adjacent profile passed **102 + 31 subtests**; 23 independent SQLite/non-SQLite assertions passed; exact scope, tree and clean worktree were verified.
- Exact-head CI [run 38656935852](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38656935852): **success** (`offline-safety`). PR receipt comment id `6181119818` records the candidate and checks.
- Known limitation: the three `TestGitHubWorkflow` presence tests are not PASS because `.github/workflows/scheduled-data-refresh.yml` is absent on the exact base. Full PR #245 product/legal/source acceptance remains NOT PASS; NTM full-sync remains blocked without a lawful populated synchronized snapshot. A6 `core-s1-6415f443120f-r9-g106` remains unchanged and undispatched; no protected action was performed.

## 2026-10-15 — Scheduled read-only source freshness monitor restored on draft PR #256

- Exact parent `863011a250c4713d0a867b03f0ca1d8c79197274` lacked `.github/workflows/scheduled-data-refresh.yml`, so all three workflow-presence regressions failed.
- Draft [PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256) now publishes exact head `b2f47ba1661ad5e983b3df7d809e04484fc78590`, tree `1c358d8a6bc86167eb772ca37279a8a000c4bbe1`; local author commit `6790fc8aff47da7a5104fe1bdf6690ec3ea06a1c` has the same tree. The only added file is the scheduled workflow; blob `1693b3403d4d403b86b49b30d4e6018af89864bd` is byte-identical to the already-tested PR255 lineage.
- The workflow runs daily at 03:17 UTC or manually, has `contents: read`, pinned actions and dependencies, no persisted checkout credentials, and only read-only bundle/CBR checks with an isolated `/tmp` SQLite target.
- A0 focused/adjacent execution passed **109 tests + 71 subtests**, exit 0. A broader backend diagnostic passed **562 + 103 subtests** before a separate empty-fixture failure (`exchange_rates` table absent).
- Independent A5 `/root/a5_cycle262`: **PASS, no findings**. It passed **16 focused** and **105 + 31 subtests** adjacent, checked exact lineage, YAML/security boundaries and verified no SQLite artifacts.
- Executing the workflow bundle step now correctly reports all six committed normative bundles stale by **114-119 days** (revisions 2026-06-18/23) and exits 1 as the intended freshness enforcement signal.
- Exact-head CI [run 38662810786](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38662810786): attempt 1 hit two unrelated tempfile Git-directory cleanup races after 118/120 tests; the unchanged exact-head failed-job rerun attempt 2 succeeded. PR receipt comment id `6181916495` records the candidate and checks.
- Full PR #245 product/legal/source acceptance remains NOT PASS. NTM full-sync remains blocked without a lawful populated synchronized snapshot. A6 `core-s1-6415f443120f-r9-g106` remains unchanged and undispatched; no protected action was performed.

## 2026-10-15 — Exchange-rate fallback restored for absent disposable schema on draft PR #256

- Exact parent `b2f47ba1661ad5e983b3df7d809e04484fc78590` raised `no such table: exchange_rates` while comparing scenarios against an empty disposable SQLite database, despite the existing local FX constants.
- Draft [PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256) now publishes exact head `8eda154558e486a3136d4ecfe31460793f89ec79`, tree `33e07fde1443bfc297b54de7434d9118035d6a86`; local author commit `f0fb0be13a39e43946d2dd42e3871c648eb71602` has the exact same tree.
- Both exchange-rate readers now detect only an absent table and use the existing constants. Stored rows keep their prior override behavior; connection, introspection and malformed persisted-table failures still propagate.
- A0 final bounded command passed **111 tests + 71 subtests**, exit 0, with no disposable DB/WAL/SHM left behind. Fresh independent A5 `/root/a5_cycle263`: **PASS, no findings**; focused plus payment coverage passed **36 tests**, and four injected failure checks confirmed errors are not broadly swallowed.
- Exact-head CI [run 38668497328](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38668497328): **success**. PR receipt comment id `6182677315` records the candidate and checks.
- The same empty-schema scenario now advances beyond FX and reproduces a separate missing `country_risks` failure; that is the next bounded defect, not part of this repair. Full #245 product/legal/source acceptance remains NOT PASS; the lawful populated synchronized NTM snapshot remains unavailable. A6 is unchanged and undispatched; no protected action was performed.

## 2026-10-15 — Scenario-comparison database isolation completed on draft PR #256

- Exact parent `8eda154558e486a3136d4ecfe31460793f89ec79` raised `no such table: country_risks` when the scenario E2E ran on an empty disposable SQLite database.
- Draft [PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256) now publishes exact head `f2788ce1967320134d2896050623fbc37d405f5d`, tree `f3d62421237e8eb4ba941199b4470a1f6750d68a`; local author commit `b08f8f4b5025d8bd466a0b9890754d366cb82eab` has the exact same tree.
- `test_invoice_and_compare.py` now creates the explicit disposable schema needed by the scenario-calculation path and rebinds its service-local session factories. Production code and normative semantics are unchanged; an adversarial production call still raises when `country_risks` is truly absent instead of treating the country as neutral.
- A0 focused module passed **2 tests**; final bounded profile passed **113 tests + 71 subtests**, exit 0; `py_compile`, diff-check and no-local-DB checks exited 0.
- Fresh independent A5 `/root/a5_cycle264`: **PASS, no findings**. Its poison-ambient-DB focused run passed **1**, adjacent payment/ROP/risk profile passed **73**, and a production empty-schema probe confirmed that the missing-table error still propagates.
- Exact-head CI [run 38673744569](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38673744569): **success**. PR receipt comment id `6183378494` records the candidate and checks.
- Separate parent-existing fixture debt remains: three `test_rate_display.py` cases fail when `hs_rates` is absent. Full #245 product/legal/source acceptance remains NOT PASS; all six committed normative bundles remain stale; the lawful populated synchronized NTM snapshot remains unavailable. A6 is unchanged and undispatched; no protected action was performed.

## 2026-10-15 — Rate-display database isolation completed on draft PR #256

- Exact parent `f2788ce1967320134d2896050623fbc37d405f5d` failed all three `test_rate_display.py` cases because the disposable environment had no `hs_rates` table.
- Draft [PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256) now publishes exact head `0e9b39b4580de33ed6c02a976cdafc6837cc6e6e`, tree `eac1723f88bbbaefc0a10cd7f945437957020fc8`; local author commit `2e2e88dd89a53f6766151a79c7f95cfe0679d9ec` has the exact same tree.
- `test_rate_display.py` now creates a per-test disposable `hs_rates` schema, patches both bound readers and seeds only the parent rate already required by the unchanged 45 ₽/l expectation. Production missing-table behavior remains fail-closed; no product calculation, normative source or legal applicability changed.
- A0 focused execution passed **3 tests**; the bounded adjacent profile passed **116 tests + 71 subtests**, exit 0. `py_compile`, diff-check and repository-artifact checks also exited 0.
- Fresh independent A5 `/root/a5_cycle265`: **PASS, no findings**. It independently repeated focused **3 passed** and adjacent **116 + 71 subtests**, verified teardown and one-file scope, and confirmed an empty production-like schema still raises `OperationalError` for missing `hs_rates`.
- Exact-head CI [run 38678637960 / job 116237878852](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38678637960/job/116237878852): **success**. PR receipt comment id `6184021384` records the candidate and checks.
- Full PR #245 product/legal/source acceptance remains NOT PASS. All six committed normative bundles remain stale and the lawful populated synchronized NTM snapshot remains unavailable. A6 `core-s1-6415f443120f-r9-g106` is unchanged and undispatched; no protected action was performed.
- Next: run the next clean bounded backend fixture tranche on this exact head and repair only a concretely reproduced defect while keeping source/snapshot blockers explicit.

## 2026-10-15 — Normative-bundle order isolation completed on draft PR #256

- A clean broad backend diagnostic on exact parent `0e9b39b4580de33ed6c02a976cdafc6837cc6e6e` reached **1,933 passed + 197 subtests** and reproduced an independent order-dependent normative fixture failure. The bounded reproduction `test_invoice_and_compare.py → test_normative_bundle.py` exited 1 with **1 failed, 8 passed, 1 teardown error**; standalone/reverse order hid the stale copied `rate_display.SessionLocal` alias and configured SQLite mutation.
- Draft [PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256) now publishes exact head `7364f190226c2f53968f9acbb76acc483a01fc91`, tree `683c522674b03ff2f562af65c3c8151c1589be3b`; local exact-tree commit `358ab9829f99e4e7f7b1e1767c2f09765455775e`. Only `customs-clear/backend/tests/test_normative_bundle.py` changed.
- The fixture redirects the environment before bootstrap, rebinds all preloaded app database aliases by identity, restores late imports, disposes/removes only disposable state, and compares the originally captured configured/source DB paths plus WAL/SHM. A5 rejected the first candidate because environment mutation changed the fingerprint path set; the repaired candidate captures that set before mutation.
- A0: both module orders **9 passed**; final adjacent profile **123 passed + 71 subtests**, exit 0; configured/source artifacts absent, pinned source SHA unchanged, `py_compile` and diff-check exit 0. Fresh independent A5 `/root/a5_cycle266`: **PASS, no findings** after both orders, missing/existing source probes and the same adjacent profile.
- Exact-head CI [run 38685076935 / job 116257955908](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38685076935/job/116257955908): **success**. PR receipt comment id `6184889391` records the exact candidate and checks.
- Scope is one test fixture; product/runtime calculation, normative data and legal applicability did not change. Three dependency-sensitive packing-list async tests remain a separate current-PR failure; full PR #245 product/legal/source acceptance remains **NOT PASS**, all six committed payment bundles remain stale, and the lawful populated synchronized NTM snapshot remains unavailable. A6 `core-s1-6415f443120f-r9-g106` is unchanged and undispatched; no protected action was performed.
- Next: consolidate and independently revalidate the dependency-independent packing-list async tests on exact PR #256, then rerun the broader offline backend diagnostic.

## 2026-10-15 — Packing-list async dependency removed from tests on draft PR #256

- Exact parent `7364f190226c2f53968f9acbb76acc483a01fc91` exited 1 with **3 failed, 1 passed** for the focused packing-list files because the isolated environment has no `pytest-asyncio`.
- Draft [PR #256](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/256) now publishes exact head `848647fbde88cdb600f81ff56757a8756ab499db`, tree `173f1d4f01a3c7a7e1f465e3216de906cd3a5b99`; local exact-tree commit `b2b73098e4dd449f8bd547dec0295f9ff0c5a3eb`. Only `test_packing_list_classify.py` and `test_packing_list_tasks.py` changed.
- The three existing async scenarios now use stdlib `asyncio.run`; the background-task case keeps one coroutine, original patch lifetime, await order and every assertion. No dependency, runtime code, normative data or legal applicability changed.
- A0: focused and reverse order each **4 passed**; adjacent packing/smart profile **95 passed + 71 subtests**; expanded safe offline profile **131 passed + 71 subtests**, exit 0. `py_compile`, exact-file parity and diff-check exited 0.
- Fresh independent A5 `/root/a5_cycle267`: **PASS, no findings**. It repeated both orders and adjacent coverage, verified all assertion expressions unchanged, confirmed `pytest-asyncio` absent and found no DB artifacts.
- Exact-head CI [run 38689939882 / job 116273266494](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/38689939882/job/116273266494): **success**. PR receipt comment id `6185608825` records the candidate and checks.
- The unfiltered full backend command was rejected before launch because it could make an unapproved request to `api.proxyapi.ru`; no bypass or external request occurred, so no whole-backend PASS is claimed. Full PR #245 product/legal/source acceptance remains NOT PASS, all six committed payment bundles remain stale, the lawful populated synchronized NTM snapshot remains unavailable, and A6 `core-s1-6415f443120f-r9-g106` remains unchanged and undispatched.
- Next: build an explicitly audited network-free broad module allowlist on this exact head and continue from the next reproduced fixture/product failure without weakening source or snapshot gates.
