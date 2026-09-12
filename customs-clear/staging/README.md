# Local read-only staging

This stack serves the built frontend on `127.0.0.1:3000` and the API on
`127.0.0.1:8001`. The API opens a standalone SQLite snapshot in strict
read-only mode. Startup migrations, schedulers, sync jobs, external AI calls,
audit writes and every NTM enforcement bridge are disabled. The container also
mounts the database read-only and runs with a read-only root filesystem.

Snapshot creation requires an approved, current official source manifest plus
an exact match with the pinned full catalog, tariff values, current Alembic head
and NTM v2 schema. Backend startup then runs the complete fail-closed NTM
coverage audit before opening the HTTP port. An incomplete, stale or mismatched
database therefore never becomes healthy.

**Current release status: positive full staging is blocked.** The tracked ETT
bundle is a DB-derived export rather than independently parsed EEC evidence. It
contains 2 invalid rows and 27 duplicate rows across 23 codes, including 18
materially conflicting duty-rate groups. It also does not prove newer EEC
chapter amendments or temporary/as-of tariff footnotes. Fingerprints make this
problem reproducible; they do not make the rates legally current.

## Build a snapshot

From `customs-clear/`:

Inspect the non-mutating readiness decision and write its evidence report:

```bash
python backend/scripts/build_full_staging_snapshot.py \
  --check-inputs \
  --report /absolute/path/to/staging-input-readiness.json
```

The command exits non-zero with `positive_snapshot_allowed=false`. This is the
required fail-closed result. Baseline schema v1 is permanently
`quarantine_only`: editing its release booleans cannot enable a snapshot.
A positive path requires a separate decision and a separately implemented,
reviewed schema-v2 validator; that design is intentionally not present here.

Consequently, the following release command is intentionally blocked today:

```bash
python backend/scripts/build_full_staging_snapshot.py \
  /absolute/path/to/customs-staging.db \
  --report /absolute/path/to/customs-staging-build.json
```

It creates no directory or database. The dormant build stages already fail
closed on code/rate/prefix fingerprints, require a canonical and fully populated
FTS5 index, and measure configured-database state, but cannot be reached through
the v1 release contract.

The generic snapshot-copy command is subject to the same permanent v1
quarantine:

```bash
python staging/prepare_database.py \
  /absolute/path/to/current-customs.db \
  /absolute/path/to/customs-staging.db
```

Neither this copy path nor the builder accepts an alternate baseline CLI
argument or can bypass the current ETT quarantine.

## Start

There is no releasable full snapshot to start under schema v1. After a future
approved schema-v2 implementation produces a successful immutable snapshot,
the operational sequence from `customs-clear/` is:

```bash

cp .env.staging.example .env.staging
```

Fill every empty value in `.env.staging`. Use the absolute successful snapshot
path for `STAGING_DATABASE_PATH`. Generate unique local values;
for example, `openssl rand -hex 32` is suitable for the secret key and admin
token. The filled file is ignored by Git.

Then validate and start the stack:

```bash
docker compose --env-file .env.staging -f docker-compose.staging.yml config --quiet
docker compose --env-file .env.staging -f docker-compose.staging.yml build
docker compose --env-file .env.staging -f docker-compose.staging.yml up --build --wait
curl --fail http://127.0.0.1:8001/api/health/ready
curl --fail http://127.0.0.1:3000/api/health/ready
```

The exact backend product acceptance can also be rerun without allowing writes:

```bash
cd backend
DATABASE_URL=sqlite:////absolute/path/to/customs-staging.db \
  python scripts/run_e2e_scenarios.py \
  --require-full-data \
  --require-primary-search \
  --report /absolute/path/to/mvp-staging-acceptance.json
```

Run this only after `prepare_database.py --validate-only` (the builder does that
automatically). `--require-full-data` protects the four application scenarios;
the preceding staging validator is the stricter exact 21/96/17,809 + 13,290
catalog gate.

This unmodified `up --wait` run with a verified full snapshot remains mandatory
before release, but is intentionally unavailable while the source quarantine is
closed. CI currently proves both the quarantine rejection and a tiny read-only
container smoke. `staging/ci-smoke.override.yml` must never be presented as a
full-catalog acceptance environment.

Stop it with:

```bash
docker compose --env-file .env.staging -f docker-compose.staging.yml down
```

Only loopback ports are published; this definition intentionally does not
support a public bind. Automatic external sync/provider jobs are disabled and
provider keys are blank, but the bridge network is not an egress sandbox. A
missing database path or secret causes Compose to fail before it starts any
service. To refresh data, create a new snapshot and restart the stack; never make
the staging mount writable.
