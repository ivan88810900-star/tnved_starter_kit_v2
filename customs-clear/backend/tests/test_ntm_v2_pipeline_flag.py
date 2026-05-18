"""Feature flag NTM_V2_TR_TS_ENABLED: пайплайн get_full_ntm_requirements и /api/non_tariff внутренняя логика."""

from __future__ import annotations

import asyncio
import logging

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.ntm_v2 import NtmApplicabilityRuleV2, NtmMeasureV2
from app.services.ntm_v2_import import import_tr_ts_catalog_to_ntm_v2
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


def test_flag_off_uses_legacy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NTM_V2_TR_TS_ENABLED", raising=False)
    from app.services.ntm_engine_v2 import (
        get_tr_ts_requirements_for_pipeline,
        is_ntm_v2_tr_ts_enabled,
    )
    from app.services.tr_ts_catalog import get_tr_ts_requirements

    assert is_ntm_v2_tr_ts_enabled() is False
    hs = "8517620000"
    assert get_tr_ts_requirements_for_pipeline(hs, "") == get_tr_ts_requirements(hs)


@pytest.mark.parametrize("truthy", ["1", "true", "TRUE", "yes", "on"])
def test_flag_on_values(monkeypatch: pytest.MonkeyPatch, truthy: str) -> None:
    from app.services.ntm_engine_v2 import is_ntm_v2_tr_ts_enabled

    monkeypatch.setenv("NTM_V2_TR_TS_ENABLED", truthy)
    assert is_ntm_v2_tr_ts_enabled() is True


def test_flag_on_uses_v2_adapter(memory_sessionmaker: sessionmaker, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NTM_V2_TR_TS_ENABLED", "true")
    import_tr_ts_catalog_to_ntm_v2()
    from app.services.ntm_engine_v2 import get_tr_ts_requirements_for_pipeline
    from app.services.tr_ts_catalog import get_tr_ts_requirements

    hs = "8517620000"
    legacy = get_tr_ts_requirements(hs)
    v2p = get_tr_ts_requirements_for_pipeline(hs, "")
    assert {(r["permit_type"], r["tr_ts"]) for r in v2p} == {(r["permit_type"], r["tr_ts"]) for r in legacy}
    assert v2p == legacy


def test_get_full_ntm_tr_ts_slice_matches_legacy_after_import(
    memory_sessionmaker: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NTM_V2_TR_TS_ENABLED", raising=False)
    import_tr_ts_catalog_to_ntm_v2()
    from app.services.ntm_layers import get_all_layer_requirements
    from app.services.tr_ts_catalog import get_full_ntm_requirements, get_tr_ts_requirements

    hs, desc = "8517620000", ""
    expected_off = get_full_ntm_requirements(hs, desc)

    monkeypatch.setenv("NTM_V2_TR_TS_ENABLED", "true")
    expected_on = get_full_ntm_requirements(hs, desc)
    layers = get_all_layer_requirements(hs, desc)
    n_layers = len(layers)
    tr_off = expected_off[:-n_layers] if n_layers else expected_off
    tr_on = expected_on[:-n_layers] if n_layers else expected_on
    assert tr_on == tr_off
    assert tr_on == get_tr_ts_requirements(hs)


def test_spaced_hs_parity_with_flag_on(memory_sessionmaker: sessionmaker, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NTM_V2_TR_TS_ENABLED", "true")
    import_tr_ts_catalog_to_ntm_v2()
    from app.services.ntm_engine_v2 import get_tr_ts_requirements_for_pipeline
    from app.services.tr_ts_catalog import get_tr_ts_requirements

    plain = "8517620000"
    spaced = "8517 62.00-00"
    assert get_tr_ts_requirements_for_pipeline(spaced, "") == get_tr_ts_requirements(plain)


def test_empty_v2_logs_warning_no_fallback(
    memory_sessionmaker: sessionmaker, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("NTM_V2_TR_TS_ENABLED", "true")
    # Без import_tr_ts_catalog_to_ntm_v2 — таблицы пустые
    from app.services.ntm_engine_v2 import get_tr_ts_requirements_v2_legacy_shape

    caplog.set_level(logging.WARNING, logger="app.services.ntm_engine_v2")
    out = get_tr_ts_requirements_v2_legacy_shape("8517620000", "")
    assert out == []
    assert any("NTM_V2_TR_TS" in r.message for r in caplog.records)


def test_compare_pipeline_tr_ts_vs_legacy_when_flag_on(
    memory_sessionmaker: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NTM_V2_TR_TS_ENABLED", "true")
    import_tr_ts_catalog_to_ntm_v2()
    from app.services.ntm_engine_v2 import compare_pipeline_tr_ts_vs_legacy_catalog

    cmp = compare_pipeline_tr_ts_vs_legacy_catalog("8471300000", "Ноутбук")
    assert cmp["ntm_v2_tr_ts_enabled"] is True
    assert cmp["is_full_match"] is True


@pytest.mark.parametrize("hs_code,description,expected", REGRESSION_MATRIX)
def test_ntm_regression_matrix_with_v2_flag_on(
    hs_code: str,
    description: str,
    expected: set[tuple[str, str | None]],
    memory_sessionmaker: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NTM_V2_TR_TS_ENABLED", "true")
    import_tr_ts_catalog_to_ntm_v2()
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
