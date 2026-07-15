#!/usr/bin/env python3
"""Smoke-тест основных API endpoints.

Запуск: cd customs-clear/backend && PYTHONPATH=. python3 scripts/smoke_test.py
"""
from __future__ import annotations

import os


def _run_check(name: str, fn):
    try:
        fn()
        print(f"  OK: {name}")
        return True
    except Exception as e:
        print(f"  FAIL: {name} — {e}")
        return False


def main() -> int:
    try:
        from fastapi.testclient import TestClient

        from app.main import app
        from app.services.normative_store import init_db
    except ImportError as exc:
        print(f"Ошибка импорта: {exc}")
        print("Установите зависимости: pip install -r requirements.txt")
        return 1

    client = TestClient(app)
    print("Инициализация БД...")
    init_db()

    smoke_username = (os.getenv("SMOKE_USERNAME") or "declarant").strip()
    smoke_password = (os.getenv("SMOKE_PASSWORD") or os.getenv("DECLARANT_PASSWORD") or "").strip()
    if not smoke_password:
        print("Для smoke-теста задайте SMOKE_PASSWORD или DECLARANT_PASSWORD.")
        return 1
    login = client.post(
        "/api/auth/login",
        data={
            "username": smoke_username,
            "password": smoke_password,
        },
    )
    if not login.is_success:
        print(f"Не удалось создать тестовую сессию: HTTP {login.status_code}")
        return 1

    print("Smoke-тесты API:")
    ok = 0
    ok += _run_check("GET /api/health", lambda: client.get("/api/health").raise_for_status())
    ok += _run_check("GET /api/sources/status", lambda: client.get("/api/sources/status").raise_for_status())
    ok += _run_check("POST /api/calculator/compute", lambda: client.post("/api/calculator/compute", json={
        "hs_code": "8509400000", "customs_value": 100000, "freight": 10000
    }).raise_for_status())
    ok += _run_check("POST /api/compliance/check", lambda: client.post("/api/compliance/check", json={
        "items": [{"hs_code": "8509400000", "description": "Тест", "customs_value": 100000, "freight": 0}]
    }).raise_for_status())
    ok += _run_check("POST /api/non_tariff/check", lambda: client.post("/api/non_tariff/check", json={
        "items": [{"hs_code": "8509400000", "description": "Тест", "permits": []}]
    }).raise_for_status())
    ok += _run_check("GET /api/health/ready", lambda: client.get("/api/health/ready").raise_for_status())
    ok += _run_check("GET /api/trois/suggest", lambda: client.get("/api/trois/suggest", params={"q": "sam"}).raise_for_status())
    ok += _run_check("GET /api/assistant/decisions/recent", lambda: client.get("/api/assistant/decisions/recent", params={"limit": 3}).raise_for_status())
    ok += _run_check("GET /api/assistant/decisions/similar", lambda: client.get("/api/assistant/decisions/similar", params={"q": "товар", "limit": 3}).raise_for_status())
    ok += _run_check("GET /api/assistant/decisions/hints", lambda: client.get("/api/assistant/decisions/hints", params={"q": "товар"}).raise_for_status())
    ok += _run_check("GET /api/auth/me", lambda: client.get("/api/auth/me").raise_for_status())
    ok += _run_check("GET /api/assistant/decisions/stats", lambda: client.get("/api/assistant/decisions/stats").raise_for_status())
    ok += _run_check("GET /api/integrations/alta/status", lambda: client.get("/api/integrations/alta/status").raise_for_status())

    print(f"\n{ok}/13 тестов пройдено")
    return 0 if ok == 13 else 1


if __name__ == "__main__":
    raise SystemExit(main())
