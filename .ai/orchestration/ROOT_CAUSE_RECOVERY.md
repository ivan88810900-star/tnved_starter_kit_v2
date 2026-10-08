# Recovery correction - local candidate, not deployed

Source baseline: `c29015e9c25232e07d06bc3869abc45db3b066a2` (7 October 2026).
This document does not grant writes, external export or protected actions.

## Verified defects and boundaries

The response-side contact scanner confused JSON newline escapes before a Python
decorator with a contact address. Both findings validation and receipt writing
needed original-string inspection, while retaining aggregate credential checks.
Original JSON keys and values are now scanned without that representation error.
Real contacts, credentials, changed bindings, source injection and unsafe output
paths remain rejected. No findings are removed or silently accepted.

The submitted preflight also confused the executing code commit with the immutable
request's contract commit. An infrastructure-only upgrade therefore rejected an
unchanged pending packet. `--request-contract-sha` explicitly pins the existing
request's original commit; its committed contract must be byte-identical to the
canonical executing commit's contract. Request identity, packet hash, preparation
time and delivery generation are preserved. Actual contract changes still fail.
A new lawful lease does not by itself create or authorize a replacement request.

A new docstring in the submitted scanner contained a fictitious contact literal
and failed the existing source-safety regression. The example was corrected,
not the scanner or test weakened. The old 66-test-only result missed this failure.

Current main already includes normalized A-CORE/A-PRODUCT roles and the UTC-Z
lease helper. Do not duplicate those fixes or execute stale state-branch copies.
The RUNBOOK now identifies main as code/protocol authority, state as inert data,
and distinguishes mutable controller recovery from read-only diagnosis.

Notification unit tests establish how receipts must be classified, not what was
actually delivered in an old platform session. `notify_parent: notified` is only
an internal handoff. A saved incident alone cannot suppress undelivered alerts.
Historical notification configuration and the exact causes of past provider
failures remain unverified where original evidence is unavailable.

## Principal executor integration (after review/activation)

There is no second coordinator, scheduler, daemon, automatic provider call or
GitHub-writing adapter in this change. The existing principal executor has an
actual read-only CLI entry point:

```sh
python3 -m tools.tariff_agents --repo "$TRUSTED_CHECKOUT" recovery-status \
  --state-root "$STATE_CHECKOUT" --code-sha "$EXACT_CODE_SHA" \
  --state-sha "$EXACT_STATE_SHA" --publication-policy blocked
```

Use separately connector-observed SHAs and clean local Git checkouts. The command
compares executing helpers with committed bytes, validates the committed task
board, reads pending-request/lease snapshots and rechecks snapshot integrity. It
does not select controller authority, acquire a lease or mutate projections.
`blocked` records a known publication restriction. `unknown` is the default;
neither choice permits a write and there is no approval/force switch.

Its `READ_ONLY_WORK_AVAILABLE` result separates local analysis and tests from an
A6-specific owner gate. A released lease does not establish native session
termination. Notification delivery remains UNCONFIRMED; the command sends nothing.
Use `notification_attempt` and `needs_notification` only with actual transport
receipts or owner acknowledgements. The external executor's use of this command
and actual task-result/push/email delivery still require a controlled live check.
Updating this file does not update an existing platform automation prompt.

Before a separately authorized external action, rehearse the existing bridge
without network or credentials, retaining the original pending contract commit:

```sh
python3 -m tools.tariff_agents.preflight \
  --repo "$TRUSTED_CHECKOUT" --state-root "$STATE_CHECKOUT" \
  --trusted-sha "$EXACT_CODE_SHA" --state-sha "$EXACT_STATE_SHA" \
  --request-contract-sha "$EXISTING_REQUEST_CONTRACT_SHA" \
  --request-id "$EXISTING_REQUEST_ID" --packet-sha256 "$EXISTING_PACKET_SHA256"
```

The preflight's synthetic event is temporary local test data, never an owner
command or export receipt. Matching committed candidate objects must already be
available locally; it performs no Git fetch. A passing result is not provider
compatibility proof, independent review, permission or a live delivery-ledger check.
Consumed requests, missing/expired leases and version drift still stop the path.

## Safety denial and deployment

A platform-denied write is distinct from GitHub CAS conflict, repository access
or a normal approval prompt. Do not retry it via a different API, account, payload,
chat, agent or raw Git route. Until officially resolved, keep remote code, lease,
state and PRs unchanged; continue permitted isolated local work only.

After official clearance, reread refs and native lifecycle evidence, use canonical
lease CAS and verify holder/token. Publish one scoped draft candidate through the
existing connector, then obtain actual independent A5 and exact-head GitHub CI.
No merge, activation, workflow rerun, production mutation or A6 export is granted
by this candidate. The already-prepared r9-g106 must not be recreated. The existing
state-branch validation workflow must not be overwritten by this main-based diff.

## Fresh local verification and remaining gaps

The unmodified main orchestration baseline was reconstructed from GitHub bytes
and blob-verified: 139 existing tests passed. The input patch's 66 new tests passed
individually, but full discovery exposed the docstring regression described above.
The final code has 224 tests: 139 existing + 66 input + 7 immutable-contract tests
+ 12 principal-CLI/mandatory-suite tests. Discovery and the required verifier both
pass all 224; the verifier now requires the new suites and existing snapshot CLI
suite, rejecting missing or empty tests. No existing test was removed or weakened.
The credential-free safety workflow retains its verifier and snapshot checks and
also runs discovery. Exact commands, hashes and fresh logs accompany the candidate.

This is the complete available orchestration suite, NOT the full backend/frontend
product suite. Synthetic snapshots are not validation of the full live runtime
board. No existing r9 packet was rebuilt. No independent A5 session, new GitHub CI,
real provider call, native executor activation or delivered notification is claimed.
