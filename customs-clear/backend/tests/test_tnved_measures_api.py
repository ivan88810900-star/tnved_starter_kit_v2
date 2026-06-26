"""GET /api/v1/tnved/{code} — поле measures для фронта frontend/web."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

MEASURES_CASES: dict[str, list[str]] = {
    "5208211000": ["ДС"],
    "6101100000": ["ДС"],
    "6401100000": ["ДС"],
    "9503001000": ["ДС"],
    "3304100000": ["ДС"],
    "8517130000": ["Марк"],
    "8401100000": ["Серт"],
}


def test_commodity_measures_regression() -> None:
    for code, expected in MEASURES_CASES.items():
        r = client.get(f"/api/v1/tnved/{code}")
        assert r.status_code == 200, f"{code}: {r.status_code}"
        measures = [m.get("type", "") for m in r.json().get("measures", [])]
        if expected == []:
            assert measures == [], f"{code}: expected empty, got {measures}"
        else:
            assert all(e in measures for e in expected), f"{code}: expected {expected}, got {measures}"
            assert len(measures) > 0
