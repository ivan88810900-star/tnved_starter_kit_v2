"""Тестовые значения обязательных auth-переменных окружения."""
from __future__ import annotations

import os

# После ужесточения auth-конфига эти переменные обязательны на старте приложения.
# В тестовом раннере задаём безопасные фиктивные значения через setdefault,
# чтобы реальные значения из окружения (если есть) не перетирать.
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-backend-tests-0123456789")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("VIEWER_PASSWORD", "test-viewer-password")
os.environ.setdefault("DECLARANT_PASSWORD", "test-declarant-password")
