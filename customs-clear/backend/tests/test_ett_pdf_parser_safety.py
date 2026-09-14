from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from app.services import ett_pdf_parser as parser


@pytest.mark.parametrize("max_groups", [0, 1, 5, 96, -1])
def test_retired_sync_cannot_fetch_or_write_even_for_full_corpus(monkeypatch, max_groups):
    from app.services import normative_store

    def forbidden(*args, **kwargs):
        pytest.fail("quarantined ETT sync performed a network/database operation")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    monkeypatch.setattr(parser, "_fetch_pdf_links", forbidden)
    monkeypatch.setattr(parser, "parse_ett_pdf_from_url", forbidden)
    for name in ("upsert_hs_rate", "upsert_source_status", "append_sync_log", "SessionLocal"):
        monkeypatch.setattr(normative_store, name, forbidden)

    result = asyncio.run(parser.sync_ett_from_pdfs(max_groups=max_groups))

    assert result["status"] == "REVIEW_REQUIRED"
    assert result["rows"] == result["files"] == 0
    assert result["quarantined"] is True
    assert result["reason"] == "versioned_manifest_review_required"


def test_legacy_download_entry_points_are_also_inert(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("retired downloader opened an HTTP client")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    assert asyncio.run(parser._fetch_pdf_links()) == []
    assert asyncio.run(parser.parse_ett_pdf_from_url("http://127.0.0.1/private")) == []


@pytest.mark.parametrize("value", [
    "", "товары", "0", "5", "8471300000 Ноутбуки 2026", "Прочие 0",
    "8471300000 изделия с содержанием сахара 5%", "5% + 0,2 евро за кг",
    "5%, но не менее 0,2 евро за кг", "не более 10%", "0,2 евро/кг",
    "5% (сноска 1)", "5% с 01.01.2026", "5%\n10%", "5% 10%",
    "НДС 22%", "-5%", "NaN%", "Infinity%", "٥%", "5%\n",
])
def test_only_isolated_percentage_cells_can_yield_a_duty(value):
    assert parser._extract_duty_from_line(value) is None


@pytest.mark.parametrize(("value", "expected"), [
    ("0%", "0%"), ("5 %", "5%"), (" 12,50% ", "12.5%"),
    ("100%", "100%"), ("0.125%", "0.125%"),
])
def test_explicit_isolated_percentage_is_not_confused_with_missing_data(value, expected):
    assert parser._extract_duty_from_line(value) == expected


@pytest.mark.parametrize("value", ["", "НДС 22%", "НДС: 10", "НДС 0%", "22%"])
def test_ett_never_supplies_vat_even_when_text_mentions_it(value):
    assert parser._extract_vat_from_line(value) is None


def test_flattened_rows_retain_conflicts_without_fabricating_payment_records():
    text = (
        "8471 30 000 0 Ноутбуки массой не более 10 кг\n"
        "8471300000 Ноутбуки 5%, но не менее 0,2 евро/кг\n"
        "8471300000 НДС 22%\n"
        "8471 Заголовок 5%\n"
        "84713000001 лишняя цифра 10%"
    )
    records = parser._parse_pdf_text(text)

    assert len(records) == 3
    assert [row["hs_code"] for row in records] == ["8471300000"] * 3
    for row in records:
        assert row["review_status"] == "REVIEW_REQUIRED"
        assert row["candidate_only"] is True
        assert row["raw_text"]
        assert not {
            "hs_prefix", "duty_rate", "vat_import_rate", "vat_rule",
            "vat_rule_basis", "excise_type", "excise_value", "has_antidumping",
            "source_revision",
        }.intersection(row)


def test_unidentified_table_columns_cannot_establish_advalorem_duty():
    records = parser._parse_table_to_records([
        ["8471300000", "Содержание вещества 10%", "5%, но не менее 0,2 евро/кг"],
        ["8471300000", "Товар", "0"],
    ])
    assert len(records) == 2
    assert all("duty_rate" not in row and "vat_import_rate" not in row for row in records)


@pytest.mark.parametrize("code", ["8471", "847130", "84713000001", "٨471300000", "из 8471300000"])
def test_code_normalization_cannot_synthesize_or_sanitize_a_leaf(code):
    assert parser._normalize_hs(code) is None


def test_guessed_odata_registry_cannot_be_claimed_as_ett(monkeypatch):
    from app.services import ett_odata_parser

    def forbidden(*args, **kwargs):
        pytest.fail("guessed OData ETT discovery opened a network path")

    monkeypatch.setattr(ett_odata_parser, "fetch_odata_registry", forbidden)
    result = asyncio.run(ett_odata_parser.try_fetch_ett_registry(["Bogus ETT", "Contains rate"]))
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["quarantined"] is True
    assert result["rows"] == 0


def test_combined_odata_sync_reports_ett_review_without_disabling_separate_preferences(monkeypatch):
    from app.services import ett_odata_parser

    async def fetch_preference(registry_name, **kwargs):
        assert registry_name == "Классификатор льгот по уплате таможенных платежей"
        return [{"CustomsPreferentialDutyCode": "X"}], None

    monkeypatch.setattr(ett_odata_parser, "fetch_odata_registry", fetch_preference)
    monkeypatch.setenv("ETT_ODATA_REGISTRY_NAMES", "arbitrary caller guessed registry")
    result = asyncio.run(ett_odata_parser.sync_all_odata())
    assert result["status"] == "WARNING"
    assert result["sources"][0]["status"] == "OK"
    assert result["sources"][1]["status"] == "REVIEW_REQUIRED"


def test_full_tariff_script_cannot_initialize_database_or_run_other_syncs(monkeypatch, capsys):
    from app.services import ett_odata_parser, normative_store, preview_cache_revision

    def forbidden(*args, **kwargs):
        pytest.fail("quarantined full tariff CLI performed a side effect")

    monkeypatch.setattr(normative_store, "init_db", forbidden)
    monkeypatch.setattr(ett_odata_parser, "sync_all_odata", forbidden)
    monkeypatch.setattr(preview_cache_revision, "bump_preview_cache_revision", forbidden)
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    path = Path(__file__).resolve().parents[1] / "scripts" / "load_full_tariff.py"
    spec = importlib.util.spec_from_file_location("legacy_full_tariff_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    exit_code = asyncio.run(module.main())
    assert exit_code != 0
    output = capsys.readouterr().out
    assert "REVIEW_REQUIRED" in output
    assert "Готово" not in output


def test_landing_page_cannot_mark_ett_rates_fresh_or_replace_approved_provenance(monkeypatch):
    from app.services import source_sync

    def forbidden(*args, **kwargs):
        pytest.fail("retired index freshness path fetched or wrote source state")

    for name in ("_http_get_with_retries", "upsert_source_status", "append_sync_log", "upsert_hs_rate"):
        monkeypatch.setattr(source_sync, name, forbidden)
    result = asyncio.run(source_sync.sync_eec_snapshot())
    assert result["source"] == "EEC_ETT"
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["rows"] == 0
    assert result["quarantined"] is True
    assert "revision" not in result


def test_admin_ett_endpoint_preserves_quarantine_without_cache_revision_write(monkeypatch):
    from app.api import sources

    def forbidden(*args, **kwargs):
        pytest.fail("quarantined API operation wrote a cache revision")

    monkeypatch.setattr(sources, "require_admin_token", lambda token: None)
    monkeypatch.setattr(sources, "clear_preview_cache", forbidden)
    result = asyncio.run(sources.sources_sync_ett(x_admin_token="test-only"))
    assert result.status_code == 200
    payload = json.loads(result.body)
    assert payload["status"] == "REVIEW_REQUIRED"
    assert payload["rows"] == 0
