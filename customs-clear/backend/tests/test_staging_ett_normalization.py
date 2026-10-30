from __future__ import annotations

import hashlib
import importlib.util
import os
from copy import deepcopy

import pytest
import sqlalchemy as sa
from sqlalchemy import MetaData, Table, create_engine, event, func, inspect, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateTable

from app.services.staging_ett_normalization import (
    COLLECTED_UNVERIFIED,
    ETT_NORMALIZER_VERSION,
    LEGAL_STATUS_UNVERIFIED,
    SYNTAX_AMBIGUOUS,
    SYNTAX_PARSED,
    _canonical_json,
    _sha256_text,
    build_ett_normalization_plan,
    ett_normalization_table,
    normalize_staged_ett,
)
from app.services.staging_nsi_ingest import StagingIngestError


SOURCE_ID = "eec-ett:group01:2022-04-25"
SOURCE_REVISION = "2022-04-25-group01"


def _package():
    source = {"source_id": SOURCE_ID, "source_revision": SOURCE_REVISION}
    rows = []
    provenance = []
    duties = ["0"] * 30 + ["5"] * 51 + ["5 63С)"] * 5
    for ordinal, duty in enumerate(duties, start=1):
        hs_code = f"{ordinal:010d}"
        description = f"Товар №{ordinal} — тест"
        supplementary_unit = "кг" if ordinal % 2 else ""
        raw_line = f"{hs_code}\t{description}\t{supplementary_unit}\t{duty}"
        payload = {
            "hs_code": hs_code,
            "description": description,
            "supplementary_unit": supplementary_unit,
            "duty_text": duty,
            "page_number": 1 + (ordinal - 1) // 20,
            "line_number": ordinal,
            "raw_line": raw_line,
        }
        row_sha = _sha256_text(payload)
        rows.append(
            {
                "source_id": SOURCE_ID,
                "row_sha256": row_sha,
                "ordinal": ordinal,
                "hs_code": hs_code,
                "description": description,
                "supplementary_unit": supplementary_unit,
                "duty_text": duty,
                "raw_line": raw_line,
                "status": COLLECTED_UNVERIFIED,
            }
        )
        provenance.append(
            {
                "ordinal": ordinal,
                "hs_code": hs_code,
                "row_sha256": row_sha,
                "page_number": payload["page_number"],
                "line_number": payload["line_number"],
            }
        )
    run = {
        "run_id": "raw-run",
        "source_id": SOURCE_ID,
        "scope": {
            "source_identity": {"source_revision": SOURCE_REVISION},
            "row_provenance": provenance,
        },
        "status": COLLECTED_UNVERIFIED,
        "raw_count": 86,
        "unique_count": 86,
    }
    return source, run, rows


def _raw_tables(metadata: MetaData):
    sources = Table(
        "source_objects",
        metadata,
        sa.Column("source_id", sa.Text, primary_key=True),
        sa.Column("source_revision", sa.Text, nullable=False),
    )
    runs = Table(
        "ingest_runs",
        metadata,
        sa.Column("run_id", sa.Text, primary_key=True),
        sa.Column("source_id", sa.Text, nullable=False),
        sa.Column("scope", sa.JSON, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("raw_count", sa.Integer, nullable=False),
        sa.Column("unique_count", sa.Integer, nullable=False),
    )
    rows = Table(
        "ett_collected_rows",
        metadata,
        sa.Column("source_id", sa.Text, primary_key=True),
        sa.Column("row_sha256", sa.Text, primary_key=True),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("hs_code", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("supplementary_unit", sa.Text, nullable=False),
        sa.Column("duty_text", sa.Text, nullable=False),
        sa.Column("raw_line", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
    )
    return sources, runs, rows


@pytest.fixture()
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'normalization.sqlite'}")

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    metadata = MetaData()
    sources, runs, rows = _raw_tables(metadata)
    ett_normalization_table(metadata, schema=None)
    metadata.create_all(engine)
    source, run, package_rows = _package()
    with engine.begin() as connection:
        connection.execute(sources.insert(), [source])
        connection.execute(runs.insert(), [run])
        connection.execute(rows.insert(), package_rows)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield engine, factory
    finally:
        engine.dispose()


def test_synthetic_86_accounted_with_exact_81_5_split_and_unverified_status():
    source, run, rows = _package()
    plan = build_ett_normalization_plan(source=source, ingest_run=run, raw_rows=rows)
    assert plan.raw_count == 86
    assert plan.parsed_count == 81
    assert plan.ambiguous_count == 5
    assert len(plan.rows) == 86
    assert {row.legal_status for row in plan.rows} == {LEGAL_STATUS_UNVERIFIED}
    assert not any(row.verified or row.admitted for row in plan.rows)
    qualified = plan.rows[-5:]
    assert all(row.original_duty_text == "5 63С)" for row in qualified)
    assert all(row.syntax_status == SYNTAX_AMBIGUOUS for row in qualified)
    assert all(row.normalized_rate_text is None for row in qualified)
    assert [row.normalized_rate_text for row in plan.rows[:30]] == ["0"] * 30
    assert [row.normalized_rate_text for row in plan.rows[30:81]] == ["5"] * 51


def test_leading_zeros_and_unicode_are_preserved_but_unicode_rate_is_ambiguous():
    source, run, rows = _package()
    rows = deepcopy(rows[:1])
    provenance = deepcopy(run["scope"]["row_provenance"][:1])
    rows[0]["hs_code"] = "0000000001"
    rows[0]["description"] = "Ёж — масло"
    rows[0]["duty_text"] = "５"
    rows[0]["raw_line"] = "0000000001 Ёж — масло ５"
    payload = {
        "hs_code": rows[0]["hs_code"],
        "description": rows[0]["description"],
        "supplementary_unit": rows[0]["supplementary_unit"],
        "duty_text": rows[0]["duty_text"],
        "page_number": provenance[0]["page_number"],
        "line_number": provenance[0]["line_number"],
        "raw_line": rows[0]["raw_line"],
    }
    rows[0]["row_sha256"] = _sha256_text(payload)
    provenance[0].update(hs_code=rows[0]["hs_code"], row_sha256=rows[0]["row_sha256"])
    run = deepcopy(run)
    run.update(raw_count=1, unique_count=1)
    run["scope"]["row_provenance"] = provenance
    plan = build_ett_normalization_plan(source=source, ingest_run=run, raw_rows=rows)
    assert plan.rows[0].hs_code == "0000000001"
    assert plan.rows[0].original_description == "Ёж — масло"
    assert plan.rows[0].is_ambiguous is True


def test_dry_run_uses_explicit_session_and_performs_zero_mutations(database, monkeypatch):
    engine, factory = database
    monkeypatch.setenv("DATABASE_URL", "postgresql://must-not-be-used.invalid/db")
    results = ett_normalization_table(MetaData(), schema=None)
    with factory() as session:
        outcome = normalize_staged_ett(session, source_id=SOURCE_ID, schema=None, dry_run=True)
        assert outcome.dry_run is True
        assert outcome.mutation_count == 0
        assert session.scalar(select(func.count()).select_from(results)) == 0
    assert os.environ["DATABASE_URL"].endswith("invalid/db")


def test_exact_replay_is_zero_mutation_same_digest_and_new_version_keeps_history(database):
    engine, factory = database
    results = ett_normalization_table(MetaData(), schema=None)
    with factory() as session, session.begin():
        first = normalize_staged_ett(session, source_id=SOURCE_ID, schema=None)
    with factory() as session, session.begin():
        replay = normalize_staged_ett(session, source_id=SOURCE_ID, schema=None)
        assert replay.replayed is True
        assert replay.mutation_count == 0
        assert replay.plan.digest == first.plan.digest
    with factory() as session, session.begin():
        second = normalize_staged_ett(
            session,
            source_id=SOURCE_ID,
            parser_version="ett-duty-syntax-v2",
            schema=None,
        )
        assert second.mutation_count == 86
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(results)) == 172


@pytest.mark.parametrize(
    "mutation,error",
    [
        (lambda source, run, rows: rows[0].update(row_sha256="0" * 64), "canonical raw row SHA mismatch"),
        (lambda source, run, rows: run["scope"].pop("row_provenance"), "row_provenance"),
        (lambda source, run, rows: rows[1].update(ordinal=1), "raw ordinals"),
        (lambda source, run, rows: rows.pop(1), "counts"),
        (lambda source, run, rows: rows[1].update(hs_code=rows[0]["hs_code"]), "duplicate raw"),
    ],
)
def test_corruption_conflicts_missing_provenance_duplicates_and_gaps_fail_before_write(mutation, error):
    source, run, rows = _package()
    mutation(source, run, rows)
    with pytest.raises(StagingIngestError, match=error):
        build_ett_normalization_plan(source=source, ingest_run=run, raw_rows=rows)


def test_unknown_text_is_accounted_as_ambiguous_not_silently_rejected():
    source, run, rows = _package()
    rows = deepcopy(rows[:1])
    provenance = deepcopy(run["scope"]["row_provenance"][:1])
    rows[0]["duty_text"] = "по специальной формуле"
    payload = {
        "hs_code": rows[0]["hs_code"],
        "description": rows[0]["description"],
        "supplementary_unit": rows[0]["supplementary_unit"],
        "duty_text": rows[0]["duty_text"],
        "page_number": provenance[0]["page_number"],
        "line_number": provenance[0]["line_number"],
        "raw_line": rows[0]["raw_line"],
    }
    rows[0]["row_sha256"] = _sha256_text(payload)
    provenance[0]["row_sha256"] = rows[0]["row_sha256"]
    run = deepcopy(run)
    run.update(raw_count=1, unique_count=1)
    run["scope"]["row_provenance"] = provenance
    plan = build_ett_normalization_plan(source=source, ingest_run=run, raw_rows=rows)
    assert plan.raw_count == plan.ambiguous_count == 1
    assert plan.rows[0].normalized_rate_text is None


def test_existing_result_conflict_fails_without_extra_mutation(database):
    engine, factory = database
    results = ett_normalization_table(MetaData(), schema=None)
    with factory() as session, session.begin():
        normalize_staged_ett(session, source_id=SOURCE_ID, schema=None)
    with engine.begin() as connection:
        connection.execute(
            results.update()
            .where(results.c.ordinal == 86)
            .values(original_duty_text="tampered")
        )
    with factory() as session:
        with pytest.raises(StagingIngestError, match="original_duty_text"):
            normalize_staged_ett(session, source_id=SOURCE_ID, schema=None)
        assert session.scalar(select(func.count()).select_from(results)) == 86


def test_caller_rollback_removes_the_whole_new_result_package(database):
    engine, factory = database
    results = ett_normalization_table(MetaData(), schema=None)
    with factory() as session:
        outcome = normalize_staged_ett(session, source_id=SOURCE_ID, schema=None)
        assert outcome.mutation_count == 86
        session.rollback()
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(results)) == 0


def test_last_row_corruption_proves_complete_validation_precedes_first_write(database):
    engine, factory = database
    raw = Table("ett_collected_rows", MetaData(), autoload_with=engine)
    results = ett_normalization_table(MetaData(), schema=None)
    with engine.begin() as connection:
        connection.execute(raw.update().where(raw.c.ordinal == 86).values(row_sha256="0" * 64))
    with factory() as session:
        with pytest.raises(StagingIngestError, match="row provenance identity mismatch"):
            normalize_staged_ett(session, source_id=SOURCE_ID, schema=None)
        assert session.scalar(select(func.count()).select_from(results)) == 0


def _load_migration():
    path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "alembic",
        "versions",
        "j4k5l6m7n8o9_ett_staging_normalization_results.py",
    )
    spec = importlib.util.spec_from_file_location("ett_normalization_migration", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_adds_one_table_and_preserves_existing_seven(tmp_path):
    migration = _load_migration()
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.sqlite'}")
    metadata = MetaData()
    raw_sources, raw_runs, raw_rows = _raw_tables(metadata)
    for number in range(4):
        Table(f"existing_staging_{number}", metadata, sa.Column("id", sa.Integer, primary_key=True))
    metadata.create_all(engine)
    before = set(inspect(engine).get_table_names())
    assert len(before) == 7
    migration.create_normalization_results(engine, schema=None)
    after = set(inspect(engine).get_table_names())
    assert before <= after
    assert after - before == {"ett_normalization_results"}
    migration.drop_normalization_results(engine, schema=None)
    assert set(inspect(engine).get_table_names()) == before
    engine.dispose()


def test_service_and_migration_contract_match_and_postgresql_ddl_dml_compile():
    migration = _load_migration()
    service_table = ett_normalization_table(MetaData())
    migration_table = migration.normalization_results_table(MetaData())
    assert list(service_table.c.keys()) == list(migration_table.c.keys())
    ddl = str(CreateTable(migration_table).compile(dialect=postgresql.dialect()))
    assert "tariff_ingest.ett_normalization_results" in ddl
    statement = service_table.insert().values(
        source_id=SOURCE_ID,
        raw_row_sha256="a" * 64,
        ordinal=1,
        parser_version=ETT_NORMALIZER_VERSION,
        source_revision=SOURCE_REVISION,
        hs_code="0000000001",
        page_number=1,
        line_number=1,
        original_description="товар",
        original_supplementary_unit="",
        original_duty_text="5",
        original_raw_line="raw",
        syntax_status=SYNTAX_PARSED,
        normalized_rate_text="5",
        is_ambiguous=False,
        ambiguity_reason=None,
        legal_status=LEGAL_STATUS_UNVERIFIED,
        verified=False,
        admitted=False,
        result_sha256="b" * 64,
    )
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "tariff_ingest.ett_normalization_results" in compiled

