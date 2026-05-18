"""Advisory requirements (possible / needs_clarification) в ответе non_tariff check."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.core import NonTariffRule
from app.models.ntm_v2 import NtmApplicabilityRuleV2, NtmMeasureV2
from app.services.ntm_v2_legacy_rules_import import (
    LEGACY_RULES_IMPORT_APPLICABILITY,
    advisory_reason_for_applicability,
    get_advisory_legacy_rule_requirements_v2,
    import_legacy_non_tariff_rules_to_ntm_v2,
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


def _import_all_seed_rules(sm: sessionmaker) -> None:
    from app.services.normative_store import SEED_NON_TARIFF_RULES

    with sm() as s:
        for row in SEED_NON_TARIFF_RULES:
            s.add(NonTariffRule(**row))
        s.commit()
    import_legacy_non_tariff_rules_to_ntm_v2()


def _catalog(hs: str, desc: str = "") -> list[dict]:
    if hs.startswith("9503"):
        return [
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
    if hs.startswith("33"):
        return [
            {
                "permit_type": "ДС",
                "tr_ts": "009/2011",
                "tr_ts_full_name": "",
                "description": "Косметика",
                "legal_ref": "catalog",
                "matched_prefix": "3304",
                "priority": 1,
                "trigger": None,
            }
        ]
    if hs.startswith("8517"):
        rows = [
            {
                "permit_type": "ДС",
                "tr_ts": "004/2011",
                "tr_ts_full_name": "",
                "description": "Телефоны",
                "legal_ref": "catalog",
                "matched_prefix": "8517",
                "priority": 1,
                "trigger": None,
            }
        ]
        if "wi-fi" in desc.lower():
            rows.append(
                {
                    "permit_type": "НФ",
                    "tr_ts": None,
                    "tr_ts_full_name": "",
                    "description": "Wi-Fi",
                    "legal_ref": "trigger",
                    "matched_prefix": "8517",
                    "priority": 2,
                    "trigger": "wifi",
                }
            )
        return rows
    return []


async def _check(
    hs: str,
    desc: str,
    monkeypatch: pytest.MonkeyPatch,
    *,
    enforcement: bool = True,
) -> dict:
    from app.services.non_tariff_service import check_position_non_tariff

    monkeypatch.setenv("NTM_V2_RULES_ENFORCEMENT_ENABLED", "true" if enforcement else "false")
    return await check_position_non_tariff(
        hs_code=hs,
        description=desc,
        country="DE",
        permits=[],
        skip_registry_verify=True,
        rules_enforcement_enabled=enforcement,
    )


@pytest.mark.parametrize(
    ("hs", "desc", "expected_pt"),
    [
        ("8517120000", "Смартфон с Wi-Fi", "СС"),
        ("9503007500", "Кукла пластиковая", "СГР"),
        ("3304990000", "Косметика для взрослых", "СГР"),
    ],
)
def test_advisory_present_for_matrix_cases(
    memory_sessionmaker: sessionmaker,
    minimal_ntm_patches: None,
    monkeypatch: pytest.MonkeyPatch,
    hs: str,
    desc: str,
    expected_pt: str,
) -> None:
    _import_all_seed_rules(memory_sessionmaker)
    monkeypatch.setattr(
        "app.services.non_tariff_service.get_full_ntm_requirements",
        lambda h, d="": _catalog(h, d),
    )
    res = asyncio.run(_check(hs, desc, monkeypatch))
    pts = {a["permit_type"] for a in res.get("advisory_requirements") or []}
    assert expected_pt in pts
    assert all(a.get("applicability") == LEGACY_RULES_IMPORT_APPLICABILITY for a in res["advisory_requirements"])
    assert all(a.get("used_for_missing_check") is False for a in res["advisory_requirements"])


@pytest.mark.parametrize(
    ("hs", "desc"),
    [
        ("8517120000", "Смартфон с Wi-Fi"),
        ("9503007500", "Кукла пластиковая"),
        ("3304990000", "Косметика для взрослых"),
    ],
)
def test_advisory_does_not_affect_broker(
    memory_sessionmaker: sessionmaker,
    minimal_ntm_patches: None,
    monkeypatch: pytest.MonkeyPatch,
    hs: str,
    desc: str,
) -> None:
    _import_all_seed_rules(memory_sessionmaker)
    monkeypatch.setattr(
        "app.services.non_tariff_service.get_full_ntm_requirements",
        lambda h, d="": _catalog(h, d),
    )
    off = asyncio.run(_check(hs, desc, monkeypatch, enforcement=False))
    on = asyncio.run(_check(hs, desc, monkeypatch, enforcement=True))
    assert off["required_permit_types"] == on["required_permit_types"]
    assert off["missing_permit_types"] == on["missing_permit_types"]
    assert off["status"] == on["status"]


def test_definite_not_in_advisory(
    memory_sessionmaker: sessionmaker,
    minimal_ntm_patches: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with memory_sessionmaker() as s:
        s.add(
            NonTariffRule(
                name="Test definite",
                hs_prefix="9999",
                required_permits="КВ",
                tr_ts="",
                tr_ts_edition="",
                exception_note="",
                priority=1,
                valid_from="",
                valid_to="",
                source_url="https://test",
                source_revision="test",
            )
        )
        s.commit()
    import_legacy_non_tariff_rules_to_ntm_v2()
    with memory_sessionmaker() as s:
        rule = s.scalar(select(NtmApplicabilityRuleV2))
        assert rule is not None
        rule.applicability = "definite"
        s.commit()

    advisory = get_advisory_legacy_rule_requirements_v2("9999000000")
    assert advisory == []

    res = asyncio.run(_check("9999000000", "test", monkeypatch))
    assert "КВ" not in {a["permit_type"] for a in res.get("advisory_requirements") or []}
    assert "КВ" in res["required_permit_types"]


def test_needs_clarification_in_advisory(
    memory_sessionmaker: sessionmaker,
) -> None:
    with memory_sessionmaker() as s:
        s.add(
            NonTariffRule(
                name="Clarify rule",
                hs_prefix="8888",
                required_permits="ЛЗ",
                tr_ts="",
                tr_ts_edition="",
                exception_note="особое условие",
                priority=1,
                valid_from="",
                valid_to="",
                source_url="https://test",
                source_revision="test",
            )
        )
        s.commit()
    import_legacy_non_tariff_rules_to_ntm_v2()
    with memory_sessionmaker() as s:
        rule = s.scalar(select(NtmApplicabilityRuleV2))
        assert rule is not None
        rule.applicability = "needs_clarification"
        s.commit()

    rows = get_advisory_legacy_rule_requirements_v2("8888000000")
    assert len(rows) == 1
    assert rows[0]["applicability"] == "needs_clarification"
    assert rows[0]["reason"] == advisory_reason_for_applicability("needs_clarification")
    assert rows[0]["note"] == "особое условие"


def test_advisory_empty_list_always_present(
    memory_sessionmaker: sessionmaker,
    minimal_ntm_patches: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    res = asyncio.run(_check("0101210000", "Коровы", monkeypatch, enforcement=False))
    assert "advisory_requirements" in res
    assert res["advisory_requirements"] == []


def test_advisory_dedup_same_key(
    memory_sessionmaker: sessionmaker,
) -> None:
    with memory_sessionmaker() as s:
        s.add(
            NonTariffRule(
                name="Dup rule",
                hs_prefix="7777",
                required_permits="ДС",
                tr_ts="004/2011,020/2011",
                tr_ts_edition="",
                exception_note="",
                priority=1,
                valid_from="",
                valid_to="",
                source_url="https://test",
                source_revision="test",
            )
        )
        s.commit()
    import_legacy_non_tariff_rules_to_ntm_v2()
    rows = get_advisory_legacy_rule_requirements_v2("7777000000")
    keys = {(r["permit_type"], r.get("tr_ts"), r["applicability"]) for r in rows}
    assert len(keys) == len(rows)
    assert len(rows) == 2
