# Tariff / A0 — единая точка передачи проекта

**Снимок:** 2026-10-08 (UTC). **Единственный репозиторий:** [ivan88810900-star/tnved_starter_kit_v2](https://github.com/ivan88810900-star/tnved_starter_kit_v2).  
**Авторитетное состояние:** ветка `agent/orchestration-state`, файлы `.ai/TASK_BOARD.json`, `.ai/COORDINATOR_LEASE.json`, `.ai/orchestration/A6_LIVE_STATUS.json`. Этот документ — указатель и контрольная точка, **не** право на запись/merge/A6. Перед действием заново читать текущие HEAD и state. Не полагаться на Business-чат.

## 1. Восстановление инфраструктуры — PR #254

- [PR #254](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/254) — `fix(agents): verified recovery and preflight`; **draft**, открыт; рабочая ветка `review/tariff-recovery-20261008`.
- Проверенный final candidate HEAD: `957702311efd8d29c0ff18c58bcd3b523b7fcd77`, base `main` `c29015e9c25232e07d06bc3869abc45db3b066a2`. На снимке `main` всё ещё этот SHA; не объединять без отдельного разрешения Ivan.
- 14 инфраструктурных файлов: восстановление preflight, A6 structured-safety/receipts, recovery-status, CLI, required verifier, CI, runbook и тесты. В `test_audit_bridge.py` в двух disposable Git-fixtures отключены `maintenance.auto` и `gc.auto` — устранён race `tearDown` на Git 2.55; строгая очистка не подавлена.
- Независимый **whole-PR** Codex review на прежнем SHA `6031c4a8...` подтвердил P2: default `publication_policy=unknown` скрывал существующий A6 owner gate в `task_owner_action_required`. См. [finding](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/254#discussion_r4217405436).
- На текущем SHA `957702311e...` `recovery_status` теперь учитывает `observed["owner_action_required"]`; отдельный регрессионный тест внесён в `test_operations.py`. Новый [независимый Codex re-review](https://github.com/ivan88810900-star/tnved_starter_kit_v2/pull/254#issuecomment-6057912061) завершён **без major issues** именно на `957702311e...`. Исторический P2 review thread закрыт после независимой воспроизводимости и проверки исправления. Не представлять это как формальное GitHub `APPROVED` от человека: Codex оставил advisory review.
- [Exact-head GitHub CI PASS, run 37763266913](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/37763266913), job `113264825797`: `offline-safety`, проверка тестов и committed snapshot PASS. Независимый локальный replay A0 восстановил Git blobs текущих `operations.py`, `test_operations.py`, `test_audit_bridge.py` и запустил required verifier **225/225 PASS** и полный orchestration **225/225 PASS** с socket guard, **0 network attempts**; Python 3.13 / Git 2.47 локально, Git 2.55 на Actions. Это не product-suite и не запуск A6.
- Для **protected merge #254 -> main** требуется одно явное разрешение Ivan на указанный exact SHA; никакой merge автоматом. После любого изменения HEAD повторить независимый review + CI.

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

1. Получить разрешение владельца **только на protected merge PR #254 при неизменном SHA**. До решения продолжать отдельные read-only локальные исследования и тесты; не выдавать PR за merged.
2. **После** разрешённого merge заново зафиксировать main SHA; приобрести coordinator lease через **current trusted main** `tools/tariff_agents/lease.py` и GitHub CAS; перечитать holder/token/TTL. На реальных непроизводственных сценариях проверять: recovery state/board, создание -> allocation -> implementation -> independent QA -> CI, зависание и освобождение, корректную диагностику и доказанную видимость уведомления. Не имитировать child session IDs, A5/A6, delivery receipts. Нет доступа к native Work executor — пометить unavailable.
3. #244: воспроизвести полный backend/CI по ставкам, FX, НДС, акцизам, спецпошлинам и преференциям с реальными source versions/effective dates, unknown/fail-closed, сформировать и протестировать payment quote end-to-end без production writes; независимый A5 текущего SHA.
4. #245: проверка применимости ТР, СС/ДС/СГР, лицензий, нотификаций, маркировки и исключений по кодам и свойствам, source/provenance и confidence; самостоятельная полнота нормативного набора и full backend+frontend; independent A5. Не включать SGR enforcement без отдельного решения.
5. Далее A3: реестр **официальных** документов, версии, даты вступления, полнота и обновления; A4: классификация/семантика/AI grounded-only; интеграция пользовательского сценария описание -> код -> ставки/платежи -> документы/доказательства.
6. По каждому готовому блоку: commit-bound A5 -> обязательные CI -> A6 **только когда разрешено и требуется** -> owner decision. Любой новый HEAD обнуляет прежнее «готово» для этого exact SHA.

## 5. Сроки / риски

Предыдущие ориентиры: **9 октября** — платёжный кандидат; **23 октября** — NTM; **30 октября** — официальные источники; **10 ноября** — RC1; **17 ноября** — целевая v1.0. На 8 октября платёжный draft уже существует, но **его окончательная приёмка к 9 октября под риском**: нет полного подтверждённого product backend/источников/A6-gate. Отсутствует подтверждение для обещания v1.0 по нормативной полноте. Перепланировать только по новой фактической evidence и явно отмечать gate.

## 6. Authority, безопасность, продолжение из другого чата

- A0 — один координатор; не порождать второй A0, не дублировать executor/automations. Рабочее состояние в GitHub, не в чате. На момент снимка старое расписание специально отключено, активных Automations в этой среде не найдено; **фоновое исполнение не установлено**.
- **Перед любым remote write:** `main` `AGENTS.md`, `.ai/orchestration/CONTRACT.md`; state `.ai/orchestration/RUNBOOK.md`, `.ai/TASK_PROTOCOL.md`, `.ai/TASK_BOARD.json`, `.ai/COORDINATOR_LEASE.json`, `.ai/orchestration/A6_LIVE_STATUS.json`. Запрашивать lease актуальным helper; CAS на текущем blob SHA; reread holder/token; каждый существенный write проверять. Не обходить платформенный security refusal. Отдельно в журнале: предыдущая блокировка записи lease была устранена **только для штатного CAS acquisition generation 107 2026-10-08**; это не доказывает общий доступ без ограничений. При потере lease прекратить write.
- Во время перепроверки внешний сеанс внёс 2 коммита в PR #254 с исправлением P2; A0 здесь **не отправлял дублирующий патч**. При новом внешнем движении branch немедленно reconcile HEAD и избежать пересекающихся записей. Все дополнительные findings проверять самостоятельно, не признавать review автоматически.
- Никогда без Ivan: merge защищённых веток, production deploy/DB/migrations, enforcement flags, изменение credentials/permissions/secrets, удаление/force push, A6 export. Никакой доставки в основной пользовательский чат не подтверждено.
- Статус блоков честно разделять: **сделано / сейчас / осталось / что нужно от владельца**. Прогресс доказан конкретным SHA, CI job, A5 и diff, не «агент запущен».
