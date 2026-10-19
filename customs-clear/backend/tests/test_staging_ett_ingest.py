from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from sqlalchemy import MetaData, create_engine, event, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker

from app.services.staging_ett_ingest import EttCollectedRow, ett_staging_tables, ingest_ett_rows
from app.services.staging_nsi_ingest import COLLECTED_UNVERIFIED, SourceObject, StagingIngestError


SOURCE_BYTES = b"immutable official ETT group 01 PDF bytes"


def _source(**changes) -> SourceObject:
    value = SourceObject(
        source_id="ett-group-01-2026-10-19",
        authority="EEC",
        dataset="EEC-ETT",
        source_url="https://eec.eaeunion.org/upload/ett/group01.pdf",
        source_revision="ett-2026-10-19-group01",
        object_bucket="official-originals",
        object_key="ett/2026-10-19/group01.pdf",
        sha256=hashlib.sha256(SOURCE_BYTES).hexdigest(),
        size_bytes=len(SOURCE_BYTES),
        media_type="application/pdf",
        captured_at=datetime(2026, 10, 19, tzinfo=timezone.utc),
    )
    return replace(value, **changes)


def _rows(count: int = 3) -> list[EttCollectedRow]:
    return [
        EttCollectedRow(
            ordinal=index,
            hs_code=f"{index - 1:010d}",
            description=f"Товар {index}",
            supplementary_unit="кг",
            duty_text=f"{index}%",
            page_number=1 + (index // 2),
            line_number=index,
            raw_line=f"{index - 1:010d} Товар {index} кг {index}%",
        )
        for index in range(1, count + 1)
    ]


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'ett.sqlite'}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    metadata = MetaData()
    ett_staging_tables(metadata, schema=None)
    metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def _ingest(session, **kwargs):
    return ingest_ett_rows(
        session,
        source=kwargs.pop("source", _source()),
        source_bytes=kwargs.pop("source_bytes", SOURCE_BYTES),
        rows=kwargs.pop("rows", _rows()),
        scope=kwargs.pop("scope", {"group": "01", "pages": [1, 2]}),
        schema=None,
        now=datetime(2026, 10, 19, 17, 30, tzinfo=timezone.utc),
        **kwargs,
    )


def test_atomic_success_preserves_leading_zeros_and_unverified_counts(db) -> None:
    tables = ett_staging_tables(MetaData(), schema=None)
    with db() as session, session.begin():
        result = _ingest(session)
        assert result.replayed is False
        assert result.raw_count == result.unique_count == 3
        assert result.next_ordinal == 4
    with db() as session:
        run = session.execute(select(tables["ingest_runs"])).mappings().one()
        captured = session.execute(select(tables["ett_collected_rows"]).order_by(tables["ett_collected_rows"].c.ordinal)).mappings().all()
        assert [row["hs_code"] for row in captured] == ["0000000000", "0000000001", "0000000002"]
        assert all(row["status"] == COLLECTED_UNVERIFIED for row in captured)
        assert all(len(row["row_sha256"]) == 64 for row in captured)
        assert run["status"] == COLLECTED_UNVERIFIED
        assert run["raw_count"] == run["unique_count"] == 3
        assert run["normalized_count"] == run["rejected_count"] == 0
        assert run["scope"]["stage_counts"] == {
            "normalized": 0,
            "verified": 0,
            "admitted": 0,
        }
        assert run["scope"]["row_provenance"] == [
            {
                "ordinal": row.ordinal,
                "hs_code": row.hs_code,
                "row_sha256": stored["row_sha256"],
                "page_number": row.page_number,
                "line_number": row.line_number,
            }
            for row, stored in zip(_rows(), captured)
        ]
        assert run["resume_cursor"] == {"next_ordinal": 4, "raw_count": 3, "complete": True}


def test_exact_replay_is_read_only_and_creates_no_duplicates(db) -> None:
    tables = ett_staging_tables(MetaData(), schema=None)
    with db() as session, session.begin():
        first = _ingest(session)
    with db() as session, session.begin():
        before = session.execute(select(tables["ingest_runs"].c.updated_at)).scalar_one()
        replay = _ingest(session)
        assert replay.run_id == first.run_id
        assert replay.replayed is True
        assert session.scalar(select(func.count()).select_from(tables["source_objects"])) == 1
        assert session.scalar(select(func.count()).select_from(tables["ingest_runs"])) == 1
        assert session.scalar(select(func.count()).select_from(tables["ett_collected_rows"])) == 3
        assert session.execute(select(tables["ingest_runs"].c.updated_at)).scalar_one() == before


def test_raw_text_is_preserved_exactly(db) -> None:
    tables = ett_staging_tables(MetaData(), schema=None)
    source_row = replace(
        _rows()[0],
        description="  Товар из PDF  ",
        supplementary_unit=" шт ",
        duty_text=" 5 % ",
        raw_line="  0000000000  Товар из PDF  5 %  ",
    )
    with db() as session, session.begin():
        _ingest(session, rows=[source_row])
    with db() as session:
        stored = session.execute(select(tables["ett_collected_rows"])).mappings().one()
        assert stored["description"] == source_row.description
        assert stored["supplementary_unit"] == source_row.supplementary_unit
        assert stored["duty_text"] == source_row.duty_text
        assert stored["raw_line"] == source_row.raw_line


@pytest.mark.parametrize(
    "rows,error",
    [
        (_rows(87), "between 1 and 86"),
        ([replace(_rows()[0], hs_code="123")], "10-digit"),
        ([replace(_rows()[0], ordinal=2)], "contiguous"),
        ([_rows()[0], replace(_rows()[1], hs_code=_rows()[0].hs_code)], "duplicate ETT hs_code"),
        ([_rows()[0], replace(_rows()[1], ordinal=1)], "contiguous"),
        (
            [_rows()[0], replace(_rows()[0], ordinal=2)],
            "duplicate ETT row_sha256",
        ),
        ([replace(_rows()[0], description="")], "description is required"),
        ([replace(_rows()[0], raw_line="")], "raw_line is required"),
    ],
)
def test_invalid_rows_fail_before_any_write(db, rows, error) -> None:
    tables = ett_staging_tables(MetaData(), schema=None)
    with db() as session:
        with pytest.raises(StagingIngestError, match=error):
            _ingest(session, rows=rows)
        assert session.scalar(select(func.count()).select_from(tables["source_objects"])) == 0
        assert session.scalar(select(func.count()).select_from(tables["ingest_runs"])) == 0
        assert session.scalar(select(func.count()).select_from(tables["ett_collected_rows"])) == 0


@pytest.mark.parametrize(
    "source,source_bytes",
    [
        (_source(sha256="0" * 64), SOURCE_BYTES),
        (_source(size_bytes=1), SOURCE_BYTES),
        (_source(source_url="relative.pdf"), SOURCE_BYTES),
        (_source(source_revision=" changed "), SOURCE_BYTES),
        (_source(object_key=" other.pdf "), SOURCE_BYTES),
    ],
)
def test_source_identity_and_content_are_exact(db, source, source_bytes) -> None:
    with db() as session, pytest.raises(StagingIngestError):
        _ingest(session, source=source, source_bytes=source_bytes)


@pytest.mark.parametrize(
    "changes",
    [
        {"authority": "ATTACKER"},
        {"source_url": "http://eec.eaeunion.org/upload/ett/group01.pdf"},
        {"source_url": "https://evil.example/upload/ett/group01.pdf"},
        {"source_url": "https://eec.eaeunion.org.evil.example/group01.pdf"},
        {"source_url": "https://eec.eaeunion.org@evil.example/group01.pdf"},
        {"source_url": "https://user@eec.eaeunion.org/group01.pdf"},
        {"source_url": "https://eec.eaeunion.org:443/group01.pdf"},
        {"source_url": "https://eec.eaeunion.org/group01.pdf#alternate"},
    ],
)
def test_official_eec_provenance_boundary_rejects_lookalikes(db, changes) -> None:
    with db() as session, pytest.raises(StagingIngestError):
        _ingest(session, source=_source(**changes))


def test_future_official_eec_pdf_paths_and_queries_are_not_hardcoded(db) -> None:
    source = _source(
        source_url="https://eec.eaeunion.org/upload/ett/2030/group97.pdf?download=1"
    )
    with db() as session, session.begin():
        result = _ingest(session, source=source)
        assert result.replayed is False


def test_conflicting_source_run_and_row_fail_without_mutating_unrelated_rows(db) -> None:
    tables = ett_staging_tables(MetaData(), schema=None)
    with db() as session, session.begin():
        first = _ingest(session)
        unrelated_source = _source(
            source_id="unrelated-source",
            source_url="https://eec.eaeunion.org/upload/ett/unrelated.pdf",
            source_revision="unrelated-revision",
            object_key="ett/unrelated.pdf",
        )
        session.execute(
            tables["source_objects"].insert().values(
                source_id=unrelated_source.source_id,
                authority=unrelated_source.authority,
                dataset=unrelated_source.dataset,
                source_url=unrelated_source.source_url,
                source_revision=unrelated_source.source_revision,
                object_bucket=unrelated_source.object_bucket,
                object_key=unrelated_source.object_key,
                sha256=unrelated_source.sha256,
                size_bytes=unrelated_source.size_bytes,
                media_type=unrelated_source.media_type,
                captured_at=unrelated_source.captured_at,
                status=COLLECTED_UNVERIFIED,
            )
        )
        session.execute(
            tables["ett_collected_rows"].insert().values(
                ordinal=1,
                source_id="unrelated-source",
                hs_code="9999999999",
                description="unrelated",
                supplementary_unit="",
                duty_text="",
                raw_line="unrelated",
                row_sha256="f" * 64,
                status=COLLECTED_UNVERIFIED,
            )
        )
    with db() as session, session.begin():
        session.execute(tables["ingest_runs"].update().where(tables["ingest_runs"].c.run_id == first.run_id).values(raw_count=99))
    with db() as session:
        with pytest.raises(StagingIngestError, match="ingest_runs.raw_count"):
            _ingest(session)
        assert session.scalar(select(func.count()).select_from(tables["ett_collected_rows"]).where(tables["ett_collected_rows"].c.source_id == "unrelated-source")) == 1

    with db() as session, session.begin():
        session.execute(tables["ingest_runs"].update().where(tables["ingest_runs"].c.run_id == first.run_id).values(raw_count=3))
        session.execute(tables["ett_collected_rows"].update().where((tables["ett_collected_rows"].c.source_id == first.source_id) & (tables["ett_collected_rows"].c.ordinal == 1)).values(description="tampered"))
    with db() as session:
        with pytest.raises(StagingIngestError, match="ett_collected_rows.description"):
            _ingest(session)
        assert session.scalar(select(func.count()).select_from(tables["ett_collected_rows"]).where(tables["ett_collected_rows"].c.source_id == "unrelated-source")) == 1

    with db() as session, session.begin():
        session.execute(tables["ett_collected_rows"].update().where((tables["ett_collected_rows"].c.source_id == first.source_id) & (tables["ett_collected_rows"].c.ordinal == 1)).values(description=_rows()[0].description))
        run = session.execute(select(tables["ingest_runs"]).where(tables["ingest_runs"].c.run_id == first.run_id)).mappings().one()
        scope = dict(run["scope"])
        provenance = [dict(item) for item in scope["row_provenance"]]
        provenance[0]["page_number"] = 99
        scope["row_provenance"] = provenance
        session.execute(tables["ingest_runs"].update().where(tables["ingest_runs"].c.run_id == first.run_id).values(scope=scope))
    with db() as session:
        with pytest.raises(StagingIngestError, match="ingest_runs.scope"):
            _ingest(session)
        assert session.scalar(select(func.count()).select_from(tables["ett_collected_rows"]).where(tables["ett_collected_rows"].c.source_id == "unrelated-source")) == 1


def test_existing_source_identity_conflict_fails_before_new_run(db) -> None:
    tables = ett_staging_tables(MetaData(), schema=None)
    with db() as session, session.begin():
        _ingest(session)
    changed_bytes = b"different immutable official ETT bytes"
    changed = _source(
        sha256=hashlib.sha256(changed_bytes).hexdigest(),
        size_bytes=len(changed_bytes),
        source_revision="ett-2026-10-19-group01-amended",
    )
    with db() as session:
        with pytest.raises(StagingIngestError, match="source_objects.source_revision"):
            _ingest(session, source=changed, source_bytes=changed_bytes)
        assert session.scalar(select(func.count()).select_from(tables["ingest_runs"])) == 1
        assert session.scalar(select(func.count()).select_from(tables["ett_collected_rows"])) == 3


def test_caller_rollback_removes_whole_new_capture(db) -> None:
    tables = ett_staging_tables(MetaData(), schema=None)
    with db() as session:
        _ingest(session)
        session.rollback()
    with db() as session:
        assert session.scalar(select(func.count()).select_from(tables["source_objects"])) == 0
        assert session.scalar(select(func.count()).select_from(tables["ingest_runs"])) == 0
        assert session.scalar(select(func.count()).select_from(tables["ett_collected_rows"])) == 0


def test_exact_86_rows_advance_cursor_to_87(db) -> None:
    with db() as session, session.begin():
        result = _ingest(session, rows=_rows(86))
        assert result.raw_count == 86
        assert result.next_ordinal == 87


def test_postgresql_contract_compiles() -> None:
    tables = ett_staging_tables(MetaData())
    statement = tables["ett_collected_rows"].insert().values(
        ordinal=1,
        source_id="source",
        hs_code="0000000001",
        description="товар",
        supplementary_unit="кг",
        duty_text="5%",
        raw_line="raw",
        row_sha256="a" * 64,
        status=COLLECTED_UNVERIFIED,
    )
    assert "tariff_ingest.ett_collected_rows" in str(statement.compile(dialect=postgresql.dialect()))


def test_ett_row_contract_matches_live_schema_without_phantom_columns() -> None:
    table = ett_staging_tables(MetaData(), schema=None)["ett_collected_rows"]
    assert set(table.c.keys()) == {
        "source_id",
        "hs_code",
        "description",
        "supplementary_unit",
        "duty_text",
        "raw_line",
        "row_sha256",
        "status",
        "ordinal",
    }
    assert {column.name for column in table.primary_key.columns} == {
        "source_id",
        "row_sha256",
    }
    assert "run_id" not in table.c
    assert "page_number" not in table.c
    assert "line_number" not in table.c
    assert {
        foreign_key.target_fullname for foreign_key in table.foreign_keys
    } == {"source_objects.source_id"}
