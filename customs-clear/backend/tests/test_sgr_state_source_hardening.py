"""Fail-closed contracts for the EAEU SGR, FSS and REO adapters."""

from __future__ import annotations

import json
import sys
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.core import FssNotification, ReoRegistryEntry, SgrCertificate
from scripts import sync_sgr_registry, sync_state_registries


def _sessionmaker(*tables):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=list(tables))
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _result_contract(stdout: str) -> dict:
    line = next(
        row
        for row in reversed(stdout.splitlines())
        if row.startswith("REGULATORY_SYNC_RESULT=")
    )
    return json.loads(line.split("=", 1)[1])


def _raw_sgr(number: str) -> dict:
    return {"data": {"NUMB_DOC": number, "NAME_PROD": f"product {number}"}}


def _raw_fss(number: str) -> dict:
    return {"data": {"NotificationNumber": number, "Name": f"device {number}"}}


def _raw_reo(number: str) -> dict:
    return {"data": {"RecordId": number, "DeviceModelNam": f"model {number}"}}


def test_nsi_pagination_rejects_short_sgr_and_state_snapshots() -> None:
    with (
        patch.object(sync_sgr_registry, "_nsi_sgr_total", return_value=3),
        patch.object(sync_sgr_registry, "_http_post_json", return_value=[_raw_sgr("ONE")]),
        pytest.raises(RuntimeError, match="fetched_rows=1 expected_rows=3"),
    ):
        sync_sgr_registry._nsi_sgr_rows(code="1995", date_iso="2026-09-01")

    with (
        patch.object(sync_state_registries, "_nsi_total", return_value=2),
        patch.object(sync_state_registries, "_http_post_json", return_value=[_raw_fss("ONE")]),
        pytest.raises(RuntimeError, match="fetched_rows=1 expected_rows=2"),
    ):
        sync_state_registries._nsi_fetch_rows(code="1994", date_iso="2026-09-01")


def test_sgr_partial_nsi_never_deletes_and_full_shrink_is_rejected() -> None:
    sm = _sessionmaker(SgrCertificate.__table__)
    with sm() as db:
        db.add_all(
            SgrCertificate(sgr_number=f"OLD-{index}", product_name="known good")
            for index in range(10)
        )
        db.commit()

    with sm() as db, patch.object(
        sync_sgr_registry,
        "_nsi_sgr_rows",
        return_value=[_raw_sgr("NEW-PARTIAL")],
    ):
        assert sync_sgr_registry.sync_from_nsi(
            db,
            code="1995",
            date_iso="2026-09-01",
            max_rows=1,
        ) == (1, "nsi_ok")
        db.commit()

    with sm() as db:
        assert db.query(SgrCertificate).count() == 11

    with sm() as db, patch.object(
        sync_sgr_registry,
        "_nsi_sgr_rows",
        return_value=[_raw_sgr("NEW-FULL")],
    ):
        with pytest.raises(RuntimeError, match="shrank more than"):
            sync_sgr_registry.sync_from_nsi(
                db,
                code="1995",
                date_iso="2026-09-01",
                minimum_rows=1,
            )

    with sm() as db:
        assert db.query(SgrCertificate).count() == 11
        assert db.query(SgrCertificate).filter_by(sgr_number="NEW-FULL").count() == 0


def test_sgr_contract_attests_only_explicit_canonical_full_nsi(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sm = _sessionmaker(SgrCertificate.__table__)
    monkeypatch.setenv("REGULATORY_EEC_SGR_REGISTRY_MIN_ROWS", "1")
    monkeypatch.setenv("SGR_REGISTRY_SYNC_URL", "https://untrusted.invalid/sgr.csv")
    with (
        patch.object(sys, "argv", ["sync_sgr_registry.py", "--nsi", "--strict", "--json"]),
        patch.object(sync_sgr_registry, "SessionLocal", sm),
        patch.object(sync_sgr_registry, "init_db"),
        patch.object(sync_sgr_registry, "_nsi_sgr_rows", return_value=[_raw_sgr("CANONICAL")]),
        patch.object(sync_sgr_registry, "registry_http_get_text") as csv_download,
        patch.object(sync_sgr_registry, "upsert_source_status"),
        patch.object(sync_sgr_registry, "append_sync_log"),
        patch.object(sync_sgr_registry, "bump_preview_cache_revision"),
    ):
        assert sync_sgr_registry.main() == 0
    payload = _result_contract(capsys.readouterr().out)
    assert payload["official_source"] is True
    assert payload["snapshot_kind"] == "full"
    assert payload["source_variant"] == "nsi"
    csv_download.assert_not_called()

    with (
        patch.object(
            sys,
            "argv",
            [
                "sync_sgr_registry.py",
                "--nsi",
                "--nsi-code",
                "custom-dictionary",
                "--nsi-limit",
                "1",
                "--strict",
                "--json",
            ],
        ),
        patch.object(sync_sgr_registry, "SessionLocal", sm),
        patch.object(sync_sgr_registry, "init_db"),
        patch.object(sync_sgr_registry, "_nsi_sgr_rows", return_value=[_raw_sgr("CUSTOM")]),
        patch.object(sync_sgr_registry, "upsert_source_status"),
        patch.object(sync_sgr_registry, "append_sync_log"),
        patch.object(sync_sgr_registry, "bump_preview_cache_revision"),
    ):
        assert sync_sgr_registry.main() == 0
    payload = _result_contract(capsys.readouterr().out)
    assert payload["official_source"] is False
    assert payload["snapshot_kind"] == "partial"


def test_state_nsi_only_ignores_env_and_atomically_replaces_canonical_snapshots(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sm = _sessionmaker(FssNotification.__table__, ReoRegistryEntry.__table__)
    with sm() as db:
        db.add(FssNotification(number="OLD-FSS", name="old"))
        db.add(ReoRegistryEntry(number="OLD-REO", model_name="old"))
        db.commit()
    monkeypatch.setenv("FSS_NOTIFICATIONS_SYNC_URL", "https://untrusted.invalid/fss.csv")
    monkeypatch.setenv("REO_REGISTRY_SYNC_URL", "https://untrusted.invalid/reo.csv")
    monkeypatch.setenv("REGULATORY_EEC_FSS_NOTIFICATIONS_REGISTRY_MIN_ROWS", "1")
    monkeypatch.setenv("REGULATORY_EEC_REO_VCHU_REGISTRY_MIN_ROWS", "1")

    def fetch(*, code: str, **_kwargs):
        return [_raw_fss("NEW-FSS")] if code == "1994" else [_raw_reo("NEW-REO")]

    with (
        patch.object(
            sys,
            "argv",
            ["sync_state_registries.py", "--nsi-only", "--strict", "--json"],
        ),
        patch.object(sync_state_registries, "SessionLocal", sm),
        patch.object(sync_state_registries, "init_db"),
        patch.object(sync_state_registries, "_nsi_fetch_rows", side_effect=fetch),
        patch.object(sync_state_registries, "registry_http_get_text") as csv_download,
        patch.object(sync_state_registries, "upsert_source_status"),
        patch.object(sync_state_registries, "append_sync_log"),
        patch.object(sync_state_registries, "bump_preview_cache_revision"),
    ):
        assert sync_state_registries.main() == 0
    payload = _result_contract(capsys.readouterr().out)
    assert payload["official_source"] is True
    assert payload["snapshot_kind"] == "full"
    csv_download.assert_not_called()
    with sm() as db:
        assert [row.number for row in db.query(FssNotification).all()] == ["NEW-FSS"]
        assert [row.number for row in db.query(ReoRegistryEntry).all()] == ["NEW-REO"]


def test_state_limited_nsi_is_partial_upsert_and_never_deletes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    sm = _sessionmaker(FssNotification.__table__, ReoRegistryEntry.__table__)
    with sm() as db:
        db.add(FssNotification(number="OLD-FSS", name="old"))
        db.add(ReoRegistryEntry(number="OLD-REO", model_name="old"))
        db.commit()

    def fetch(*, code: str, **_kwargs):
        return [_raw_fss("NEW-FSS")] if code == "1994" else [_raw_reo("NEW-REO")]

    with (
        patch.object(
            sys,
            "argv",
            [
                "sync_state_registries.py",
                "--nsi-only",
                "--nsi-limit",
                "1",
                "--strict",
                "--json",
            ],
        ),
        patch.object(sync_state_registries, "SessionLocal", sm),
        patch.object(sync_state_registries, "init_db"),
        patch.object(sync_state_registries, "_nsi_fetch_rows", side_effect=fetch),
        patch.object(sync_state_registries, "upsert_source_status"),
        patch.object(sync_state_registries, "append_sync_log"),
        patch.object(sync_state_registries, "bump_preview_cache_revision"),
    ):
        assert sync_state_registries.main() == 0
    payload = _result_contract(capsys.readouterr().out)
    assert payload["official_source"] is False
    assert payload["snapshot_kind"] == "partial"
    with sm() as db:
        assert {row.number for row in db.query(FssNotification).all()} == {"OLD-FSS", "NEW-FSS"}
        assert {row.number for row in db.query(ReoRegistryEntry).all()} == {"OLD-REO", "NEW-REO"}
