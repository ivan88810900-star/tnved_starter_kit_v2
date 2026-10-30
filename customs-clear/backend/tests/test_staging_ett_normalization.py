from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
from copy import deepcopy
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy import MetaData, Table, create_engine, event, func, inspect, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.schema import CreateTable

from app.services.staging_ett_ingest import (
    ETT_PARSER_VERSION as RAW_ETT_PARSER_VERSION,
    EttCollectedRow,
    ett_staging_tables,
    ingest_ett_rows,
)
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
from app.services.staging_nsi_ingest import SourceObject, StagingIngestError


SOURCE_ID = "eec-ett:group01:2022-04-25"
SOURCE_REVISION = "2022-04-25-group01"
SOURCE_BYTES = b"synthetic immutable ETT group01 bytes"


def _source_object() -> SourceObject:
    return SourceObject(
        source_id=SOURCE_ID,
        authority="EEC",
        dataset="EEC-ETT",
        source_url="https://eec.eaeunion.org/upload/ett/group01.pdf",
        source_revision=SOURCE_REVISION,
        object_bucket="official-originals",
        object_key="ett/2022-04-25/group01/original.pdf",
        sha256=hashlib.sha256(SOURCE_BYTES).hexdigest(),
        size_bytes=len(SOURCE_BYTES),
        media_type="application/pdf",
        captured_at=datetime(2026, 10, 30, tzinfo=timezone.utc),
    )


def _collected_rows() -> list[EttCollectedRow]:
    result = []
    duties = ["0"] * 30 + ["5"] * 51 + ["5 63С)"] * 5
    for ordinal, duty in enumerate(duties, start=1):
        hs_code = f"{ordinal:010d}"
        description = f"Товар №{ordinal} — тест"
        supplementary_unit = "кг" if ordinal % 2 else ""
        result.append(
            EttCollectedRow(
                ordinal=ordinal,
                hs_code=hs_code,
                description=description,
                supplementary_unit=supplementary_unit,
                duty_text=duty,
                page_number=1 + (ordinal - 1) // 20,
                line_number=ordinal,
                raw_line=(
                    f"{hs_code}\t{description}\t{supplementary_unit}\t{duty}"
                ),
            )
        )
    return result


def _package():
    source_object = _source_object()
    source = {
        "source_id": source_object.source_id,
        "source_url": source_object.source_url,
        "source_revision": source_object.source_revision,
        "object_bucket": source_object.object_bucket,
        "object_key": source_object.object_key,
        "sha256": source_object.sha256,
        "size_bytes": source_object.size_bytes,
    }
    rows = []
    provenance = []
    for row in _collected_rows():
        payload = {
            "hs_code": row.hs_code,
            "description": row.description,
            "supplementary_unit": row.supplementary_unit,
            "duty_text": row.duty_text,
            "page_number": row.page_number,
            "line_number": row.line_number,
            "raw_line": row.raw_line,
        }
        row_sha = _sha256_text(payload)
        rows.append(
            {
                "source_id": SOURCE_ID,
                "row_sha256": row_sha,
                "ordinal": row.ordinal,
                "hs_code": row.hs_code,
                "description": row.description,
                "supplementary_unit": row.supplementary_unit,
                "duty_text": row.duty_text,
                "raw_line": row.raw_line,
                "status": COLLECTED_UNVERIFIED,
            }
        )
        provenance.append(
            {
                "ordinal": row.ordinal,
                "hs_code": row.hs_code,
                "row_sha256": row_sha,
                "page_number": payload["page_number"],
                "line_number": payload["line_number"],
            }
        )
    source_scope = {"group": "01"}
    identity = {
        "source_id": source_object.source_id,
        "source_sha256": source_object.sha256,
        "source_size_bytes": source_object.size_bytes,
        "source_url": source_object.source_url,
        "source_revision": source_object.source_revision,
        "object_bucket": source_object.object_bucket,
        "object_key": source_object.object_key,
        "scope": source_scope,
        "parser_version": RAW_ETT_PARSER_VERSION,
    }
    run = {
        "run_id": f"ett:{_sha256_text(identity)}",
        "source_id": SOURCE_ID,
        "scope": {
            **source_scope,
            "source_identity": identity,
            "stage_counts": {"normalized": 0, "verified": 0, "admitted": 0},
            "row_provenance": provenance,
        },
        "parser_version": RAW_ETT_PARSER_VERSION,
        "status": COLLECTED_UNVERIFIED,
        "raw_count": 86,
        "unique_count": 86,
    }
    return source, run, rows


@pytest.fixture()
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'normalization.sqlite'}")

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    metadata = MetaData()
    ett_staging_tables(metadata, schema=None)
    ett_normalization_table(metadata, schema=None)
    metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session, session.begin():
        ingest_ett_rows(
            session,
            source=_source_object(),
            source_bytes=SOURCE_BYTES,
            rows=_collected_rows(),
            scope={"group": "01"},
            schema=None,
            now=datetime(2026, 10, 30, tzinfo=timezone.utc),
        )
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


def _corrupt_raw_hash_only(source, run, rows):
    rows[0]["row_sha256"] = "0" * 64


def _corrupt_raw_and_provenance_hash(source, run, rows):
    rows[0]["row_sha256"] = "0" * 64
    run["scope"]["row_provenance"][0]["row_sha256"] = "0" * 64


@pytest.mark.parametrize(
    "mutation,error",
    [
        (_corrupt_raw_hash_only, "row provenance identity mismatch"),
        (_corrupt_raw_and_provenance_hash, "canonical raw row SHA mismatch"),
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


def test_boolean_ordinals_are_not_accepted_as_integers():
    source, run, rows = _package()
    rows[0]["ordinal"] = True
    run["scope"]["row_provenance"][0]["ordinal"] = True
    with pytest.raises(StagingIngestError, match="raw ordinal"):
        build_ett_normalization_plan(source=source, ingest_run=run, raw_rows=rows)


def test_real_raw_ingest_fixture_rejects_boolean_provenance_before_write(database):
    engine, factory = database
    raw_tables = ett_staging_tables(MetaData(), schema=None)
    results = ett_normalization_table(MetaData(), schema=None)
    with engine.begin() as connection:
        run = connection.execute(select(raw_tables["ingest_runs"])).mappings().one()
        scope = deepcopy(run["scope"])
        scope["row_provenance"][0]["ordinal"] = True
        connection.execute(
            raw_tables["ingest_runs"].update().values(scope=scope)
        )
    with factory() as session:
        with pytest.raises(StagingIngestError, match="provenance ordinal"):
            normalize_staged_ett(
                session, source_id=SOURCE_ID, schema=None, dry_run=True
            )
        assert session.scalar(select(func.count()).select_from(results)) == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_id", "different-source"),
        ("source_sha256", "0" * 64),
        ("source_url", "https://eec.eaeunion.org/upload/ett/other.pdf"),
        ("object_key", "ett/other/original.pdf"),
    ],
)
def test_full_stored_identity_must_match_source_objects_even_with_rehashed_run_id(
    database, field, value
):
    engine, factory = database
    raw_tables = ett_staging_tables(MetaData(), schema=None)
    results = ett_normalization_table(MetaData(), schema=None)
    with engine.begin() as connection:
        run = connection.execute(select(raw_tables["ingest_runs"])).mappings().one()
        scope = deepcopy(run["scope"])
        scope["source_identity"][field] = value
        new_run_id = f"ett:{_sha256_text(scope['source_identity'])}"
        connection.execute(
            raw_tables["ingest_runs"]
            .update()
            .values(run_id=new_run_id, scope=scope)
        )
    with factory() as session:
        with pytest.raises(StagingIngestError, match="source_identity"):
            normalize_staged_ett(
                session, source_id=SOURCE_ID, schema=None, dry_run=True
            )
        assert session.scalar(select(func.count()).select_from(results)) == 0


def test_deterministic_raw_run_id_is_recomputed_before_write(database):
    engine, factory = database
    raw_tables = ett_staging_tables(MetaData(), schema=None)
    results = ett_normalization_table(MetaData(), schema=None)
    with engine.begin() as connection:
        connection.execute(
            raw_tables["ingest_runs"].update().values(run_id=f"ett:{'0' * 64}")
        )
    with factory() as session:
        with pytest.raises(StagingIngestError, match="run_id mismatch"):
            normalize_staged_ett(
                session, source_id=SOURCE_ID, schema=None, dry_run=True
            )
        assert session.scalar(select(func.count()).select_from(results)) == 0


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


def test_insert_failure_after_partial_execution_requires_and_honors_caller_rollback(database):
    engine, factory = database
    results = ett_normalization_table(MetaData(), schema=None)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TRIGGER fail_ett_normalization_ordinal_43
            BEFORE INSERT ON ett_normalization_results
            WHEN NEW.ordinal = 43
            BEGIN
                SELECT RAISE(ABORT, 'injected normalization failure');
            END
            """
        )
    with factory() as session:
        with pytest.raises(StagingIngestError, match="conflicting concurrent"):
            normalize_staged_ett(session, source_id=SOURCE_ID, schema=None)
        session.rollback()
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(results)) == 0


def test_dry_run_disables_autoflush_of_unrelated_pending_orm_state(database):
    engine, factory = database

    class Base(DeclarativeBase):
        pass

    class PendingSentinel(Base):
        __tablename__ = "pending_sentinel"

        id: Mapped[int] = mapped_column(primary_key=True)

    Base.metadata.create_all(engine)
    with factory() as session:
        sentinel = PendingSentinel(id=1)
        session.add(sentinel)
        flushed = []

        @event.listens_for(session, "before_flush")
        def _record_flush(_session, _context, _instances):
            flushed.append(True)

        result = normalize_staged_ett(
            session, source_id=SOURCE_ID, schema=None, dry_run=True
        )
        assert result.mutation_count == 0
        assert flushed == []
        assert sentinel in session.new
        session.rollback()
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(PendingSentinel)) == 0


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
        "scripts",
        "staging_migrations",
        "ett_normalization_results_v1.py",
    )
    spec = importlib.util.spec_from_file_location("ett_normalization_migration", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    return module


def _create_conflicting_result_table(engine, defect):
    metadata = MetaData()
    Table(
        "ett_collected_rows",
        metadata,
        sa.Column("source_id", sa.Text, primary_key=True),
        sa.Column("row_sha256", sa.Text, primary_key=True),
    )
    expected = ett_normalization_table(MetaData(), schema=None)
    columns = []
    for column in expected.columns:
        column_type = sa.Integer if defect == "type" and column.name == "source_id" else column.type
        if defect == "varchar_length" and column.name == "source_id":
            column_type = sa.String(1)
        nullable = column.nullable
        if defect == "nullability" and column.name == "normalized_rate_text":
            nullable = False
        columns.append(sa.Column(column.name, column_type, nullable=nullable))
    constraints = []
    if defect != "primary_key":
        constraints.append(sa.PrimaryKeyConstraint("source_id", "raw_row_sha256", "parser_version"))
    if defect != "unique":
        constraints.extend(
            [
                sa.UniqueConstraint(
                    "source_id",
                    "ordinal",
                    "parser_version",
                    name="uq_ett_normalization_source_ordinal_version",
                ),
                sa.UniqueConstraint(
                    "result_sha256", name="uq_ett_normalization_result_sha256"
                ),
            ]
        )
    if defect != "foreign_key":
        foreign_key_options = {}
        if defect == "foreign_key_ondelete":
            foreign_key_options["ondelete"] = "CASCADE"
        if defect == "foreign_key_deferrable":
            foreign_key_options["deferrable"] = True
        constraints.append(
            sa.ForeignKeyConstraint(
                ["source_id", "raw_row_sha256"],
                ["ett_collected_rows.source_id", "ett_collected_rows.row_sha256"],
                name="fk_ett_normalization_raw_row",
                **foreign_key_options,
            )
        )
    Table("ett_normalization_results", metadata, *columns, *constraints)
    metadata.create_all(engine)


@pytest.mark.parametrize(
    "defect",
    [
        "type",
        "varchar_length",
        "nullability",
        "primary_key",
        "unique",
        "foreign_key",
        "foreign_key_ondelete",
        "foreign_key_deferrable",
    ],
)
def test_migration_rejects_conflicting_existing_contract_without_mutation(
    tmp_path, defect
):
    migration = _load_migration()
    engine = create_engine(f"sqlite:///{tmp_path / f'conflict-{defect}.sqlite'}")
    _create_conflicting_result_table(engine, defect)
    before = set(inspect(engine).get_table_names())
    with engine.begin() as connection:
        with pytest.raises(RuntimeError, match="conflicting existing"):
            migration.apply(connection, schema=None)
        assert set(inspect(connection).get_table_names()) == before
        with pytest.raises(RuntimeError, match="refusing to drop conflicting"):
            migration.revert(connection, schema=None)
        assert set(inspect(connection).get_table_names()) == before
    engine.dispose()


def test_migration_adds_one_table_and_preserves_existing_seven(tmp_path):
    migration = _load_migration()
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.sqlite'}")
    metadata = MetaData()
    ett_staging_tables(metadata, schema=None)
    for number in range(4):
        Table(f"existing_staging_{number}", metadata, sa.Column("id", sa.Integer, primary_key=True))
    metadata.create_all(engine)
    before = set(inspect(engine).get_table_names())
    assert len(before) == 7
    commit_events = []
    with engine.begin() as connection:
        event.listen(connection, "commit", lambda _connection: commit_events.append(True))
        first = migration.apply(connection, schema=None)
        assert first.created is True
        after = set(inspect(connection).get_table_names())
        assert before <= after
        assert after - before == {"ett_normalization_results"}
        replay = migration.apply(connection, schema=None)
        assert replay.created is False
        reverted = migration.revert(connection, schema=None)
        assert reverted.created is True
        assert connection.in_transaction()
        assert commit_events == []
    assert set(inspect(engine).get_table_names()) == before
    engine.dispose()


def test_migration_requires_connection_with_active_caller_transaction(tmp_path):
    migration = _load_migration()
    engine = create_engine(f"sqlite:///{tmp_path / 'transaction-contract.sqlite'}")
    with pytest.raises(TypeError, match="Connection, not an Engine"):
        migration.apply(engine, schema=None)
    with engine.connect() as connection:
        assert not connection.in_transaction()
        with pytest.raises(RuntimeError, match="active caller-owned transaction"):
            migration.apply(connection, schema=None)
    assert "ett_normalization_results" not in inspect(engine).get_table_names()
    engine.dispose()


def test_service_and_migration_contract_match_and_postgresql_ddl_dml_compile():
    migration = _load_migration()
    service_table = ett_normalization_table(MetaData())
    migration_table = ett_normalization_table(MetaData())
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

