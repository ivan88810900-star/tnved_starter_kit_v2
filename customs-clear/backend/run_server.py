#!/usr/bin/env python3
"""Точка входа для десктоп-сервера CustomsClear."""
import uvicorn

if __name__ == "__main__":
    # В frozen-сборках надёжнее передавать приложение объектом, а не строкой импорта.
    from app.main import app as fastapi_app

    uvicorn.run(
        fastapi_app,
        host="127.0.0.1",
        port=8001,
        log_level="info",
    )
