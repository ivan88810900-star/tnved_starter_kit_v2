"""Тесты NTM v2: импорт каталога ТР ТС, движок, shadow-сравнение с legacy."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.ntm_v2 import NtmApplicabilityRuleV2, NtmMeasureV2
from app.services.ntm_v2_import import import_tr_ts_catalog_to_ntm_v2
from app.services.tr_ts_catalog import ALL_REGULATIONS


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


def test_import_creates_measures_and_rules(memory_sessionmaker: sessionmaker) -> None:
    r1 = import_tr_ts_catalog_to_ntm_v2()
    assert r1["measures_created"] == r1["unique_measures"]
    assert r1["rules_created"] == len(ALL_REGULATIONS)
    assert r1["measures_skipped_duplicates"] == 0
    assert r1["rules_skipped_duplicates"] == 0

    with memory_sessionmaker() as s:
        assert s.query(NtmMeasureV2).count() == r1["unique_measures"]
        assert s.query(NtmApplicabilityRuleV2).count() == len(ALL_REGULATIONS)


def test_import_idempotent(memory_sessionmaker: sessionmaker) -> None:
    r1 = import_tr_ts_catalog_to_ntm_v2()
    r2 = import_tr_ts_catalog_to_ntm_v2()
    assert r2["measures_created"] == 0
    assert r2["rules_created"] == 0
    assert r2["measures_skipped_duplicates"] == r1["unique_measures"]
    assert r2["rules_skipped_duplicates"] == len(ALL_REGULATIONS)

    with memory_sessionmaker() as s:
        assert s.query(NtmMeasureV2).count() == r1["unique_measures"]
        assert s.query(NtmApplicabilityRuleV2).count() == len(ALL_REGULATIONS)


def test_measure_not_duplicated_per_tr_and_permit(memory_sessionmaker: sessionmaker) -> None:
    import_tr_ts_catalog_to_ntm_v2()
    with memory_sessionmaker() as s:
        rows = s.query(NtmMeasureV2).filter_by(tr_ts_act_code="004/2011", permit_type="ДС").all()
        assert len(rows) == 1


def test_engine_prefix_8517(memory_sessionmaker: sessionmaker) -> None:
    from app.services.ntm_engine_v2 import evaluate_ntm_v2

    import_tr_ts_catalog_to_ntm_v2()
    out = evaluate_ntm_v2(hs_code="8517620000")
    keys = {(r["permit_type"], r["tr_ts"]) for r in out["requirements"]}
    assert ("ДС", "004/2011") in keys
    assert any(r["matched_hs_scope"] == "8517" for r in out["requirements"] if r["tr_ts"] == "004/2011")


def test_engine_normalizes_hs_formatting(memory_sessionmaker: sessionmaker) -> None:
    from app.services.ntm_engine_v2 import evaluate_ntm_v2

    import_tr_ts_catalog_to_ntm_v2()
    a = evaluate_ntm_v2(hs_code="8517 62.00-00")
    b = evaluate_ntm_v2(hs_code="8517620000")
    assert a["requirements"] == b["requirements"]


def test_engine_excludes_rule_by_valid_to(memory_sessionmaker: sessionmaker) -> None:
    from app.services.ntm_engine_v2 import evaluate_ntm_v2

    import_tr_ts_catalog_to_ntm_v2()
    with memory_sessionmaker() as s:
        rule = (
            s.query(NtmApplicabilityRuleV2)
            .join(NtmMeasureV2)
            .filter(NtmMeasureV2.tr_ts_act_code == "004/2011", NtmMeasureV2.permit_type == "ДС")
            .filter(NtmApplicabilityRuleV2.hs_code == "8517")
            .one()
        )
        rule.valid_to = date.today() - timedelta(days=1)
        s.commit()

    out = evaluate_ntm_v2(hs_code="8517620000")
    assert all(not (r["tr_ts"] == "004/2011" and r["permit_type"] == "ДС") for r in out["requirements"])


def test_engine_includes_rule_when_dates_open(memory_sessionmaker: sessionmaker) -> None:
    from app.services.ntm_engine_v2 import evaluate_ntm_v2

    import_tr_ts_catalog_to_ntm_v2()
    out = evaluate_ntm_v2(hs_code="8517620000")
    assert any(r["tr_ts"] == "004/2011" and r["permit_type"] == "ДС" for r in out["requirements"])


def test_shadow_full_overlap(memory_sessionmaker: sessionmaker) -> None:
    from app.services.ntm_engine_v2 import compare_legacy_tr_ts_catalog_vs_ntm_v2

    import_tr_ts_catalog_to_ntm_v2()
    cmp = compare_legacy_tr_ts_catalog_vs_ntm_v2("8517620000")
    assert cmp["is_full_match"] is True
    assert cmp["legacy_only"] == []
    assert cmp["v2_only"] == []


def test_shadow_legacy_only(monkeypatch: pytest.MonkeyPatch, memory_sessionmaker: sessionmaker) -> None:
    from app.services import ntm_engine_v2 as eng

    import_tr_ts_catalog_to_ntm_v2()

    def _fake_legacy(_hs: str) -> list[dict]:
        return [{"permit_type": "ДС", "tr_ts": "999/2099"}]

    monkeypatch.setattr(eng, "get_tr_ts_requirements", _fake_legacy)
    cmp = eng.compare_legacy_tr_ts_catalog_vs_ntm_v2("8517620000")
    assert "ДС|999/2099" in cmp["legacy_only"]
    assert cmp["is_full_match"] is False


def test_shadow_v2_only(monkeypatch: pytest.MonkeyPatch, memory_sessionmaker: sessionmaker) -> None:
    from app.services import ntm_engine_v2 as eng

    import_tr_ts_catalog_to_ntm_v2()
    monkeypatch.setattr(eng, "get_tr_ts_requirements", lambda _hs: [])
    cmp = eng.compare_legacy_tr_ts_catalog_vs_ntm_v2("8517620000")
    assert len(cmp["v2_only"]) > 0
    assert cmp["is_full_match"] is False


def test_regression_matrix_tr_ts_shadow_smoke(memory_sessionmaker: sessionmaker) -> None:
    """Smoke: только ключи ТР ТС из каталога (без НФ/ЛЗ/СГР из слоёв)."""
    from tests.test_ntm_pipeline import REGRESSION_MATRIX

    from app.services.ntm_engine_v2 import compare_legacy_tr_ts_catalog_vs_ntm_v2

    import_tr_ts_catalog_to_ntm_v2()
    mismatches: list[tuple[str, dict]] = []
    seen_hs: set[str] = set()
    for hs, _desc, expected in REGRESSION_MATRIX:
        if hs in seen_hs:
            continue
        seen_hs.add(hs)
        cmp = compare_legacy_tr_ts_catalog_vs_ntm_v2(hs)
        if not cmp["is_full_match"]:
            mismatches.append((hs, cmp))
    assert mismatches == [], f"unexpected TR TS mismatches: {mismatches[:5]}"


def _matched_official_rule_import_keys(
    memory_sessionmaker: sessionmaker,
    hs_code: str,
    description: str,
) -> set[str]:
    """Те же runtime-матчи, что ``evaluate_ntm_v2`` для ``official_sgr_registry``."""
    from datetime import date

    from sqlalchemy import select
    from sqlalchemy.orm import joinedload

    from app.services.ntm_engine_v2 import _rule_matches_runtime
    from app.services.ntm_v2_official_sgr_import import OFFICIAL_SGR_SOURCE_KIND

    from app.models.ntm_v2 import NtmApplicabilityRuleV2, NtmMeasureV2
    from app.services.hs_matching import normalize_hs_code

    norm = normalize_hs_code(hs_code)
    ref = date.today()
    keys: set[str] = set()
    with memory_sessionmaker() as s:
        stmt = (
            select(NtmApplicabilityRuleV2)
            .join(NtmMeasureV2, NtmApplicabilityRuleV2.measure_id == NtmMeasureV2.id)
            .options(joinedload(NtmApplicabilityRuleV2.measure))
            .where(
                NtmMeasureV2.status == "active",
                NtmMeasureV2.source_kind == OFFICIAL_SGR_SOURCE_KIND,
                NtmApplicabilityRuleV2.source_kind == OFFICIAL_SGR_SOURCE_KIND,
            )
        )
        for rule in s.scalars(stmt).unique().all():
            if _rule_matches_runtime(
                rule,
                norm_hs=norm,
                description=description,
                country=None,
                as_of=ref,
            ):
                keys.add(rule.rule_import_key)
    return keys


@pytest.fixture
def official_sgr_engine_imported(memory_sessionmaker: sessionmaker) -> None:
    from app.services.ntm_v2_official_sgr_import import import_official_sgr_rules_to_ntm_v2, load_official_sgr_payload

    import_official_sgr_rules_to_ntm_v2(load_official_sgr_payload())


CHILD_DIAPERS_ENGINE_KEY = "official_sgr_registry|rule:eec299-9619-child-diapers-clarify"
EXCLUDE_ONLY_ENGINE_KEY = "official_sgr_registry|rule:test-exclude-only-hs"


@pytest.mark.parametrize(
    ("description", "expect_child"),
    [
        ("детские подгузники", True),
        ("пеленки для младенцев", True),
        ("подгузники для взрослых", False),
        ("подгузники", False),
    ],
)
def test_engine_official_sgr_child_diapers_9619(
    memory_sessionmaker: sessionmaker,
    official_sgr_engine_imported: None,
    description: str,
    expect_child: bool,
) -> None:
    keys = _matched_official_rule_import_keys(memory_sessionmaker, "9619000000", description)
    assert (CHILD_DIAPERS_ENGINE_KEY in keys) is expect_child


def test_engine_official_sgr_child_diapers_via_evaluate_ntm_v2(
    memory_sessionmaker: sessionmaker,
    official_sgr_engine_imported: None,
) -> None:
    from app.services.ntm_engine_v2 import evaluate_ntm_v2
    from app.services.ntm_v2_official_sgr_import import OFFICIAL_SGR_SOURCE_KIND

    out = evaluate_ntm_v2(
        hs_code="9619000000",
        description="детские подгузники",
        source_kinds=frozenset({OFFICIAL_SGR_SOURCE_KIND}),
    )
    assert out["requirements"]
    keys = _matched_official_rule_import_keys(memory_sessionmaker, "9619000000", "детские подгузники")
    assert CHILD_DIAPERS_ENGINE_KEY in keys


def test_engine_official_sgr_exclude_only_rule(
    memory_sessionmaker: sessionmaker,
    official_sgr_engine_imported: None,
) -> None:
    from app.services.ntm_v2_official_sgr_import import import_official_sgr_rules_to_ntm_v2

    import_official_sgr_rules_to_ntm_v2(
        {
            "source_document": "test",
            "rules": [
                {
                    "rule_id": "test-exclude-only-hs",
                    "hs_scope": "9619",
                    "hs_scope_mode": "prefix",
                    "permit_type": "СГР",
                    "applicability": "possible",
                    "title": "Test exclude-only HS rule",
                    "evidence": "test",
                    "exclude_if_contains_any": ["взросл"],
                }
            ],
        }
    )
    keys_ok = _matched_official_rule_import_keys(memory_sessionmaker, "9619000000", "товар")
    keys_ex = _matched_official_rule_import_keys(memory_sessionmaker, "9619000000", "товар для взрослых")
    assert EXCLUDE_ONLY_ENGINE_KEY in keys_ok
    assert EXCLUDE_ONLY_ENGINE_KEY not in keys_ex


def test_rule_description_matches_official_sgr_and_mode(
    memory_sessionmaker: sessionmaker,
    official_sgr_engine_imported: None,
) -> None:
    from app.services.ntm_engine_v2 import _rule_description_matches

    dm = {
        "mode": "official_sgr_and",
        "description_contains_any": ["подгузник", "пеленк"],
        "description_requires_any": ["детск", "младен", "baby"],
        "exclude_if_contains_any": ["взросл"],
        "substrings": ["подгузник", "пеленк"],
    }
    assert _rule_description_matches(dm, "детские подгузники") is True
    assert _rule_description_matches(dm, "подгузники для взрослых") is False
    assert _rule_description_matches(dm, "подгузники") is False


def test_rule_description_matches_official_sgr_exclude_only_mode() -> None:
    from app.services.ntm_engine_v2 import _rule_description_matches

    dm = {"mode": "official_sgr", "exclude_if_contains_any": ["взросл"]}
    assert _rule_description_matches(dm, "товар") is True
    assert _rule_description_matches(dm, "детское средство") is True
    assert _rule_description_matches(dm, "товар для взрослых") is False
