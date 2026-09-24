# Trusted A6 live bridge

The A6 live workflow is a narrow transport from an A0-reviewed, immutable Git
candidate to the checked `tools.tariff_agents.audit` adapter. It is not a feature
runner, a legal decision maker, or an approval mechanism.

## Trust boundary

- The only trigger is a newly created issue comment on issue `#214` whose body is
  exactly `/tariff-a6-live run-pending`. GitHub resolves this workflow and ref from
  the default branch. A separate credential-free context gate always runs and
  independently fails unless the event type, exact command, issue number, non-PR
  context, owner identity and association, default-branch ref, and exact workflow
  checkout SHA match. The credentialed
  job depends on that gate, so invalid context fails rather than looking green
  because a job was skipped.
- The command carries no request fields, paths, commits, or URLs. The bridge reads
  the single validated, unconsumed `pending_live_smoke` from
  `agent/orchestration-state`, verifies an unexpired A0 coordinator lease, and binds
  the inert state checkout commit into the receipt. State files are never executed.
- A repository-wide concurrency lock serializes accepted commands. Before any
  environment credential is available, the gate uses read-only Actions metadata to
  reject every later `issue_comment` delivery. A failed first delivery is not retried.
- The workflow must first be reviewed and merged through the repository's normal
  protected-default-branch process. A workflow copied to or dispatched from an
  agent/PR ref cannot run the credentialed job. The first live smoke is therefore
  blocked until that protected merge; this branch itself cannot prove LIVE_VERIFIED.
- The trusted bridge checkout is pinned to `github.sha`, uses a commit-pinned
  checkout action, and does not persist GitHub credentials.
- Candidate base, head, and contract inputs are exact lowercase 40-hex commit
  IDs. They are fetched as Git objects only. Candidate files are never checked
  out, imported, executed, tested, or used to select commands.
- The packet phase has no Anthropic credential. Only the single adapter invocation
  receives `ANTHROPIC_API_KEY` and `TARIFF_ANTHROPIC_MODEL`. Claude receives the
  adapter's bounded packet and has no tools, GitHub token, database, shell,
  production, merge, deploy, or write permission.
- Workflow permissions are only `contents: read` and `actions: read`; the latter is
  used solely by the pre-credential duplicate-delivery gate. Existing offline safety
  CI remains separate and credential-free.
- The credentialed job is attached to the dedicated `tariff-a6-trusted` GitHub
  Environment. The owner confirms that its deployment-branch policy allows only
  `main`, `ANTHROPIC_API_KEY` is stored as an environment secret,
  `TARIFF_ANTHROPIC_MODEL` is stored as an environment variable, and the former
  repository-level copies have been removed. This is an owner assertion: the
  bridge review did not inspect protected setting values. These settings are a
  protected human action and are not changed by this PR. Provider status remains
  `BLOCKED` until this reviewed workflow is present on the allowed default-branch
  path; no live request may be dispatched from this branch.

## A0 invocation protocol

After the reviewed workflow is present on the protected default branch, the lawful
A0 holder rereads the Actions ledger and authoritative state. If the existing request
is still validated, undispatched and unconsumed, A0 posts the exact command once to
issue `#214` through the authorized owner GitHub context. The workflow accepts no
request data from the comment. The pending record supplies the request ID, exact
base/head/contract commits, complete `paths_json`, and allowlisted public sources.
A0 polls that exact workflow run ID and downloads `tariff-a6-live-<run_id>`.

The bridge rebuilds and validates the packet twice from committed blobs. A valid
provider response must bind the packet hash and head commit and pass the adapter's
strict finding schema. The receipt additionally binds the request, workflow run,
triggering comment, authoritative state commit, A0 lease holder/generation, trusted
workflow commit, base/head/contract commits, and packet hash.

`bridge_status: LIVE_VERIFIED` means only that a real, structurally valid Anthropic
response was received for that exact packet. Its `audit_status` remains
`NEEDS_A0_VALIDATION`, its findings are advisory, and A0 must independently
reproduce/adjudicate them. It is not `AUDIT_PASSED` or product readiness.

Missing configuration, provider failure, an invalid response, mismatched commits,
unsafe paths/content, incomplete changed-path scope, wrong workflow ref, or an
unreadable commit all fail closed as `UNAVAILABLE` or `BLOCKED`. Only the scrubbed
receipt/findings artifact is retained; packets, full environments, credentials,
provider error bodies, and secret values are never uploaded.
