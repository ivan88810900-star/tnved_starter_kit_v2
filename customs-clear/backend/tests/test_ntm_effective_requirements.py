"""Тесты effective requirements (без изменения missing-логики)."""

from __future__ import annotations

import asyncio

from app.services.ntm_effective_requirements import build_effective_requirements
from app.services.non_tariff_service import check_position_non_tariff


def test_build_broker_only_used_for_missing() -> None:
    out = build_effective_requirements(
        broker_required_permits=[
            {
                "permit_type": "ДС",
                "tr_ts": "004/2011",
                "matched_prefix": "8471",
                "legal_ref": "",
                "description": "",
                "trigger": None,
            }
        ],
        rules=[],
        measures=[],
        trigger_measures=[],
    )
    assert len(out["used_for_missing_check"]) == 1
    assert out["used_for_missing_check"][0]["used_for_missing_check"] is True
    assert "broker_catalog_layers" in out["used_for_missing_check"][0]["sources"]


def test_rule_only_informational() -> None:
    out = build_effective_requirements(
        broker_required_permits=[],
        rules=[
            {
                "name": "r",
                "required_permits": ["СС"],
                "tr_ts": ["020/2011"],
                "hs_prefix": "85",
            }
        ],
        measures=[],
        trigger_measures=[],
    )
    assert len(out["informational_only"]) == 1
    assert out["informational_only"][0]["used_for_missing_check"] is False
    assert out["informational_only"][0]["key"] == "СС|020/2011"


def test_measure_only_informational() -> None:
    out = build_effective_requirements(
        broker_required_permits=[],
        rules=[],
        measures=[
            {
                "permit_type": "КВ",
                "tr_ts_code": "",
                "commodity_code": "9999999999",
                "measure_type": "other",
                "source_level": "exact",
            }
        ],
        trigger_measures=[],
    )
    assert any(x["key"] == "КВ|" for x in out["informational_only"])


def test_broker_plus_rule_same_key_merged_used_true() -> None:
    out = build_effective_requirements(
        broker_required_permits=[
            {
                "permit_type": "ДС",
                "tr_ts": "004/2011",
                "matched_prefix": "85",
                "legal_ref": "",
                "description": "",
                "trigger": None,
            }
        ],
        rules=[
            {
                "name": "seed",
                "required_permits": ["ДС"],
                "tr_ts": ["004/2011"],
                "hs_prefix": "8517",
            }
        ],
        measures=[],
        trigger_measures=[],
    )
    assert len(out["all"]) == 1
    row = out["all"][0]
    assert row["used_for_missing_check"] is True
    assert "broker_catalog_layers" in row["sources"]
    assert "rules_db" in row["sources"]


def test_different_tr_ts_same_permit_not_collapsed() -> None:
    out = build_effective_requirements(
        broker_required_permits=[
            {"permit_type": "ДС", "tr_ts": "004/2011", "matched_prefix": "", "legal_ref": "", "description": "", "trigger": None},
            {"permit_type": "ДС", "tr_ts": "020/2011", "matched_prefix": "", "legal_ref": "", "description": "", "trigger": None},
        ],
        rules=[],
        measures=[],
        trigger_measures=[],
    )
    assert len(out["all"]) == 2


def test_empty_tr_ts_stable() -> None:
    out = build_effective_requirements(
        broker_required_permits=[
            {
                "permit_type": "РУ",
                "tr_ts": None,
                "matched_prefix": "30",
                "legal_ref": "SENSITIVE_OVERRIDES",
                "description": "",
                "trigger": None,
            }
        ],
        rules=[],
        measures=[],
        trigger_measures=[],
    )
    assert out["all"][0]["key"] == "РУ|"
    assert "sensitive_override" in out["all"][0]["sources"]


def test_check_position_debug_does_not_change_business_fields() -> None:
    async def _run(debug: bool) -> dict:
        return await check_position_non_tariff(
            "8471300000",
            "Ноутбук обычный",
            "CN",
            [],
            skip_registry_verify=True,
            include_effective_requirements_debug=debug,
        )

    base = asyncio.run(_run(False))
    dbg = asyncio.run(_run(True))

    for k in (
        "status",
        "required_permit_types",
        "missing_permit_types",
        "required_permits",
    ):
        assert base[k] == dbg[k], k

    assert "effective_requirements_debug" not in base
    assert "effective_requirements_debug" in dbg
    er = dbg["effective_requirements_debug"]
    assert "all" in er and "used_for_missing_check" in er
    used_keys = {x["key"] for x in er["used_for_missing_check"]}
    broker_keys = {_row_key(p) for p in dbg["required_permits"]}
    assert used_keys == broker_keys


def _row_key(p: dict) -> str:
    pt = str(p.get("permit_type") or "")
    ts = p.get("tr_ts")
    t = (str(ts).strip() if ts is not None else "") or ""
    return f"{pt}|{t}"
