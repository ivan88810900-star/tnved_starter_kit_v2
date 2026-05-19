"""Валидация и отчёт official SGR seed dataset."""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.ntm_v2 import NtmApplicabilityRuleV2, NtmMeasureV2
from app.services.ntm_v2_official_sgr_dataset_report import build_official_sgr_dataset_report
from app.services.ntm_v2_official_sgr_dataset_validation import validate_official_sgr_dataset
from app.services.ntm_v2_official_sgr_import import (
    evaluate_official_sgr_from_seed_payload,
    import_official_sgr_rules_to_ntm_v2,
    load_official_sgr_payload,
    official_sgr_seed_rule_matches_position,
)


@pytest.fixture
def valid_payload() -> dict:
    return load_official_sgr_payload()


def test_seed_passes_validator_without_errors(valid_payload: dict) -> None:
    result = validate_official_sgr_dataset(valid_payload)
    assert result["valid"] is True
    assert result["error_count"] == 0
    assert result["summary"]["total_rules"] >= 40
    assert result["warning_count"] == 0


def test_3808_definite_no_wide_hs_warning(valid_payload: dict) -> None:
    result = validate_official_sgr_dataset(valid_payload)
    wide = [w for w in result["warnings"] if w.get("rule_id") == "eec299-3808-disinfectants"]
    assert wide == []


def test_duplicate_rule_id_detected(valid_payload: dict) -> None:
    payload = copy.deepcopy(valid_payload)
    payload["rules"].append(copy.deepcopy(payload["rules"][0]))
    result = validate_official_sgr_dataset(payload)
    assert result["valid"] is False
    assert any(e["code"] == "duplicate_rule_id" for e in result["errors"])


def test_invalid_applicability_detected(valid_payload: dict) -> None:
    payload = copy.deepcopy(valid_payload)
    payload["rules"][0]["applicability"] = "maybe"
    result = validate_official_sgr_dataset(payload)
    assert result["valid"] is False
    assert any(e["code"] == "invalid_applicability" for e in result["errors"])


def test_missing_required_field_detected(valid_payload: dict) -> None:
    payload = copy.deepcopy(valid_payload)
    del payload["rules"][0]["title"]
    result = validate_official_sgr_dataset(payload)
    assert result["valid"] is False
    assert any(e["code"] == "missing_required" for e in result["errors"])


def test_prohibited_definite_9503_rejected(valid_payload: dict) -> None:
    payload = copy.deepcopy(valid_payload)
    payload["rules"].append(
        {
            "rule_id": "bad-toy-definite",
            "hs_scope": "9503",
            "hs_scope_mode": "prefix",
            "permit_type": "СГР",
            "applicability": "definite",
            "title": "Игрушки",
            "evidence": "test",
        }
    )
    result = validate_official_sgr_dataset(payload)
    assert result["valid"] is False
    assert any(e["code"] == "prohibited_definite_hs" for e in result["errors"])


def test_no_9503_or_8508_in_official_seed(valid_payload: dict) -> None:
    for row in valid_payload["rules"]:
        hs = str(row.get("hs_scope") or "")
        assert not hs.startswith("9503")
        assert not hs.startswith("8508")


def test_dataset_report_sanity_all_pass(valid_payload: dict) -> None:
    report = build_official_sgr_dataset_report(valid_payload, run_sanity=True)
    assert report["validation"]["valid"] is True
    assert report["sanity_passed"] is True


@pytest.mark.parametrize(
    ("hs", "desc", "expect_definite", "expect_any"),
    [
        ("3808990000", "Дезинфектант", True, True),
        ("9503007500", "Кукла", False, False),
        ("3304990000", "Косметика для взрослых", False, False),
        ("3304990000", "Детский крем", True, True),
        ("2201900000", "Питьевая вода", False, False),
        ("2201900000", "минеральная вода лечебная", False, True),
        ("9999999999", "БАД витаминный", False, True),
        ("1901100000", "детское питание смесь", True, True),
    ],
)
def test_seed_evaluate_matrix(
    valid_payload: dict,
    hs: str,
    desc: str,
    expect_definite: bool,
    expect_any: bool,
) -> None:
    ev = evaluate_official_sgr_from_seed_payload(valid_payload, hs, desc)
    assert ev["has_definite_sgr"] is expect_definite
    assert bool(ev["matched_rules"]) is expect_any


def test_mineral_water_needs_clarification(valid_payload: dict) -> None:
    ev = evaluate_official_sgr_from_seed_payload(valid_payload, "2201900000", "минеральная вода лечебная")
    assert any(m["applicability"] == "needs_clarification" for m in ev["matched_rules"])


def test_child_diapers_needs_clarification_not_definite(valid_payload: dict) -> None:
    ev = evaluate_official_sgr_from_seed_payload(valid_payload, "9619000000", "Подгузники детские")
    assert ev["has_definite_sgr"] is False
    assert any(m["applicability"] == "needs_clarification" for m in ev["matched_rules"])


def test_antifreeze_3820_possible(valid_payload: dict) -> None:
    ev = evaluate_official_sgr_from_seed_payload(valid_payload, "3820000000", "Антифриз")
    assert any(m["applicability"] == "possible" for m in ev["matched_rules"])


@pytest.fixture
def memory_sessionmaker(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[NtmMeasureV2.__table__, NtmApplicabilityRuleV2.__table__],
    )
    sm = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr("app.db.SessionLocal", sm)
    return sm


def test_expanded_seed_import_idempotent(memory_sessionmaker: sessionmaker, valid_payload: dict) -> None:
    r1 = import_official_sgr_rules_to_ntm_v2(valid_payload)
    assert r1["rules_created"] == len(valid_payload["rules"])
    r2 = import_official_sgr_rules_to_ntm_v2(valid_payload)
    assert r2["rules_created"] == 0
    assert r2["rules_updated"] >= r1["rules_created"]
