# Local read-only staging

This stack serves the built frontend on `127.0.0.1:3000` and the API on
`127.0.0.1:8001`. The API opens a standalone SQLite snapshot in strict
read-only mode. Startup migrations, schedulers, sync jobs, external AI calls,
audit writes and every NTM enforcement bridge are disabled. The container also
mounts the database read-only and runs with a read-only root filesystem.

Snapshot creation requires an exact match with the repository's pinned full
catalog (21 sections, 96 chapters, 17,809 commodities and 13,290 active ETT
codes), the current Alembic head and the expected NTM v2 schema. Backend startup
then runs the complete fail-closed NTM coverage audit before opening the HTTP
port. An incomplete, stale or mismatched database therefore never becomes
healthy.

## Start

From `customs-clear/`:

```bash
python staging/prepare_database.py \
  /absolute/path/to/current-customs.db \
  /absolute/path/to/customs-staging.db

cp .env.staging.example .env.staging
```

Fill every empty value in `.env.staging`. Use the absolute snapshot path from
the first command for `STAGING_DATABASE_PATH`. Generate unique local values;
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

This unmodified `up --wait` run with a full snapshot is a mandatory local or
release-acceptance gate. `staging/ci-smoke.override.yml` only verifies that the
read-only containers and proxy can boot around a tiny CI fixture; it must never
be used as a full-catalog acceptance environment.

Stop it with:

```bash
docker compose --env-file .env.staging -f docker-compose.staging.yml down
```

The Docker network is internal, so containers cannot reach external sources.
Only loopback ports are published; this definition intentionally does not
support a public bind. A missing database path or secret causes Compose to fail
before it starts any service. To refresh data, create a new snapshot and restart
the stack; never make the staging mount writable.
