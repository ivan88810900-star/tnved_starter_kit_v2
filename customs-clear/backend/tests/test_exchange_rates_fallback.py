from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.core import ExchangeRate
from app.services import exchange_rates


def _session_factory(tmp_path, database_name: str):
    engine = create_engine(f"sqlite:///{tmp_path / database_name}")
    return engine, sessionmaker(bind=engine)


def test_readers_use_local_fallback_when_exchange_rates_table_is_absent(
    tmp_path, monkeypatch
) -> None:
    _, session_factory = _session_factory(tmp_path, "missing-table.sqlite")
    monkeypatch.setattr(exchange_rates, "SessionLocal", session_factory)

    assert exchange_rates.get_rates_map() == exchange_rates.FALLBACK

    payload = exchange_rates.get_rates_payload()
    assert payload["status"] == "OK"
    assert payload["base"] == "RUB"
    assert payload["updated_at"] == ""
    assert payload["map"] == exchange_rates.FALLBACK
    assert {item["currency_code"] for item in payload["rates"]} == set(
        exchange_rates.TRACKED
    )


def test_persisted_rates_override_fallback_values(tmp_path, monkeypatch) -> None:
    engine, session_factory = _session_factory(tmp_path, "persisted.sqlite")
    ExchangeRate.__table__.create(engine)
    updated_at = datetime(2026, 10, 15, 1, 30, 0)
    with session_factory() as db:
        db.add(
            ExchangeRate(
                currency_code="USD",
                rate=77.5,
                nominal=1.0,
                updated_at=updated_at,
            )
        )
        db.commit()
    monkeypatch.setattr(exchange_rates, "SessionLocal", session_factory)

    rates = exchange_rates.get_rates_map()
    assert rates["USD"] == 77.5
    assert rates["EUR"] == exchange_rates.FALLBACK["EUR"]
    assert rates["RUB"] == 1.0

    payload = exchange_rates.get_rates_payload()
    assert payload["updated_at"] == updated_at.isoformat()
    assert payload["map"] == {"USD": 77.5, "RUB": 1.0}
