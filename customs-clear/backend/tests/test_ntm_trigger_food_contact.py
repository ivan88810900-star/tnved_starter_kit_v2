"""Fail-closed regressions for the food-contact description trigger."""

from __future__ import annotations

import pytest

from app.services.ntm_triggers import find_measures_by_description


def _food_contact_rows(description: str, hs_code: str) -> list[dict]:
    return [
        row
        for row in find_measures_by_description(description, hs_code)
        if row.get("permit_type") == "ДС"
        and row.get("regulatory_act") == "ТР ТС 005/2011"
    ]


@pytest.mark.parametrize(
    ("description", "hs_code"),
    [
        ("Вода природная минеральная лечебно-столовая", "2201100000"),
        ("Виноград столовый свежий", "0806101000"),
        ("Соль пищевая поваренная столовая", "2501009100"),
        ("Столовая группа мебели из массива", "9403601000"),
        ("Столовые ножницы хозяйственные", "8213000000"),
        ("Столовый ножедержатель", "3924900000"),
        ("Столовая ложементная вставка", "3926909709"),
        ("Столовые приборчики декоративные", "8306290009"),
        ("Столовый нож\u0301едержатель", "3924900000"),
        ("Столовый нож\u200dедержатель", "3924900000"),
        ("Столовый нож＿едержатель", "3924900000"),
        ("Маркер\u200dстоловый нож", "3926909709"),
        ("Маркер＿столовый нож", "3926909709"),
    ],
)
def test_generic_stolov_word_does_not_prove_food_contact(
    description: str,
    hs_code: str,
) -> None:
    assert _food_contact_rows(description, hs_code) == []


@pytest.mark.parametrize(
    ("description", "expected_trigger"),
    [
        ("Набор столовых приборов из нержавеющей стали", "столовых приборов"),
        ("Столовый нож.", "столовый нож"),
        ("Столовая ложка,", "столовая ложка"),
        ("Столовой вилкой", "столовой вилкой"),
        ("Комплект столовых\u00a0ложек", "столовых\u00a0ложек"),
        ("Комплект к столовым приборам", "столовым приборам"),
        ("Комплект к столовым сервизам", "столовым сервизам"),
        ("Комплект к столовым ножам", "столовым ножам"),
        ("Столовые\u2003приборы", "столовые\u2003приборы"),
        ("Набор столовыми ножами", "столовыми ножами"),
        ("Столовым сервизом", "столовым сервизом"),
        ("Посуда керамическая", "посуда"),
        ("Маркировка: пищевой контакт", "пищевой контакт"),
    ],
)
def test_explicit_food_contact_wording_remains_supported(
    description: str,
    expected_trigger: str,
) -> None:
    rows = _food_contact_rows(description, "8215201000")
    assert len(rows) == 1
    assert rows[0]["trigger"] == expected_trigger


def test_unrelated_notification_trigger_is_unchanged() -> None:
    rows = find_measures_by_description("Ноутбук с Wi-Fi", "8471300000")
    assert any(row.get("permit_type") == "НФ" for row in rows)
