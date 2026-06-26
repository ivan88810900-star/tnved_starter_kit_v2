"""Импорт legacy non_tariff_rules → NTM v2 и shadow-сравнение."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.core import NonTariffRule
from app.models.ntm_v2 import NtmApplicabilityRuleV2, NtmMeasureV2
from app.services.ntm_v2_legacy_rules_import import (
    LEGACY_RULES_IMPORT_APPLICABILITY,
    RULES_SOURCE_KIND,
    compare_legacy_non_tariff_rules_vs_ntm_v2,
    import_legacy_non_tariff_rules_to_ntm_v2,
    permit_type_to_measure_kind,
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


def _add_legacy_rule(
    sm: sessionmaker,
    *,
    name: str = "Test rule",
    hs_prefix: str = "8517",
    required_permits: str = "ДС",
    tr_ts: str = "004/2011",
    valid_from: str = "",
    valid_to: str = "",
    priority: int = 3,
) -> NonTariffRule:
    with sm() as s:
        row = NonTariffRule(
            name=name,
            hs_prefix=hs_prefix,
            required_permits=required_permits,
            tr_ts=tr_ts,
            tr_ts_edition="edition",
            exception_note="note",
            priority=priority,
            valid_from=valid_from,
            valid_to=valid_to,
            source_url="https://example.test",
            source_revision="test",
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        return row


def test_permit_type_to_measure_kind_mapping() -> None:
    assert permit_type_to_measure_kind("СС") == "technical_regulation"
    assert permit_type_to_measure_kind("ДС") == "technical_regulation"
    assert permit_type_to_measure_kind("СГР") == "sgr"
    assert permit_type_to_measure_kind("ЛЗ") == "license"
    assert permit_type_to_measure_kind("РУ") == "registration"
    assert permit_type_to_measure_kind("ВС") == "vet"
    assert permit_type_to_measure_kind("ФСС") == "phyto"
    assert permit_type_to_measure_kind("КВ") == "other"
    assert permit_type_to_measure_kind("XYZ") == "other"


def test_import_one_rule_creates_measure_and_rule(memory_sessionmaker: sessionmaker) -> None:
    _add_legacy_rule(memory_sessionmaker)
    r = import_legacy_non_tariff_rules_to_ntm_v2()
    assert r["legacy_rules_processed"] == 1
    assert r["measures_created"] == 1
    assert r["rules_created"] == 1
    with memory_sessionmaker() as s:
        assert s.query(NtmMeasureV2).filter_by(source_kind=RULES_SOURCE_KIND).count() == 1
        rule = s.query(NtmApplicabilityRuleV2).filter_by(source_kind=RULES_SOURCE_KIND).one()
        assert rule.applicability == LEGACY_RULES_IMPORT_APPLICABILITY


def test_import_cartesian_permits_and_tr_ts(memory_sessionmaker: sessionmaker) -> None:
    _add_legacy_rule(
        memory_sessionmaker,
        required_permits="СС,ДС",
        tr_ts="004/2011,020/2011",
    )
    r = import_legacy_non_tariff_rules_to_ntm_v2()
    assert r["rules_created"] == 4
    assert r["measures_created"] == 4
    with memory_sessionmaker() as s:
        assert s.query(NtmApplicabilityRuleV2).count() == 4


def test_import_empty_tr_ts(memory_sessionmaker: sessionmaker) -> None:
    _add_legacy_rule(memory_sessionmaker, tr_ts="", required_permits="ЛЗ")
    r = import_legacy_non_tariff_rules_to_ntm_v2()
    assert r["rules_created"] == 1
    with memory_sessionmaker() as s:
        m = s.query(NtmMeasureV2).one()
        assert m.tr_ts_act_code == ""
        assert m.permit_type == "ЛЗ"


def test_import_skips_empty_required_permits(memory_sessionmaker: sessionmaker) -> None:
    _add_legacy_rule(memory_sessionmaker, required_permits="")
    r = import_legacy_non_tariff_rules_to_ntm_v2()
    assert r["legacy_rules_skipped_no_permits"] == 1
    assert r["rules_created"] == 0


def test_import_idempotent(memory_sessionmaker: sessionmaker) -> None:
    _add_legacy_rule(memory_sessionmaker)
    r1 = import_legacy_non_tariff_rules_to_ntm_v2()
    r2 = import_legacy_non_tariff_rules_to_ntm_v2()
    assert r2["measures_created"] == 0
    assert r2["rules_created"] == 0
    assert r2["rules_skipped_duplicates"] == r1["rules_created"]
    with memory_sessionmaker() as s:
        assert s.query(NtmMeasureV2).count() == 1


def test_import_preserves_valid_dates(memory_sessionmaker: sessionmaker) -> None:
    _add_legacy_rule(
        memory_sessionmaker,
        valid_from="2024-01-01",
        valid_to="2028-12-31",
    )
    import_legacy_non_tariff_rules_to_ntm_v2()
    with memory_sessionmaker() as s:
        rule = s.query(NtmApplicabilityRuleV2).one()
        assert rule.valid_from == date(2024, 1, 1)
        assert rule.valid_to == date(2028, 12, 31)


def test_compare_full_overlap(memory_sessionmaker: sessionmaker) -> None:
    _add_legacy_rule(memory_sessionmaker, hs_prefix="8517", required_permits="ДС", tr_ts="004/2011")
    import_legacy_non_tariff_rules_to_ntm_v2()
    cmp = compare_legacy_non_tariff_rules_vs_ntm_v2("8517620000")
    assert cmp["is_full_match"] is True
    assert cmp["legacy_only"] == []
    assert cmp["v2_only"] == []


def test_compare_legacy_only_when_v2_not_imported(memory_sessionmaker: sessionmaker) -> None:
    _add_legacy_rule(memory_sessionmaker)
    cmp = compare_legacy_non_tariff_rules_vs_ntm_v2("8517620000")
    assert cmp["legacy_only"]
    assert cmp["is_full_match"] is False


def test_compare_excludes_expired_rule_by_as_of(memory_sessionmaker: sessionmaker) -> None:
    _add_legacy_rule(
        memory_sessionmaker,
        valid_from="2010-01-01",
        valid_to="2015-12-31",
    )
    import_legacy_non_tariff_rules_to_ntm_v2()
    cmp = compare_legacy_non_tariff_rules_vs_ntm_v2("8517620000", as_of=date(2026, 5, 14))
    assert cmp["legacy_only"] == []
    assert cmp["v2_only"] == []
    assert cmp["is_full_match"] is True


def test_compare_active_on_as_of(memory_sessionmaker: sessionmaker) -> None:
    _add_legacy_rule(
        memory_sessionmaker,
        valid_from="2020-01-01",
        valid_to="2099-12-31",
    )
    import_legacy_non_tariff_rules_to_ntm_v2()
    cmp = compare_legacy_non_tariff_rules_vs_ntm_v2("8517620000", as_of=date(2026, 1, 1))
    assert "ДС|004/2011" in cmp["overlap"]


def test_smoke_regression_matrix_hs(memory_sessionmaker: sessionmaker) -> None:
    """Smoke: импорт сидовых правил из normative_store + compare по кодам матрицы."""
    from app.services.normative_store import SEED_NON_TARIFF_RULES

    with memory_sessionmaker() as s:
        for row in SEED_NON_TARIFF_RULES:
            s.add(NonTariffRule(**row))
        s.commit()
    import_legacy_non_tariff_rules_to_ntm_v2()

    from tests.test_ntm_pipeline import REGRESSION_MATRIX

    mismatches: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for hs, _desc, _exp in REGRESSION_MATRIX:
        if hs in seen:
            continue
        seen.add(hs)
        cmp = compare_legacy_non_tariff_rules_vs_ntm_v2(hs)
        if not cmp["is_full_match"]:
            mismatches.append((hs, cmp))
    assert mismatches == [], f"legacy rules v2 mismatches: {mismatches[:5]}"
