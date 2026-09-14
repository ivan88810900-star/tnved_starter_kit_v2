# Trusted A6 live bridge

The A6 live workflow is a narrow transport from an A0-reviewed, immutable Git
candidate to the checked `tools.tariff_agents.audit` adapter. It is not a feature
runner, a legal decision maker, or an approval mechanism.

## Trust boundary

- The only trigger is `repository_dispatch` with event type `tariff-a6-live`.
  GitHub resolves this event's workflow and ref from the default branch. A separate
  credential-free context gate always runs and independently fails unless the event
  type, default-branch ref, and exact workflow checkout SHA match. The credentialed
  job depends on that gate, so invalid context fails rather than looking green
  because a job was skipped.
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
- Workflow permissions are `contents: read`. Existing offline safety CI remains
  separate and credential-free.
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

After the reviewed workflow is present on the protected default branch, A0 chooses a
unique request ID and sends the narrow repository dispatch. Its `client_payload`
must contain exactly six string fields: `request_id`, exact `base_sha`, exact
`head_sha`, exact `contract_sha`, `paths_json` containing every changed path, and
`official_sources_json` containing a JSON array of public allowlisted source URLs
(use `[]` when absent). All commits must be reachable in the same repository. A0
polls that exact workflow run ID and downloads `tariff-a6-live-<run_id>`.

The bridge rebuilds and validates the packet twice from committed blobs. A valid
provider response must bind the packet hash and head commit and pass the adapter's
strict finding schema. The receipt additionally binds the request, workflow run,
trusted workflow commit, base/head/contract commits, and packet hash.

`bridge_status: LIVE_VERIFIED` means only that a real, structurally valid Anthropic
response was received for that exact packet. Its `audit_status` remains
`NEEDS_A0_VALIDATION`, its findings are advisory, and A0 must independently
reproduce/adjudicate them. It is not `AUDIT_PASSED` or product readiness.

Missing configuration, provider failure, an invalid response, mismatched commits,
unsafe paths/content, incomplete changed-path scope, wrong workflow ref, or an
unreadable commit all fail closed as `UNAVAILABLE` or `BLOCKED`. Only the scrubbed
receipt/findings artifact is retained; packets, full environments, credentials,
provider error bodies, and secret values are never uploaded.
