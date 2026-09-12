"""Commercial TWS data cannot cross the official-payment admission boundary."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pandas as pd
import pytest

from app.services import regulatory_sync as tws


def test_apply_is_blocked_before_download_initialization_or_write():
    with (
        patch.object(tws, "download_tws_tariff_excel", side_effect=AssertionError("download")),
        patch("app.services.normative_store.init_db", side_effect=AssertionError("init")),
        patch("app.services.normative_store.upsert_hs_rate", side_effect=AssertionError("write")),
        patch("app.services.normative_store.append_sync_log", side_effect=AssertionError("stamp")),
    ):
        result = tws.run_tws_tariff_sync()
    assert result["status"] == "manual_review_required"
    assert result["rows_upserted"] == 0
    for field in ("db_mutated", "active_rates_written", "source_evidence_verified", "legal_review_verified", "retention_verified"):
        assert result[field] is False


def test_dry_run_retains_counts_without_database_access_or_synthetic_rates(tmp_path):
    frame = pd.DataFrame([
        {"Код ТН ВЭД": "7112300000", "Пошлина": ""},
        {"Код ТН ВЭД": "7112910000", "Пошлина": "0%"},
    ])
    with (
        patch.object(tws, "download_tws_tariff_excel", return_value=(tmp_path / "observed.xlsx", b"mocked transport")),
        patch.object(tws, "load_tws_tariff_dataframe", return_value=(frame, ("Код ТН ВЭД", "Пошлина", None, None), "fixture")),
        patch("app.services.normative_store.init_db", side_effect=AssertionError("init")),
        patch("app.services.normative_store.SessionLocal", side_effect=AssertionError("database")),
    ):
        result = tws.run_tws_tariff_sync(dry_run=True)
    assert result["status"] == "manual_review_required"
    assert result["parser_result"] == {"status": "parsed", "rates_count": 2}
    assert result["rows_parsed"] == 2
    assert result["rows_upserted"] == 0
    assert result["unresolved_duty_rows"] == 1
    assert result["unresolved_vat_rows"] == 2
    assert result["unresolved_excise_rows"] == 2
    assert result["candidate_only"] is True
    assert result["db_mutated"] is False
    assert result["legal_review_verified"] is False


@pytest.mark.parametrize("raw", [None, "", "—", "-", float("nan")])
def test_missing_duty_never_becomes_zero(raw):
    assert tws.parse_duty_text_to_hs_fields(raw)["duty_rate"] is None


@pytest.mark.parametrize("raw", [None, "", "0/10/22", "5/105", "нет данных", True, -1, float("nan"), "1" * 400])
def test_missing_or_ambiguous_vat_has_no_default(raw):
    assert tws.parse_vat_cell(raw, default=22) is None


@pytest.mark.parametrize("raw, expected", [(0, 0.0), ("0%", 0.0), ("10 %", 10.0), ("22", 22.0)])
def test_explicit_numeric_vat_is_only_a_candidate(raw, expected):
    assert tws.parse_vat_cell(raw) == expected


def test_conditional_duty_is_not_reduced_to_unconditional_zero():
    text = "беспошлинно при наличии сертификата происхождения"
    assert tws.parse_duty_text_to_hs_fields(text)["duty_rate"] == text
    assert tws.parse_duty_text_to_hs_fields("0%")["duty_rate"] == "0"


@pytest.mark.parametrize("raw", [None, "", "неизвестно", "2813 руб. + 16%, но не менее 3820 руб.", "1" * 400 + "%"])
def test_unknown_or_combined_excise_is_unavailable(raw):
    kind, value, _ = tws.parse_excise_cell(raw)
    assert kind == "unavailable"
    assert value is None


def test_dataframe_preserves_zero_source_text_without_broadening_code():
    frame = pd.DataFrame([
        {"Код ТН ВЭД": "7112300000", "Пошлина": 0, "НДС": 0},
        {"Код ТН ВЭД": "71123000000", "Пошлина": "5%", "НДС": "10%"},
        {"Код ТН ВЭД": "x7112300000", "Пошлина": "5%", "НДС": "10%"},
    ])
    rows = tws.dataframe_to_hs_rate_rows(frame)
    assert len(rows) == 1
    row = rows[0]
    assert row["hs_code"] == "7112300000"
    assert row["hs_prefix"] == ""
    assert row["duty_rate"] == "0"
    assert row["vat_import_rate"] == 0.0
    assert row["source_text"]["duty"] == "0"
    assert row["source_text"]["vat"] == "0"
    assert row["candidate_only"] is True
    assert row["legal_review_verified"] is False


def test_default_cli_exits_blocked_and_does_not_create_database(tmp_path):
    db = tmp_path / "never-created.db"
    backend = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(backend / "scripts/sync_tws_data.py")],
        cwd=tmp_path, env={**os.environ, "DATABASE_URL": f"sqlite:///{db}"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 2, result.stderr
    body = json.loads(result.stdout)
    assert body["status"] == "manual_review_required"
    assert body["db_mutated"] is False
    assert not db.exists()
