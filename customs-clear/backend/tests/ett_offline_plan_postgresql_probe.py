"""Disposable PostgreSQL execution probe for generated ETT plan SQL."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.staging_ett_normalization_core import sha256_json
from app.services.staging_ett_offline_plan import _render_sql, build_offline_artifacts
from tests.test_ett_offline_plan_runner import _build_package


DATABASE = "tariff_staging"


def _psql(
    *,
    sql: str | None = None,
    path: Path | None = None,
    succeeds: bool = True,
    database: str = DATABASE,
):
    command = [
        "sudo",
        "-u",
        "postgres",
        "psql",
        "-X",
        "--set",
        "ON_ERROR_STOP=1",
        "--tuples-only",
        "--no-align",
        "--dbname",
        database,
    ]
    if path is not None:
        command.extend(["--single-transaction", "--file", str(path)])
    else:
        command.extend(["--command", sql or ""])
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    if succeeds and completed.returncode != 0:
        raise AssertionError(completed.stderr)
    if not succeeds and completed.returncode == 0:
        raise AssertionError("PostgreSQL command unexpectedly succeeded")
    return completed


def _hex_json(value) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8").hex()


def _setup_sql(plan) -> str:
    source_hex = _hex_json(plan["source_object"])
    run_hex = _hex_json(plan["ingest_run"])
    raw_hex = _hex_json(plan["raw_rows"])
    placeholders = "\n".join(
        f"CREATE TABLE tariff_ingest.existing_staging_{index} (id integer PRIMARY KEY);"
        for index in range(1, 5)
    )
    return f"""
CREATE SCHEMA tariff_ingest;
CREATE TABLE tariff_ingest.source_objects (
    source_id text PRIMARY KEY, authority text NOT NULL, dataset text NOT NULL,
    source_url text NOT NULL, source_revision text NOT NULL,
    object_bucket text NOT NULL, object_key text NOT NULL, sha256 text NOT NULL,
    size_bytes bigint NOT NULL, media_type text NOT NULL,
    captured_at timestamptz NOT NULL, status text NOT NULL,
    UNIQUE (object_bucket, object_key)
);
CREATE TABLE tariff_ingest.ingest_runs (
    run_id text PRIMARY KEY, source_id text NOT NULL, scope jsonb NOT NULL,
    parser_version text NOT NULL, status text NOT NULL, raw_count integer NOT NULL,
    unique_count integer NOT NULL, normalized_count integer NOT NULL,
    rejected_count integer NOT NULL, resume_cursor jsonb NOT NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE tariff_ingest.ett_collected_rows (
    source_id text NOT NULL REFERENCES tariff_ingest.source_objects(source_id),
    hs_code text NOT NULL, description text NOT NULL,
    supplementary_unit text NOT NULL, duty_text text NOT NULL,
    raw_line text NOT NULL, row_sha256 text NOT NULL,
    status text NOT NULL, ordinal integer NOT NULL,
    PRIMARY KEY (source_id, row_sha256), UNIQUE (source_id, hs_code)
);
{placeholders}
WITH d AS (
  SELECT convert_from(decode('{source_hex}', 'hex'), 'UTF8')::jsonb AS j
)
INSERT INTO tariff_ingest.source_objects
SELECT j->>'source_id', j->>'authority', j->>'dataset', j->>'source_url',
       j->>'source_revision', j->>'object_bucket', j->>'object_key', j->>'sha256',
       (j->>'size_bytes')::bigint, j->>'media_type',
       (j->>'captured_at')::timestamptz, j->>'status' FROM d;
WITH d AS (
  SELECT convert_from(decode('{run_hex}', 'hex'), 'UTF8')::jsonb AS j
)
INSERT INTO tariff_ingest.ingest_runs (
  run_id, source_id, scope, parser_version, status, raw_count, unique_count,
  normalized_count, rejected_count, resume_cursor
)
SELECT j->>'run_id', j->>'source_id', j->'scope', j->>'parser_version',
       j->>'status', (j->>'raw_count')::integer, (j->>'unique_count')::integer,
       (j->>'normalized_count')::integer, (j->>'rejected_count')::integer,
       j->'resume_cursor' FROM d;
INSERT INTO tariff_ingest.ett_collected_rows
SELECT * FROM jsonb_to_recordset(
  convert_from(decode('{raw_hex}', 'hex'), 'UTF8')::jsonb
) AS x(
  source_id text, hs_code text, description text, supplementary_unit text,
  duty_text text, raw_line text, row_sha256 text, status text, ordinal integer
);
"""


def _scalar(sql: str) -> str:
    return _psql(sql=sql).stdout.strip()


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        package_dir = root / "package"
        _build_package(package_dir)
        plan, apply_sql = build_offline_artifacts(package_dir)
        setup = root / "setup.sql"
        setup.write_text(_setup_sql(plan), encoding="utf-8")
        apply_path = root / "apply.sql"
        apply_path.write_text(apply_sql, encoding="utf-8")

        _psql(sql="CREATE DATABASE wrong_database", database="postgres")
        _psql(path=setup, database="wrong_database")
        wrong_database = _psql(
            path=apply_path, succeeds=False, database="wrong_database"
        )
        assert "offline plan targets tariff_staging only" in wrong_database.stderr
        assert _psql(
            sql="SELECT to_regclass('tariff_ingest.ett_normalization_results')",
            database="wrong_database",
        ).stdout.strip() == ""

        _psql(path=setup)
        assert _scalar(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema='tariff_ingest'"
        ) == "7"

        _psql(
            sql="INSERT INTO tariff_ingest.ingest_runs "
            "SELECT 'ett:" + "f" * 64 + "', source_id, scope, parser_version, "
            "status, raw_count, unique_count, normalized_count, rejected_count, "
            "resume_cursor, started_at, completed_at, updated_at "
            "FROM tariff_ingest.ingest_runs LIMIT 1"
        )
        duplicate_run = _psql(path=apply_path, succeeds=False)
        assert "exactly one raw ingest run" in duplicate_run.stderr
        assert _scalar(
            "SELECT to_regclass('tariff_ingest.ett_normalization_results')"
        ) == ""
        _psql(
            sql="DELETE FROM tariff_ingest.ingest_runs WHERE run_id='ett:"
            + "f" * 64
            + "'"
        )

        original_url = plan["source_object"]["source_url"].replace("'", "''")
        _psql(
            sql="UPDATE tariff_ingest.source_objects "
            "SET source_url='https://example.invalid/corrupt'"
        )
        bad_source = _psql(path=apply_path, succeeds=False)
        assert "source_objects package mismatch" in bad_source.stderr
        assert _scalar(
            "SELECT to_regclass('tariff_ingest.ett_normalization_results')"
        ) == ""
        _psql(
            sql="UPDATE tariff_ingest.source_objects "
            f"SET source_url='{original_url}'"
        )

        original_description = plan["raw_rows"][0]["description"].replace("'", "''")
        _psql(
            sql="UPDATE tariff_ingest.ett_collected_rows "
            "SET description='corrupt' WHERE ordinal=1"
        )
        bad_raw = _psql(path=apply_path, succeeds=False)
        assert "ett_collected_rows package mismatch" in bad_raw.stderr
        assert _scalar(
            "SELECT to_regclass('tariff_ingest.ett_normalization_results')"
        ) == ""
        _psql(
            sql="UPDATE tariff_ingest.ett_collected_rows "
            f"SET description='{original_description}' WHERE ordinal=1"
        )

        holder_command = [
            "sudo",
            "-u",
            "postgres",
            "psql",
            "-X",
            "--set",
            "ON_ERROR_STOP=1",
            "--dbname",
            DATABASE,
            "--command",
            "BEGIN; LOCK TABLE tariff_ingest.ett_collected_rows "
            "IN ROW EXCLUSIVE MODE; SELECT pg_sleep(3); COMMIT;",
        ]
        holder = subprocess.Popen(
            holder_command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        for _ in range(30):
            if _scalar(
                "SELECT count(*) FROM pg_locks "
                "WHERE relation='tariff_ingest.ett_collected_rows'::regclass "
                "AND mode='RowExclusiveLock' AND granted"
            ) == "1":
                break
            time.sleep(0.1)
        else:
            raise AssertionError("concurrent writer lock was not observed")
        locked_apply = root / "apply-locked.sql"
        locked_apply.write_text("SET lock_timeout='200ms';\n" + apply_sql, encoding="utf-8")
        lock_failure = _psql(path=locked_apply, succeeds=False)
        assert "lock timeout" in lock_failure.stderr
        assert _scalar(
            "SELECT to_regclass('tariff_ingest.ett_normalization_results')"
        ) == ""
        holder_stdout, holder_stderr = holder.communicate(timeout=10)
        assert holder.returncode == 0, holder_stdout + holder_stderr

        _psql(path=apply_path)
        assert _scalar(
            "SELECT count(*) FROM tariff_ingest.ett_normalization_results"
        ) == "86"
        assert _scalar(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema='tariff_ingest'"
        ) == "8"
        assert _scalar(
            "SELECT count(*) FILTER (WHERE syntax_status='PARSED'), "
            "count(*) FILTER (WHERE is_ambiguous), "
            "count(*) FILTER (WHERE legal_status<>'UNVERIFIED'), "
            "count(*) FILTER (WHERE verified), count(*) FILTER (WHERE admitted) "
            "FROM tariff_ingest.ett_normalization_results"
        ) == "81|5|0|0|0"
        stored_rows = json.loads(
            _scalar(
                "SELECT jsonb_agg(to_jsonb(r) ORDER BY ordinal)::text "
                "FROM tariff_ingest.ett_normalization_results r"
            )
        )
        assert sha256_json(stored_rows) == plan["normalization_digest"]
        fingerprint_sql = (
            "SELECT md5(string_agg(xmin::text || ':' || result_sha256, ',' "
            "ORDER BY ordinal)) FROM tariff_ingest.ett_normalization_results "
            f"WHERE source_id='{plan['source_object']['source_id']}' "
            f"AND parser_version='{plan['normalizer_version']}'"
        )
        before_replay = _scalar(fingerprint_sql)
        _psql(path=apply_path)
        assert _scalar(fingerprint_sql) == before_replay

        _psql(
            sql="UPDATE tariff_ingest.ett_normalization_results "
            "SET original_duty_text='corrupt' WHERE ordinal=1"
        )
        conflict_fingerprint = _scalar(fingerprint_sql)
        failed = _psql(path=apply_path, succeeds=False)
        assert "conflicting existing normalization version" in failed.stderr
        assert _scalar(fingerprint_sql) == conflict_fingerprint
        first = plan["rows"][0]
        escaped = first["original_duty_text"].replace("'", "''")
        _psql(
            sql="UPDATE tariff_ingest.ett_normalization_results "
            f"SET original_duty_text='{escaped}' WHERE ordinal=1"
        )

        next_plan = copy.deepcopy(plan)
        next_plan["normalizer_version"] = "ett-duty-syntax-v2"
        for row in next_plan["rows"]:
            row["parser_version"] = next_plan["normalizer_version"]
            payload = dict(row)
            payload.pop("result_sha256")
            row["result_sha256"] = sha256_json(payload)
        next_plan["normalization_digest"] = sha256_json(next_plan["rows"])
        next_sql = root / "apply-v2.sql"
        next_sql.write_text(_render_sql(next_plan), encoding="utf-8")
        _psql(path=next_sql)
        assert _scalar(
            "SELECT count(*) FROM tariff_ingest.ett_normalization_results"
        ) == "172"
        assert _scalar(
            "SELECT count(DISTINCT parser_version) "
            "FROM tariff_ingest.ett_normalization_results"
        ) == "2"

        trigger_sql = """
        CREATE FUNCTION tariff_ingest.reject_ett_plan_row() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN RETURN NULL; END $$;
        CREATE TRIGGER reject_ett_plan_row BEFORE INSERT
        ON tariff_ingest.ett_normalization_results
        FOR EACH ROW EXECUTE FUNCTION tariff_ingest.reject_ett_plan_row();
        """
        _psql(sql=trigger_sql)
        next_next_plan = copy.deepcopy(next_plan)
        next_next_plan["normalizer_version"] = "ett-duty-syntax-v3"
        for row in next_next_plan["rows"]:
            row["parser_version"] = next_next_plan["normalizer_version"]
            payload = dict(row)
            payload.pop("result_sha256")
            row["result_sha256"] = sha256_json(payload)
        trigger_sql_path = root / "apply-v3.sql"
        trigger_sql_path.write_text(_render_sql(next_next_plan), encoding="utf-8")
        trigger_failure = _psql(path=trigger_sql_path, succeeds=False)
        assert "unsupported triggers or RLS" in trigger_failure.stderr
        assert _scalar(
            "SELECT count(*) FROM tariff_ingest.ett_normalization_results"
        ) == "172"
        _psql(
            sql="DROP TRIGGER reject_ett_plan_row ON "
            "tariff_ingest.ett_normalization_results; "
            "DROP FUNCTION tariff_ingest.reject_ett_plan_row()"
        )
        _psql(
            sql="ALTER TABLE tariff_ingest.ett_normalization_results ENABLE ROW LEVEL SECURITY"
        )
        rls_failure = _psql(path=apply_path, succeeds=False)
        assert "unsupported triggers or RLS" in rls_failure.stderr
        _psql(
            sql="ALTER TABLE tariff_ingest.ett_normalization_results DISABLE ROW LEVEL SECURITY"
        )

        _psql(sql="DROP TABLE tariff_ingest.ett_normalization_results")
        _psql(
            sql="CREATE TABLE tariff_ingest.ett_normalization_results ("
            "source_id varchar(1), raw_row_sha256 text, ordinal integer, "
            "parser_version text, source_revision text, hs_code text, "
            "page_number integer, line_number integer, original_description text, "
            "original_supplementary_unit text, original_duty_text text, "
            "original_raw_line text, syntax_status text, normalized_rate_text text, "
            "is_ambiguous boolean, ambiguity_reason text, legal_status text, "
            "verified boolean, admitted boolean, result_sha256 text)"
        )
        schema_failure = _psql(path=apply_path, succeeds=False)
        assert "conflicting ett_normalization_results column contract" in schema_failure.stderr
        assert _scalar(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema='tariff_ingest'"
        ) == "8"

    print("PostgreSQL offline plan probe: first apply/replay/conflict/history/schema PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

