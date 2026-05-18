"""Курсы валют (ЦБ РФ) для расчётов калькулятора."""

from __future__ import annotations

from typing import Any

import httpx
from loguru import logger

CBR_DAILY_JSON_URL = "https://www.cbr-xml-daily.ru/daily_json.js"
FALLBACK_USD_RUB = 100.0
FALLBACK_EUR_RUB = 110.0


class CurrencyService:
    """Курсы USD/EUR к рублю с официального JSON ЦБ; кэш в памяти на время процесса."""

    _cached_usd_rub: float | None = None
    _cached_eur_rub: float | None = None

    @classmethod
    def get_usd_rate(cls) -> float:
        if cls._cached_usd_rub is not None:
            return cls._cached_usd_rub
        try:
            with httpx.Client(timeout=20.0) as client:
                resp = client.get(CBR_DAILY_JSON_URL)
                resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            valute = data.get("Valute") or {}
            usd = valute.get("USD") or {}
            raw = usd.get("Value")
            if raw is None:
                raise ValueError("Valute.USD.Value отсутствует в ответе ЦБ")
            if isinstance(raw, (int, float)):
                rate = float(raw)
            else:
                rate = float(str(raw).strip().replace(",", "."))
            if rate <= 0:
                raise ValueError(f"Некорректный курс USD: {rate}")
            cls._cached_usd_rub = rate
            return rate
        except Exception as e:
            logger.warning(
                "CurrencyService: не удалось получить курс USD с {} — используем fallback {}: {}",
                CBR_DAILY_JSON_URL,
                FALLBACK_USD_RUB,
                e,
            )
            cls._cached_usd_rub = FALLBACK_USD_RUB
            return FALLBACK_USD_RUB

    @classmethod
    def get_eur_rate(cls) -> float:
        """Курс EUR/RUB (Valute.EUR.Value), тот же источник, что и для USD."""
        if cls._cached_eur_rub is not None:
            return cls._cached_eur_rub
        try:
            with httpx.Client(timeout=20.0) as client:
                resp = client.get(CBR_DAILY_JSON_URL)
                resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            valute = data.get("Valute") or {}
            eur = valute.get("EUR") or {}
            raw = eur.get("Value")
            if raw is None:
                raise ValueError("Valute.EUR.Value отсутствует в ответе ЦБ")
            if isinstance(raw, (int, float)):
                rate = float(raw)
            else:
                rate = float(str(raw).strip().replace(",", "."))
            if rate <= 0:
                raise ValueError(f"Некорректный курс EUR: {rate}")
            cls._cached_eur_rub = rate
            return rate
        except Exception as e:
            logger.warning(
                "CurrencyService: не удалось получить курс EUR с {} — используем fallback {}: {}",
                CBR_DAILY_JSON_URL,
                FALLBACK_EUR_RUB,
                e,
            )
            cls._cached_eur_rub = FALLBACK_EUR_RUB
            return FALLBACK_EUR_RUB

    @classmethod
    def clear_cache(cls) -> None:
        """Сброс кэша (тесты / повторный запрос к ЦБ в том же процессе)."""
        cls._cached_usd_rub = None
        cls._cached_eur_rub = None
