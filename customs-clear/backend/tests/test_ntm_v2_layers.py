"""Импорт и runtime ntm_layers → NTM v2 (флаг ``NTM_V2_LAYERS_ENABLED``)."""

from __future__ import annotations

import asyncio
import logging

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.ntm_v2 import NtmApplicabilityRuleV2, NtmMeasureV2
from app.services.ntm_v2_import import import_ntm_layers_to_ntm_v2, import_tr_ts_catalog_to_ntm_v2
from tests.test_ntm_pipeline import REGRESSION_MATRIX


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


def test_import_layers_creates_measures_and_rules(memory_sessionmaker: sessionmaker) -> None:
    r = import_ntm_layers_to_ntm_v2()
    assert r["layers_measures_created"] == 5
    assert r["layers_rules_created"] > 0
    assert r["layers_measures_skipped"] == 0
    with memory_sessionmaker() as s:
        assert s.query(NtmMeasureV2).filter_by(source_kind="legacy_ntm_layers").count() == 5


def test_import_layers_idempotent(memory_sessionmaker: sessionmaker) -> None:
    r1 = import_ntm_layers_to_ntm_v2()
    r2 = import_ntm_layers_to_ntm_v2()
    assert r2["layers_measures_created"] == 0
    assert r2["layers_rules_skipped"] == r1["layers_rules_created"] + r1["layers_rules_skipped"]


def test_import_tr_ts_and_layers_no_conflict(memory_sessionmaker: sessionmaker) -> None:
    t1 = import_tr_ts_catalog_to_ntm_v2()
    l1 = import_ntm_layers_to_ntm_v2()
    t2 = import_tr_ts_catalog_to_ntm_v2()
    l2 = import_ntm_layers_to_ntm_v2()
    assert t2["measures_created"] == 0
    assert l2["layers_measures_created"] == 0
    with memory_sessionmaker() as s:
        assert s.query(NtmMeasureV2).count() == t1["unique_measures"] + 5


def test_engine_vet_by_hs_prefix(memory_sessionmaker: sessionmaker) -> None:
    import_ntm_layers_to_ntm_v2()
    from app.services.ntm_engine_v2 import evaluate_ntm_v2

    out = evaluate_ntm_v2(hs_code="0201100000", description="Говядина")
    kinds = [r["measure_kind"] for r in out["requirements"]]
    assert "vet" in kinds


def test_engine_sgr_respects_description(memory_sessionmaker: sessionmaker) -> None:
    import_ntm_layers_to_ntm_v2()
    from app.services.ntm_engine_v2 import evaluate_ntm_v2

    out = evaluate_ntm_v2(hs_code="2106909200", description="БАД витаминный комплекс")
    sgr = [r for r in out["requirements"] if r.get("measure_kind") == "sgr"]
    assert len(sgr) == 1


def test_engine_hs_spaced(memory_sessionmaker: sessionmaker) -> None:
    import_ntm_layers_to_ntm_v2()
    from app.services.ntm_engine_v2 import evaluate_ntm_v2

    a = evaluate_ntm_v2(hs_code="0201 10.00-00", description="")
    b = evaluate_ntm_v2(hs_code="0201100000", description="")
    assert [x for x in a["requirements"] if x.get("measure_kind") == "vet"] == [
        x for x in b["requirements"] if x.get("measure_kind") == "vet"
    ]


def test_layers_flag_off_uses_legacy(memory_sessionmaker: sessionmaker, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NTM_V2_LAYERS_ENABLED", raising=False)
    import_ntm_layers_to_ntm_v2()
    from app.services import ntm_layers as nl
    from app.services.ntm_engine_v2 import get_layer_requirements_for_pipeline

    hs, d = "0808108000", "Яблоки"
    assert get_layer_requirements_for_pipeline(hs, d) == nl.get_all_layer_requirements(hs, d)


def test_layers_flag_on_matches_legacy(memory_sessionmaker: sessionmaker, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NTM_V2_LAYERS_ENABLED", "true")
    import_ntm_layers_to_ntm_v2()
    from app.services import ntm_layers as nl
    from app.services.ntm_engine_v2 import get_layer_requirements_for_pipeline

    hs, d = "0401200001", "Молоко"
    v2 = get_layer_requirements_for_pipeline(hs, d)
    leg = nl.get_all_layer_requirements(hs, d)
    assert {(r["permit_type"], r.get("tr_ts"), r.get("matched_prefix")) for r in v2} == {
        (r["permit_type"], r.get("tr_ts"), r.get("matched_prefix")) for r in leg
    }


def test_compare_pipeline_layers_full_match(memory_sessionmaker: sessionmaker, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NTM_V2_LAYERS_ENABLED", "true")
    import_ntm_layers_to_ntm_v2()
    from app.services.ntm_engine_v2 import compare_pipeline_layers_vs_legacy

    cmp = compare_pipeline_layers_vs_legacy("8525600000", "Радиостанция")
    assert cmp["is_full_match"] is True
    assert cmp["ntm_v2_layers_enabled"] is True


def test_compare_layers_legacy_only_fixture(monkeypatch: pytest.MonkeyPatch, memory_sessionmaker: sessionmaker) -> None:
    monkeypatch.setenv("NTM_V2_LAYERS_ENABLED", "true")
    import_ntm_layers_to_ntm_v2()
    from app.services import ntm_engine_v2 as eng

    def _empty(_hs: str, _d: str = "") -> list[dict]:
        return []

    monkeypatch.setattr(eng, "get_layer_requirements_v2_legacy_shape", _empty)
    cmp = eng.compare_pipeline_layers_vs_legacy("0808108000", "Яблоки")
    assert cmp["legacy_only"]
    assert cmp["is_full_match"] is False


def test_compare_layers_runtime_only_fixture(monkeypatch: pytest.MonkeyPatch, memory_sessionmaker: sessionmaker) -> None:
    monkeypatch.setenv("NTM_V2_LAYERS_ENABLED", "true")
    import_ntm_layers_to_ntm_v2()
    from app.services import ntm_engine_v2 as eng

    def _fake(_hs: str, _d: str = "") -> list[dict]:
        return [
            {
                "permit_type": "XX",
                "tr_ts": None,
                "tr_ts_full_name": "Test",
                "description": "d",
                "legal_ref": "L",
                "matched_prefix": "99",
                "priority": 1,
                "trigger": None,
                "measure_kind": "other",
            }
        ]

    monkeypatch.setattr(eng, "get_layer_requirements_v2_legacy_shape", _fake)
    cmp = eng.compare_pipeline_layers_vs_legacy("0808108000", "Яблоки")
    assert cmp["runtime_only"]


def test_v2_layers_runtime_does_not_call_get_sgr_requirement(
    memory_sessionmaker: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """При NTM_V2_LAYERS_ENABLED путь не должен вызывать legacy get_sgr_requirement."""
    monkeypatch.setenv("NTM_V2_LAYERS_ENABLED", "true")
    import_ntm_layers_to_ntm_v2()

    def _boom(*_a: object, **_k: object) -> None:
        raise AssertionError("get_sgr_requirement must not be called when v2 layers enabled")

    monkeypatch.setattr("app.services.ntm_layers.get_sgr_requirement", _boom)

    from app.services.ntm_engine_v2 import get_layer_requirements_for_pipeline
    from app.services.tr_ts_catalog import get_full_ntm_requirements

    cases = [
        ("2106909200", "БАД витаминный комплекс"),
        ("2201100000", "Минеральная вода лечебная"),
        ("2201100000", "Вода питьевая"),
        ("1901000000", ""),
    ]
    for hs, desc in cases:
        get_layer_requirements_for_pipeline(hs, desc)
        get_full_ntm_requirements(hs, desc)


@pytest.mark.parametrize(
    "hs_code,description,expect_sgr",
    [
        ("1901000000", "", True),
        ("2106909200", "БАД витаминный комплекс", True),
        ("2201100000", "Минеральная вода лечебная", True),
        ("2201100000", "Вода питьевая", False),
        ("8471300000", "Ноутбук", False),
    ],
)
def test_sgr_v2_parity_with_legacy_shape(
    memory_sessionmaker: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
    hs_code: str,
    description: str,
    expect_sgr: bool,
) -> None:
    monkeypatch.setenv("NTM_V2_LAYERS_ENABLED", "true")
    import_ntm_layers_to_ntm_v2()
    from app.services import ntm_layers as nl
    from app.services.ntm_engine_v2 import get_layer_requirements_for_pipeline

    v2 = get_layer_requirements_for_pipeline(hs_code, description)
    leg = nl.get_all_layer_requirements(hs_code, description)
    v2_sgr = [r for r in v2 if r.get("permit_type") == "СГР"]
    leg_sgr = [r for r in leg if r.get("permit_type") == "СГР"]
    assert bool(v2_sgr) == expect_sgr
    assert bool(leg_sgr) == expect_sgr
    if expect_sgr:
        assert v2_sgr[0]["matched_prefix"] == leg_sgr[0]["matched_prefix"]
        assert v2_sgr[0].get("trigger") == leg_sgr[0].get("trigger")


def test_empty_layers_db_warning(memory_sessionmaker: sessionmaker, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setenv("NTM_V2_LAYERS_ENABLED", "true")
    from app.services.ntm_engine_v2 import get_layer_requirements_v2_legacy_shape

    caplog.set_level(logging.WARNING, logger="app.services.ntm_engine_v2")
    out = get_layer_requirements_v2_legacy_shape("0808108000", "Яблоки")
    assert out == []
    assert any("NTM_V2_LAYERS" in r.message for r in caplog.records)


@pytest.mark.parametrize("hs_code,description,expected", REGRESSION_MATRIX)
def test_regression_matrix_tr_ts_and_layers_flags_on(
    hs_code: str,
    description: str,
    expected: set[tuple[str, str | None]],
    memory_sessionmaker: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NTM_V2_TR_TS_ENABLED", "true")
    monkeypatch.setenv("NTM_V2_LAYERS_ENABLED", "true")
    import_tr_ts_catalog_to_ntm_v2()
    import_ntm_layers_to_ntm_v2()
    from app.services.non_tariff_service import check_position_non_tariff

    result = asyncio.run(
        check_position_non_tariff(
            hs_code=hs_code,
            description=description,
            country="CN",
            permits=[],
            skip_registry_verify=True,
        )
    )
    permits = result.get("required_permits") or []
    got = {(str(p["permit_type"]), p.get("tr_ts")) for p in permits}
    assert got == expected
