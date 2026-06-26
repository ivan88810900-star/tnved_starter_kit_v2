"""Тесты MVP: ИНН, коды ТР ТС, нормализация ответа внешнего классификатора."""
from __future__ import annotations

from app.services.custom_classifier_service import _normalize_external_response
from app.services.document_intel import validate_inn_ru
from app.services.normative_store import extract_tr_ts_act_codes


def test_inn_10_valid() -> None:
    # Пример ИНН юрлица с валидной КС (из открытых тестовых наборов)
    assert validate_inn_ru("7707083893")["valid"] is True


def test_inn_10_invalid() -> None:
    assert validate_inn_ru("7707083890")["valid"] is False


def test_extract_tr_ts_codes() -> None:
    codes = extract_tr_ts_act_codes(["ТР ТС 004/2011", "020/2011", "без кода"])
    assert "004/2011" in codes
    assert "020/2011" in codes


def test_normalize_custom_classifier_payload() -> None:
    out = _normalize_external_response(
        {"hs_code": "8509400000", "confidence": 0.9},
        "чайник",
    )
    assert out is not None
    assert out["results"][0]["code"] == "8509400000"
    assert out["results"][0]["recommended"] is True
