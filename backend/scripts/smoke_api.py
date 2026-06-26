"""Быстрая проверка API: реальный FastAPI + текущая SQLite-БД.

Запуск:
    cd backend
    python3 -m scripts.smoke_api
Проверяет:
  - /api/codes/chapters возвращает непустой список;
  - /api/codes/children/<главы> возвращает детей с title_full;
  - /api/codes/<code> возвращает объект с title_full и path;
  - /api/codes/search?q=... отрабатывает.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402


def check(condition: bool, message: str) -> None:
    status = "OK " if condition else "FAIL"
    print(f"  [{status}] {message}")
    if not condition:
        sys.exit(1)


def main() -> None:
    with TestClient(app) as client:
        print("== /api/codes/chapters ==")
        r = client.get("/api/codes/chapters")
        check(r.status_code == 200, f"status=200 (got {r.status_code})")
        chapters = r.json()
        check(isinstance(chapters, list) and len(chapters) > 0, f"non-empty list (n={len(chapters)})")
        ch10 = next((c for c in chapters if c["code"] == "10"), None)
        check(ch10 is not None, "chapter 10 present")

        print("== /api/codes/children/10?group_next=true ==")
        r = client.get("/api/codes/children/10?group_next=true&include_tariff=false")
        check(r.status_code == 200, f"status=200 (got {r.status_code})")
        kids = r.json()
        check(isinstance(kids, list) and len(kids) > 0, f"non-empty list (n={len(kids)})")
        have_full = sum(1 for k in kids if k.get("title_full"))
        check(have_full > 0, f"at least one child has title_full ({have_full}/{len(kids)})")

        print("== /api/codes/1001 ==")
        r = client.get("/api/codes/1001")
        check(r.status_code == 200, f"status=200 (got {r.status_code})")
        detail = r.json()
        check(detail.get("code") == "1001", "code == 1001")
        check(bool(detail.get("title_full")), f"title_full is present: {detail.get('title_full')!r}")
        check(isinstance(detail.get("path"), list), "path is a list")

        print("== /api/codes/search?q=пшеница ==")
        r = client.get("/api/codes/search?q=пшеница")
        check(r.status_code == 200, f"status=200 (got {r.status_code})")
        results = r.json()
        check(isinstance(results, list) and len(results) > 0, f"non-empty list (n={len(results)})")
        has_full_in_results = sum(1 for x in results if x.get("title_full"))
        print(f"     title_full hit-rate in search: {has_full_in_results}/{len(results)}")

    print("\nSmoke OK")


if __name__ == "__main__":
    main()
