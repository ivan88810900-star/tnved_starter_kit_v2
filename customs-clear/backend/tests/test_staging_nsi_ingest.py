from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import MetaData, create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.services.staging_nsi_ingest import (
    Checkpoint,
    ImmutablePage,
    SourceObject,
    StagingIngestError,
    WorkerLimits,
    STABLE_CURSOR_CONTRACT,
    STABLE_CURSOR_SORT,
    ingest_page,
    load_checkpoint,
    run_bounded_worker,
    staging_tables,
)
from scripts.ingest_nsi_staging_pages import _read_limited


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _row(index: int) -> dict[str, Any]:
    return {
        "id": f"record-{index:09d}",
        "versionId": "snapshot-v1",
        "dateTimeFrom": "2026-10-16T00:00:00Z",
        "dateTimeTo": "2100-01-01T00:00:00Z",
        "dateTimeUpdated": "2026-10-16T00:00:00Z",
        "data": {"NUMB_DOC": f"RU.00.00.00.000.E.{index:06d}.00.00"},
    }


def _digest_rows(rows: list[dict[str, Any]]) -> str:
    hashes = [hashlib.sha256(_canonical(row)).hexdigest() for row in rows]
    return hashlib.sha256(("".join(f"{value}\n" for value in hashes)).encode("ascii")).hexdigest()


def _source(source_id: str, raw: bytes, media_type: str) -> SourceObject:
    return SourceObject(
        source_id=source_id,
        authority="EEC",
        dataset="NSI-1995",
        source_url="https://nsi.eaeunion.org/portal/1995",
        source_revision="snapshot-v1",
        object_bucket="official-originals",
        object_key=f"sgr/test/{source_id}.json",
        sha256=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
        media_type=media_type,
        captured_at=datetime(2026, 10, 19, tzinfo=timezone.utc),
    )


def _page(offset: int, rows: list[dict[str, Any]], *, overlap: int, total: int = 5) -> ImmutablePage:
    page_bytes = _canonical(rows)
    manifest = {
        "logical_offset": offset,
        "request_offset": offset - overlap,
        "returned_count": len(rows),
        "overlap_count": overlap,
        "source_advance": len(rows) - overlap,
        "next_offset": offset + len(rows) - overlap,
        "page_sha256": hashlib.sha256(page_bytes).hexdigest(),
        "expected_overlap_sha256": _digest_rows(rows[:overlap]) if overlap else None,
        "total_before": total,
        "total_after": total,
        "drift_detected": False,
        "terminal_total_reconciled": offset + len(rows) - overlap == total,
        "ordering_proof": {
            "kind": "stable_cursor",
            "snapshot_id": "snapshot-v1",
            "sort": STABLE_CURSOR_SORT,
            "cursor_contract": STABLE_CURSOR_CONTRACT,
        },
    }
    manifest_bytes = _canonical(manifest)
    return ImmutablePage(
        page_source=_source(f"page-{offset}", page_bytes, "application/json"),
        manifest_source=_source(f"manifest-{offset}", manifest_bytes, "application/json"),
        page_bytes=page_bytes,
        manifest_bytes=manifest_bytes,
    )


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'staging.sqlite'}")
    metadata = MetaData()
    staging_tables(metadata, schema=None)
    metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def test_bounded_worker_commits_two_pages_and_replay_is_idempotent(db) -> None:
    first = _page(0, [_row(0), _row(1), _row(2)], overlap=0)
    second_rows = [_row(0), _row(1), _row(2), _row(3), _row(4)]
    second = _page(3, second_rows, overlap=3)
    pages = {0: first, 3: second}

    result = run_bounded_worker(
        session_factory=db,
        page_reader=lambda checkpoint, _budget: pages[checkpoint.next_offset],
        epoch_id="epoch-1",
        dataset="NSI-1995",
        schema=None,
        limits=WorkerLimits(4, 10, 100_000, 10),
    )
    assert result.pages_committed == 2
    assert result.physical_rows == 5
    assert result.checkpoint == Checkpoint(
        generation=2,
        next_offset=5,
        trailing_overlap_sha256=_digest_rows(second_rows),
        trailing_overlap_count=5,
        source_total=5,
        snapshot_id="snapshot-v1",
        complete=True,
        run_id=result.checkpoint.run_id,
    )
    tables = staging_tables(MetaData(), schema=None)
    with db() as session:
        assert session.scalar(select(func.count()).select_from(tables["source_objects"])) == 4
        assert session.scalar(select(func.count()).select_from(tables["ingest_runs"])) == 2
        assert session.scalar(select(func.count()).select_from(tables["global_records"])) == 5
        assert session.scalar(select(func.count()).select_from(tables["run_rows"])) == 5
        checkpoint = load_checkpoint(session, epoch_id="epoch-1", dataset="NSI-1995", schema=None)
        assert checkpoint.complete is True

    replay = run_bounded_worker(
        session_factory=db,
        page_reader=lambda _checkpoint, _budget: pytest.fail("complete checkpoint must not read a page"),
        epoch_id="epoch-1",
        dataset="NSI-1995",
        schema=None,
        limits=WorkerLimits(4, 10, 100_000, 10),
    )
    assert replay.pages_committed == 0
    with db() as session:
        assert session.scalar(select(func.count()).select_from(tables["run_rows"])) == 5


def test_replay_requires_the_exact_manifest_cursor_and_source_object(db) -> None:
    original = _page(0, [_row(0)], overlap=0, total=1)
    with db() as session:
        with session.begin():
            ingest_page(
                session,
                page=original,
                checkpoint=Checkpoint(),
                epoch_id="epoch-replay",
                dataset="NSI-1995",
                schema=None,
            )

    manifest = json.loads(original.manifest_bytes)
    manifest["terminal_total_reconciled"] = False
    manifest_bytes = _canonical(manifest)
    divergent = ImmutablePage(
        page_source=original.page_source,
        manifest_source=_source("manifest-0-divergent", manifest_bytes, "application/json"),
        page_bytes=original.page_bytes,
        manifest_bytes=manifest_bytes,
    )
    with db() as reader:
        committed = load_checkpoint(
            reader,
            epoch_id="epoch-replay",
            dataset="NSI-1995",
            schema=None,
        )
    with db() as session:
        with session.begin():
            exact_replay = ingest_page(
                session,
                page=original,
                checkpoint=committed,
                epoch_id="epoch-replay",
                dataset="NSI-1995",
                schema=None,
            )
    assert exact_replay.replayed is True
    assert exact_replay.next_checkpoint == committed

    with db() as session:
        with pytest.raises(StagingIngestError, match="conflicting deterministic run_id"):
            with session.begin():
                ingest_page(
                    session,
                    page=divergent,
                    checkpoint=committed,
                    epoch_id="epoch-replay",
                    dataset="NSI-1995",
                    schema=None,
                )

    tables = staging_tables(MetaData(), schema=None)
    with db() as session:
        assert session.scalar(select(func.count()).select_from(tables["source_objects"])) == 2
        assert session.scalar(select(func.count()).select_from(tables["ingest_runs"])) == 1
        assert session.scalar(select(func.count()).select_from(tables["run_rows"])) == 1
        assert load_checkpoint(
            session,
            epoch_id="epoch-replay",
            dataset="NSI-1995",
            schema=None,
        ).complete is True


@pytest.mark.parametrize(
    ("table_name", "column", "replacement"),
    [
        ("run_rows", "sgr_number", "CORRUPTED"),
        ("global_records", "raw_json", '{"corrupted":true}'),
    ],
)
def test_replay_rejects_corrupted_materialized_rows(
    db,
    table_name: str,
    column: str,
    replacement: str,
) -> None:
    page = _page(0, [_row(0)], overlap=0, total=1)
    with db() as session:
        with session.begin():
            ingest_page(
                session,
                page=page,
                checkpoint=Checkpoint(),
                epoch_id="epoch-corrupted-replay",
                dataset="NSI-1995",
                schema=None,
            )

    tables = staging_tables(MetaData(), schema=None)
    with db() as session:
        with session.begin():
            session.execute(tables[table_name].update().values({column: replacement}))
    with db() as reader:
        with pytest.raises(StagingIngestError, match="stored checkpoint"):
            load_checkpoint(
                reader,
                epoch_id="epoch-corrupted-replay",
                dataset="NSI-1995",
                schema=None,
            )


@pytest.mark.parametrize(
    "checkpoint_mutation",
    [
        {"next_offset": 0},
        {"source_total": 0},
        {"snapshot_id": ""},
        {"run_id": "missing-run"},
        {"trailing_overlap_sha256": "not-a-sha256"},
        {"generation": 999},
    ],
)
def test_load_checkpoint_rejects_corrupted_checkpoint_binding(
    db,
    checkpoint_mutation: dict[str, Any],
) -> None:
    page = _page(0, [_row(0)], overlap=0, total=1)
    run_bounded_worker(
        session_factory=db,
        page_reader=lambda _checkpoint, _budget: page,
        epoch_id="epoch-corrupt-checkpoint",
        dataset="NSI-1995",
        schema=None,
        limits=WorkerLimits(1, 1, 100_000, 10),
    )
    tables = staging_tables(MetaData(), schema=None)
    with db() as session:
        with session.begin():
            session.execute(tables["checkpoints"].update().values(**checkpoint_mutation))
    with db() as session:
        with pytest.raises(StagingIngestError, match="stored checkpoint"):
            load_checkpoint(
                session,
                epoch_id="epoch-corrupt-checkpoint",
                dataset="NSI-1995",
                schema=None,
            )


def test_load_checkpoint_rejects_divergent_run_cursor(db) -> None:
    page = _page(0, [_row(0)], overlap=0, total=1)
    run_bounded_worker(
        session_factory=db,
        page_reader=lambda _checkpoint, _budget: page,
        epoch_id="epoch-corrupt-run-cursor",
        dataset="NSI-1995",
        schema=None,
        limits=WorkerLimits(1, 1, 100_000, 10),
    )
    tables = staging_tables(MetaData(), schema=None)
    with db() as session:
        with session.begin():
            cursor = dict(
                session.scalar(select(tables["ingest_runs"].c.resume_cursor))
            )
            cursor["next_offset"] = 0
            session.execute(tables["ingest_runs"].update().values(resume_cursor=cursor))
    with db() as session:
        with pytest.raises(StagingIngestError, match="stored checkpoint"):
            load_checkpoint(
                session,
                epoch_id="epoch-corrupt-run-cursor",
                dataset="NSI-1995",
                schema=None,
            )


@pytest.mark.parametrize(
    "run_mutation",
    ["scope-logical-offset", "scope-page-source", "run-source", "run-raw-count"],
)
def test_load_checkpoint_rejects_divergent_run_lineage(db, run_mutation: str) -> None:
    page = _page(0, [_row(0)], overlap=0, total=1)
    run_bounded_worker(
        session_factory=db,
        page_reader=lambda _checkpoint, _budget: page,
        epoch_id="epoch-corrupt-run-lineage",
        dataset="NSI-1995",
        schema=None,
        limits=WorkerLimits(1, 1, 100_000, 10),
    )
    tables = staging_tables(MetaData(), schema=None)
    with db() as session:
        with session.begin():
            if run_mutation.startswith("scope-"):
                scope = dict(session.scalar(select(tables["ingest_runs"].c.scope)))
                if run_mutation == "scope-logical-offset":
                    scope["logical_offset"] = 999
                else:
                    scope["page_source_id"] = "bogus-source"
                session.execute(tables["ingest_runs"].update().values(scope=scope))
            elif run_mutation == "run-source":
                session.execute(
                    tables["ingest_runs"].update().values(source_id="bogus-source")
                )
            else:
                session.execute(tables["ingest_runs"].update().values(raw_count=999))
    with db() as session:
        with pytest.raises(StagingIngestError, match="stored checkpoint"):
            load_checkpoint(
                session,
                epoch_id="epoch-corrupt-run-lineage",
                dataset="NSI-1995",
                schema=None,
            )


@pytest.mark.parametrize(
    "material_mutation",
    [
        "physical-status",
        "physical-global",
        "physical-sgr",
        "global-raw",
        "global-first-source",
        "global-first-manifest",
        "ordering-kind",
        "ordering-contract",
    ],
)
def test_load_checkpoint_rejects_corrupted_material_lineage(
    db,
    material_mutation: str,
) -> None:
    page = _page(0, [_row(0)], overlap=0, total=1)
    run_bounded_worker(
        session_factory=db,
        page_reader=lambda _checkpoint, _budget: page,
        epoch_id="epoch-corrupt-material-lineage",
        dataset="NSI-1995",
        schema=None,
        limits=WorkerLimits(1, 1, 100_000, 10),
    )
    tables = staging_tables(MetaData(), schema=None)
    with db() as session:
        with session.begin():
            if material_mutation == "physical-status":
                session.execute(tables["run_rows"].update().values(status="ADMITTED"))
            elif material_mutation == "physical-global":
                session.execute(
                    tables["run_rows"].update().values(global_record_id="f" * 64)
                )
            elif material_mutation == "physical-sgr":
                session.execute(tables["run_rows"].update().values(sgr_number="CORRUPTED"))
            elif material_mutation == "global-raw":
                session.execute(
                    tables["global_records"].update().values(raw_json='{"corrupted":true}')
                )
            elif material_mutation == "global-first-source":
                session.execute(
                    tables["global_records"].update().values(first_source_id="missing-source")
                )
            elif material_mutation == "global-first-manifest":
                session.execute(
                    tables["global_records"].update().values(first_source_id="manifest-0")
                )
            else:
                scope = dict(session.scalar(select(tables["ingest_runs"].c.scope)))
                proof = dict(scope["ordering_proof"])
                if material_mutation == "ordering-kind":
                    proof["kind"] = "bogus"
                else:
                    proof["cursor_contract"] = "bogus"
                scope["ordering_proof"] = proof
                session.execute(tables["ingest_runs"].update().values(scope=scope))
    with db() as session:
        with pytest.raises(StagingIngestError, match="stored checkpoint"):
            load_checkpoint(
                session,
                epoch_id="epoch-corrupt-material-lineage",
                dataset="NSI-1995",
                schema=None,
            )


@pytest.mark.parametrize(
    "capture_run_mutation",
    [
        "scope-offset",
        "scope-epoch",
        "parser",
        "raw-count",
        "cursor",
        "cursor-overlap-count",
    ],
)
def test_load_checkpoint_rejects_corrupted_historical_first_capture_run(
    db,
    capture_run_mutation: str,
) -> None:
    first = _page(0, [_row(0)], overlap=0, total=1)
    first = ImmutablePage(
        page_source=_source("page-first", first.page_bytes, "application/json"),
        manifest_source=_source("manifest-first", first.manifest_bytes, "application/json"),
        page_bytes=first.page_bytes,
        manifest_bytes=first.manifest_bytes,
    )
    later = _page(0, [_row(0)], overlap=0, total=1)
    later = ImmutablePage(
        page_source=_source("page-later", later.page_bytes, "application/json"),
        manifest_source=_source("manifest-later", later.manifest_bytes, "application/json"),
        page_bytes=later.page_bytes,
        manifest_bytes=later.manifest_bytes,
    )
    for epoch_id, page in (("epoch-first", first), ("epoch-later", later)):
        run_bounded_worker(
            session_factory=db,
            page_reader=lambda _checkpoint, _budget, page=page: page,
            epoch_id=epoch_id,
            dataset="NSI-1995",
            schema=None,
            limits=WorkerLimits(1, 1, 100_000, 10),
        )

    tables = staging_tables(MetaData(), schema=None)
    with db() as session:
        with session.begin():
            first_run = session.execute(
                select(tables["ingest_runs"]).where(
                    tables["ingest_runs"].c.source_id == "page-first"
                )
            ).mappings().one()
            predicate = tables["ingest_runs"].c.run_id == first_run["run_id"]
            if capture_run_mutation.startswith("scope-"):
                scope = dict(first_run["scope"])
                if capture_run_mutation == "scope-offset":
                    scope["logical_offset"] = 999
                else:
                    scope["epoch_id"] = "different-epoch"
                session.execute(tables["ingest_runs"].update().where(predicate).values(scope=scope))
            elif capture_run_mutation == "parser":
                session.execute(
                    tables["ingest_runs"].update().where(predicate).values(parser_version="bogus")
                )
            elif capture_run_mutation == "raw-count":
                session.execute(
                    tables["ingest_runs"].update().where(predicate).values(raw_count=999)
                )
            elif capture_run_mutation == "cursor":
                cursor = dict(first_run["resume_cursor"])
                cursor["next_offset"] = 999
                session.execute(
                    tables["ingest_runs"].update().where(predicate).values(resume_cursor=cursor)
                )
            else:
                cursor = dict(first_run["resume_cursor"])
                cursor["trailing_overlap_count"] = 20
                session.execute(
                    tables["ingest_runs"].update().where(predicate).values(resume_cursor=cursor)
                )
    with db() as session:
        with pytest.raises(StagingIngestError, match="stored checkpoint"):
            load_checkpoint(
                session,
                epoch_id="epoch-later",
                dataset="NSI-1995",
                schema=None,
            )


def test_load_checkpoint_rejects_corrupted_historical_request_offset(db) -> None:
    first = _page(0, [_row(0), _row(1), _row(2)], overlap=0)
    second = _page(3, [_row(0), _row(1), _row(2), _row(3), _row(4)], overlap=3)
    pages = {0: first, 3: second}
    run_bounded_worker(
        session_factory=db,
        page_reader=lambda checkpoint, _budget: pages[checkpoint.next_offset],
        epoch_id="epoch-first-multipage",
        dataset="NSI-1995",
        schema=None,
        limits=WorkerLimits(2, 5, 100_000, 10),
    )
    later = _page(0, [_row(3)], overlap=0, total=1)
    later = ImmutablePage(
        page_source=_source("page-later-single", later.page_bytes, "application/json"),
        manifest_source=_source(
            "manifest-later-single", later.manifest_bytes, "application/json"
        ),
        page_bytes=later.page_bytes,
        manifest_bytes=later.manifest_bytes,
    )
    run_bounded_worker(
        session_factory=db,
        page_reader=lambda _checkpoint, _budget: later,
        epoch_id="epoch-later-single",
        dataset="NSI-1995",
        schema=None,
        limits=WorkerLimits(1, 1, 100_000, 10),
    )

    tables = staging_tables(MetaData(), schema=None)
    with db() as session:
        with session.begin():
            capture_run = session.execute(
                select(tables["ingest_runs"]).where(
                    tables["ingest_runs"].c.source_id == "page-3"
                )
            ).mappings().one()
            scope = dict(capture_run["scope"])
            scope["request_offset"] = 1
            session.execute(
                tables["ingest_runs"]
                .update()
                .where(tables["ingest_runs"].c.run_id == capture_run["run_id"])
                .values(scope=scope)
            )
    with db() as session:
        with pytest.raises(StagingIngestError, match="stored checkpoint"):
            load_checkpoint(
                session,
                epoch_id="epoch-later-single",
                dataset="NSI-1995",
                schema=None,
            )


def test_interruption_preserves_first_page_and_resume_continues(db) -> None:
    first = _page(0, [_row(0), _row(1), _row(2)], overlap=0)
    second = _page(3, [_row(0), _row(1), _row(2), _row(3), _row(4)], overlap=3)
    calls = 0

    def interrupted(checkpoint: Checkpoint, _budget: int) -> ImmutablePage:
        nonlocal calls
        calls += 1
        if calls == 1:
            return first
        raise OSError("controlled source mount interrupted")

    with pytest.raises(OSError, match="interrupted"):
        run_bounded_worker(
            session_factory=db,
            page_reader=interrupted,
            epoch_id="epoch-1",
            dataset="NSI-1995",
            schema=None,
            limits=WorkerLimits(4, 10, 100_000, 10),
        )
    with db() as session:
        assert load_checkpoint(session, epoch_id="epoch-1", dataset="NSI-1995", schema=None).next_offset == 3

    resumed = run_bounded_worker(
        session_factory=db,
        page_reader=lambda checkpoint, _budget: second if checkpoint.next_offset == 3 else pytest.fail(),
        epoch_id="epoch-1",
        dataset="NSI-1995",
        schema=None,
        limits=WorkerLimits(2, 10, 100_000, 10),
    )
    assert resumed.pages_committed == 1
    assert resumed.checkpoint.complete is True


@pytest.mark.parametrize(
    "fault",
    ["overlap", "overlap_length", "drift", "prior_total", "ordering", "checksum", "global_id"],
)
def test_failure_rolls_back_candidate_page_without_advancing_checkpoint(db, fault: str) -> None:
    first = _page(0, [_row(0), _row(1), _row(2)], overlap=0)
    run_bounded_worker(
        session_factory=db,
        page_reader=lambda _checkpoint, _budget: first,
        epoch_id="epoch-1",
        dataset="NSI-1995",
        schema=None,
        limits=WorkerLimits(1, 10, 100_000, 10),
    )
    rows = [_row(0), _row(1), _row(2), _row(3), _row(4)]
    second = _page(3, rows, overlap=3)
    manifest = json.loads(second.manifest_bytes)
    page_bytes = second.page_bytes
    if fault == "overlap":
        manifest["expected_overlap_sha256"] = "0" * 64
    elif fault == "overlap_length":
        manifest["overlap_count"] = 2
        manifest["request_offset"] = 1
        manifest["source_advance"] = 3
        manifest["next_offset"] = 6
    elif fault == "drift":
        manifest["total_after"] = 6
        manifest["drift_detected"] = True
    elif fault == "prior_total":
        manifest["total_before"] = 6
        manifest["total_after"] = 6
    elif fault == "ordering":
        manifest.pop("ordering_proof")
    elif fault == "checksum":
        manifest["page_sha256"] = "0" * 64
    elif fault == "global_id":
        rows[3]["id"] = "record-1"
        rows[3]["data"]["NUMB_DOC"] = "changed"
        page_bytes = _canonical(rows)
        manifest["page_sha256"] = hashlib.sha256(page_bytes).hexdigest()
    manifest_bytes = _canonical(manifest)
    candidate = ImmutablePage(
        page_source=_source("page-3", page_bytes, "application/json"),
        manifest_source=_source("manifest-3", manifest_bytes, "application/json"),
        page_bytes=page_bytes,
        manifest_bytes=manifest_bytes,
    )
    with pytest.raises(StagingIngestError):
        run_bounded_worker(
            session_factory=db,
            page_reader=lambda _checkpoint, _budget: candidate,
            epoch_id="epoch-1",
            dataset="NSI-1995",
            schema=None,
            limits=WorkerLimits(1, 10, 100_000, 10),
        )
    tables = staging_tables(MetaData(), schema=None)
    with db() as session:
        assert load_checkpoint(session, epoch_id="epoch-1", dataset="NSI-1995", schema=None).next_offset == 3
        assert session.scalar(select(func.count()).select_from(tables["ingest_runs"])) == 1
        assert session.scalar(select(func.count()).select_from(tables["run_rows"])) == 3


def test_explicit_session_is_required() -> None:
    with pytest.raises(ValueError, match="explicit staging Session"):
        ingest_page(  # type: ignore[arg-type]
            None,
            page=_page(0, [_row(0)], overlap=0, total=1),
            checkpoint=Checkpoint(),
            epoch_id="epoch",
            dataset="NSI-1995",
            schema=None,
        )
    with pytest.raises(ValueError, match="session_factory"):
        run_bounded_worker(  # type: ignore[arg-type]
            session_factory=None,
            page_reader=lambda _checkpoint, _budget: _page(0, [_row(0)], overlap=0, total=1),
            epoch_id="epoch",
            dataset="NSI-1995",
            schema=None,
            limits=WorkerLimits(1, 1, 1000, 1),
        )


def test_resource_limit_rolls_back_whole_page(db) -> None:
    page = _page(0, [_row(0), _row(1)], overlap=0, total=2)
    with pytest.raises(StagingIngestError, match="max_rows"):
        run_bounded_worker(
            session_factory=db,
            page_reader=lambda _checkpoint, _budget: page,
            epoch_id="epoch",
            dataset="NSI-1995",
            schema=None,
            limits=WorkerLimits(1, 1, 100_000, 10),
        )
    tables = staging_tables(MetaData(), schema=None)
    with db() as session:
        assert session.scalar(select(func.count()).select_from(tables["source_objects"])) == 0
        assert session.scalar(select(func.count()).select_from(tables["ingest_runs"])) == 0
        assert session.scalar(select(func.count()).select_from(tables["run_rows"])) == 0


@pytest.mark.parametrize("max_seconds", [float("nan"), float("inf")])
def test_non_finite_max_seconds_is_rejected_before_source_read(
    db,
    max_seconds: float,
) -> None:
    source_read = False

    def forbidden_reader(_checkpoint: Checkpoint, _budget: int) -> ImmutablePage:
        nonlocal source_read
        source_read = True
        raise AssertionError("invalid limits must fail before source access")

    with pytest.raises(ValueError, match="finite and positive"):
        run_bounded_worker(
            session_factory=db,
            page_reader=forbidden_reader,
            epoch_id="epoch-non-finite-limit",
            dataset="NSI-1995",
            schema=None,
            limits=WorkerLimits(1, 1, 100_000, max_seconds),
        )
    assert source_read is False


def test_elapsed_source_read_does_not_commit_after_max_seconds(db) -> None:
    page = _page(0, [_row(0)], overlap=0, total=1)
    ticks = iter([0.0, 0.0, 11.0])

    result = run_bounded_worker(
        session_factory=db,
        page_reader=lambda _checkpoint, _budget: page,
        epoch_id="epoch-time-read",
        dataset="NSI-1995",
        schema=None,
        limits=WorkerLimits(1, 1, 100_000, 10),
        clock=lambda: next(ticks),
    )

    assert result.pages_committed == 0
    assert result.physical_rows == 0
    assert result.checkpoint == Checkpoint()
    tables = staging_tables(MetaData(), schema=None)
    with db() as session:
        assert session.scalar(select(func.count()).select_from(tables["source_objects"])) == 0
        assert session.scalar(select(func.count()).select_from(tables["ingest_runs"])) == 0
        assert session.scalar(select(func.count()).select_from(tables["run_rows"])) == 0


def test_elapsed_ingest_rolls_back_page_before_commit(db) -> None:
    page = _page(0, [_row(0)], overlap=0, total=1)
    ticks = iter([0.0, 0.0, 0.0, 11.0])

    with pytest.raises(StagingIngestError, match="max_seconds"):
        run_bounded_worker(
            session_factory=db,
            page_reader=lambda _checkpoint, _budget: page,
            epoch_id="epoch-time-ingest",
            dataset="NSI-1995",
            schema=None,
            limits=WorkerLimits(1, 1, 100_000, 10),
            clock=lambda: next(ticks),
        )

    tables = staging_tables(MetaData(), schema=None)
    with db() as session:
        assert session.scalar(select(func.count()).select_from(tables["source_objects"])) == 0
        assert session.scalar(select(func.count()).select_from(tables["ingest_runs"])) == 0
        assert session.scalar(select(func.count()).select_from(tables["run_rows"])) == 0
        assert load_checkpoint(
            session,
            epoch_id="epoch-time-ingest",
            dataset="NSI-1995",
            schema=None,
        ) == Checkpoint()


def test_physical_captures_are_distinct_while_global_revision_id_is_stable(db) -> None:
    first = _page(0, [_row(0)], overlap=0, total=1)
    for epoch, page in (("epoch-1", first), ("epoch-2", first)):
        result = run_bounded_worker(
            session_factory=db,
            page_reader=lambda _checkpoint, _budget, candidate=page: candidate,
            epoch_id=epoch,
            dataset="NSI-1995",
            schema=None,
            limits=WorkerLimits(1, 1, 100_000, 10),
        )
        assert result.physical_rows == 1
    tables = staging_tables(MetaData(), schema=None)
    with db() as session:
        assert session.scalar(select(func.count()).select_from(tables["global_records"])) == 1
        assert session.scalar(select(func.count()).select_from(tables["run_rows"])) == 2
        assert session.scalar(select(func.count(func.distinct(tables["run_rows"].c.run_id)))) == 2


def test_stable_cursor_proof_is_exact_and_rows_must_be_strictly_ordered(db) -> None:
    page = _page(0, [_row(1), _row(0)], overlap=0, total=2)
    with pytest.raises(StagingIngestError, match="strictly ordered"):
        run_bounded_worker(
            session_factory=db,
            page_reader=lambda _checkpoint, _budget: page,
            epoch_id="epoch-order",
            dataset="NSI-1995",
            schema=None,
            limits=WorkerLimits(1, 2, 100_000, 10),
        )


def test_source_provenance_must_match_requested_dataset_and_capture(db) -> None:
    page = _page(0, [_row(0)], overlap=0, total=1)
    wrong_dataset = ImmutablePage(
        page_source=SourceObject(**{**page.page_source.__dict__, "dataset": "OTHER"}),
        manifest_source=SourceObject(**{**page.manifest_source.__dict__, "dataset": "OTHER"}),
        page_bytes=page.page_bytes,
        manifest_bytes=page.manifest_bytes,
    )
    with pytest.raises(StagingIngestError, match="source dataset"):
        run_bounded_worker(
            session_factory=db,
            page_reader=lambda _checkpoint, _budget: wrong_dataset,
            epoch_id="epoch-provenance",
            dataset="NSI-1995",
            schema=None,
            limits=WorkerLimits(1, 1, 100_000, 10),
        )

    wrong_authority = ImmutablePage(
        page_source=page.page_source,
        manifest_source=SourceObject(
            **{**page.manifest_source.__dict__, "authority": "UNRELATED"}
        ),
        page_bytes=page.page_bytes,
        manifest_bytes=page.manifest_bytes,
    )
    with pytest.raises(StagingIngestError, match="authorities differ"):
        run_bounded_worker(
            session_factory=db,
            page_reader=lambda _checkpoint, _budget: wrong_authority,
            epoch_id="epoch-provenance",
            dataset="NSI-1995",
            schema=None,
            limits=WorkerLimits(1, 1, 100_000, 10),
        )

    with pytest.raises(ValueError, match="canonical"):
        run_bounded_worker(
            session_factory=db,
            page_reader=lambda _checkpoint, _budget: page,
            epoch_id="epoch-provenance",
            dataset=" NSI-1995 ",
            schema=None,
            limits=WorkerLimits(1, 1, 100_000, 10),
        )

    blank_provenance = ImmutablePage(
        page_source=SourceObject(
            **{
                **page.page_source.__dict__,
                "authority": "",
                "source_url": "",
                "object_bucket": "",
                "media_type": "",
            }
        ),
        manifest_source=SourceObject(
            **{
                **page.manifest_source.__dict__,
                "authority": "",
                "source_url": "",
                "object_bucket": "",
                "media_type": "",
            }
        ),
        page_bytes=page.page_bytes,
        manifest_bytes=page.manifest_bytes,
    )
    with pytest.raises(StagingIngestError, match="source authority is required"):
        run_bounded_worker(
            session_factory=db,
            page_reader=lambda _checkpoint, _budget: blank_provenance,
            epoch_id="epoch-provenance",
            dataset="NSI-1995",
            schema=None,
            limits=WorkerLimits(1, 1, 100_000, 10),
        )

    slash_media = ImmutablePage(
        page_source=SourceObject(**{**page.page_source.__dict__, "media_type": "/"}),
        manifest_source=SourceObject(**{**page.manifest_source.__dict__, "media_type": "/"}),
        page_bytes=page.page_bytes,
        manifest_bytes=page.manifest_bytes,
    )
    with pytest.raises(StagingIngestError, match="media_type is malformed"):
        run_bounded_worker(
            session_factory=db,
            page_reader=lambda _checkpoint, _budget: slash_media,
            epoch_id="epoch-provenance",
            dataset="NSI-1995",
            schema=None,
            limits=WorkerLimits(1, 1, 100_000, 10),
        )


@pytest.mark.parametrize("epoch_id", ["", " epoch ", "\t"])
def test_checkpoint_epoch_must_be_nonblank_and_canonical(db, epoch_id: str) -> None:
    with pytest.raises(ValueError, match="epoch_id"):
        run_bounded_worker(
            session_factory=db,
            page_reader=lambda _checkpoint, _budget: _page(
                0, [_row(0)], overlap=0, total=1
            ),
            epoch_id=epoch_id,
            dataset="NSI-1995",
            schema=None,
            limits=WorkerLimits(1, 1, 100_000, 10),
        )

    page = _page(0, [_row(0)], overlap=0, total=1)
    manifest = json.loads(page.manifest_bytes)
    manifest["ordering_proof"]["cursor_contract"] = "arbitrary-string"
    manifest_bytes = _canonical(manifest)
    invalid = ImmutablePage(
        page_source=page.page_source,
        manifest_source=_source("manifest-invalid-proof", manifest_bytes, "application/json"),
        page_bytes=page.page_bytes,
        manifest_bytes=manifest_bytes,
    )
    with pytest.raises(StagingIngestError, match="unsupported contract"):
        run_bounded_worker(
            session_factory=db,
            page_reader=lambda _checkpoint, _budget: invalid,
            epoch_id="epoch-proof",
            dataset="NSI-1995",
            schema=None,
            limits=WorkerLimits(1, 1, 100_000, 10),
        )


def test_stale_checkpoint_cannot_commit_a_divergent_page(db) -> None:
    first = _page(0, [_row(0)], overlap=0, total=1)
    with db() as session:
        with session.begin():
            ingest_page(
                session,
                page=first,
                checkpoint=Checkpoint(),
                epoch_id="epoch-cas",
                dataset="NSI-1995",
                schema=None,
            )

    other = _page(0, [_row(1)], overlap=0, total=1)
    other = ImmutablePage(
        page_source=_source("page-divergent", other.page_bytes, "application/json"),
        manifest_source=_source("manifest-divergent", other.manifest_bytes, "application/json"),
        page_bytes=other.page_bytes,
        manifest_bytes=other.manifest_bytes,
    )
    with db() as session:
        with pytest.raises(StagingIngestError, match="checkpoint CAS lost"):
            with session.begin():
                ingest_page(
                    session,
                    page=other,
                    checkpoint=Checkpoint(),
                    epoch_id="epoch-cas",
                    dataset="NSI-1995",
                    schema=None,
                )
    tables = staging_tables(MetaData(), schema=None)
    with db() as session:
        assert session.scalar(select(func.count()).select_from(tables["ingest_runs"])) == 1
        assert session.scalar(select(func.count()).select_from(tables["run_rows"])) == 1
        assert load_checkpoint(session, epoch_id="epoch-cas", dataset="NSI-1995", schema=None).generation == 1


def test_limited_reader_rejects_oversized_object_before_open(tmp_path, monkeypatch) -> None:
    source = tmp_path / "large.bin"
    source.write_bytes(b"x" * 32)
    opened = False

    def forbidden_open(*_args, **_kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("oversized source must not be opened")

    monkeypatch.setattr(Path, "open", forbidden_open)
    with pytest.raises(RuntimeError, match="remaining budget"):
        _read_limited(source, 8)
    assert opened is False


def test_cli_rejects_an_explicit_wrong_database_before_reading_job(tmp_path) -> None:
    env = os.environ.copy()
    env["TARIFF_TEST_STAGING_URL"] = f"sqlite:///{tmp_path / 'wrong.sqlite'}"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/ingest_nsi_staging_pages.py",
            "--database-url-env",
            "TARIFF_TEST_STAGING_URL",
            "--expected-database-name",
            "tariff_staging",
            "--job-file",
            str(tmp_path / "must-not-be-read.json"),
        ],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "explicit database mismatch" in result.stderr
    assert not (tmp_path / "wrong.sqlite").exists()


def test_cli_explicit_schema_initialization_creates_additive_contract(tmp_path) -> None:
    page = _page(0, [_row(0)], overlap=0, total=1)
    page_path = tmp_path / "page.json"
    manifest_path = tmp_path / "manifest.json"
    page_path.write_bytes(page.page_bytes)
    manifest_path.write_bytes(page.manifest_bytes)

    def source_json(source: SourceObject) -> dict[str, Any]:
        values = dict(source.__dict__)
        values["captured_at"] = source.captured_at.isoformat()
        return values

    job_path = tmp_path / "job.json"
    job_path.write_text(
        json.dumps(
            {
                "epoch_id": "epoch-cli",
                "dataset": "NSI-1995",
                "pages": [
                    {
                        "logical_offset": 0,
                        "page_path": page_path.name,
                        "manifest_path": manifest_path.name,
                        "page_source": source_json(page.page_source),
                        "manifest_source": source_json(page.manifest_source),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    database_path = tmp_path / "tariff_staging.sqlite"
    env = os.environ.copy()
    env["TARIFF_TEST_STAGING_URL"] = f"sqlite:///{database_path}"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/ingest_nsi_staging_pages.py",
            "--database-url-env",
            "TARIFF_TEST_STAGING_URL",
            "--expected-database-name",
            str(database_path),
            "--job-file",
            str(job_path),
            "--schema",
            "",
            "--initialize-schema",
            "--max-pages",
            "1",
        ],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["physical_rows"] == 1
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        tables = staging_tables(MetaData(), schema=None)
        with engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(tables["global_records"])) == 1
            assert connection.scalar(select(func.count()).select_from(tables["run_rows"])) == 1
            assert connection.scalar(select(func.count()).select_from(tables["checkpoints"])) == 1
    finally:
        engine.dispose()
