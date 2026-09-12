# Optional API activation — never paste a secret in chat

Native Work coordination uses the existing GitHub integration; no API key is
needed for the actual subagents in the current Work session. This does not prove
an unattended API session or a future automation has identical capabilities.

## OpenAI Agents API (hosted environment)

1. In the OpenAI Platform create a dedicated project/service account for Tariff.
   Enable billing and set a conservative project budget/rate limits.
2. Create a restricted project API key permitting the Agents API sessions/events/
   history and chosen model access needed by the application. Give no organization
   administration permissions. Availability depends on the account; if the key UI
   cannot grant this narrowly, verify access before enabling the runner.
3. Store it in the runner's environment secret manager as `OPENAI_API_KEY`.
   Set non-secret `TARIFF_OPENAI_MODEL` to an available model supporting Agents API.
   Do not write either credential into `.env` in Git or CLI command arguments.
4. Run `python -m tools.tariff_agents.runtime preflight`, then use its create/history
   commands from a trusted runner. Native configuration must return enabled=true,
   max_concurrent_subagents=3. Keep actual session/environment/subagent IDs as proof.
5. Hosted environment avoids installing a separate executor. Do not place app/A6/
   publication credentials in the hosted worker filesystem or session input.

If API execution is later launched by a reviewed GitHub Action, use repository
Settings -> Secrets and variables -> Actions -> New repository secret, with the
same name OPENAI_API_KEY, restricted to the necessary trusted job/environment.
The shipped offline CI does not consume this secret. Adding it alone does not
activate an unattended API runner. Never expose secrets to untrusted PR code or
pull_request_target/workflow_run checkout execution. No secret was added by setup.

## Claude external A6

Create a dedicated Anthropic API key for the Tariff workspace with minimal
available API scope and budget limit. Store only in the trusted audit runner's
secret manager as `ANTHROPIC_API_KEY`. Set `TARIFF_ANTHROPIC_MODEL` to an available
Claude model. No GitHub/DB/cloud permission is needed by Claude.

Use the audit module's packet creation and validation before sending. The packet
contains only explicit tracked source/tests/diff/contract and public official
source references. The adapter has no tools and does not retrieve the repository.
A0 must validate findings; a Claude response is not legal approval. No key or
model -> UNAVAILABLE. No fake A6 pass: absent optional configuration is recorded as NOT_CONFIGURED;
independent A5 and CI can still establish readiness under the owner mandate.
A configured provider failure or invalid/truncated result blocks high-risk readiness.

## GitHub

Existing connected GitHub app permits repository read/write. No replacement PAT
is requested. Runtime A0 needs read contents/PR/checks and write contents on agent
branches plus PR write; workflow/check reads only for CI triage. Avoid admin,
secrets, deployments and production permissions. GitHub branch restrictions must
be enforced by repository rules; a contents-write token alone is not branch scoped.
Do not change permissions/secrets during this implementation.

## Sources checked during discovery

- https://developers.openai.com/api/docs/guides/agents-api/multi-agent
- https://developers.openai.com/api/docs/guides/agents-api/environments/openai-hosted
- https://developers.openai.com/api/docs/guides/agents-api/sessions
- https://developers.openai.com/api/docs/guides/agents-api/sessions/events
- https://learn.chatgpt.com/docs/agent-configuration/subagents

Runtime-specific setup and current model availability must be verified at activation.
