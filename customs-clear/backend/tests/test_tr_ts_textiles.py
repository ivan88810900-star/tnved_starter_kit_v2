"""ТР ТС 017/2011 — ткани хлопковые (глава 52)."""

from app.services.tr_ts_catalog import get_tr_ts_requirements


def test_cotton_fabric_requires_ds() -> None:
    reqs = get_tr_ts_requirements("5208211000")
    assert any(r.get("permit_type") == "ДС" and r.get("tr_ts") == "017/2011" for r in reqs)


def test_cotton_yarn_chapter_52_has_ds() -> None:
    reqs = get_tr_ts_requirements("5205120000")
    assert any(r.get("permit_type") == "ДС" and r.get("tr_ts") == "017/2011" for r in reqs)
