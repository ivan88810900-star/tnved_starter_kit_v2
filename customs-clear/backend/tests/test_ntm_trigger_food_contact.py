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
        ("Столовый нож с деревянной ручкой", "столовый нож"),
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
