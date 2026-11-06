# Recovered catalog HTTP/UI receipt — 2026-11-06

Base: `eeef5028d45ea14af09e0afb01f600bca5602316`.
Branch: `agent/recovered-catalog-http-ui-v1`. Candidate SHA is bound in issue #257
after publication; this document does not label an uncommitted tree as a commit.

## Result and read path

The existing dictionary screen now supports an explicit local read-only profile:
React Dictionary/TnvedAccordionTree → HTTP recovery router → existing
TnvedRecoveryStore → a dedicated copy of the already accepted structural SQLite.
The normal production application entry point is not started. No second catalog,
ORM ingestion, legal admission, rate fallback or synthesized hierarchy is added.

The working copy has SHA-256
`c5959912f7c1a3e8c0329130d511243c9ead4e5ae5501dc7ce7facff2d6bdff4`,
matching the accepted 18,014-node artifact. The server validates this pin before
serving. Health and catalog payloads carry the same pin; changed files fail closed.
Original backup bytes are checked separately after acceptance, never written.

## Executed user scenario

1. Open the existing `/tnved` screen and search `0101210000`.
2. Open the returned card: `чистопородные племенные животные`.
3. Compare its exact source path with SQLite:
   `ГРУППА 01 ЖИВЫЕ ЖИВОТНЫЕ` →
   `Лошади, ослы, мулы и лошаки живые:` → `лошади:` →
   `чистопородные племенные животные`.
4. See explicit unverified-source, unknown-validity and unavailable-rates notices.
5. Open parent `0101` from the card and see its four actual direct children.
6. Return to the child through the displayed child list.

Playwright uses actual locally served production-built React assets and real HTTP
responses. Its expectation JSON is derived read-only from the pinned SQLite.
There are no mocked responses, injected seed rows, normal app startup, remote
providers or ORM fixtures in this browser scenario. Every catalog HTTP response
observed in the scenario is 200; browser page errors are zero. Search/name/path,
card code after parent navigation, snapshot identity and absence of rates are
asserted. Screenshots are retained locally, not raw data uploaded to GitHub.

## Commands and results

- `python -m unittest -v tests.test_tnved_recovery_http tests.test_tnved_catalog_api.HermeticTnvedCatalogApiTests`:
  exit 0; 10 top-level tests, no skips. The existing wrapper executes 12 additional
  nested seed-independent contracts. The three new contracts check the read path,
  Cyrillic search, pin/mutation failures, unknown codes and rejected write methods.
- `python scripts/run_tnved_recovery_ci.py`: exit 0; 4 discovered/executed, 0 skipped.
  Repeated because the adapter changed; the accepted artifact was not rebuilt.
- `node node_modules/vite/bin/vite.js build`: exit 0. Existing bundle-size/CSS
  warnings remain.
- `node node_modules/typescript/bin/tsc --noEmit`: exit 2, four pre-existing TS2339
  errors in `PermitDocumentsBlock.tsx`, lines 77/80 (`tr_ts_full_name`, `note` on
  `NormativeDocument`). A temporary source archive of unchanged main with exactly
  the same isolated dependencies reproduces the identical errors. Not a typecheck
  PASS; this unrelated file was not changed.
- `node scripts/recovery-browser-check.cjs http://127.0.0.1:18001 EXPECTATION_JSON OUTPUT_DIR`:
  exit 0, scenario PASS; Playwright/system Chrome in a separate browser context.

Frontend packages live in a separate dependency directory. Its package-lock was
copied from this repository and converted using the bundled pnpm; installation
was frozen and install scripts disabled. All direct installed versions were
compared to the original package-lock: no differences. Source manifests and
lockfiles were not changed. Python uses the previously accepted isolated venv;
uvicorn was added from the repository's requirements for the local HTTP server.

Full local commands, logs, screenshots and hashes are in the workspace sibling
`evidence/2026-11-06-http-ui/`; the queue receipt binds results to the final Git SHA.

## Coordination and limits

Owner confirmation in the current Codex chat says the former Business Tariff Dot
is paused and authorizes this single A0. No separate attachment was accessible;
no claim is made to have inspected one. Free lease generation 444 was acquired
through the trusted-main helper and GitHub CAS as generation 445; remote token
and holder were verified. The claimed exact file scope is recorded in existing
issue #257, comment 6683141133. No overlapping owned file was found.

Historical TASK_BOARD/ownership records were not cleared, and the previously
denied TASK_BOARD write was not retried. Author checks are not independent A5.
No new agent, chat or schedule was created, and no schedule was changed.

This is local structural-read acceptance, not production runtime cutover, full
backend/frontend acceptance or legal/current-edition confirmation. NTM, payments,
auth and other application workflows are outside the read-only profile. DB HOLD
remains. No Neon request, persistent DB mutation, chapter29 replay, merge, deploy,
enforcement activation, secrets/permissions change or external A6 call occurred.
