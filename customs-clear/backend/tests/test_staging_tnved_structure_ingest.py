from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import MetaData, create_engine, func, select
from sqlalchemy.orm import Session

from app.services.staging_tnved_structure_ingest import (
    STATUS,
    StructureIngestError,
    ingest_structure,
    read_accepted_sqlite,
    staging_tables,
)


def _fixture(path: Path) -> tuple[str, str]:
    connection = sqlite3.connect(path)
    connection.executescript("""
    CREATE TABLE recovery_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE recovery_sources(id TEXT PRIMARY KEY);
    CREATE TABLE recovery_editions(id TEXT PRIMARY KEY);
    CREATE TABLE recovery_notes(id TEXT PRIMARY KEY);
    CREATE TABLE recovery_sections(id TEXT PRIMARY KEY);
    CREATE TABLE recovery_section_chapters(id TEXT PRIMARY KEY);
    CREATE TABLE recovery_nodes(id TEXT PRIMARY KEY);
    CREATE TABLE recovery_node_notes(id TEXT PRIMARY KEY);
    CREATE TABLE tnved_entries(id INTEGER PRIMARY KEY, hs_code TEXT UNIQUE NOT NULL, parent_hs TEXT NOT NULL, level INTEGER NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL, chapter TEXT NOT NULL, source_url TEXT NOT NULL, source_revision TEXT NOT NULL);
    INSERT INTO recovery_sources VALUES ('s1');
    INSERT INTO recovery_editions VALUES ('e1');
    INSERT INTO tnved_entries VALUES (1,'01','',2,'chapter','["chapter"]','01','https://eec.eaeunion.org/a.pdf','e1');
    INSERT INTO tnved_entries VALUES (2,'0101','01',4,'heading','["chapter","heading"]','01','https://eec.eaeunion.org/a.pdf','e1');
    """)
    connection.executemany("INSERT INTO recovery_metadata VALUES (?,?)", [("catalog_id", "fixture"), ("generated_at_source", "2026-10-20T00:00:00+00:00")])
    connection.commit()
    from app.services.staging_tnved_structure_ingest import _logical_digest
    logical = _logical_digest(connection)
    connection.close()
    return hashlib.sha256(path.read_bytes()).hexdigest(), logical


def test_exact_ingest_and_replay_are_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "accepted.sqlite"
    sha, logical = _fixture(path)
    artifact, rows = read_accepted_sqlite(path, expected_sha256=sha, expected_logical_sha256=logical)
    engine = create_engine(f"sqlite:///{tmp_path / 'staging.sqlite'}")
    with Session(engine) as session, session.begin():
        first = ingest_structure(session, artifact=artifact, rows=rows, schema=None, initialize_schema=True, now=datetime(2026, 10, 20, tzinfo=timezone.utc))
    with Session(engine) as session, session.begin():
        second = ingest_structure(session, artifact=artifact, rows=rows, schema=None, now=datetime(2026, 10, 21, tzinfo=timezone.utc))
        tables = staging_tables(MetaData(), schema=None)
        assert session.scalar(select(func.count()).select_from(tables["rows"])) == 2
        assert session.scalar(select(func.count()).select_from(tables["rows"]).where(tables["rows"].c.status == STATUS)) == 2
    assert first.replayed is False
    assert second.replayed is True


def test_hash_and_incomplete_state_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "accepted.sqlite"
    sha, logical = _fixture(path)
    with pytest.raises(StructureIngestError, match="artifact SHA"):
        read_accepted_sqlite(path, expected_sha256="0" * 64, expected_logical_sha256=logical)
    artifact, rows = read_accepted_sqlite(path, expected_sha256=sha, expected_logical_sha256=logical)
    engine = create_engine(f"sqlite:///{tmp_path / 'staging.sqlite'}")
    tables = staging_tables(MetaData(), schema=None)
    tables["artifacts"].metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        session.execute(tables["artifacts"].insert().values(artifact_sha256=artifact.sha256, logical_sha256=artifact.logical_sha256, size_bytes=artifact.size_bytes, catalog_id=artifact.catalog_id, generated_at_source=artifact.generated_at_source, source_count=artifact.source_count, edition_count=artifact.edition_count, entry_count=artifact.entry_count, status=STATUS))
    with Session(engine) as session, session.begin(), pytest.raises(StructureIngestError, match="incomplete"):
        ingest_structure(session, artifact=artifact, rows=rows, schema=None, now=datetime.now(timezone.utc))


@pytest.mark.parametrize(
    "change",
    [
        {"hs_code": "BAD"},
        {"parent_hs": "010101"},
        {"level": -1},
        {"path_json": "not-json"},
        {"source_url": "https://evil.example/a.pdf"},
        {"row_sha256": "0" * 64},
        {"parent_hs": "02"},
    ],
)
def test_public_ingest_boundary_rejects_forged_rows(tmp_path: Path, change: dict) -> None:
    path = tmp_path / "accepted.sqlite"
    sha, logical = _fixture(path)
    artifact, rows = read_accepted_sqlite(path, expected_sha256=sha, expected_logical_sha256=logical)
    forged = [replace(rows[0], **change), *rows[1:]]
    engine = create_engine(f"sqlite:///{tmp_path / 'staging.sqlite'}")
    tables = staging_tables(MetaData(), schema=None)
    tables["artifacts"].metadata.create_all(engine)
    with Session(engine) as session, session.begin(), pytest.raises(StructureIngestError):
        ingest_structure(session, artifact=artifact, rows=forged, schema=None, now=datetime.now(timezone.utc))
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(tables["artifacts"])) == 0
        assert session.scalar(select(func.count()).select_from(tables["rows"])) == 0
