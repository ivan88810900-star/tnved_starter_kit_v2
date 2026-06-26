# Cursor Task automation — GitHub Actions + Cursor CLI

Production path for implementing issues labeled **`cursor-task`**.

> **Cloud Agents Environment** in the Cursor UI is **not** used (save failures `501` and limited control).  
> Active automation: **this workflow** + [Cursor Headless CLI](https://cursor.com/docs/cli/headless) + [GitHub Actions](https://cursor.com/docs/cli/github-actions).

## Flow

```text
Codex (or Ivan) creates GitHub Issue with label cursor-task
        ↓
.github/workflows/cursor-task-agent.yml (on: issues opened/labeled)
        ↓
Cursor CLI: cursor-agent -p --force  (restricted: files only)
        ↓
Workflow: commit → push → gh pr create
        ↓
Codex review → Ivan merge
```

## Trigger

| Event | Condition |
|-------|-----------|
| `issues` / `opened`, `labeled` | Issue labels include `cursor-task` |
| `workflow_dispatch` | Input `issue_number`; issue fetched via API and validated |

The job runs when the issue **already has** the `cursor-task` label (including issues created by Codex with the label attached at creation time). It does **not** depend on `github.event.label.name` from a `labeled` event only.

`edited` is **not** a trigger: otherwise any issue author could retrigger runs (and pre-auth comments/minutes) on every edit after a maintainer added `cursor-task`. Re-run requires removing/re-adding the label (`labeled`) or a new labeled issue (`opened` with label).

**Issues only:** labeling a **Pull Request** with `cursor-task` does **not** start the agent (`!github.event.issue.pull_request`). Only ordinary GitHub Issues are eligible. This avoids running the write-enabled Cursor agent against PR body text.

**Manual fallback:** `workflow_dispatch` with input `issue_number` runs the same pipeline when GitHub does not deliver an `issues` event run. The resolve step fetches the issue via GitHub API and applies the same label / PR / closed checks.

## Manual fallback run

Primary trigger remains `issues: opened` and `issues: labeled`. Use manual dispatch when relabeling does not create a workflow run (observed on some private-repo setups).

```bash
gh workflow run cursor-task-agent.yml \
  --repo ivan88810900-star/tnved_starter_kit_v2 \
  -f issue_number=6
```

`issue_number` must be a **positive integer** with no extra characters (e.g. `6` is valid; `6.9`, `6abc`, `0`, `-1`, `006` are rejected fail-fast before any GitHub API call).

```bash
gh run list \
  --repo ivan88810900-star/tnved_starter_kit_v2 \
  --workflow cursor-task-agent.yml \
  --limit 10
```

The dispatch run uses the same trusted-actor gate, duplicate guard, staged validation, and git credential boundaries as automatic runs. Only trusted actors may start `workflow_dispatch`.

## Required secret

| Secret | Description |
|--------|-------------|
| `CURSOR_API_KEY` | API key from [Cursor dashboard → CLI](https://cursor.com/docs/cli/reference/authentication.md) |

Configure: **Repository → Settings → Secrets and variables → Actions → New repository secret**

If the secret is missing, the workflow fails immediately with a clear error (no API call).

**Never** commit API keys. They are not printed in logs. The agent step runs without `GITHUB_TOKEN`/`GH_TOKEN` in its environment; staged diff is scanned for secret markers and literal `CURSOR_API_KEY` values before commit.

CLI binary: **`cursor-agent`** (official install path). Override via env `CURSOR_AGENT_BIN` if needed.

## Trusted actors

Write-enabled automation runs only when **`github.actor`** is in the allowlist:

| Source | Value |
|--------|--------|
| Default | `ivan88810900-star` |
| Optional repo variable | `CURSOR_TASK_TRUSTED_ACTORS` — comma-separated logins, e.g. `ivan88810900-star,another-maintainer` |

If a user with triage permission adds `cursor-task` but is not trusted, the workflow comments on the issue and **does not** checkout, run the agent, commit, push, or open a PR.

## Git credential boundary

- `actions/checkout` uses **`persist-credentials: false`** so the Cursor agent step does not receive stored git push credentials.
- **Push** uses `gh auth setup-git` only in the controlled push step (after staged validation).
- Issue title/body remain untrusted prompt input; combine with trusted-actor gate and staged denylist.

## Checkout / sparse checkout

The workflow uses **sparse checkout** (cone mode) to materialize only project paths needed for Cursor Task automation:

- `.github/`, `scripts/`, `docs/`, `AGENTS.md`
- `customs-clear/backend/app`, `tests`, `scripts`, `data`, `alembic`
- `customs-clear/frontend`

**Excluded:** `customs-clear/backend/downloads/tamdoc_archive/` — archived HTML downloads with very long filenames can break checkout on GitHub-hosted runners (`File name too long`).

Automation tasks should not rely on that archive by default. Data/archive-heavy tasks may need a dedicated workflow or local execution.

## Staged denylist / secret scan

After `git add -A`, `validate_cursor_task_staged_changes.py` blocks commit if staged paths or diff contain:

- `.env`, `.env.*`, `*.db`, `*.sqlite`, `*.log`, `logs/`, `tmp/`, workflow artifact names, `.cursor/` runtime paths
- Obvious secret markers (`CURSOR_API_KEY=`, `GEMINI_API_KEY=`, `TOKEN=`, …) or literal `CURSOR_API_KEY` value in diff

## Failure comments

If the job fails after authorization (install, agent, validation, commit, push, PR create), a final step comments on the source issue with the **workflow run URL** and a failure status.

## Shell safety (issue title/body)

Issue **title** and **body** are untrusted user input. The workflow does **not** embed `${{ github.event.issue.title }}` or `body` in `run:` shell scripts.

- `actions/github-script` writes issue context to `$RUNNER_TEMP/cursor-task/issue-context.json` (JSON-escaped; not in repo root).
- PR title: `scripts/automation/render_cursor_task_pr_title.py` → `$PR_TITLE` for `gh pr create`.
- PR body: `render_cursor_task_pr_body.py` + `--body-file` (also under runner temp).
- Step outputs (`issue_number`, `branch_name`) use `env:` bridges, not inline `${{ ... }}` inside shell commands.

## Runtime artifacts (not committed)

Workflow temp files (`issue-context.json`, `open-prs.json`, `pr-body.md`) are created under **`$RUNNER_TEMP/cursor-task/`**, outside the checked-out repository. `git add -A` therefore stages only Cursor agent changes in the repo, not CI payload or duplicate-guard JSON.

## Workflow permissions

```yaml
permissions:
  contents: write      # branch, commit, push
  pull-requests: write # gh pr create
  issues: write        # comments on issue
```

`GITHUB_TOKEN` is used for `gh` CLI (PR/issue comments). `CURSOR_API_KEY` is only used for the Cursor agent step.

## Branch naming

`cursor/issue-<number>-<slug>`

`<slug>` — lowercased issue title, non-alphanumeric → `-`, max 40 chars.

Example: issue `#3` → `cursor/issue-3-official-sgr-section-ii-batch`

## Duplicate protection

1. **Concurrency** — one run per issue number (`cursor-task-issue-<n>`).
2. **Open PR check** — after trusted-actor authorization and `actions/checkout` (`persist-credentials: false`), `gh pr list --limit 1000` + `count_cursor_task_duplicate_prs.py`; counts only open PRs whose `headRefName` starts with `cursor/issue-<n>-` **and** whose head repository owner/name match the current repository (fork PRs with colliding branch names are ignored). Job-level `GH_REPO` keeps GitHub CLI repo context explicit.
3. **Label-only trigger** — removing/re-adding `cursor-task` can re-run; duplicate PR check still applies.

## What the agent is allowed to do

Per [Cursor restricted-autonomy pattern](https://cursor.com/docs/cli/github-actions):

| Step | Who |
|------|-----|
| Read issue, `AGENTS.md`, `CURRENT_PROJECT_FOCUS.md` | Cursor CLI |
| Edit files, run tests in repo | Cursor CLI (`cursor-agent -p --force`) |
| Branch / commit / push / open PR | GitHub Actions (deterministic) |

Prompt is built in `scripts/automation/run_cursor_task_from_issue.py`.

## Disable automation

- Remove label `cursor-task` before labeling (won’t trigger), or
- Disable workflow: **Actions → Cursor Task Agent → ⋮ → Disable workflow**, or
- Delete/rename `.github/workflows/cursor-task-agent.yml` (not recommended; prefer disable).

## Local dry-run (no API key)

Smoke-test prompt assembly without calling Cursor:

```bash
cd /path/to/tnved_starter_kit_v2
cat > issue-context.json <<'EOF'
{"number": 99, "title": "Test task", "body": "Goal: noop\nTests: echo ok", "html_url": "https://github.com/example/issues/99"}
EOF
DRY_RUN=1 python3 scripts/automation/run_cursor_task_from_issue.py
python3 scripts/automation/prepare_cursor_task_branch.py issue-context.json
```

## Files

| Path | Role |
|------|------|
| `.github/workflows/cursor-task-agent.yml` | Workflow |
| `scripts/automation/run_cursor_task_from_issue.py` | Prompt + `cursor-agent -p --force` |
| `scripts/automation/authorize_cursor_task_actor.py` | Trusted-actor logic (unit-tested; workflow inlines equivalent bash) |
| `scripts/automation/validate_cursor_task_staged_changes.py` | Pre-commit staged denylist + secret scan |
| `scripts/automation/prepare_cursor_task_branch.py` | Branch name helper |
| `scripts/automation/render_cursor_task_pr_body.py` | PR body template |
| `scripts/automation/run_cursor_task_from_issue.sh` | Shell wrapper |

## PR body policy

Generated cursor-task PR bodies include **`Closes #<n>`** so the source issue closes automatically when Ivan merges the PR.

## After merge (manual)

1. Add `CURSOR_API_KEY` in GitHub Secrets (if not already).
2. Optional: set repo variable `CURSOR_TASK_TRUSTED_ACTORS` for extra maintainers.
3. Create a test issue from template **Cursor Task**, add label `cursor-task` (as a trusted actor).
4. Watch **Actions → Cursor Task Agent** and confirm PR + issue comments.
5. Codex review → Ivan merge.

### First E2E checklist

| Scenario | Expected |
|----------|----------|
| Malicious title/body in issue | Treated as text only; PR title/body via Python renderers; no shell injection |
| True no-op (agent changes nothing) | No commit; issue comment “no file changes” |
| Add-only file | Staged, validated, committed, PR opened |
| Modify-only / delete-only | Same commit path after validation |
| Unauthorized labeler | Skip message; no agent/commit/PR |
| Forced failure after “started” | Issue comment with workflow run URL |

## Troubleshooting

| Symptom | Check |
|---------|--------|
| Workflow doesn’t start | Label exactly `cursor-task`; Actions enabled on repo |
| Fails on first step | `CURSOR_API_KEY` secret |
| Skipped run | Open PR already exists for `cursor/issue-<n>-*` |
| No file changes | Issue scope unclear; read agent log in workflow run |
| `cursor-agent: not found` | Install step failed; see Cursor install docs |

## Related docs

- [WORKFLOW.md](./WORKFLOW.md)
- [SETUP_CODEX_CURSOR_WORKFLOW.md](./SETUP_CODEX_CURSOR_WORKFLOW.md)
- [CURSOR_TASK_TEMPLATE.md](./CURSOR_TASK_TEMPLATE.md)
