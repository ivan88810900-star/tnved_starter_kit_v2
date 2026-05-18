#!/usr/bin/env python3
"""Smoke-тест основных API endpoints.

Запуск: cd customs-clear/backend && PYTHONPATH=. python3 scripts/smoke_test.py
"""
from __future__ import annotations

import sys

try:
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services.normative_store import init_db
except ImportError as e:
    print(f"Ошибка импорта: {e}")
    print("Установите зависимости: pip install -r requirements.txt")
    sys.exit(1)

client = TestClient(app)

def test(name: str, fn):
    try:
        fn()
        print(f"  OK: {name}")
        return True
    except Exception as e:
        print(f"  FAIL: {name} — {e}")
        return False

def main():
    print("Инициализация БД...")
    init_db()

    print("Smoke-тесты API:")
    ok = 0
    ok += test("GET /api/health", lambda: client.get("/api/health").raise_for_status())
    ok += test("GET /api/sources/status", lambda: client.get("/api/sources/status").raise_for_status())
    ok += test("POST /api/calculator/compute", lambda: client.post("/api/calculator/compute", json={
        "hs_code": "8509400000", "customs_value": 100000, "freight": 10000
    }).raise_for_status())
    ok += test("POST /api/compliance/check", lambda: client.post("/api/compliance/check", json={
        "items": [{"hs_code": "8509400000", "description": "Тест", "customs_value": 100000, "freight": 0}]
    }).raise_for_status())
    ok += test("POST /api/non_tariff/check", lambda: client.post("/api/non_tariff/check", json={
        "items": [{"hs_code": "8509400000", "description": "Тест", "permits": []}]
    }).raise_for_status())
    ok += test("GET /api/health/ready", lambda: client.get("/api/health/ready").raise_for_status())
    ok += test("GET /api/trois/suggest", lambda: client.get("/api/trois/suggest", params={"q": "sam"}).raise_for_status())
    ok += test("GET /api/assistant/decisions/recent", lambda: client.get("/api/assistant/decisions/recent", params={"limit": 3}).raise_for_status())
    ok += test("GET /api/assistant/decisions/similar", lambda: client.get("/api/assistant/decisions/similar", params={"q": "товар", "limit": 3}).raise_for_status())
    ok += test("GET /api/assistant/decisions/hints", lambda: client.get("/api/assistant/decisions/hints", params={"q": "товар"}).raise_for_status())
    ok += test("GET /api/assistant/decisions/export", lambda: client.get("/api/assistant/decisions/export", params={"format": "json"}).raise_for_status())
    ok += test("GET /api/assistant/decisions/stats", lambda: client.get("/api/assistant/decisions/stats").raise_for_status())
    ok += test("GET /api/integrations/alta/status", lambda: client.get("/api/integrations/alta/status").raise_for_status())

    print(f"\n{ok}/13 тестов пройдено")
    sys.exit(0 if ok == 13 else 1)

if __name__ == "__main__":
    main()
