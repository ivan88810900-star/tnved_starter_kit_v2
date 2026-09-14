"""Rollback, live-identity and FSA structure guards for managed opendata."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.tnved import CustomsDocMask, FsaCertificate, OpendataSyncLog, TroisRegistry
from app.services import opendata_client, opendata_customs, opendata_fsa, opendata_trois
from app.services.opendata_client import OpendataMeta, OpendataVersion
from app.services.opendata_snapshot_evidence import (
    encode_live_snapshot_details,
    fsa_snapshot_details_match,
)


def _sessionmaker(*tables):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=list(tables))
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _meta(version, *, provenance_verified: bool = True):
    return SimpleNamespace(
        modified="03.09.2026",
        provenance_verified=provenance_verified,
        versions=[version],
    )


_MASK_RAW = (
    "SID_SMEV;KOD;N_MSK;NAME_MSK;K_MASKA;DSCR_MSK;DATBEG;DATEND\n"
    "sid;0101;1;Mask;AA-999;;;\n"
).encode()
_TROIS_RAW = (
    "REGNOM;G31_12;NOTE;NAME;NAMEL;DATEEND;NAMET;MKTU\n"
    "00257/KNOWN;KNOWN;active;holder;;;;\n"
).encode()


def test_latest_version_uses_embedded_revision_not_metadata_order() -> None:
    older = OpendataVersion("data-20260831.csv", "https://example.invalid/old")
    newer = OpendataVersion(
        "data-20260901T1200-structure-20260902T0100.csv",
        "https://example.invalid/new",
    )
    meta = OpendataMeta("id", "title", "", "CSV", [older, newer])
    assert opendata_client.latest_version(meta) is newer
    assert opendata_client.ordered_versions(
        meta.versions,
        oldest_first=True,
    ) == [older, newer]


@pytest.mark.parametrize(
    "snapshot_id",
    (
        "data-20261340.csv",
        "data-undated.csv",
        "data-20260901-extra.csv",
    ),
)
def test_snapshot_revision_key_fails_closed_when_not_sortable(snapshot_id: str) -> None:
    with pytest.raises(ValueError):
        opendata_client.snapshot_revision_key(snapshot_id)


def test_official_opendata_url_rejects_query_mutation() -> None:
    with pytest.raises(RuntimeError, match="untrusted FTS opendata URL"):
        opendata_client._validate_official_url(
            "https://customs.gov.ru/7730176610-trois/data-20260903.csv?other=1",
            agency="fts",
            dataset_id=opendata_trois.TROIS_DATASET_ID,
            expected_suffix=".csv",
        )


def test_mask44_force_cannot_roll_back_a_successful_snapshot(tmp_path: Path) -> None:
    sm = _sessionmaker(CustomsDocMask.__table__, OpendataSyncLog.__table__)
    with sm() as db:
        db.add(CustomsDocMask(kod="0101", name="known", mask_pattern="KNOWN"))
        db.add(
            OpendataSyncLog(
                source_key="mask44",
                dataset_id=opendata_customs.MASK44_DATASET_ID,
                snapshot_id="data-20260903.csv",
                row_count=1,
                status="ok",
            )
        )
        db.commit()
    candidate = SimpleNamespace(
        snapshot_id="data-20260902.csv",
        url="https://official.invalid/data-20260902.csv",
    )
    with (
        patch.object(opendata_customs, "SessionLocal", sm),
        patch.object(opendata_customs, "fetch_fts_meta", return_value=_meta(candidate)),
        patch.object(opendata_customs, "backend_opendata_dir", return_value=tmp_path),
        patch.object(opendata_customs, "download_bytes") as download,
        pytest.raises(RuntimeError, match="refusing snapshot rollback"),
    ):
        opendata_customs.sync_mask44(force=True)
    download.assert_not_called()
    with sm() as db:
        assert [row.mask_pattern for row in db.query(CustomsDocMask).all()] == ["KNOWN"]


def test_trois_cannot_roll_back_a_successful_snapshot(tmp_path: Path) -> None:
    sm = _sessionmaker(TroisRegistry.__table__, OpendataSyncLog.__table__)
    with sm() as db:
        db.add(TroisRegistry(reg_number="KNOWN", trademark="KNOWN", brand="KNOWN"))
        db.add(
            OpendataSyncLog(
                source_key=opendata_trois.SOURCE_KEY,
                dataset_id=opendata_trois.TROIS_DATASET_ID,
                snapshot_id="data-20260903.csv",
                row_count=1,
                status="ok",
            )
        )
        db.commit()
    candidate = SimpleNamespace(
        snapshot_id="data-20260902.csv",
        url="https://official.invalid/data-20260902.csv",
    )
    with (
        patch.object(opendata_trois, "SessionLocal", sm),
        patch.object(opendata_trois, "fetch_fts_meta", return_value=_meta(candidate)),
        patch.object(opendata_trois, "backend_opendata_dir", return_value=tmp_path),
        patch.object(opendata_trois, "download_bytes") as download,
        pytest.raises(RuntimeError, match="refusing snapshot rollback"),
    ):
        opendata_trois.sync_trois_opendata()
    download.assert_not_called()


def test_fsa_cannot_replace_live_rows_with_an_older_revision(tmp_path: Path) -> None:
    sm = _sessionmaker(FsaCertificate.__table__, OpendataSyncLog.__table__)
    with sm() as db:
        db.add(
            FsaCertificate(
                registry_number="KNOWN",
                doc_type="СС",
                product_name="known",
                source_snapshot="data-20260903.7z",
            )
        )
        db.add(
            OpendataSyncLog(
                source_key="fsa_rss",
                dataset_id=opendata_fsa.FSA_RSS_ID,
                snapshot_id="data-20260903.7z",
                row_count=1,
                status="ok",
            )
        )
        db.commit()
    candidate = SimpleNamespace(
        snapshot_id="data-20260902.7z",
        url="https://official.invalid/data-20260902.7z",
        structure_url="https://official.invalid/structure-20260902.csv",
    )
    with (
        patch.object(opendata_fsa, "SessionLocal", sm),
        patch.object(opendata_fsa, "fetch_fsa_meta", return_value=_meta(candidate)),
        patch.object(opendata_fsa, "backend_opendata_dir", return_value=tmp_path),
        patch.object(opendata_fsa, "download_bytes") as download,
        pytest.raises(RuntimeError, match="refusing snapshot rollback"),
    ):
        opendata_fsa._sync_fsa_dataset(
            opendata_fsa.FSA_RSS_ID,
            doc_type="СС",
            source_key="fsa_rss",
            force=True,
        )
    download.assert_not_called()
    with sm() as db:
        assert [row.registry_number for row in db.query(FsaCertificate).all()] == ["KNOWN"]


def _add_mask_with_exact_evidence(
    sm,
    *,
    snapshot_id: str,
    url: str,
    artifact: bytes = _MASK_RAW,
) -> None:
    artifact_sha = hashlib.sha256(artifact).hexdigest()
    with sm() as db:
        db.add(CustomsDocMask(kod="0101", name="Mask", mask_pattern="AA-999"))
        db.flush()
        live_rows, fingerprint = opendata_customs._mask44_live_fingerprint(db)
        db.add(
            OpendataSyncLog(
                source_key="mask44",
                dataset_id=opendata_customs.MASK44_DATASET_ID,
                snapshot_id=snapshot_id,
                file_url=url,
                file_sha256=artifact_sha,
                row_count=live_rows,
                status="ok",
                details=encode_live_snapshot_details(
                    source_key="mask44",
                    dataset_id=opendata_customs.MASK44_DATASET_ID,
                    snapshot_id=snapshot_id,
                    artifact_url=url,
                    artifact_sha256=artifact_sha,
                    live_rows=live_rows,
                    live_fingerprint_sha256=fingerprint,
                ),
            )
        )
        db.commit()


def test_mask44_skip_requires_exact_live_content_not_only_row_count(tmp_path: Path) -> None:
    sm = _sessionmaker(CustomsDocMask.__table__, OpendataSyncLog.__table__)
    snapshot_id = "data-20260903.csv"
    url = "https://official.invalid/data-20260903.csv"
    _add_mask_with_exact_evidence(sm, snapshot_id=snapshot_id, url=url)
    meta = _meta(SimpleNamespace(snapshot_id=snapshot_id, url=url))
    with (
        patch.object(opendata_customs, "SessionLocal", sm),
        patch.object(opendata_customs, "fetch_fts_meta", return_value=meta),
        patch.object(opendata_customs, "backend_opendata_dir", return_value=tmp_path),
        patch.object(opendata_customs, "download_bytes", return_value=_MASK_RAW) as download,
    ):
        assert opendata_customs.sync_mask44()["status"] == "skipped"
        download.assert_called_once()

    with sm() as db:
        row = db.query(CustomsDocMask).one()
        row.mask_pattern = "TAMPERED"
        db.commit()
    with (
        patch.object(opendata_customs, "SessionLocal", sm),
        patch.object(opendata_customs, "fetch_fts_meta", return_value=meta),
        patch.object(opendata_customs, "backend_opendata_dir", return_value=tmp_path),
        patch.object(opendata_customs, "download_bytes", return_value=_MASK_RAW) as download,
        patch.object(opendata_customs, "configured_minimum_rows", return_value=1),
    ):
        assert opendata_customs.sync_mask44()["status"] == "ok"
    download.assert_called_once()
    with sm() as db:
        assert db.query(CustomsDocMask).one().mask_pattern == "AA-999"


def test_mask44_rejects_changed_bytes_under_immutable_snapshot_id(
    tmp_path: Path,
) -> None:
    sm = _sessionmaker(CustomsDocMask.__table__, OpendataSyncLog.__table__)
    snapshot_id = "data-20260903.csv"
    url = "https://official.invalid/data-20260903.csv"
    _add_mask_with_exact_evidence(sm, snapshot_id=snapshot_id, url=url)
    changed = _MASK_RAW.replace(b"AA-999", b"BB-999")
    meta = _meta(SimpleNamespace(snapshot_id=snapshot_id, url=url))
    with (
        patch.object(opendata_customs, "SessionLocal", sm),
        patch.object(opendata_customs, "fetch_fts_meta", return_value=meta),
        patch.object(opendata_customs, "backend_opendata_dir", return_value=tmp_path),
        patch.object(opendata_customs, "download_bytes", return_value=changed),
        patch.object(opendata_customs, "configured_minimum_rows", return_value=1),
        pytest.raises(RuntimeError, match="immutable data artifact"),
    ):
        opendata_customs.sync_mask44()
    with sm() as db:
        assert db.query(CustomsDocMask).one().mask_pattern == "AA-999"
        assert db.query(OpendataSyncLog).count() == 1


def _add_trois_with_exact_evidence(
    sm,
    *,
    snapshot_id: str,
    url: str,
    artifact: bytes = _TROIS_RAW,
) -> None:
    artifact_sha = hashlib.sha256(artifact).hexdigest()
    with sm() as db:
        db.add(
            TroisRegistry(
                reg_number="00257/KNOWN",
                trademark="KNOWN",
                brand="KNOWN",
                right_holder="holder",
                status="active",
            )
        )
        db.flush()
        live_rows, fingerprint = opendata_trois._trois_live_fingerprint(db)
        db.add(
            OpendataSyncLog(
                source_key=opendata_trois.SOURCE_KEY,
                dataset_id=opendata_trois.TROIS_DATASET_ID,
                snapshot_id=snapshot_id,
                file_url=url,
                file_sha256=artifact_sha,
                row_count=live_rows,
                status="ok",
                details=encode_live_snapshot_details(
                    source_key=opendata_trois.SOURCE_KEY,
                    dataset_id=opendata_trois.TROIS_DATASET_ID,
                    snapshot_id=snapshot_id,
                    artifact_url=url,
                    artifact_sha256=artifact_sha,
                    live_rows=live_rows,
                    live_fingerprint_sha256=fingerprint,
                ),
            )
        )
        db.commit()


def test_trois_skip_requires_exact_live_content_not_only_row_count(tmp_path: Path) -> None:
    sm = _sessionmaker(TroisRegistry.__table__, OpendataSyncLog.__table__)
    snapshot_id = "data-20260903.csv"
    url = "https://official.invalid/data-20260903.csv"
    _add_trois_with_exact_evidence(sm, snapshot_id=snapshot_id, url=url)
    meta = _meta(SimpleNamespace(snapshot_id=snapshot_id, url=url))
    with (
        patch.object(opendata_trois, "SessionLocal", sm),
        patch.object(opendata_trois, "fetch_fts_meta", return_value=meta),
        patch.object(opendata_trois, "backend_opendata_dir", return_value=tmp_path),
        patch.object(opendata_trois, "download_bytes", return_value=_TROIS_RAW) as download,
    ):
        assert opendata_trois.sync_trois_opendata()["status"] == "skipped"
        download.assert_called_once()

    with sm() as db:
        row = db.query(TroisRegistry).one()
        row.right_holder = "tampered"
        db.commit()
    with (
        patch.object(opendata_trois, "SessionLocal", sm),
        patch.object(opendata_trois, "fetch_fts_meta", return_value=meta),
        patch.object(opendata_trois, "backend_opendata_dir", return_value=tmp_path),
        patch.object(opendata_trois, "download_bytes", return_value=_TROIS_RAW) as download,
        patch.object(opendata_trois, "configured_minimum_rows", return_value=1),
        patch(
            "app.services.trois_registry_loader.sync_db_to_local_cache",
            return_value=None,
        ),
    ):
        assert opendata_trois.sync_trois_opendata()["status"] == "ok"
    download.assert_called_once()
    with sm() as db:
        assert db.query(TroisRegistry).one().right_holder == "holder"


def test_fsa_structure_contract_rejects_mismatch_and_number_only_schema(
    tmp_path: Path,
) -> None:
    contract = opendata_fsa._parse_fsa_structure_contract(
        b"position;field;description\n1;reg_number;Registry number\n2;cert_status;Status\n",
        doc_type="СС",
        url="https://fsa.gov.ru/opendata/7736638268-rss/structure-20260903.csv",
    )
    number_only = tmp_path / "number-only.csv"
    number_only.write_text("reg_number\nRU.C.1\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="semantic field"):
        opendata_fsa._validate_fsa_csv_schema(number_only, doc_type="СС")

    mismatched = tmp_path / "mismatched.csv"
    mismatched.write_text(
        "reg_number;product_name\nRU.C.1;product\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="not semantically identical"):
        opendata_fsa._validate_fsa_csv_schema(
            mismatched,
            doc_type="СС",
            structure_contract=contract,
        )

    full_contract = opendata_fsa._parse_fsa_structure_contract(
        (
            b"position;field;description\n"
            b"1;reg_number;Registry number\n"
            b"2;product_name;Product\n"
            b"3;cert_status;Status\n"
        ),
        doc_type="СС",
        url="https://fsa.gov.ru/opendata/7736638268-rss/structure-20260903.csv",
    )
    truncated = tmp_path / "truncated.csv"
    truncated.write_text(
        "reg_number;cert_status\nRU.C.1;active\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="not semantically identical"):
        opendata_fsa._validate_fsa_csv_schema(
            truncated,
            doc_type="СС",
            structure_contract=full_contract,
        )


def test_fsa_structure_does_not_treat_free_text_as_field_declarations() -> None:
    malicious = (
        b"field;description\n"
        b"foo;not a reg_number field\n"
        b"bar;cert_status is unavailable\n"
    )
    with pytest.raises(RuntimeError, match="does not declare"):
        opendata_fsa._parse_fsa_structure_contract(
            malicious,
            doc_type="СС",
            url="https://fsa.gov.ru/opendata/7736638268-rss/structure-20260903.csv",
        )


def test_fsa_rows_require_meaningful_values_beyond_registry_number() -> None:
    assert opendata_fsa._map_fsa_row(
        {"reg_number": "RU.C.1", "product_name": ""},
        doc_type="СС",
    ) is None
    mapped = opendata_fsa._map_fsa_row(
        {"reg_number": "RU.C.1", "product_name": "meaningful product"},
        doc_type="СС",
    )
    assert mapped is not None
    assert mapped["product_name"] == "meaningful product"


def test_fsa_sync_downloads_and_persists_bound_structure_evidence(tmp_path: Path) -> None:
    sm = _sessionmaker(FsaCertificate.__table__, OpendataSyncLog.__table__)
    snapshot_id = "data-20260903.7z"
    artifact_url = (
        "https://fsa.gov.ru/opendata/7736638268-rss/data-20260903.7z"
    )
    structure_url = (
        "https://fsa.gov.ru/opendata/7736638268-rss/structure-20260903.csv"
    )
    structure_raw = (
        b"position;field;description\n"
        b"1;reg_number;Registry number\n"
        b"2;product_name;Product\n"
    )
    archive_raw = b"7z\xbc\xaf'\x1c" + b"fixture"
    version = SimpleNamespace(
        snapshot_id=snapshot_id,
        url=artifact_url,
        structure_url=structure_url,
    )
    current_structure = [structure_raw]
    downloaded: list[str] = []

    def fake_download(url: str, *, dest: Path, **_kwargs) -> bytes:
        downloaded.append(url)
        raw = current_structure[0] if url == structure_url else archive_raw
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        return raw

    captured_contracts = []

    def fake_import(_path, *, structure_contract, db, snapshot_id, doc_type, **_kwargs):
        captured_contracts.append(structure_contract)
        db.query(FsaCertificate).filter(FsaCertificate.doc_type == doc_type).delete()
        db.add(
            FsaCertificate(
                registry_number="RU.C.1",
                doc_type=doc_type,
                product_name="official product",
                source_snapshot=snapshot_id,
            )
        )
        return {"created": 1, "updated": 0, "skipped": 0, "parsed": 1}

    with (
        patch.object(opendata_fsa, "SessionLocal", sm),
        patch.object(opendata_fsa, "fetch_fsa_meta", return_value=_meta(version)),
        patch.object(opendata_fsa, "backend_opendata_dir", return_value=tmp_path),
        patch.object(opendata_fsa, "download_bytes", side_effect=fake_download),
        patch.object(opendata_fsa, "download_file", side_effect=lambda url, **kwargs:
            opendata_client.DownloadedArtifact(kwargs["dest"],
                hashlib.sha256(fake_download(url, **kwargs)).hexdigest(),
                kwargs["dest"].stat().st_size)),
        patch.object(opendata_fsa, "_import_7z", side_effect=fake_import),
        patch.object(opendata_fsa, "configured_minimum_rows", return_value=1),
    ):
        result = opendata_fsa._sync_fsa_dataset(
            opendata_fsa.FSA_RSS_ID,
            doc_type="СС",
            source_key="fsa_rss",
        )
        unchanged = opendata_fsa._sync_fsa_dataset(
            opendata_fsa.FSA_RSS_ID,
            doc_type="СС",
            source_key="fsa_rss",
        )
        with sm() as tamper_db:
            tamper_db.query(FsaCertificate).one().product_name = "tampered"
            tamper_db.commit()
        changed_live = opendata_fsa._sync_fsa_dataset(
            opendata_fsa.FSA_RSS_ID,
            doc_type="СС",
            source_key="fsa_rss",
        )
        current_structure[0] = structure_raw + b"3;cert_status;Status\n"
        with pytest.raises(RuntimeError, match="immutable structure artifact"):
            opendata_fsa._sync_fsa_dataset(
                opendata_fsa.FSA_RSS_ID,
                doc_type="СС",
                source_key="fsa_rss",
            )

    assert downloaded == [artifact_url, structure_url] * 4
    assert [result[0]["status"], unchanged[0]["status"]] == ["ok", "skipped"]
    assert changed_live[0]["status"] == "ok"
    assert len(captured_contracts) == 2
    assert captured_contracts[0].groups >= {"registry_number", "product"}
    initial_structure_sha = hashlib.sha256(structure_raw).hexdigest()
    expected_structure_sha = initial_structure_sha
    assert result[0]["structure_sha256"] == initial_structure_sha
    with sm() as db:
        log = db.query(OpendataSyncLog).order_by(OpendataSyncLog.id.desc()).first()
        assert log is not None
        details = json.loads(log.details)
        assert details["structure"] == {
            "sha256": expected_structure_sha,
            "url": structure_url,
        }
        assert fsa_snapshot_details_match(
            log.details,
            source_key="fsa_rss",
            dataset_id=opendata_fsa.FSA_RSS_ID,
            snapshot_id=snapshot_id,
            artifact_url=artifact_url,
            artifact_sha256=log.file_sha256,
            structure_url=structure_url,
            structure_sha256=expected_structure_sha,
            live_rows=1,
            live_fingerprint_sha256=opendata_fsa._fsa_live_fingerprint(
                db,
                doc_type="СС",
            )[1],
        )
        assert db.query(FsaCertificate).one().product_name == "official product"


def test_trois_concurrent_older_writer_cannot_overwrite_newer_commit(
    tmp_path: Path,
) -> None:
    database = tmp_path / "opendata-race.db"
    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[TroisRegistry.__table__, OpendataSyncLog.__table__],
    )
    sm = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    thread_state = threading.local()
    new_writer_inside_lock = threading.Event()
    allow_new_writer_commit = threading.Event()
    results: dict[str, object] = {}
    original_upsert = opendata_trois.upsert_trois_registry_rows

    newer_raw = _TROIS_RAW.replace(b"00257/KNOWN", b"00258/NEWER").replace(
        b";KNOWN;",
        b";NEWER;",
    )
    older_raw = _TROIS_RAW.replace(b"00257/KNOWN", b"00256/OLDER").replace(
        b";KNOWN;",
        b";OLDER;",
    )

    def fake_meta(_dataset_id):
        revision = thread_state.revision
        return _meta(
            SimpleNamespace(
                snapshot_id=f"data-{revision}.csv",
                url=f"https://official.invalid/data-{revision}.csv",
            )
        )

    def fake_download(url: str, **_kwargs) -> bytes:
        return newer_raw if "20260903" in url else older_raw

    def gated_upsert(rows, **kwargs):
        stats = original_upsert(rows, **kwargs)
        if thread_state.revision == "20260903":
            new_writer_inside_lock.set()
            assert allow_new_writer_commit.wait(timeout=5)
        return stats

    def run_writer(name: str, revision: str) -> None:
        thread_state.revision = revision
        try:
            results[name] = opendata_trois.sync_trois_opendata()
        except Exception as exc:  # asserted below
            results[name] = exc

    with (
        patch.object(opendata_trois, "SessionLocal", sm),
        patch.object(opendata_trois, "fetch_fts_meta", side_effect=fake_meta),
        patch.object(opendata_trois, "backend_opendata_dir", return_value=tmp_path),
        patch.object(opendata_trois, "download_bytes", side_effect=fake_download),
        patch.object(opendata_trois, "configured_minimum_rows", return_value=1),
        patch.object(opendata_trois, "upsert_trois_registry_rows", side_effect=gated_upsert),
        patch(
            "app.services.trois_registry_loader.sync_db_to_local_cache",
            return_value=None,
        ),
    ):
        newer = threading.Thread(
            target=run_writer,
            args=("newer", "20260903"),
            name="newer-opendata",
        )
        older = threading.Thread(
            target=run_writer,
            args=("older", "20260902"),
            name="older-opendata",
        )
        newer.start()
        assert new_writer_inside_lock.wait(timeout=5)
        older.start()
        time.sleep(0.1)
        assert older.is_alive(), "older writer did not wait for the source write lock"
        allow_new_writer_commit.set()
        newer.join(timeout=5)
        older.join(timeout=5)

    assert isinstance(results["newer"], dict)
    assert results["newer"]["status"] == "ok"  # type: ignore[index]
    assert isinstance(results["older"], RuntimeError)
    assert "refusing snapshot rollback" in str(results["older"])
    with sm() as db:
        assert db.query(TroisRegistry).one().reg_number == "00258/NEWER"
        assert [row.snapshot_id for row in db.query(OpendataSyncLog).all()] == [
            "data-20260903.csv"
        ]


def test_trois_stale_same_revision_bytes_cannot_overwrite_concurrent_commit(
    tmp_path: Path,
) -> None:
    database = tmp_path / "opendata-same-revision-race.db"
    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[TroisRegistry.__table__, OpendataSyncLog.__table__],
    )
    sm = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    thread_state = threading.local()
    stale_prepared = threading.Event()
    fresh_committed = threading.Event()
    release_stale = threading.Event()
    results: dict[str, object] = {}
    real_lock = opendata_trois.acquire_opendata_write_lock

    fresh_raw = _TROIS_RAW.replace(b"00257/KNOWN", b"00258/FRESH").replace(
        b";KNOWN;",
        b";FRESH;",
    )
    stale_raw = _TROIS_RAW.replace(b"00257/KNOWN", b"00256/STALE").replace(
        b";KNOWN;",
        b";STALE;",
    )
    version = SimpleNamespace(
        snapshot_id="data-20260903.csv",
        url="https://official.invalid/data-20260903.csv",
    )

    def fake_download(_url: str, **_kwargs) -> bytes:
        return fresh_raw if thread_state.role == "fresh" else stale_raw

    def gated_lock(db, **kwargs) -> None:
        if thread_state.role == "stale":
            stale_prepared.set()
            assert release_stale.wait(timeout=5)
        real_lock(db, **kwargs)

    def run_writer(role: str) -> None:
        thread_state.role = role
        try:
            results[role] = opendata_trois.sync_trois_opendata()
        except Exception as exc:  # asserted below
            results[role] = exc
        finally:
            if role == "fresh":
                fresh_committed.set()

    with (
        patch.object(opendata_trois, "SessionLocal", sm),
        patch.object(opendata_trois, "fetch_fts_meta", return_value=_meta(version)),
        patch.object(opendata_trois, "backend_opendata_dir", return_value=tmp_path),
        patch.object(opendata_trois, "download_bytes", side_effect=fake_download),
        patch.object(opendata_trois, "configured_minimum_rows", return_value=1),
        patch.object(opendata_trois, "acquire_opendata_write_lock", side_effect=gated_lock),
        patch(
            "app.services.trois_registry_loader.sync_db_to_local_cache",
            return_value=None,
        ),
    ):
        stale = threading.Thread(target=run_writer, args=("stale",))
        fresh = threading.Thread(target=run_writer, args=("fresh",))
        stale.start()
        assert stale_prepared.wait(timeout=5)
        fresh.start()
        assert fresh_committed.wait(timeout=5)
        release_stale.set()
        stale.join(timeout=5)
        fresh.join(timeout=5)

    assert isinstance(results["fresh"], dict)
    assert results["fresh"]["status"] == "ok"  # type: ignore[index]
    assert isinstance(results["stale"], RuntimeError)
    assert "immutable data artifact" in str(results["stale"])
    with sm() as db:
        assert db.query(TroisRegistry).one().reg_number == "00258/FRESH"
        assert db.query(OpendataSyncLog).count() == 1


def test_fsa_same_revision_workers_import_their_own_staged_archive(
    tmp_path: Path,
) -> None:
    database = tmp_path / "fsa-same-revision-race.db"
    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[FsaCertificate.__table__, OpendataSyncLog.__table__],
    )
    sm = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    thread_state = threading.local()
    first_import_started = threading.Event()
    second_archive_downloaded = threading.Event()
    results: dict[str, object] = {}
    staged_archives: dict[str, Path] = {}

    snapshot_id = "data-20260903.7z"
    artifact_url = (
        "https://fsa.gov.ru/opendata/7736638268-rss/data-20260903.7z"
    )
    structure_url = (
        "https://fsa.gov.ru/opendata/7736638268-rss/structure-20260903.csv"
    )
    version = SimpleNamespace(
        snapshot_id=snapshot_id,
        url=artifact_url,
        structure_url=structure_url,
    )
    structure_raw = (
        b"position;field;description\n"
        b"1;reg_number;Registry number\n"
        b"2;product_name;Product\n"
    )
    archives = {
        "first": b"7z-first-worker",
        "second": b"7z-second-worker",
    }

    def fake_download(url: str, *, dest: Path, **_kwargs) -> bytes:
        role = thread_state.role
        raw = structure_raw if url == structure_url else archives[role]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        if url == artifact_url:
            staged_archives[role] = dest
            if role == "second":
                second_archive_downloaded.set()
        return raw

    def fake_import(path: Path, *, db, snapshot_id, doc_type, **_kwargs):
        assert thread_state.role == "first", "second worker must fail before import"
        first_import_started.set()
        assert second_archive_downloaded.wait(timeout=5)
        imported_bytes = Path(path).read_bytes()
        product_name = (
            "first" if imported_bytes == archives["first"] else "second"
        )
        db.query(FsaCertificate).filter(FsaCertificate.doc_type == doc_type).delete()
        db.add(
            FsaCertificate(
                registry_number="RU.C.1",
                doc_type=doc_type,
                product_name=product_name,
                source_snapshot=snapshot_id,
            )
        )
        return {"created": 1, "updated": 0, "skipped": 0, "parsed": 1}

    def run_writer(role: str) -> None:
        thread_state.role = role
        try:
            results[role] = opendata_fsa._sync_fsa_dataset(
                opendata_fsa.FSA_RSS_ID,
                doc_type="СС",
                source_key="fsa_rss",
            )
        except Exception as exc:  # asserted below
            results[role] = exc

    with (
        patch.object(opendata_fsa, "SessionLocal", sm),
        patch.object(opendata_fsa, "fetch_fsa_meta", return_value=_meta(version)),
        patch.object(opendata_fsa, "backend_opendata_dir", return_value=tmp_path),
        patch.object(opendata_fsa, "download_bytes", side_effect=fake_download),
        patch.object(opendata_fsa, "download_file", side_effect=lambda url, **kwargs:
            opendata_client.DownloadedArtifact(kwargs["dest"],
                hashlib.sha256(fake_download(url, **kwargs)).hexdigest(),
                kwargs["dest"].stat().st_size)),
        patch.object(opendata_fsa, "_import_7z", side_effect=fake_import),
        patch.object(opendata_fsa, "configured_minimum_rows", return_value=1),
    ):
        first = threading.Thread(target=run_writer, args=("first",))
        second = threading.Thread(target=run_writer, args=("second",))
        first.start()
        assert first_import_started.wait(timeout=5)
        second.start()
        first.join(timeout=5)
        second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert isinstance(results["first"], list)
    assert results["first"][0]["status"] == "ok"  # type: ignore[index]
    assert isinstance(results["second"], RuntimeError)
    assert "immutable data artifact" in str(results["second"])
    assert staged_archives["first"] != staged_archives["second"]
    assert all(not path.exists() for path in staged_archives.values())
    with sm() as db:
        assert db.query(FsaCertificate).one().product_name == "first"
        log = db.query(OpendataSyncLog).one()
        assert log.file_sha256 == hashlib.sha256(archives["first"]).hexdigest()
