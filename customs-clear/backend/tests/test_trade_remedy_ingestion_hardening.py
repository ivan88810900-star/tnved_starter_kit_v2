"""Strict numeric ingestion checks using synthetic trade-remedy fixtures."""
from __future__ import annotations

import importlib
import json
from decimal import Decimal

import pytest


FAMILIES = ("anti_dumping", "countervailing", "special_safeguard")
INVALID_RATES = [
    {},
    {"rate_type": "percent"},
    {"rate_type": "combined_max", "rate_value": 12, "rate_specific": 2},
    {"rate_type": "combined_min", "rate_value": 12, "rate_specific": 2},
    {"rate_type": "unknown", "rate_value": 12},
    {"rate_type": "", "rate_value": 12},
    {"rate_type": None, "rate_value": 12},
    {"rate_type": "percent", "rate_value": None},
    {"rate_type": "percent", "rate_value": ""},
    {"rate_type": "percent", "rate_value": "not-a-rate"},
    {"rate_type": "percent", "rate_value": False},
    {"rate_type": "percent", "rate_value": True},
    {"rate_type": "percent", "rate_value": -1},
    {"rate_type": "percent", "rate_value": float("nan")},
    {"rate_type": "percent", "rate_value": float("inf")},
    {"rate_type": "percent", "rate_value": "1e10000"},
    {"rate_type": "percent", "rate_value": []},
    {"rate_type": "percent", "rate_value": {}},
    {"rate_type": "percent", "rate_value": 0, "rate_percent": 12},
    {"rate_type": "percent", "rate_value": 12, "rate_specific": 2},
    {"rate_type": "specific", "rate_specific": 2, "rate_value": 3},
    {"rate_type": "specific", "rate_specific": 0, "rate_specific_value": 3},
    {"rate_type": "specific", "rate_specific": 2, "rate_percent": 12},
    {"rate_type": "specific", "rate_specific": None},
    {"rate_type": "specific", "rate_specific": False},
    {"rate_type": "specific", "rate_specific": -1},
    {"rate_type": "specific", "rate_specific": float("nan")},
    {"rate_type": "percent", "duty_type": "specific", "rate_value": 2},
    {"rate_type": "specific", "rate_value": 2, "currency_code": ""},
    {"rate_type": "specific", "rate_value": 2, "currency_code": "not-a-currency"},
    {"rate_type": "percent", "rate_value": "1.00000000000000001", "rate_percent": "1.00000000000000002"},
    {"rate_type": "specific", "rate_value": Decimal("1.00000000000000001"),
     "rate_specific": Decimal("1.00000000000000002")},
    {"rate_type": "specific", "rate_value": 2, "currency_code": "EUR", "currency": "USD"},
    {"rate_type": "specific", "rate_value": 2, "specific_uom": "kg", "unit": "t"},
    {"rate_type": "specific", "rate_value": 2, "specific_uom": "kg"},
    {"rate_type": "percent", "rate_value": 12, "needs_verification": "false"},
    {"rate_type": "percent", "rate_value": 12, "needs_verification": "true"},
    {"rate_type": "percent", "rate_value": 12, "needs_verification": 0},
    {"rate_type": "percent", "rate_value": 12, "needs_verification": 1},
    {"rate_type": "percent", "rate_value": 12, "needs_verification": None},
]


def _row(family: str, fields: dict) -> dict:
    return {
        "hs_code": "9901210000",
        "origin_country": "CN",
        "measure_type": family,
        "regulatory_act": "Synthetic ingestion fixture; not a legal source",
        "currency_code": "EUR",
        **fields,
    }


def _bundle(family: str, rows: list[dict]) -> dict:
    return {
        "revision": family.replace("_", "-") + ":2026-05-01",
        "official_url": "https://eec.eaeunion.org/comission/department/deptexsec/trade_remedies/",
        "measures": rows,
    }


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("fields", INVALID_RATES)
def test_malformed_rate_is_blocked_instead_of_zero(family: str, fields: dict) -> None:
    module = importlib.import_module("app.services." + family + "_ingestion")
    _, rows, blockers = getattr(module, "_extract_" + family + "_rows")(
        _bundle(family, [_row(family, fields)])
    )
    assert rows == []
    assert any("invalid_measure_rate" in blocker for blocker in blockers)


@pytest.mark.parametrize("family", FAMILIES)
def test_unrepresentable_json_exponent_is_a_parser_blocker(
    family: str, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = importlib.import_module("app.services." + family + "_ingestion")
    filename = "eec_" + family + ".json"
    payload = _bundle(family, [_row(family, {"rate_type": "percent", "rate_value": "RAW_NUMBER"})])
    (tmp_path / filename).write_text(json.dumps(payload).replace('"RAW_NUMBER"', "1e999999999999999999999999999999"))
    monkeypatch.setattr(module, "_BACKEND_ROOT", tmp_path)
    _, _, _, rows, blockers = module._validate_bundle_for_ingest(filename)
    assert rows == []
    assert any("parser_failed" in blocker for blocker in blockers)


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("fields", INVALID_RATES)
def test_source_parser_never_reports_invalid_rate_as_parsed(family: str, fields: dict) -> None:
    module = importlib.import_module("app.services." + family + "_ingestion")
    result = getattr(module, "_validate_official_" + family + "_bundle_payload")(
        _bundle(family, [_row(family, fields)]), rel_path="fixture.json", checksum="a" * 64
    )
    assert result["status"] == "parser_failed"
    assert result["reason"] == "invalid_" + family + "_rate_value"


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("fields,percent,specific", [
    ({"rate_type": "percent", "rate_value": 0}, 0.0, 0.0),
    ({"rate_percent": 0}, 0.0, 0.0),
    ({"rate_percent": "12,5", "rate_specific": 0}, 12.5, 0.0),
    ({"rate_type": "percent", "rate_value": 2.5, "rate_percent": "2.50"}, 2.5, 0.0),
    ({"rate_type": "specific", "rate_value": 2.5}, 0.0, 2.5),
    ({"rate_type": "percent", "rate_value": 5, "needs_verification": True}, 5.0, 0.0),
    ({"rate_type": "percent", "rate_value": 5, "needs_verification": False}, 5.0, 0.0),
    ({"rate_type": "fixed", "rate_specific": "2,5"}, 0.0, 2.5),
    ({"rate_specific": 2.5}, 0.0, 2.5),
    ({"rate_type": "specific", "rate_value": 0}, 0.0, 0.0),
    ({"rate_type": "specific", "rate_value": 2.5, "rate_specific": 2.5}, 0.0, 2.5),
])
def test_explicit_zero_and_supported_rates_are_preserved(
    family: str, fields: dict, percent: float, specific: float
) -> None:
    module = importlib.import_module("app.services." + family + "_ingestion")
    _, rows, blockers = getattr(module, "_extract_" + family + "_rows")(
        _bundle(family, [_row(family, fields)])
    )
    assert blockers == []
    assert len(rows) == 1
    assert rows[0]["rate_percent"] == percent
    assert rows[0]["rate_specific"] == specific


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("mode", ("dry_run", "apply"))
@pytest.mark.parametrize("fields", INVALID_RATES)
def test_bad_row_blocks_entire_bundle_before_database_access(
    family: str, mode: str, fields: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = importlib.import_module("app.services." + family + "_ingestion")
    payload = _bundle(family, [
        _row(family, {"rate_type": "percent", "rate_value": 12}),
        _row(family, fields),
    ])
    monkeypatch.setattr(module, "discover_" + family + "_bundle_path", lambda **_: "fixture.json")
    monkeypatch.setattr(module, "_load_bundle_payload", lambda _: (
        payload, {"status": "parsed", "checksum_sha256": "a" * 64}
    ))

    def forbidden(*args, **kwargs):
        raise AssertionError("A blocked source must not reach planning, writes or coverage queries")

    for name in ("SessionLocal", "_plan_" + family + "_rows", "_apply_" + family + "_rows",
                 "run_payment_data_coverage_report", "upsert_source_status", "append_sync_log"):
        monkeypatch.setattr(module, name, forbidden)
    result = getattr(module, "run_" + family + "_" + mode)(rel_path="fixture.json")
    assert result["status"] in {"parser_failed", "manual_review_required"}
    assert result["db_mutated"] is False
    assert any("invalid_measure_rate" in blocker for blocker in result["blockers"])


@pytest.mark.parametrize("family", FAMILIES)
def test_untyped_row_with_no_rate_cannot_be_silently_skipped(family: str) -> None:
    module = importlib.import_module("app.services." + family + "_ingestion")
    raw = _row(family, {})
    del raw["measure_type"]
    _, rows, blockers = getattr(module, "_extract_" + family + "_rows")(
        _bundle(family, [_row(family, {"rate_percent": 12}), raw])
    )
    assert len(rows) == 1
    assert any("invalid_measure_rate" in blocker for blocker in blockers)


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("literal", ("1e-400", "1e400", "NaN", "Infinity", "-Infinity"))
def test_json_number_magnitude_is_preserved_until_validation(
    family: str, literal: str, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = importlib.import_module("app.services." + family + "_ingestion")
    filename = "eec_" + family + ".json"
    payload = _bundle(family, [_row(family, {"rate_type": "percent", "rate_value": "RAW_NUMBER"})])
    (tmp_path / filename).write_text(json.dumps(payload).replace('"RAW_NUMBER"', literal))
    monkeypatch.setattr(module, "_BACKEND_ROOT", tmp_path)
    _, parser_result, _, rows, blockers = module._validate_bundle_for_ingest(filename)
    assert rows == []
    if literal in {"NaN", "Infinity", "-Infinity"}:
        assert parser_result["reason"] == "invalid_bundle_json"
        assert any("nonfinite_json_number" in blocker for blocker in blockers)
    else:
        assert any("invalid_measure_rate" in blocker for blocker in blockers)


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("fields,percent,specific", [
    ({"rate_type": "percent", "rate_value": 0}, 0.0, 0.0),
    ({"rate_type": "specific", "rate_value": 0}, 0.0, 0.0),
    ({"rate_type": "specific", "rate_value": 2.5}, 0.0, 2.5),
    ({"rate_type": "percent", "rate_value": 5, "needs_verification": True}, 5.0, 0.0),
    ({"rate_type": "percent", "rate_value": 5, "needs_verification": False}, 5.0, 0.0),
])
def test_valid_simple_rate_reaches_isolated_storage_unchanged(
    family: str, fields: dict, percent: float, specific: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db import Base
    from app.models.core import SourceStatus, SyncLog
    from app.models.tnved import SpecialDuty

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[SpecialDuty.__table__, SourceStatus.__table__, SyncLog.__table__])
    sessions = sessionmaker(bind=engine)
    module = importlib.import_module("app.services." + family + "_ingestion")
    payload = _bundle(family, [_row(family, fields)])
    monkeypatch.setattr(module, "SessionLocal", sessions)
    monkeypatch.setattr("app.services.normative_store.SessionLocal", sessions)
    monkeypatch.setattr(module, "run_payment_data_coverage_report", lambda: {})
    monkeypatch.setattr(module, "discover_" + family + "_bundle_path", lambda **_: "fixture.json")
    monkeypatch.setattr(module, "_load_bundle_payload", lambda _: (
        payload, {"status": "parsed", "checksum_sha256": "a" * 64}
    ))
    try:
        result = getattr(module, "run_" + family + "_apply")(rel_path="fixture.json")
        assert result["status"] == "OK"
        with sessions() as db:
            row = db.query(SpecialDuty).one()
            assert row.rate_percent == percent
            assert row.rate_specific == specific
            assert row.measure_type == family
            assert row.currency_code == "EUR"
            assert row.needs_verification is fields.get("needs_verification", True)
        # A flag-only source change must be detected and stored exactly. It is
        # source metadata and does not constitute legal approval.
        changed_flag = not fields.get("needs_verification", True)
        payload["measures"][0]["needs_verification"] = changed_flag
        plan = getattr(module, "run_" + family + "_dry_run")(rel_path="fixture.json")
        assert plan["row_counts"]["update"] == 1
        updated = getattr(module, "run_" + family + "_apply")(rel_path="fixture.json")
        assert updated["row_counts"]["update"] == 1
        with sessions() as db:
            assert db.query(SpecialDuty).one().needs_verification is changed_flag
    finally:
        engine.dispose()
