"""Проверяем, что bnend корректно склеивает полный текст (ETL) и роутер отдаёт title_full."""

from __future__ import annotations

from app.routers.codes import sanitize_title, is_garbage_code
from scripts.enrich_full_titles import compute_title_full


def test_compute_title_full_for_chapter():
    assert compute_title_full("10", "Зерновые культуры", None).startswith("Зерновые")


def test_compute_title_full_inherits_parent_when_own_is_garbage():
    # "мас.%" — типичный артефакт парсинга; собственный текст отбраковывается
    parent_full = "Зерновые культуры"
    assert compute_title_full("1001", "мас.% мас.%", parent_full) == "Зерновые культуры"


def test_compute_title_full_joins_with_em_dash():
    parent_full = "Зерновые культуры"
    own = "Пшеница и меслин"
    out = compute_title_full("1001", own, parent_full)
    assert "—" in out
    assert "Пшеница" in out and "Зерновые" in out


def test_compute_title_full_does_not_duplicate_parent_prefix():
    parent_full = "Зерновые культуры"
    own = "Зерновые культуры — Пшеница"
    out = compute_title_full("1001", own, parent_full)
    # уже начинается с префикса, дублирования не должно быть
    assert out.count("Зерновые культуры") == 1


def test_sanitize_title_filters_tariff_artifacts():
    assert sanitize_title("0,11 евро за кг") is None
    assert sanitize_title("мас.% мас.%") is None


def test_is_garbage_code_filters_measurement_prefix():
    # Единицы измерения как первое слово — мусор
    assert is_garbage_code("1001", "шт") is True
    # Нормальный текст — не мусор
    assert is_garbage_code("1001", "Пшеница и меслин") is False


def test_sanitize_then_is_garbage_returns_none_for_parser_junk():
    # Для «— 1)» sanitize сам возвращает None — значит в ETL оно даже не дойдёт до is_garbage_code
    assert sanitize_title("— 1)") is None
