"""Логин TestClient для защищённых маршрутов (JWT cookie, как в production)."""
from __future__ import annotations

from typing import Any


def login_declarant(client: Any) -> None:
    r = client.post(
        "/api/auth/login",
        data={"username": "declarant", "password": "test-declarant-password"},
    )
    assert r.status_code == 200, r.text


def login_viewer(client: Any) -> None:
    r = client.post(
        "/api/auth/login",
        data={"username": "viewer", "password": "test-viewer-password"},
    )
    assert r.status_code == 200, r.text


def login_admin(client: Any) -> None:
    r = client.post(
        "/api/auth/login",
        data={"username": "admin", "password": "test-admin-password"},
    )
    assert r.status_code == 200, r.text
