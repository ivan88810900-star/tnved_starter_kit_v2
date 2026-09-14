from __future__ import annotations

from app.services.tr_ts_catalog import TR_TS_FULL_NAMES, get_tr_ts_requirements


def _regulations(hs_code: str) -> set[str]:
    return {str(row["tr_ts"]) for row in get_tr_ts_requirements(hs_code)}


def test_current_eec_register_contains_001_through_053() -> None:
    assert len(TR_TS_FULL_NAMES) == 53
    assert TR_TS_FULL_NAMES["049/2020"].startswith("О требованиях к магистральным трубопроводам")
    assert "гражданской обороны" in TR_TS_FULL_NAMES["050/2021"]
    assert "мяса птицы" in TR_TS_FULL_NAMES["051/2021"]
    assert "метрополитена" in TR_TS_FULL_NAMES["052/2021"]
    assert "лакокрасочных" in TR_TS_FULL_NAMES["053/2026"]


def test_lpg_and_pipeline_are_not_broad_broker_rules() -> None:
    regs = _regulations("2711129400")
    assert "036/2016" not in regs
    assert "049/2020" not in regs


def test_metro_and_civil_defence_are_not_code_only_broker_rules() -> None:
    regs = _regulations("8605000000")
    assert "052/2021" not in regs
    assert "050/2021" not in regs


def test_poultry_051_is_not_broad_broker_enforcement() -> None:
    assert "051/2021" not in _regulations("0207121000")
