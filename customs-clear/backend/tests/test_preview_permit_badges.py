"""Регрессия badge нетарифки в preview (/api/v1/tnved/preview/{code})."""

from fastapi.testclient import TestClient

from app.api.tnved_catalog import clear_preview_cache
from app.main import app

client = TestClient(app)

PREVIEW_BADGE_CASES: dict[str, list[str]] = {
    "5208211000": ["ДС"],
    "6101100000": ["ДС"],
    "6401100000": ["ДС"],
    "9503001000": ["ДС", "СС"],
    "0401100000": ["ДС"],
    "3304100000": ["ДС"],
    "8517130000": ["Марк"],
    "8401100000": ["Серт"],
    "2204101100": ["ЛЗ", "Марк"],
    "9401100000": ["ДС"],
}


def test_preview_measure_badges_regression() -> None:
    clear_preview_cache()
    for code, expected in PREVIEW_BADGE_CASES.items():
        r = client.get(f"/api/v1/tnved/preview/{code}")
        assert r.status_code == 200, f"{code}: {r.status_code} {r.text[:200]}"
        badges = r.json().get("non_tariff", {}).get("measure_badges") or []
        if expected == []:
            assert badges == [], f"{code}: expected empty, got {badges}"
        else:
            assert all(e in badges for e in expected), f"{code}: expected {expected}, got {badges}"
