"""Admin token verification shared by the administrative routes."""
from __future__ import annotations

import hmac
import os

from fastapi import HTTPException


def require_admin_token(x_admin_token: str | None) -> None:
    """
    Строгая проверка ADMIN_API_TOKEN для админ-операций.
    Доступ без токена полностью запрещён.
    """
    expected = os.getenv("ADMIN_API_TOKEN", "").strip()
    if not expected:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: ADMIN_API_TOKEN не настроен.",
        )
    provided = (x_admin_token or "").strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Unauthorized: invalid or missing X-Admin-Token")
