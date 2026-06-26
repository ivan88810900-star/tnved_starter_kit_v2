"""Каскадный поиск non_tariff_measures по префиксам кода."""

from app.db import SessionLocal
from app.services.non_tariff_measures_lookup import build_measure_code_candidates, get_measures_for_code


def test_build_measure_code_candidates_includes_chapter_and_position_pad() -> None:
    candidates = set(build_measure_code_candidates("0601100000"))
    assert "0601100000" in candidates
    assert "0601000000" in candidates
    assert "06" in candidates


def test_get_measures_for_code_0601100000_phyto_and_certificate() -> None:
    with SessionLocal() as db:
        rows = get_measures_for_code("0601100000", db)
    types = {(m.measure_type or "").strip().lower() for m in rows}
    assert "phyto_control" in types
    assert "certificate" in types
