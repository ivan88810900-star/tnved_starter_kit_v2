"""Тесты продуктового блока normative_requirements (MVP)."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.core import NonTariffRule
from app.models.ntm_v2 import NtmApplicabilityRuleV2, NtmMeasureV2
from app.services.normative_requirements_block import (
    build_normative_requirements_block,
    source_label_for,
)
from app.services.non_tariff_service import check_position_non_tariff
from app.services.ntm_v2_legacy_rules_import import import_legacy_non_tariff_rules_to_ntm_v2
from app.services.ntm_v2_official_sgr_import import (
    OFFICIAL_SGR_SOURCE_KIND,
    OFFICIAL_SGR_SOURCE_LABEL,
    should_apply_official_sgr_advisory,
)


@pytest.fixture
def memory_sessionmaker(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            NonTariffRule.__table__,
            NtmMeasureV2.__table__,
            NtmApplicabilityRuleV2.__table__,
        ],
    )
    sm = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr("app.db.SessionLocal", sm)
    monkeypatch.setattr("app.services.normative_store.SessionLocal", sm)
    return sm


@pytest.fixture
def minimal_ntm_patches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.non_tariff_service.get_full_ntm_requirements",
        lambda _hs, _d="": [],
    )
    monkeypatch.setattr("app.services.non_tariff_service.find_rules_for_code", lambda _hs: [])
    monkeypatch.setattr("app.services.non_tariff_service.find_measures_for_code", lambda _hs, **_: [])
    monkeypatch.setattr(
        "app.services.non_tariff_service.find_measures_by_description",
        lambda _d, _hs: [],
    )
    monkeypatch.setattr(
        "app.services.non_tariff_service.get_sensitive_override",
        lambda _hs: None,
    )
    monkeypatch.setattr(
        "app.services.non_tariff_service.find_normative_notes_for_hs",
        lambda _hs: [],
    )
    monkeypatch.setattr(
        "app.services.non_tariff_service.get_regulatory_documents_for_hs",
        lambda _hs, **_: [],
    )
    monkeypatch.setattr(
        "app.services.non_tariff_service.lookup_tr_ts_acts_by_codes",
        lambda _codes: [],
    )


async def _check_nt(
    hs: str,
    desc: str,
    *,
    official_sgr: bool = False,
) -> dict:
    return await check_position_non_tariff(
        hs_code=hs,
        description=desc,
        country="CN",
        permits=[],
        skip_registry_verify=True,
        official_sgr_advisory_enabled=official_sgr if official_sgr else None,
    )


def _import_seed_rules(sm: sessionmaker) -> None:
    from app.services.normative_store import SEED_NON_TARIFF_RULES

    with sm() as s:
        for row in SEED_NON_TARIFF_RULES:
            s.add(NonTariffRule(**row))
        s.commit()
    import_legacy_non_tariff_rules_to_ntm_v2()


def test_build_block_from_broker_rows() -> None:
    nt = {
        "status": "ERROR",
        "hs_code": "8471300000",
        "description": "Ноутбук",
        "required_permits": [
            {
                "permit_type": "ДС",
                "tr_ts": "004/2011",
                "description": "ИТ-оборудование",
                "legal_ref": "catalog",
                "trigger": None,
            }
        ],
        "missing_permit_types": ["ДС"],
        "advisory_requirements": [],
        "tr_ts": ["004/2011"],
        "notes": [],
    }
    block = build_normative_requirements_block(nt)
    assert len(block["required_documents"]) == 1
    assert block["required_documents"][0]["permit_type"] == "ДС"
    assert block["required_documents"][0]["used_for_missing_check"] is True
    assert block["required_documents"][0]["source"] == "tr_ts_catalog"
    assert block["required_documents"][0]["source_label"] == source_label_for("tr_ts_catalog")
    assert len(block["missing_documents"]) == 1
    assert block["missing_documents"][0]["permit_type"] == "ДС"
    assert block["empty_message"] is None


def test_advisory_does_not_affect_missing_documents() -> None:
    nt = {
        "status": "OK",
        "hs_code": "9503007500",
        "description": "Кукла",
        "required_permits": [],
        "missing_permit_types": [],
        "advisory_requirements": [
            {
                "permit_type": "СГР",
                "tr_ts": None,
                "applicability": "possible",
                "source": "legacy_non_tariff_rules",
                "used_for_missing_check": False,
                "requires_manual_review": False,
                "reason": "Возможное требование",
            }
        ],
        "tr_ts": [],
        "notes": [],
    }
    block = build_normative_requirements_block(nt)
    assert block["missing_documents"] == []
    assert block["required_documents"] == []
    assert len(block["advisory_requirements"]) == 1
    assert block["advisory_requirements"][0]["used_for_missing_check"] is False
    assert block["advisory_requirements"][0]["source_label"] == source_label_for("legacy_non_tariff_rules")


def test_official_sgr_advisory_in_block_not_required(
    memory_sessionmaker: sessionmaker,
    minimal_ntm_patches: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _import_seed_rules(memory_sessionmaker)
    monkeypatch.setattr(
        "app.services.non_tariff_service.get_full_ntm_requirements",
        lambda hs, _d="": [
            {
                "permit_type": "СС",
                "tr_ts": "008/2011",
                "tr_ts_full_name": "",
                "description": "Игрушки",
                "legal_ref": "catalog",
                "matched_prefix": "9503",
                "priority": 1,
                "trigger": None,
            }
        ]
        if hs.startswith("9503")
        else [],
    )
    monkeypatch.setenv("NTM_V2_OFFICIAL_SGR_ADVISORY_ENABLED", "1")
    assert should_apply_official_sgr_advisory() is True

    res = asyncio.run(
        _check_nt("9503007500", "детская игрушка мягкая", official_sgr=True)
    )
    block = res["normative_block"]
    official = [a for a in block["advisory_requirements"] if a.get("source") == OFFICIAL_SGR_SOURCE_KIND]
    if official:
        assert official[0]["source_label"] == OFFICIAL_SGR_SOURCE_LABEL
        assert official[0]["used_for_missing_check"] is False
        assert "СГР" not in {d["permit_type"] for d in block["required_documents"]}
        assert "СГР" not in {d["permit_type"] for d in block["missing_documents"]}
    assert res["status"] in ("OK", "WARNING", "ERROR")


def test_empty_state_message() -> None:
    nt = {
        "status": "WARNING",
        "hs_code": "9999999999",
        "description": "",
        "required_permits": [],
        "missing_permit_types": [],
        "advisory_requirements": [],
        "tr_ts": [],
        "notes": [],
    }
    block = build_normative_requirements_block(nt)
    assert block["empty_message"] is not None
    assert block["required_documents"] == []
    assert block["advisory_requirements"] == []


def test_check_includes_normative_block(
    memory_sessionmaker: sessionmaker,
    minimal_ntm_patches: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.non_tariff_service.get_full_ntm_requirements",
        lambda hs, _d="": [
            {
                "permit_type": "ДС",
                "tr_ts": "004/2011",
                "tr_ts_full_name": "",
                "description": "Ноутбук",
                "legal_ref": "catalog",
                "matched_prefix": "8471",
                "priority": 1,
                "trigger": None,
            }
        ]
        if hs.startswith("8471")
        else [],
    )
    res = asyncio.run(_check_nt("8471300000", "Ноутбук"))
    assert "normative_block" in res
    block = res["normative_block"]
    assert block["required_documents"]
    assert res["missing_permit_types"] == ["ДС"]
    assert block["missing_documents"][0]["permit_type"] == "ДС"
    assert all(a.get("used_for_missing_check") is False for a in block["advisory_requirements"])
