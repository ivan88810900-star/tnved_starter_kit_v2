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
from tests.test_ett_offline_plan_runner import (
    _build_legacy_append_package,
    _build_legacy_package,
    _build_package,
)


DATABASE = "tariff_staging"


def _psql(
    *,
    sql: str | None = None,
    path: Path | None = None,
    succeeds: bool = True,
    database: str = DATABASE,
    rollback: bool = False,
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
    script = None
    if path is not None:
        script = path.read_text(encoding="utf-8")
        boundary = "ROLLBACK" if rollback else "COMMIT"
        script = f"BEGIN;\n{script}\n{boundary};\n"
    else:
        command.extend(["--command", sql or ""])
    completed = subprocess.run(
        command,
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )
    diagnostics = (
        f"command return code: {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )
    if succeeds and completed.returncode != 0:
        raise AssertionError(diagnostics)
    if not succeeds and completed.returncode == 0:
        raise AssertionError("PostgreSQL command unexpectedly succeeded\n" + diagnostics)
    return completed


def _assert_error(completed: subprocess.CompletedProcess[str], expected: str) -> None:
    if expected not in completed.stderr:
        raise AssertionError(
            f"expected PostgreSQL error {expected!r}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )


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


def _setup_legacy_sql(plan) -> str:
    source_hex = _hex_json(plan["source_object"])
    runs_hex = _hex_json(plan["ingest_runs"])
    raw_hex = _hex_json(plan["raw_rows"])
    return f"""
WITH d AS (
  SELECT convert_from(decode('{source_hex}', 'hex'), 'UTF8')::jsonb AS j
)
INSERT INTO tariff_ingest.source_objects
SELECT j->>'source_id', j->>'authority', j->>'dataset', j->>'source_url',
       j->>'source_revision', j->>'object_bucket', j->>'object_key', j->>'sha256',
       (j->>'size_bytes')::bigint, j->>'media_type',
       (j->>'captured_at')::timestamptz, j->>'status' FROM d;
INSERT INTO tariff_ingest.ingest_runs (
  run_id, source_id, scope, parser_version, status, raw_count, unique_count,
  normalized_count, rejected_count, resume_cursor
)
SELECT x.run_id, x.source_id, x.scope, x.parser_version, x.status, x.raw_count,
       x.unique_count, x.normalized_count, x.rejected_count, x.resume_cursor
FROM jsonb_to_recordset(
  convert_from(decode('{runs_hex}', 'hex'), 'UTF8')::jsonb
) AS x(
  run_id text, source_id text, scope jsonb, parser_version text, status text,
  raw_count integer, unique_count integer, normalized_count integer,
  rejected_count integer, resume_cursor jsonb
);
INSERT INTO tariff_ingest.ett_collected_rows
SELECT * FROM jsonb_to_recordset(
  convert_from(decode('{raw_hex}', 'hex'), 'UTF8')::jsonb
) AS x(
  source_id text, hs_code text, description text, supplementary_unit text,
  duty_text text, raw_line text, row_sha256 text, status text, ordinal integer
);
"""


def _result_insert_sql(rows) -> str:
    rows_hex = _hex_json(rows)
    return f"""
INSERT INTO tariff_ingest.ett_normalization_results (
  source_id, raw_row_sha256, ordinal, parser_version, source_revision,
  hs_code, page_number, line_number, original_description,
  original_supplementary_unit, original_duty_text, original_raw_line,
  syntax_status, normalized_rate_text, is_ambiguous, ambiguity_reason,
  legal_status, verified, admitted, result_sha256
)
SELECT * FROM jsonb_to_recordset(
  convert_from(decode('{rows_hex}', 'hex'), 'UTF8')::jsonb
) AS x(
  source_id text, raw_row_sha256 text, ordinal integer, parser_version text,
  source_revision text, hs_code text, page_number integer, line_number integer,
  original_description text, original_supplementary_unit text,
  original_duty_text text, original_raw_line text, syntax_status text,
  normalized_rate_text text, is_ambiguous boolean, ambiguity_reason text,
  legal_status text, verified boolean, admitted boolean, result_sha256 text
);
"""


def _run_insert_sql(run) -> str:
    run_hex = _hex_json(run)
    return f"""
INSERT INTO tariff_ingest.ingest_runs (
  run_id, source_id, scope, parser_version, status, raw_count, unique_count,
  normalized_count, rejected_count, resume_cursor
)
SELECT x.run_id, x.source_id, x.scope, x.parser_version, x.status, x.raw_count,
       x.unique_count, x.normalized_count, x.rejected_count, x.resume_cursor
FROM jsonb_to_record(
  convert_from(decode('{run_hex}', 'hex'), 'UTF8')::jsonb
) AS x(
  run_id text, source_id text, scope jsonb, parser_version text, status text,
  raw_count integer, unique_count integer, normalized_count integer,
  rejected_count integer, resume_cursor jsonb
);
"""


def _raw_insert_sql(rows) -> str:
    rows_hex = _hex_json(rows)
    return f"""
INSERT INTO tariff_ingest.ett_collected_rows
SELECT * FROM jsonb_to_recordset(
  convert_from(decode('{rows_hex}', 'hex'), 'UTF8')::jsonb
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
        _assert_error(wrong_database, "offline plan targets tariff_staging only")
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
        _assert_error(duplicate_run, "exactly one raw ingest run")
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
        _assert_error(bad_source, "source_objects package mismatch")
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
        _assert_error(bad_raw, "ett_collected_rows package mismatch")
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
        _assert_error(lock_failure, "lock timeout")
        assert _scalar(
            "SELECT to_regclass('tariff_ingest.ett_normalization_results')"
        ) == ""
        holder_stdout, holder_stderr = holder.communicate(timeout=10)
        assert holder.returncode == 0, holder_stdout + holder_stderr

        _psql(path=apply_path, rollback=True)
        assert _scalar(
            "SELECT to_regclass('tariff_ingest.ett_normalization_results')"
        ) == ""
        assert _scalar(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema='tariff_ingest'"
        ) == "7"

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

        legacy_package_dir = root / "legacy-package"
        _build_legacy_package(legacy_package_dir)
        legacy_plan, legacy_sql = build_offline_artifacts(legacy_package_dir)
        legacy_setup = root / "legacy-setup.sql"
        legacy_setup.write_text(_setup_legacy_sql(legacy_plan), encoding="utf-8")
        _psql(path=legacy_setup)
        legacy_apply = root / "legacy-apply.sql"
        legacy_apply.write_text(legacy_sql, encoding="utf-8")
        legacy_source_id = legacy_plan["source_object"]["source_id"]
        _psql(sql="DROP TABLE tariff_ingest.ett_normalization_results")
        missing_target = _psql(path=legacy_apply, succeeds=False)
        _assert_error(
            missing_target, "legacy normalization target table is missing"
        )
        assert _scalar(
            "SELECT to_regclass('tariff_ingest.ett_normalization_results')"
        ) == ""
        _psql(path=apply_path)
        assert _scalar(
            "SELECT count(*) FROM tariff_ingest.ett_normalization_results"
        ) == "86"
        before_replay = _scalar(fingerprint_sql)
        staging_fingerprint_sql = (
            "SELECT md5(string_agg(v, ',' ORDER BY v)) FROM ("
            "SELECT 'source:' || xmin::text || ':' || to_jsonb(s)::text AS v "
            "FROM tariff_ingest.source_objects s "
            f"WHERE source_id='{legacy_source_id}' UNION ALL "
            "SELECT 'run:' || xmin::text || ':' || to_jsonb(r)::text "
            "FROM tariff_ingest.ingest_runs r "
            f"WHERE source_id='{legacy_source_id}' UNION ALL "
            "SELECT 'raw:' || xmin::text || ':' || to_jsonb(r)::text "
            "FROM tariff_ingest.ett_collected_rows r "
            f"WHERE source_id='{legacy_source_id}') x"
        )
        staging_before = _scalar(staging_fingerprint_sql)

        original_legacy_url = legacy_plan["source_object"]["source_url"].replace(
            "'", "''"
        )
        _psql(
            sql="UPDATE tariff_ingest.source_objects "
            "SET source_url='https://example.invalid/corrupt' "
            f"WHERE source_id='{legacy_source_id}'"
        )
        failure = _psql(path=legacy_apply, succeeds=False)
        _assert_error(failure, "source_objects package mismatch")
        _psql(
            sql="UPDATE tariff_ingest.source_objects "
            f"SET source_url='{original_legacy_url}' "
            f"WHERE source_id='{legacy_source_id}'"
        )

        first_run = legacy_plan["ingest_runs"][0]["run_id"]
        _psql(
            sql="UPDATE tariff_ingest.ingest_runs SET status='CORRUPT' "
            f"WHERE run_id='{first_run}'"
        )
        failure = _psql(path=legacy_apply, succeeds=False)
        _assert_error(failure, "legacy ingest_runs package mismatch")
        _psql(
            sql="UPDATE tariff_ingest.ingest_runs "
            "SET status='COLLECTED_UNVERIFIED' "
            f"WHERE run_id='{first_run}'"
        )

        first_description = legacy_plan["raw_rows"][0]["description"].replace(
            "'", "''"
        )
        _psql(
            sql="UPDATE tariff_ingest.ett_collected_rows SET description='corrupt' "
            f"WHERE source_id='{legacy_source_id}' AND ordinal=1"
        )
        failure = _psql(path=legacy_apply, succeeds=False)
        _assert_error(failure, "ett_collected_rows package mismatch")
        _psql(
            sql="UPDATE tariff_ingest.ett_collected_rows "
            f"SET description='{first_description}' "
            f"WHERE source_id='{legacy_source_id}' AND ordinal=1"
        )
        staging_before = _scalar(staging_fingerprint_sql)

        partial = copy.deepcopy(legacy_plan["rows"][0])
        partial["original_duty_text"] = "corrupt"
        _psql(sql=_result_insert_sql([partial]))
        partial_fingerprint = _scalar(
            "SELECT xmin::text || ':' || result_sha256 "
            "FROM tariff_ingest.ett_normalization_results "
            f"WHERE source_id='{legacy_source_id}'"
        )
        failure = _psql(path=legacy_apply, succeeds=False)
        _assert_error(failure, "conflicting existing normalization version")
        assert _scalar(
            "SELECT xmin::text || ':' || result_sha256 "
            "FROM tariff_ingest.ett_normalization_results "
            f"WHERE source_id='{legacy_source_id}'"
        ) == partial_fingerprint
        _psql(
            sql="DELETE FROM tariff_ingest.ett_normalization_results "
            f"WHERE source_id='{legacy_source_id}'"
        )

        _psql(path=legacy_apply, rollback=True)
        assert _scalar(
            "SELECT count(*) FROM tariff_ingest.ett_normalization_results"
        ) == "86"
        _psql(path=legacy_apply)
        assert _scalar(
            "SELECT count(*) FROM tariff_ingest.ett_normalization_results"
        ) == "619"
        assert _scalar(
            "SELECT count(*) FILTER (WHERE syntax_status='PARSED'), "
            "count(*) FILTER (WHERE is_ambiguous), "
            "count(*) FILTER (WHERE legal_status<>'UNVERIFIED'), "
            "count(*) FILTER (WHERE verified), count(*) FILTER (WHERE admitted) "
            "FROM tariff_ingest.ett_normalization_results"
        ) == "444|175|0|0|0"
        legacy_stored = json.loads(
            _scalar(
                "SELECT jsonb_agg(to_jsonb(r) ORDER BY ordinal)::text "
                "FROM tariff_ingest.ett_normalization_results r "
                f"WHERE source_id='{legacy_source_id}'"
            )
        )
        assert sha256_json(legacy_stored) == legacy_plan["normalization_digest"]
        legacy_fingerprint_sql = (
            "SELECT md5(string_agg(xmin::text || ':' || result_sha256, ',' "
            "ORDER BY ordinal)) FROM tariff_ingest.ett_normalization_results "
            f"WHERE source_id='{legacy_source_id}' "
            f"AND parser_version='{legacy_plan['normalizer_version']}'"
        )
        legacy_before_replay = _scalar(legacy_fingerprint_sql)
        _psql(path=legacy_apply)
        assert _scalar(legacy_fingerprint_sql) == legacy_before_replay
        assert _scalar(fingerprint_sql) == before_replay
        assert _scalar(staging_fingerprint_sql) == staging_before

        target_holder = subprocess.Popen(
            [
                "sudo", "-u", "postgres", "psql", "-X",
                "--set", "ON_ERROR_STOP=1", "--dbname", DATABASE,
                "--command",
                "BEGIN; LOCK TABLE tariff_ingest.ett_normalization_results "
                "IN ROW EXCLUSIVE MODE; SELECT pg_sleep(3); COMMIT;",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(30):
            if _scalar(
                "SELECT count(*) FROM pg_locks WHERE relation="
                "'tariff_ingest.ett_normalization_results'::regclass "
                "AND mode='RowExclusiveLock' AND granted"
            ) == "1":
                break
            time.sleep(0.1)
        else:
            raise AssertionError("target concurrent writer lock was not observed")
        locked_legacy_apply = root / "legacy-apply-locked.sql"
        locked_legacy_apply.write_text(
            "SET lock_timeout='200ms';\n" + legacy_sql, encoding="utf-8"
        )
        failure = _psql(path=locked_legacy_apply, succeeds=False)
        _assert_error(failure, "lock timeout")
        holder_stdout, holder_stderr = target_holder.communicate(timeout=10)
        assert target_holder.returncode == 0, holder_stdout + holder_stderr
        assert _scalar(legacy_fingerprint_sql) == legacy_before_replay

        _psql(
            sql="DELETE FROM tariff_ingest.ett_normalization_results "
            f"WHERE source_id='{legacy_source_id}'; "
            "DELETE FROM tariff_ingest.ett_collected_rows "
            f"WHERE source_id='{legacy_source_id}'; "
            "DELETE FROM tariff_ingest.ingest_runs "
            f"WHERE source_id='{legacy_source_id}'; "
            "DELETE FROM tariff_ingest.source_objects "
            f"WHERE source_id='{legacy_source_id}'"
        )
        assert _scalar(fingerprint_sql) == before_replay

        append_package_dir = root / "legacy-append-package"
        _build_legacy_append_package(append_package_dir)
        append_plan, append_sql = build_offline_artifacts(append_package_dir)
        append_source_id = append_plan["source_object"]["source_id"]
        append_base_plan = {
            "source_object": append_plan["source_object"],
            "ingest_runs": append_plan["base_ingest_runs"],
            "raw_rows": append_plan["base_raw_rows"],
        }
        append_setup = root / "legacy-append-setup.sql"
        append_setup.write_text(
            _setup_legacy_sql(append_base_plan)
            + _result_insert_sql(append_plan["base_results"]),
            encoding="utf-8",
        )
        _psql(path=append_setup)
        append_apply = root / "legacy-append-apply.sql"
        append_apply.write_text(append_sql, encoding="utf-8")
        assert _scalar(
            "SELECT count(*) FROM tariff_ingest.ett_normalization_results"
        ) == "619"
        assert _scalar(
            "SELECT count(*) FROM tariff_ingest.ingest_runs "
            f"WHERE source_id='{append_source_id}'"
        ) == "3"
        assert _scalar(
            "SELECT count(*) FROM tariff_ingest.ett_collected_rows "
            f"WHERE source_id='{append_source_id}'"
        ) == "533"

        schema_cases = (
            (
                "ingest nullability",
                "ALTER TABLE tariff_ingest.ingest_runs "
                "ALTER COLUMN status DROP NOT NULL",
                "append write table column contract mismatch: tariff_ingest.ingest_runs",
                "ALTER TABLE tariff_ingest.ingest_runs "
                "ALTER COLUMN status SET NOT NULL",
            ),
            (
                "ingest primary key",
                "ALTER TABLE tariff_ingest.ingest_runs "
                "DROP CONSTRAINT ingest_runs_pkey",
                "append write table constraint contract mismatch: tariff_ingest.ingest_runs",
                "ALTER TABLE tariff_ingest.ingest_runs ADD PRIMARY KEY (run_id)",
            ),
            (
                "raw column type",
                "ALTER TABLE tariff_ingest.ett_collected_rows "
                "ALTER COLUMN description TYPE varchar(200)",
                "append write table column contract mismatch: tariff_ingest.ett_collected_rows",
                "ALTER TABLE tariff_ingest.ett_collected_rows "
                "ALTER COLUMN description TYPE text",
            ),
            (
                "raw unique",
                "ALTER TABLE tariff_ingest.ett_collected_rows "
                "DROP CONSTRAINT ett_collected_rows_source_id_hs_code_key",
                "append write table constraint contract mismatch: tariff_ingest.ett_collected_rows",
                "ALTER TABLE tariff_ingest.ett_collected_rows "
                "ADD UNIQUE (source_id, hs_code)",
            ),
            (
                "normalization nullability",
                "ALTER TABLE tariff_ingest.ett_normalization_results "
                "ALTER COLUMN admitted DROP NOT NULL",
                "append write table column contract mismatch: "
                "tariff_ingest.ett_normalization_results",
                "ALTER TABLE tariff_ingest.ett_normalization_results "
                "ALTER COLUMN admitted SET NOT NULL",
            ),
            (
                "normalization foreign key",
                "ALTER TABLE tariff_ingest.ett_normalization_results "
                "DROP CONSTRAINT fk_ett_normalization_raw_row",
                "append write table constraint contract mismatch: "
                "tariff_ingest.ett_normalization_results",
                "ALTER TABLE tariff_ingest.ett_normalization_results "
                "ADD CONSTRAINT fk_ett_normalization_raw_row "
                "FOREIGN KEY (source_id, raw_row_sha256) "
                "REFERENCES tariff_ingest.ett_collected_rows "
                "(source_id, row_sha256)",
            ),
        )
        for label, mutate_schema, expected_error, restore_schema in schema_cases:
            _psql(sql=mutate_schema)
            failure = _psql(path=append_apply, succeeds=False)
            _assert_error(failure, expected_error)
            _psql(sql=restore_schema)
            assert _scalar(
                "SELECT count(*) FROM tariff_ingest.ett_normalization_results"
            ) == "619", label

        _psql(
            sql="ALTER TABLE tariff_ingest.ett_collected_rows "
            "ENABLE ROW LEVEL SECURITY"
        )
        failure = _psql(path=append_apply, succeeds=False)
        _assert_error(failure, "append targets have unsupported triggers or RLS")
        _psql(
            sql="ALTER TABLE tariff_ingest.ett_collected_rows "
            "DISABLE ROW LEVEL SECURITY"
        )
        _psql(
            sql="CREATE FUNCTION tariff_ingest.reject_append_run() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$; "
            "CREATE TRIGGER reject_append_run BEFORE INSERT "
            "ON tariff_ingest.ingest_runs FOR EACH ROW "
            "EXECUTE FUNCTION tariff_ingest.reject_append_run()"
        )
        failure = _psql(path=append_apply, succeeds=False)
        _assert_error(failure, "append targets have unsupported triggers or RLS")
        _psql(
            sql="DROP TRIGGER reject_append_run ON tariff_ingest.ingest_runs; "
            "DROP FUNCTION tariff_ingest.reject_append_run()"
        )

        _psql(path=append_apply, rollback=True)
        assert _scalar(
            "SELECT count(*) FROM tariff_ingest.ett_normalization_results"
        ) == "619"

        _psql(sql=_run_insert_sql(append_plan["append_ingest_run"]))
        failure = _psql(path=append_apply, succeeds=False)
        _assert_error(failure, "append current state is partial or conflicting")
        assert _scalar(
            "SELECT count(*) FROM tariff_ingest.ett_collected_rows "
            f"WHERE source_id='{append_source_id}'"
        ) == "533"
        _psql(
            sql="DELETE FROM tariff_ingest.ingest_runs "
            f"WHERE run_id='{append_plan['append_ingest_run']['run_id']}'"
        )

        _psql(sql=_raw_insert_sql(append_plan["append_raw_rows"][:1]))
        failure = _psql(path=append_apply, succeeds=False)
        _assert_error(failure, "append current state is partial or conflicting")
        assert _scalar(
            "SELECT count(*) FROM tariff_ingest.ingest_runs "
            f"WHERE source_id='{append_source_id}'"
        ) == "3"
        _psql(
            sql="DELETE FROM tariff_ingest.ett_collected_rows "
            f"WHERE source_id='{append_source_id}' AND ordinal=534"
        )

        append_holder = subprocess.Popen(
            [
                "sudo", "-u", "postgres", "psql", "-X",
                "--set", "ON_ERROR_STOP=1", "--dbname", DATABASE,
                "--command",
                "BEGIN; LOCK TABLE tariff_ingest.ett_collected_rows "
                "IN ROW EXCLUSIVE MODE; SELECT pg_sleep(3); COMMIT;",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(30):
            if _scalar(
                "SELECT count(*) FROM pg_locks WHERE relation="
                "'tariff_ingest.ett_collected_rows'::regclass "
                "AND mode='RowExclusiveLock' AND granted"
            ) == "1":
                break
            time.sleep(0.1)
        else:
            raise AssertionError("append concurrent writer lock was not observed")
        locked_append_apply = root / "legacy-append-apply-locked.sql"
        locked_append_apply.write_text(
            "SET lock_timeout='200ms';\n" + append_sql, encoding="utf-8"
        )
        failure = _psql(path=locked_append_apply, succeeds=False)
        _assert_error(failure, "lock timeout")
        holder_stdout, holder_stderr = append_holder.communicate(timeout=10)
        assert append_holder.returncode == 0, holder_stdout + holder_stderr

        append_old_staging_sql = (
            "SELECT md5(string_agg(v, ',' ORDER BY v)) FROM ("
            "SELECT 'source:' || xmin::text || ':' || to_jsonb(s)::text AS v "
            "FROM tariff_ingest.source_objects s "
            f"WHERE source_id='{append_source_id}' UNION ALL "
            "SELECT 'run:' || xmin::text || ':' || to_jsonb(r)::text "
            "FROM tariff_ingest.ingest_runs r "
            f"WHERE source_id='{append_source_id}' "
            f"AND run_id<>'{append_plan['append_ingest_run']['run_id']}' "
            "UNION ALL "
            "SELECT 'raw:' || xmin::text || ':' || to_jsonb(r)::text "
            "FROM tariff_ingest.ett_collected_rows r "
            f"WHERE source_id='{append_source_id}' AND ordinal <= 533) x"
        )
        append_old_results_sql = (
            "SELECT md5(string_agg(xmin::text || ':' || result_sha256, ',' "
            "ORDER BY ordinal)) FROM tariff_ingest.ett_normalization_results "
            f"WHERE source_id='{append_source_id}' AND ordinal <= 533"
        )
        append_old_staging = _scalar(append_old_staging_sql)
        append_old_results = _scalar(append_old_results_sql)
        _psql(path=append_apply)
        assert _scalar(
            "SELECT count(*) FROM tariff_ingest.ett_normalization_results"
        ) == "624"
        assert _scalar(
            "SELECT count(*) FILTER (WHERE syntax_status='PARSED'), "
            "count(*) FILTER (WHERE is_ambiguous), "
            "count(*) FILTER (WHERE legal_status<>'UNVERIFIED'), "
            "count(*) FILTER (WHERE verified), count(*) FILTER (WHERE admitted) "
            "FROM tariff_ingest.ett_normalization_results"
        ) == "447|177|0|0|0"
        assert _scalar(
            "SELECT count(*) FROM tariff_ingest.ingest_runs "
            f"WHERE source_id='{append_source_id}'"
        ) == "4"
        assert _scalar(
            "SELECT count(*) FROM tariff_ingest.ett_collected_rows "
            f"WHERE source_id='{append_source_id}'"
        ) == "538"
        assert _scalar(append_old_staging_sql) == append_old_staging
        assert _scalar(append_old_results_sql) == append_old_results
        stored_scope = json.loads(
            _scalar(
                "SELECT scope::text FROM tariff_ingest.ingest_runs "
                f"WHERE run_id='{append_plan['append_ingest_run']['run_id']}'"
            )
        )
        assert stored_scope["append_crosswalk_sha256"] == append_plan[
            "append_crosswalk_sha256"
        ]
        assert sha256_json(stored_scope["append_crosswalk"]) == append_plan[
            "append_crosswalk_sha256"
        ]
        assert [
            row["storage_ordinal"] for row in stored_scope["append_crosswalk"]
        ] == [534, 535, 536, 537, 538]
        assert [
            row["source_position"] for row in stored_scope["append_crosswalk"]
        ] != [534, 535, 536, 537, 538]
        append_all_fingerprint_sql = (
            "SELECT md5(string_agg(v, ',' ORDER BY v)) FROM ("
            "SELECT 'source:' || xmin::text || ':' || to_jsonb(s)::text AS v "
            "FROM tariff_ingest.source_objects s "
            f"WHERE source_id='{append_source_id}' UNION ALL "
            "SELECT 'run:' || xmin::text || ':' || to_jsonb(r)::text "
            "FROM tariff_ingest.ingest_runs r "
            f"WHERE source_id='{append_source_id}' UNION ALL "
            "SELECT 'raw:' || xmin::text || ':' || to_jsonb(r)::text "
            "FROM tariff_ingest.ett_collected_rows r "
            f"WHERE source_id='{append_source_id}' UNION ALL "
            "SELECT 'result:' || xmin::text || ':' || to_jsonb(r)::text "
            "FROM tariff_ingest.ett_normalization_results r "
            f"WHERE source_id='{append_source_id}') x"
        )
        append_all_fingerprint = _scalar(append_all_fingerprint_sql)
        _psql(path=append_apply)
        assert _scalar(append_all_fingerprint_sql) == append_all_fingerprint
        assert _scalar(append_old_staging_sql) == append_old_staging
        assert _scalar(append_old_results_sql) == append_old_results

        _psql(
            sql="DELETE FROM tariff_ingest.ett_normalization_results "
            f"WHERE source_id='{append_source_id}'; "
            "DELETE FROM tariff_ingest.ett_collected_rows "
            f"WHERE source_id='{append_source_id}'; "
            "DELETE FROM tariff_ingest.ingest_runs "
            f"WHERE source_id='{append_source_id}'; "
            "DELETE FROM tariff_ingest.source_objects "
            f"WHERE source_id='{append_source_id}'"
        )
        assert _scalar(fingerprint_sql) == before_replay

        _psql(
            sql="UPDATE tariff_ingest.ett_normalization_results "
            "SET original_duty_text='corrupt' WHERE ordinal=1"
        )
        conflict_fingerprint = _scalar(fingerprint_sql)
        failed = _psql(path=apply_path, succeeds=False)
        _assert_error(failed, "conflicting existing normalization version")
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
        _assert_error(trigger_failure, "unsupported triggers or RLS")
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
        _assert_error(rls_failure, "unsupported triggers or RLS")
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
        _assert_error(
            schema_failure, "conflicting ett_normalization_results column contract"
        )
        assert _scalar(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema='tariff_ingest'"
        ) == "8"

    print(
        "PostgreSQL offline plan probe: "
        "first apply/replay/conflict/history/schema/append5 PASS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


