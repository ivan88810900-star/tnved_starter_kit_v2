from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.models.core import SgrCertificate, SgrRegistryRawRevision
from scripts import sync_sgr_registry as sync


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    SgrRegistryRawRevision.__table__.create(engine)
    SgrCertificate.__table__.create(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def _official_shape_item() -> dict:
    # Shape captured from NSI dictionary 1995. versionId is intentionally absent:
    # the live element does not guarantee that optional field.
    return {
        "id": "11111111-2222-4333-8444-555555555555",
        "dateTimeFrom": "2025-10-15T00:00:00.000Z",
        "dateTimeTo": "2100-01-01T00:00:00.000Z",
        "dateTimeUpdated": "2025-10-15T18:09:46.283Z",
        "data": {
            "NUMB_DOC": "RU.77.99.88.003.R.000001.04.25",
            "SERIALNUMB": "000001",
            "NAME_PROD": "Средство косметическое для ухода за кожей",
            "FIRMMADE_NAME": "Изготовитель",
            "FIRMGET_NAME": "Получатель",
            "DATE_DOC": "02.04.2025",
            "STATUS": {"code": "01", "name": "Действует", "type": "String"},
            "DOC_NORM": "Решение Комиссии Таможенного союза",
            "DOC_USEAREA": "Евразийский экономический союз",
            "DOC_PROTOCOL": "Протокол испытаний",
        },
    }


def _import_item(db: Session, item: dict) -> SgrCertificate:
    row = sync._row_from_nsi_dict(item)
    assert row is not None
    sync.upsert_sgr(db, row)
    db.commit()
    return db.scalar(select(SgrCertificate).where(SgrCertificate.sgr_number == row["sgr_number"]))


def test_nsi_raw_round_trip_sha_metadata_and_normalized_linkage(session: Session) -> None:
    item = _official_shape_item()

    current = _import_item(session, item)
    revision = session.scalar(select(SgrRegistryRawRevision))

    expected_raw = json.dumps(
        item,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    expected_sha = hashlib.sha256(expected_raw.encode("utf-8")).hexdigest()
    assert revision is not None
    assert json.loads(revision.raw_json) == item
    assert revision.raw_json == expected_raw
    assert revision.raw_sha256 == expected_sha
    assert revision.source_record_id == item["id"]
    assert revision.source_version_id is None
    assert revision.date_time_from == item["dateTimeFrom"]
    assert revision.date_time_to == item["dateTimeTo"]
    assert revision.update_datetime == ""
    assert revision.date_time_updated == item["dateTimeUpdated"]
    assert current is not None
    assert current.source_raw_sha256 == expected_sha
    assert current.doc_norm == item["data"]["DOC_NORM"]
    assert current.doc_usearea == item["data"]["DOC_USEAREA"]


def test_same_raw_is_idempotent_and_changed_raw_retains_previous_revision(session: Session) -> None:
    first = _official_shape_item()
    first_current = _import_item(session, first)
    first_sha = first_current.source_raw_sha256

    same_current = _import_item(session, deepcopy(first))
    assert same_current.source_raw_sha256 == first_sha
    assert len(session.scalars(select(SgrRegistryRawRevision)).all()) == 1

    changed = deepcopy(first)
    changed["dateTimeUpdated"] = "2026-10-14T07:01:02.456"
    changed["data"]["DOC_NORM"] = "Обновлённое основание"
    changed["data"]["DOC_USEAREA"] = "Российская Федерация"
    current = _import_item(session, changed)
    revisions = session.scalars(
        select(SgrRegistryRawRevision).order_by(SgrRegistryRawRevision.id)
    ).all()

    assert len(revisions) == 2
    assert revisions[0].raw_sha256 == first_sha
    assert json.loads(revisions[0].raw_json) == first
    assert json.loads(revisions[1].raw_json) == changed
    assert current.source_raw_sha256 == revisions[1].raw_sha256
    assert current.source_raw_sha256 != first_sha
    assert current.doc_norm == "Обновлённое основание"
    assert current.doc_usearea == changed["data"]["DOC_USEAREA"]


def test_update_datetime_and_optional_version_id_are_persisted_when_present(session: Session) -> None:
    item = _official_shape_item()
    item["versionId"] = "revision-42"
    item["updateDateTime"] = "2026-10-14T08:00:00"

    _import_item(session, item)
    revision = session.scalar(select(SgrRegistryRawRevision))

    assert revision is not None
    assert revision.source_version_id == "revision-42"
    assert revision.update_datetime == "2026-10-14T08:00:00"
