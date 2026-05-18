"""NTM v2 rules enforcement в missing-check (``NTM_V2_RULES_ENFORCEMENT_ENABLED``)."""

from __future__ import annotations

import asyncio
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.core import NonTariffRule
from app.models.ntm_v2 import NtmApplicabilityRuleV2, NtmMeasureV2
from app.services.ntm_v2_legacy_rules_import import (
    LEGACY_RULES_IMPORT_APPLICABILITY,
    compare_non_tariff_check_rules_enforcement,
    get_legacy_rule_requirements_for_enforcement,
    get_legacy_rule_requirements_v2_legacy_shape,
    import_legacy_non_tariff_rules_to_ntm_v2,
    is_ntm_v2_rules_enforcement_enabled,
    merge_v2_legacy_rules_into_broker,
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
        lambda hs: "РУ" if (hs or "").startswith("30") else None,
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


def _seed_v2_rule(
    sm: sessionmaker,
    *,
    hs_prefix: str = "3004",
    required_permits: str = "ДС",
    tr_ts: str = "061/2012",
    valid_to: str = "",
) -> None:
    with sm() as s:
        s.add(
            NonTariffRule(
                name="Лекарства seed",
                hs_prefix=hs_prefix,
                required_permits=required_permits,
                tr_ts=tr_ts,
                tr_ts_edition="",
                exception_note="",
                priority=5,
                valid_from="",
                valid_to=valid_to,
                source_url="https://test",
                source_revision="test",
            )
        )
        s.commit()
    import_legacy_non_tariff_rules_to_ntm_v2()


def _import_all_seed_rules(sm: sessionmaker) -> None:
    from app.services.normative_store import SEED_NON_TARIFF_RULES

    with sm() as s:
        for row in SEED_NON_TARIFF_RULES:
            s.add(NonTariffRule(**row))
        s.commit()
    import_legacy_non_tariff_rules_to_ntm_v2()


def _catalog_ss_for_toys(hs: str, _d: str = "") -> list[dict]:
    if not (hs or "").startswith("9503"):
        return []
    return [
        {
            "permit_type": "СС",
            "tr_ts": "008/2011",
            "tr_ts_full_name": "О безопасности игрушек",
            "description": "Игрушки",
            "legal_ref": "catalog",
            "matched_prefix": "9503",
            "priority": 1,
            "trigger": None,
        }
    ]


def _catalog_ds_for_33(hs: str, _d: str = "") -> list[dict]:
    if not (hs or "").startswith("33"):
        return []
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


def _catalog_ds_nf_for_phone(hs: str, _d: str = "") -> list[dict]:
    if not (hs or "").startswith("8517"):
        return []
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
    if "wi-fi" in (_d or "").lower() or "wifi" in (_d or "").lower():
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


async def _check(
    hs: str,
    desc: str = "Лекарство",
    *,
    enforcement: bool | None,
    monkeypatch: pytest.MonkeyPatch,
) -> dict:
    from app.services.non_tariff_service import check_position_non_tariff

    if enforcement is not None:
        monkeypatch.delenv("NTM_V2_RULES_ENFORCEMENT_ENABLED", raising=False)
        if enforcement:
            monkeypatch.setenv("NTM_V2_RULES_ENFORCEMENT_ENABLED", "true")
    return await check_position_non_tariff(
        hs_code=hs,
        description=desc,
        country="DE",
        permits=[],
        skip_registry_verify=True,
        rules_enforcement_enabled=enforcement,
    )


def test_flag_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NTM_V2_RULES_ENFORCEMENT_ENABLED", raising=False)
    assert is_ntm_v2_rules_enforcement_enabled() is False


def test_flag_truthy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NTM_V2_RULES_ENFORCEMENT_ENABLED", "on")
    assert is_ntm_v2_rules_enforcement_enabled() is True


def test_import_sets_applicability_possible(memory_sessionmaker: sessionmaker) -> None:
    _seed_v2_rule(memory_sessionmaker)
    with memory_sessionmaker() as s:
        rule = s.scalar(select(NtmApplicabilityRuleV2))
        assert rule is not None
        assert rule.applicability == LEGACY_RULES_IMPORT_APPLICABILITY
        assert rule.requires_manual_review is True


def test_reimport_updates_definite_to_possible(memory_sessionmaker: sessionmaker) -> None:
    _seed_v2_rule(memory_sessionmaker)
    with memory_sessionmaker() as s:
        rule = s.scalar(select(NtmApplicabilityRuleV2))
        assert rule is not None
        rule.applicability = "definite"
        s.commit()
    report = import_legacy_non_tariff_rules_to_ntm_v2()
    assert report["rules_applicability_updated"] >= 1
    with memory_sessionmaker() as s:
        rule = s.scalar(select(NtmApplicabilityRuleV2))
        assert rule is not None
        assert rule.applicability == LEGACY_RULES_IMPORT_APPLICABILITY


def test_enforcement_off_unchanged_baseline(
    memory_sessionmaker: sessionmaker,
    minimal_ntm_patches: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_v2_rule(memory_sessionmaker)
    off = asyncio.run(_check("3004909200", enforcement=False, monkeypatch=monkeypatch))
    assert set(off["required_permit_types"]) == {"РУ"}
    assert off["missing_permit_types"] == ["РУ"]
    assert off["status"] == "ERROR"


def test_possible_rule_not_enforced_in_broker(
    memory_sessionmaker: sessionmaker,
    minimal_ntm_patches: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_v2_rule(memory_sessionmaker)
    on = asyncio.run(_check("3004909200", enforcement=True, monkeypatch=monkeypatch))
    assert set(on["required_permit_types"]) == {"РУ"}
    assert set(on["missing_permit_types"]) == {"РУ"}
    assert on["status"] == "ERROR"
    enforce_rows = get_legacy_rule_requirements_for_enforcement("3004909200")
    assert enforce_rows == []
    info_rows = get_legacy_rule_requirements_v2_legacy_shape("3004909200")
    assert any(r.get("permit_type") == "ДС" for r in info_rows)
    assert all(r.get("applicability") == LEGACY_RULES_IMPORT_APPLICABILITY for r in info_rows)
    assert all(r.get("used_for_missing_check") is False for r in info_rows)


def test_definite_rule_enforced_in_broker(
    memory_sessionmaker: sessionmaker,
    minimal_ntm_patches: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_v2_rule(memory_sessionmaker)
    with memory_sessionmaker() as s:
        rule = s.scalar(select(NtmApplicabilityRuleV2))
        assert rule is not None
        rule.applicability = "definite"
        s.commit()
    on = asyncio.run(_check("3004909200", enforcement=True, monkeypatch=monkeypatch))
    assert set(on["required_permit_types"]) == {"ДС", "РУ"}
    assert set(on["missing_permit_types"]) == {"ДС", "РУ"}


def test_merge_dedup_same_key() -> None:
    broker = [
        {
            "permit_type": "ДС",
            "tr_ts": "004/2011",
            "matched_prefix": "8471",
            "priority": 1,
        }
    ]
    v2 = [
        {
            "permit_type": "ДС",
            "tr_ts": "004/2011",
            "matched_prefix": "8471",
            "priority": 0,
            "source_level": "rules_v2",
        }
    ]
    merged = merge_v2_legacy_rules_into_broker(broker, v2)
    assert len(merged) == 1
    assert merged[0]["priority"] == 1


def test_expired_v2_rule_not_enforced(
    memory_sessionmaker: sessionmaker,
    minimal_ntm_patches: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_v2_rule(memory_sessionmaker, valid_to="2015-12-31")
    rows = get_legacy_rule_requirements_v2_legacy_shape(
        "3004909200",
        as_of=date(2026, 5, 14),
    )
    assert rows == []
    on = asyncio.run(_check("3004909200", enforcement=True, monkeypatch=monkeypatch))
    assert set(on["required_permit_types"]) == {"РУ"}


@pytest.mark.parametrize(
    ("hs", "desc", "catalog_fn"),
    [
        ("8517120000", "Смартфон с Wi-Fi", _catalog_ds_nf_for_phone),
        ("9503007500", "Кукла пластиковая", _catalog_ss_for_toys),
        ("3304990000", "Косметика для взрослых", _catalog_ds_for_33),
    ],
)
def test_possible_legacy_rules_do_not_change_matrix_cases(
    memory_sessionmaker: sessionmaker,
    minimal_ntm_patches: None,
    monkeypatch: pytest.MonkeyPatch,
    hs: str,
    desc: str,
    catalog_fn,
) -> None:
    _import_all_seed_rules(memory_sessionmaker)
    monkeypatch.setattr(
        "app.services.non_tariff_service.get_full_ntm_requirements",
        catalog_fn,
    )
    on = asyncio.run(_check(hs, desc, enforcement=True, monkeypatch=monkeypatch))
    cmp = asyncio.run(compare_non_tariff_check_rules_enforcement(hs, description=desc))
    assert cmp["changed"] is False
    assert cmp["added_permit_types"] == []
    assert "СГР" not in on["required_permit_types"]
    if hs == "8517120000":
        assert "СС" not in on["required_permit_types"]
    if hs == "9503007500":
        assert "СГР" not in on["required_permit_types"]
        assert set(on["required_permit_types"]) == {"СС"}
    if hs == "3304990000":
        assert "СГР" not in on["required_permit_types"]
        assert set(on["required_permit_types"]) == {"ДС"}


def test_regression_matrix_no_rules_enforcement_diff(
    memory_sessionmaker: sessionmaker,
    minimal_ntm_patches: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.test_ntm_pipeline import REGRESSION_MATRIX

    _import_all_seed_rules(memory_sessionmaker)
    changes: list[dict] = []
    seen: set[str] = set()
    for hs, desc, _exp in REGRESSION_MATRIX:
        if hs in seen:
            continue
        seen.add(hs)
        cmp = asyncio.run(compare_non_tariff_check_rules_enforcement(hs, desc))
        if cmp["changed"]:
            changes.append(cmp)
    assert changes == []
