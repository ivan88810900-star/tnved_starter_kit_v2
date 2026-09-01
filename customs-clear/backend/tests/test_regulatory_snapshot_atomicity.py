"""Full-snapshot adapters must replace atomically and preserve known-good data on failure."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.core import (
    EuSanctionsList,
    FssNotification,
    OfacSdnList,
    ReoRegistryEntry,
    SgrCertificate,
    SourceStatus,
    SyncLog,
)
from app.models.tnved import CustomsDocMask, FsaCertificate, OpendataSyncLog, TroisRegistry
from app.services import opendata_customs, opendata_fsa, opendata_trois
from app.services import trois_registry_sync
from scripts import sync_eu_sanctions, sync_ofac_sanctions, sync_sgr_registry, sync_state_registries

_OFAC_EVIDENCE = {
    "source_url": sync_ofac_sanctions.OFAC_DEFAULT_URL,
    "revision": "sha256:test-ofac",
    "note": "test",
}
_EU_EVIDENCE = {
    "source_url": sync_eu_sanctions.EU_DEFAULT_URL,
    "revision": "sha256:test-eu",
    "note": "test",
}


class _FailCommitSession(Session):
    def commit(self) -> None:
        raise RuntimeError("injected commit failure")


def _sessionmakers(*tables):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=list(tables))
    normal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    failing = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        class_=_FailCommitSession,
    )
    return normal, failing


def _fake_7z(csv_text: str):
    class _Archive:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def extractall(self, *, path) -> None:
            (Path(path) / "snapshot.csv").write_text(csv_text, encoding="utf-8")

    return _Archive


def test_ofac_empty_or_invalid_snapshot_preserves_live_rows() -> None:
    sm, _ = _sessionmakers(
        OfacSdnList.__table__,
        SourceStatus.__table__,
        SyncLog.__table__,
    )
    with sm() as db:
        db.add(OfacSdnList(name="KNOWN GOOD", type="entity", origin_country="US", aliases="[]"))
        db.commit()

    with patch.object(sync_ofac_sanctions, "SessionLocal", sm):
        assert sync_ofac_sanctions._replace_rows([], **_OFAC_EVIDENCE) == 0
        assert sync_ofac_sanctions._replace_rows(
            [{"name": "", "type": "", "origin_country": "", "aliases": ""}],
            **_OFAC_EVIDENCE,
        ) == 0

    with sm() as db:
        assert [row.name for row in db.query(OfacSdnList).all()] == ["KNOWN GOOD"]


def test_ofac_replacement_removes_delisted_rows_and_rolls_back_commit_failure() -> None:
    sm, failing_sm = _sessionmakers(
        OfacSdnList.__table__,
        SourceStatus.__table__,
        SyncLog.__table__,
    )
    with sm() as db:
        db.add(OfacSdnList(name="DELISTED", type="entity", origin_country="US", aliases="[]"))
        db.commit()
    replacement = [{"name": "ACTIVE", "type": "entity", "origin_country": "GB", "aliases": "[]"}]

    with patch.object(sync_ofac_sanctions, "SessionLocal", failing_sm):
        with pytest.raises(RuntimeError, match="injected commit failure"):
            sync_ofac_sanctions._replace_rows(replacement, **_OFAC_EVIDENCE)
    with sm() as db:
        assert [row.name for row in db.query(OfacSdnList).all()] == ["DELISTED"]

    with patch.object(sync_ofac_sanctions, "SessionLocal", sm):
        assert sync_ofac_sanctions._replace_rows(replacement, **_OFAC_EVIDENCE) == 1
    with sm() as db:
        assert [row.name for row in db.query(OfacSdnList).all()] == ["ACTIVE"]


def test_eu_empty_or_invalid_snapshot_preserves_live_rows() -> None:
    sm, _ = _sessionmakers(
        EuSanctionsList.__table__,
        SourceStatus.__table__,
        SyncLog.__table__,
    )
    with sm() as db:
        db.add(EuSanctionsList(hs_code="8517", entity_name="KNOWN GOOD", description="old"))
        db.commit()

    with patch.object(sync_eu_sanctions, "SessionLocal", sm):
        assert sync_eu_sanctions._replace_rows([], **_EU_EVIDENCE) == 0
        assert sync_eu_sanctions._replace_rows(
            [{"hs_code": "", "entity_name": "", "description": ""}],
            **_EU_EVIDENCE,
        ) == 0

    with sm() as db:
        assert [row.entity_name for row in db.query(EuSanctionsList).all()] == ["KNOWN GOOD"]


def test_eu_replacement_removes_delisted_rows_and_rolls_back_commit_failure() -> None:
    sm, failing_sm = _sessionmakers(
        EuSanctionsList.__table__,
        SourceStatus.__table__,
        SyncLog.__table__,
    )
    with sm() as db:
        db.add(EuSanctionsList(hs_code="8517", entity_name="DELISTED", description="old"))
        db.commit()
    replacement = [{"hs_code": "8542", "entity_name": "ACTIVE", "description": "new"}]

    with patch.object(sync_eu_sanctions, "SessionLocal", failing_sm):
        with pytest.raises(RuntimeError, match="injected commit failure"):
            sync_eu_sanctions._replace_rows(replacement, **_EU_EVIDENCE)
    with sm() as db:
        assert [row.entity_name for row in db.query(EuSanctionsList).all()] == ["DELISTED"]

    with patch.object(sync_eu_sanctions, "SessionLocal", sm):
        assert sync_eu_sanctions._replace_rows(replacement, **_EU_EVIDENCE) == 1
    with sm() as db:
        assert [row.entity_name for row in db.query(EuSanctionsList).all()] == ["ACTIVE"]


def test_ofac_metadata_failure_rolls_back_destructive_replacement() -> None:
    sm, _ = _sessionmakers(
        OfacSdnList.__table__,
        SourceStatus.__table__,
        SyncLog.__table__,
    )
    with sm() as db:
        db.add(OfacSdnList(name="KNOWN GOOD", type="entity", origin_country="US", aliases="[]"))
        db.commit()

    replacement = [{"name": "UNCOMMITTED", "type": "entity", "origin_country": "GB", "aliases": "[]"}]
    with (
        patch.object(sync_ofac_sanctions, "SessionLocal", sm),
        patch.object(
            sync_ofac_sanctions,
            "stage_sync_log",
            side_effect=RuntimeError("injected metadata failure"),
        ),
        pytest.raises(RuntimeError, match="metadata failure"),
    ):
        sync_ofac_sanctions._replace_rows(
            replacement,
            source_url=sync_ofac_sanctions.OFAC_DEFAULT_URL,
            revision="sha256:test",
            note="test",
        )

    with sm() as db:
        assert [row.name for row in db.query(OfacSdnList).all()] == ["KNOWN GOOD"]
        assert db.query(SourceStatus).filter(SourceStatus.source_code == "OFAC_SDN").count() == 0
        assert db.query(SyncLog).filter(SyncLog.source_code == "OFAC_SDN").count() == 0


def test_eu_metadata_failure_rolls_back_destructive_replacement() -> None:
    sm, _ = _sessionmakers(
        EuSanctionsList.__table__,
        SourceStatus.__table__,
        SyncLog.__table__,
    )
    with sm() as db:
        db.add(EuSanctionsList(hs_code="8517", entity_name="KNOWN GOOD", description="old"))
        db.commit()

    replacement = [{"hs_code": "8542", "entity_name": "UNCOMMITTED", "description": "new"}]
    with (
        patch.object(sync_eu_sanctions, "SessionLocal", sm),
        patch.object(
            sync_eu_sanctions,
            "stage_sync_log",
            side_effect=RuntimeError("injected metadata failure"),
        ),
        pytest.raises(RuntimeError, match="metadata failure"),
    ):
        sync_eu_sanctions._replace_rows(
            replacement,
            source_url=sync_eu_sanctions.EU_DEFAULT_URL,
            revision="sha256:test",
            note="test",
        )

    with sm() as db:
        assert [row.entity_name for row in db.query(EuSanctionsList).all()] == ["KNOWN GOOD"]
        assert db.query(SourceStatus).filter(SourceStatus.source_code == "EU_SANCTIONS").count() == 0
        assert db.query(SyncLog).filter(SyncLog.source_code == "EU_SANCTIONS").count() == 0


def test_sgr_full_nsi_snapshot_preserves_on_empty_and_replaces_when_valid() -> None:
    sm, _ = _sessionmakers(SgrCertificate.__table__)
    with sm() as db:
        db.add(SgrCertificate(sgr_number="OLD-SGR", product_name="old"))
        db.commit()

    with sm() as db, patch.object(sync_sgr_registry, "_nsi_sgr_rows", return_value=[]):
        assert sync_sgr_registry.sync_from_nsi(
            db,
            code="1995",
            date_iso="2026-09-01",
        ) == (0, "nsi_empty")
        db.commit()
    with sm() as db:
        assert [row.sgr_number for row in db.query(SgrCertificate).all()] == ["OLD-SGR"]

    raw = [{"data": {"NUMB_DOC": "NEW-SGR", "NAME_PROD": "new", "STATUS": "active"}}]
    with sm() as db, patch.object(sync_sgr_registry, "_nsi_sgr_rows", return_value=raw):
        assert sync_sgr_registry.sync_from_nsi(
            db,
            code="1995",
            date_iso="2026-09-01",
        ) == (1, "nsi_ok")
        db.commit()
    with sm() as db:
        assert [row.sgr_number for row in db.query(SgrCertificate).all()] == ["NEW-SGR"]


def test_sgr_full_nsi_snapshot_rolls_back_after_replacement_failure() -> None:
    sm, _ = _sessionmakers(SgrCertificate.__table__)
    with sm() as db:
        db.add(SgrCertificate(sgr_number="OLD-SGR", product_name="old"))
        db.commit()
    raw = [{"data": {"NUMB_DOC": "NEW-SGR", "NAME_PROD": "new"}}]

    with pytest.raises(RuntimeError, match="injected row failure"):
        with (
            sm() as db,
            patch.object(sync_sgr_registry, "_nsi_sgr_rows", return_value=raw),
            patch.object(sync_sgr_registry, "upsert_sgr", side_effect=RuntimeError("injected row failure")),
        ):
            sync_sgr_registry.sync_from_nsi(db, code="1995", date_iso="2026-09-01")
    with sm() as db:
        assert [row.sgr_number for row in db.query(SgrCertificate).all()] == ["OLD-SGR"]


def test_state_registry_pair_rolls_back_when_one_snapshot_is_empty(tmp_path: Path) -> None:
    sm, _ = _sessionmakers(FssNotification.__table__, ReoRegistryEntry.__table__)
    with sm() as db:
        db.add(FssNotification(number="OLD-FSS", name="old"))
        db.add(ReoRegistryEntry(number="OLD-REO", model_name="old"))
        db.commit()
    fss_csv = tmp_path / "fss.csv"
    reo_csv = tmp_path / "reo.csv"
    fss_csv.write_text("number,name,brand,status\nNEW-FSS,new,Brand,active\n", encoding="utf-8")
    reo_csv.write_text("number,model_name,brand,status\n", encoding="utf-8")

    with (
        patch.object(
            sys,
            "argv",
            [
                "sync_state_registries.py",
                "--strict",
                "--json",
                "--fss-csv",
                str(fss_csv),
                "--reo-csv",
                str(reo_csv),
            ],
        ),
        patch.object(sync_state_registries, "SessionLocal", sm),
        patch.object(sync_state_registries, "init_db"),
        patch.object(sync_state_registries, "upsert_source_status"),
        patch.object(sync_state_registries, "append_sync_log"),
    ):
        assert sync_state_registries.main() == 1

    with sm() as db:
        assert [row.number for row in db.query(FssNotification).all()] == ["OLD-FSS"]
        assert [row.number for row in db.query(ReoRegistryEntry).all()] == ["OLD-REO"]


def test_state_registry_custom_csv_upserts_without_deleting_live_rows(tmp_path: Path) -> None:
    sm, _ = _sessionmakers(FssNotification.__table__, ReoRegistryEntry.__table__)
    with sm() as db:
        db.add(FssNotification(number="OLD-FSS", name="old"))
        db.add(ReoRegistryEntry(number="OLD-REO", model_name="old"))
        db.commit()
    fss_csv = tmp_path / "fss.csv"
    reo_csv = tmp_path / "reo.csv"
    fss_csv.write_text("number,name,brand,status\nNEW-FSS,new,Brand,active\n", encoding="utf-8")
    reo_csv.write_text(
        "number,model_name,brand,characteristics,status\nNEW-REO,new,Brand,2.4GHz,active\n",
        encoding="utf-8",
    )

    with (
        patch.object(
            sys,
            "argv",
            [
                "sync_state_registries.py",
                "--strict",
                "--json",
                "--fss-csv",
                str(fss_csv),
                "--reo-csv",
                str(reo_csv),
            ],
        ),
        patch.object(sync_state_registries, "SessionLocal", sm),
        patch.object(sync_state_registries, "init_db"),
        patch.object(sync_state_registries, "upsert_source_status"),
        patch.object(sync_state_registries, "append_sync_log"),
        patch.object(sync_state_registries, "bump_preview_cache_revision"),
    ):
        assert sync_state_registries.main() == 0

    with sm() as db:
        assert {row.number for row in db.query(FssNotification).all()} == {"OLD-FSS", "NEW-FSS"}
        assert {row.number for row in db.query(ReoRegistryEntry).all()} == {"OLD-REO", "NEW-REO"}


def test_fsa_snapshot_empty_and_commit_failure_preserve_previous_doc_type(tmp_path: Path) -> None:
    sm, failing_sm = _sessionmakers(FsaCertificate.__table__)
    with sm() as db:
        db.add(FsaCertificate(registry_number="OLD-CC", doc_type="СС", product_name="old"))
        db.add(FsaCertificate(registry_number="OLD-DS", doc_type="ДС", product_name="old"))
        db.commit()
    archive_path = tmp_path / "snapshot.7z"

    with (
        patch.object(opendata_fsa, "SessionLocal", sm),
        patch.object(
            opendata_fsa.py7zr,
            "SevenZipFile",
            _fake_7z("reg_number;product_name\n"),
        ),
        pytest.raises(RuntimeError, match="zero valid registry rows"),
    ):
        opendata_fsa._import_7z(archive_path, doc_type="СС", snapshot_id="empty")

    valid_csv = "reg_number;product_name\nNEW-CC;new certificate\n"
    with (
        patch.object(opendata_fsa, "SessionLocal", failing_sm),
        patch.object(opendata_fsa.py7zr, "SevenZipFile", _fake_7z(valid_csv)),
        pytest.raises(RuntimeError, match="injected commit failure"),
    ):
        opendata_fsa._import_7z(archive_path, doc_type="СС", snapshot_id="failed")

    with sm() as db:
        assert {(row.registry_number, row.doc_type) for row in db.query(FsaCertificate).all()} == {
            ("OLD-CC", "СС"),
            ("OLD-DS", "ДС"),
        }


def test_fsa_snapshot_replaces_only_its_document_type(tmp_path: Path) -> None:
    sm, _ = _sessionmakers(FsaCertificate.__table__)
    with sm() as db:
        db.add(FsaCertificate(registry_number="OLD-CC", doc_type="СС", product_name="old"))
        db.add(FsaCertificate(registry_number="OLD-DS", doc_type="ДС", product_name="old"))
        db.commit()
    archive_path = tmp_path / "snapshot.7z"
    valid_csv = "reg_number;product_name\nNEW-CC;new certificate\n"

    with (
        patch.object(opendata_fsa, "SessionLocal", sm),
        patch.object(opendata_fsa.py7zr, "SevenZipFile", _fake_7z(valid_csv)),
    ):
        result = opendata_fsa._import_7z(archive_path, doc_type="СС", snapshot_id="full")
    assert result["parsed"] == 1
    with sm() as db:
        assert {(row.registry_number, row.doc_type) for row in db.query(FsaCertificate).all()} == {
            ("NEW-CC", "СС"),
            ("OLD-DS", "ДС"),
        }


def test_fsa_snapshot_rolls_back_first_batch_when_later_batch_fails(tmp_path: Path) -> None:
    sm, _ = _sessionmakers(FsaCertificate.__table__)
    with sm() as db:
        db.add(FsaCertificate(registry_number="OLD-CC", doc_type="СС", product_name="old"))
        db.commit()
    archive_path = tmp_path / "snapshot.7z"
    raw_rows = [
        {"reg_number": f"NEW-CC-{index:04d}", "product_name": f"certificate {index}"}
        for index in range(501)
    ]
    original_apply = opendata_fsa._apply_fsa_rows
    calls = 0

    def flaky_apply(db, rows, *, snapshot_id):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected second batch failure")
        return original_apply(db, rows, snapshot_id=snapshot_id)

    with (
        patch.object(opendata_fsa, "SessionLocal", sm),
        patch.object(
            opendata_fsa.py7zr,
            "SevenZipFile",
            _fake_7z("reg_number;product_name\nplaceholder;placeholder\n"),
        ),
        patch.object(opendata_fsa, "_iter_csv_rows", side_effect=lambda _path: iter(raw_rows)),
        patch.object(opendata_fsa, "_apply_fsa_rows", side_effect=flaky_apply),
        pytest.raises(RuntimeError, match="injected second batch failure"),
    ):
        opendata_fsa._import_7z(archive_path, doc_type="СС", snapshot_id="failed-late")

    assert calls == 2
    with sm() as db:
        assert [row.registry_number for row in db.query(FsaCertificate).all()] == ["OLD-CC"]


def test_fsa_rss_and_rds_roll_back_as_one_aggregate_snapshot() -> None:
    sm, _ = _sessionmakers(FsaCertificate.__table__, OpendataSyncLog.__table__)
    with sm() as db:
        db.add(FsaCertificate(registry_number="OLD-CC", doc_type="СС", product_name="old"))
        db.add(FsaCertificate(registry_number="OLD-DS", doc_type="ДС", product_name="old"))
        db.commit()

    def update_rss_then_fail_rds(dataset_id, *, doc_type, db, **_kwargs):
        if doc_type == "СС":
            db.query(FsaCertificate).filter(FsaCertificate.doc_type == "СС").delete()
            db.add(FsaCertificate(registry_number="NEW-CC", doc_type="СС", product_name="new"))
            return [{"status": "ok", "snapshot_id": "rss-new", "parsed": 1}]
        raise RuntimeError("injected RDS failure")

    with (
        patch.object(opendata_fsa, "SessionLocal", sm),
        patch.object(opendata_fsa, "_sync_fsa_dataset", side_effect=update_rss_then_fail_rds),
    ):
        result = opendata_fsa.sync_fsa_certificates()

    assert result["aggregate_status"] == "error"
    with sm() as db:
        assert {(row.registry_number, row.doc_type) for row in db.query(FsaCertificate).all()} == {
            ("OLD-CC", "СС"),
            ("OLD-DS", "ДС"),
        }


def _trois_row(reg_number: str, trademark: str) -> dict[str, str]:
    return {
        "reg_number": reg_number,
        "trademark": trademark,
        "brand": trademark,
        "right_holder": "holder",
        "status": "active",
        "valid_until": "2030-01-01",
        "representatives": "goods",
    }


def test_trois_snapshot_preserves_on_empty_or_commit_failure_and_replaces_on_success() -> None:
    sm, failing_sm = _sessionmakers(TroisRegistry.__table__)
    with sm() as db:
        db.add(TroisRegistry(**_trois_row("00257/OLD", "OLD BRAND"), is_active=True))
        db.commit()

    with patch.object(trois_registry_sync, "SessionLocal", sm):
        with pytest.raises(RuntimeError, match="zero valid rows"):
            trois_registry_sync.upsert_trois_registry_rows([], replace_snapshot=True)

    replacement = [_trois_row("00258/NEW", "NEW BRAND")]
    with patch.object(trois_registry_sync, "SessionLocal", failing_sm):
        with pytest.raises(RuntimeError, match="injected commit failure"):
            trois_registry_sync.upsert_trois_registry_rows(replacement, replace_snapshot=True)
    with sm() as db:
        assert [row.reg_number for row in db.query(TroisRegistry).all()] == ["00257/OLD"]

    with patch.object(trois_registry_sync, "SessionLocal", sm):
        stats = trois_registry_sync.upsert_trois_registry_rows(replacement, replace_snapshot=True)
    assert stats["created"] == 1
    with sm() as db:
        assert [row.reg_number for row in db.query(TroisRegistry).all()] == ["00258/NEW"]


def test_trois_snapshot_rejects_implausible_shrink_before_delete() -> None:
    sm, _ = _sessionmakers(TroisRegistry.__table__)
    with sm() as db:
        db.add_all(
            TroisRegistry(**_trois_row(f"{index:05d}/OLD", f"OLD {index}"), is_active=True)
            for index in range(10)
        )
        db.commit()

    with patch.object(trois_registry_sync, "SessionLocal", sm):
        with pytest.raises(RuntimeError, match="shrank more than"):
            trois_registry_sync.upsert_trois_registry_rows(
                [_trois_row("90000/NEW", "NEW")],
                replace_snapshot=True,
                minimum_rows=1,
            )

    with sm() as db:
        assert db.query(TroisRegistry).count() == 10
        assert db.query(TroisRegistry).filter(TroisRegistry.reg_number == "90000/NEW").count() == 0


def _mask_csv(rows: int) -> bytes:
    lines = ["SID_SMEV;KOD;N_MSK;NAME_MSK;K_MASKA;DSCR_MSK;DATBEG;DATEND"]
    lines.extend(
        f"sid-{index};{index:04d};{index};Mask {index};PATTERN-{index};desc;;"
        for index in range(rows)
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def test_customs_mask_snapshot_rejects_shrink_and_preserves_last_good(tmp_path: Path) -> None:
    sm, _ = _sessionmakers(CustomsDocMask.__table__, OpendataSyncLog.__table__)
    with sm() as db:
        db.add_all(
            CustomsDocMask(kod=str(index), mask_pattern=f"OLD-{index}")
            for index in range(10)
        )
        db.commit()
    meta = SimpleNamespace(
        modified="01.09.2026",
        versions=[SimpleNamespace(snapshot_id="data-20260901.csv", url="https://official.invalid/mask.csv")],
    )

    with (
        patch.object(opendata_customs, "SessionLocal", sm),
        patch.object(opendata_customs, "fetch_fts_meta", return_value=meta),
        patch.object(opendata_customs, "download_bytes", return_value=_mask_csv(1)),
        patch.object(opendata_customs, "backend_opendata_dir", return_value=tmp_path),
        patch.object(opendata_customs, "configured_minimum_rows", return_value=1),
        pytest.raises(RuntimeError, match="shrank more than"),
    ):
        opendata_customs.sync_mask44(force=True)

    with sm() as db:
        assert db.query(CustomsDocMask).count() == 10
        assert {row.mask_pattern for row in db.query(CustomsDocMask).all()} == {
            f"OLD-{index}" for index in range(10)
        }


def test_customs_mask_snapshot_rolls_back_on_commit_failure(tmp_path: Path) -> None:
    sm, failing_sm = _sessionmakers(CustomsDocMask.__table__, OpendataSyncLog.__table__)
    with sm() as db:
        db.add_all(
            CustomsDocMask(kod=str(index), mask_pattern=f"OLD-{index}")
            for index in range(10)
        )
        db.commit()
    meta = SimpleNamespace(
        modified="01.09.2026",
        versions=[SimpleNamespace(snapshot_id="data-20260901.csv", url="https://official.invalid/mask.csv")],
    )

    with (
        patch.object(opendata_customs, "SessionLocal", failing_sm),
        patch.object(opendata_customs, "fetch_fts_meta", return_value=meta),
        patch.object(opendata_customs, "download_bytes", return_value=_mask_csv(10)),
        patch.object(opendata_customs, "backend_opendata_dir", return_value=tmp_path),
        patch.object(opendata_customs, "configured_minimum_rows", return_value=1),
        pytest.raises(RuntimeError, match="injected commit failure"),
    ):
        opendata_customs.sync_mask44(force=True)

    with sm() as db:
        assert {row.mask_pattern for row in db.query(CustomsDocMask).all()} == {
            f"OLD-{index}" for index in range(10)
        }


def test_customs_cached_success_is_reimported_when_live_row_count_differs(
    tmp_path: Path,
) -> None:
    sm, _ = _sessionmakers(CustomsDocMask.__table__, OpendataSyncLog.__table__)
    snapshot_id = "data-20260901.csv"
    with sm() as db:
        db.add(CustomsDocMask(kod="1", mask_pattern="INCOMPLETE"))
        db.add(
            OpendataSyncLog(
                source_key="mask44",
                dataset_id=opendata_customs.MASK44_DATASET_ID,
                snapshot_id=snapshot_id,
                row_count=50_000,
                status="ok",
            )
        )
        db.commit()
    meta = SimpleNamespace(
        modified="01.09.2026",
        versions=[SimpleNamespace(snapshot_id=snapshot_id, url="https://official.invalid/mask.csv")],
    )

    with (
        patch.object(opendata_customs, "SessionLocal", sm),
        patch.object(opendata_customs, "fetch_fts_meta", return_value=meta),
        patch.object(
            opendata_customs,
            "download_bytes",
            side_effect=RuntimeError("reimport attempted"),
        ) as download,
        patch.object(opendata_customs, "backend_opendata_dir", return_value=tmp_path),
        pytest.raises(RuntimeError, match="reimport attempted"),
    ):
        opendata_customs.sync_mask44()
    download.assert_called_once()


def test_trois_cached_success_is_reimported_when_live_row_count_differs(
    tmp_path: Path,
) -> None:
    sm, _ = _sessionmakers(TroisRegistry.__table__, OpendataSyncLog.__table__)
    snapshot_id = "data-20260901.csv"
    with sm() as db:
        db.add(TroisRegistry(**_trois_row("00257/OLD", "INCOMPLETE"), is_active=True))
        db.add(
            OpendataSyncLog(
                source_key=opendata_trois.SOURCE_KEY,
                dataset_id=opendata_trois.TROIS_DATASET_ID,
                snapshot_id=snapshot_id,
                row_count=50_000,
                status="ok",
            )
        )
        db.commit()
    meta = SimpleNamespace(
        modified="01.09.2026",
        versions=[SimpleNamespace(snapshot_id=snapshot_id, url="https://official.invalid/trois.csv")],
    )

    with (
        patch.object(opendata_trois, "SessionLocal", sm),
        patch.object(opendata_trois, "fetch_fts_meta", return_value=meta),
        patch.object(
            opendata_trois,
            "download_bytes",
            side_effect=RuntimeError("reimport attempted"),
        ) as download,
        patch.object(opendata_trois, "backend_opendata_dir", return_value=tmp_path),
        pytest.raises(RuntimeError, match="reimport attempted"),
    ):
        opendata_trois.sync_trois_opendata()
    download.assert_called_once()


def test_fsa_cached_success_is_reimported_when_live_row_count_differs(
    tmp_path: Path,
) -> None:
    sm, _ = _sessionmakers(FsaCertificate.__table__, OpendataSyncLog.__table__)
    snapshot_id = "data-20260901.7z"
    with sm() as db:
        db.add(
            FsaCertificate(
                registry_number="INCOMPLETE",
                doc_type="СС",
                source_snapshot=snapshot_id,
            )
        )
        db.add(
            OpendataSyncLog(
                source_key="fsa_rss",
                dataset_id=opendata_fsa.FSA_RSS_ID,
                snapshot_id=snapshot_id,
                row_count=50_000,
                status="ok",
            )
        )
        db.commit()
    meta = SimpleNamespace(
        modified="01.09.2026",
        versions=[SimpleNamespace(snapshot_id=snapshot_id, url="https://official.invalid/rss.7z")],
    )

    with (
        patch.object(opendata_fsa, "SessionLocal", sm),
        patch.object(opendata_fsa, "fetch_fsa_meta", return_value=meta),
        patch.object(opendata_fsa, "backend_opendata_dir", return_value=tmp_path),
        patch.object(
            opendata_fsa,
            "download_bytes",
            side_effect=RuntimeError("reimport attempted"),
        ) as download,
        pytest.raises(RuntimeError, match="reimport attempted"),
    ):
        opendata_fsa._sync_fsa_dataset(
            opendata_fsa.FSA_RSS_ID,
            doc_type="СС",
            source_key="fsa_rss",
        )
    download.assert_called_once()
