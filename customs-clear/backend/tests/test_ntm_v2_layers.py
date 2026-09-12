"""Импорт и runtime ntm_layers → NTM v2 (флаг ``NTM_V2_LAYERS_ENABLED``)."""

from __future__ import annotations

import asyncio
import logging
from datetime import date

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
    assert r1["layers_rules_removed"] == 0
    assert r2["layers_rules_removed"] == 0


def test_import_layers_reconciles_old_generated_snapshot_only(
    memory_sessionmaker: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import ntm_layers as nl

    current_vet = set(nl.VET_DOMAINS)
    current_phyto = set(nl.PHYTO_DOMAINS)
    added_vet = {"0309"}
    removed_vet = {"0508", "2305", "5104"}
    added_phyto = {
        "0712901100",
        "090111",
        "090112",
        "1106100000",
        "1801000000",
        "1802000000",
        "3101000000",
    }
    removed_phyto = {
        "0710",
        "0711",
        "0712",
        "0811",
        "0812",
        "0814",
        "0901",
        "0902",
        "0903",
        "0904",
        "0905",
        "0906",
        "0907",
        "0908",
        "0909",
        "0910",
        "1105",
        "1106",
        "1108",
        "1109",
    }
    assert added_vet <= current_vet
    assert added_phyto <= current_phyto
    assert removed_vet.isdisjoint(current_vet)
    assert removed_phyto.isdisjoint(current_phyto)

    monkeypatch.setattr(nl, "VET_DOMAINS", sorted((current_vet - added_vet) | removed_vet))
    monkeypatch.setattr(
        nl,
        "PHYTO_DOMAINS",
        sorted((current_phyto - added_phyto) | removed_phyto),
    )
    old_report = import_ntm_layers_to_ntm_v2()
    assert old_report["layers_rules_removed"] == 0

    # Reconciliation must not cross either ownership boundary: source_kind and
    # the generated rule_import_key namespace must both belong to this importer.
    with memory_sessionmaker() as session:
        vet_measure = session.query(NtmMeasureV2).filter_by(
            import_key="legacy_ntm_layers|vet|ВС"
        ).one()
        common = {
            "measure_id": vet_measure.id,
            "direction": "import",
            "country_iso": None,
            "hs_scope_mode": "prefix",
            "hs_code": "9999",
            "excluded_hs_json": None,
            "description_match_json": None,
            "applicability": "definite",
            "requires_manual_review": False,
            "priority": 1,
            "valid_from": None,
            "valid_to": None,
            "source_ref": "test:must-survive",
        }
        session.add_all(
            [
                NtmApplicabilityRuleV2(
                    **common,
                    source_kind="legacy_ntm_layers",
                    rule_import_key="manual_ntm_layers|must_survive",
                ),
                NtmApplicabilityRuleV2(
                    **common,
                    source_kind="official_test",
                    rule_import_key="legacy_ntm_layers|foreign|must_survive",
                ),
            ]
        )
        session.commit()

    monkeypatch.setattr(nl, "VET_DOMAINS", sorted(current_vet))
    monkeypatch.setattr(nl, "PHYTO_DOMAINS", sorted(current_phyto))
    new_report = import_ntm_layers_to_ntm_v2()
    assert new_report["layers_rules_removed"] == len(removed_vet | removed_phyto) == 23
    assert new_report["layers_rules_created"] == len(added_vet | added_phyto) == 8

    stale_keys = {
        *(f"legacy_ntm_layers|vet|hs|{prefix}" for prefix in removed_vet),
        *(f"legacy_ntm_layers|phyto|hs|{prefix}" for prefix in removed_phyto),
    }
    with memory_sessionmaker() as session:
        keys = {
            row.rule_import_key
            for row in session.query(NtmApplicabilityRuleV2).all()
        }
        assert keys.isdisjoint(stale_keys)
        assert "manual_ntm_layers|must_survive" in keys
        assert "legacy_ntm_layers|foreign|must_survive" in keys

    monkeypatch.setenv("NTM_V2_LAYERS_ENABLED", "true")
    from app.services.ntm_engine_v2 import get_layer_requirements_for_pipeline

    for hs_code in ("0508000000", "0901210000", "0710000000"):
        permit_types = {
            row["permit_type"]
            for row in get_layer_requirements_for_pipeline(hs_code, "")
        }
        if hs_code == "0508000000":
            assert "ВС" not in permit_types
        else:
            assert "ФСС" not in permit_types

    expected_exact = {
        "0309900000": ("ВС", "0309"),
        "0712901100": ("ФСС", "0712901100"),
        "0901110000": ("ФСС", "090111"),
        "0901120000": ("ФСС", "090112"),
        "1106100000": ("ФСС", "1106100000"),
        "1801000000": ("ФСС", "1801000000"),
        "1802000000": ("ФСС", "1802000000"),
        "3101000000": ("ФСС", "3101000000"),
    }
    for hs_code, (permit_type, matched_prefix) in expected_exact.items():
        matches = [
            row
            for row in get_layer_requirements_for_pipeline(hs_code, "")
            if row["permit_type"] == permit_type
        ]
        assert len(matches) == 1
        assert matches[0]["matched_prefix"] == matched_prefix

    stable_report = import_ntm_layers_to_ntm_v2()
    assert stable_report["layers_rules_created"] == 0
    assert stable_report["layers_rules_removed"] == 0


def test_import_layers_refreshes_all_retained_generated_rule_fields(
    memory_sessionmaker: sessionmaker,
) -> None:
    import_ntm_layers_to_ntm_v2()
    retained_key = "legacy_ntm_layers|vet|hs|0101"

    with memory_sessionmaker() as session:
        retained = session.query(NtmApplicabilityRuleV2).filter_by(
            rule_import_key=retained_key
        ).one()
        retained_id = retained.id
        phyto_measure = session.query(NtmMeasureV2).filter_by(
            import_key="legacy_ntm_layers|phyto|ФСС"
        ).one()
        retained.measure_id = phyto_measure.id
        retained.direction = "export"
        retained.country_iso = "CN"
        retained.hs_scope_mode = "exact"
        retained.hs_code = "9999"
        retained.excluded_hs_json = ["0101"]
        retained.description_match_json = {
            "mode": "any_substring",
            "substrings": ["never"],
        }
        retained.applicability = "possible"
        retained.requires_manual_review = True
        retained.priority = -1
        retained.valid_from = date(2099, 1, 1)
        retained.valid_to = date(2000, 1, 1)
        retained.source_ref = "corrupt:test"
        session.commit()

    report = import_ntm_layers_to_ntm_v2()
    assert report["layers_rules_created"] == 0
    assert report["layers_rules_removed"] == 0

    with memory_sessionmaker() as session:
        retained = session.query(NtmApplicabilityRuleV2).filter_by(
            rule_import_key=retained_key
        ).one()
        vet_measure = session.query(NtmMeasureV2).filter_by(
            import_key="legacy_ntm_layers|vet|ВС"
        ).one()
        assert retained.id == retained_id
        assert retained.measure_id == vet_measure.id
        assert retained.direction == "import"
        assert retained.country_iso is None
        assert retained.hs_scope_mode == "prefix"
        assert retained.hs_code == "0101"
        assert retained.excluded_hs_json is None
        assert retained.description_match_json is None
        assert retained.applicability == "definite"
        assert retained.requires_manual_review is False
        assert retained.priority > 10_000
        assert retained.valid_from is None
        assert retained.valid_to is None
        assert retained.source_kind == "legacy_ntm_layers"
        assert retained.source_ref == "ntm_layers.py:get_vet_requirement:0101"


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
