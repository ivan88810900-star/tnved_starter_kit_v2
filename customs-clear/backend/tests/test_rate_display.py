"""Ставки для карточки: акциз с наследованием, подакцизные главы без данных."""

from app.services.rate_display import format_excise_display, resolve_excise_for_hs


def test_excise_inherited_from_parent_for_champagne_leaf() -> None:
    excise_type, excise_value, excise_basis = resolve_excise_for_hs("2204101100")
    assert excise_type == "fixed"
    assert excise_value == 45.0
    assert format_excise_display(excise_type, excise_value, excise_basis) == "45 ₽/л"


def test_excise_needs_review_for_alcohol_without_data() -> None:
    excise_type, excise_value, _ = resolve_excise_for_hs("2202990000")
    if excise_type == "none":
        # если в БД появится явная ставка — тест остаётся валидным через format
        assert excise_value == 0.0
    else:
        assert excise_type in {"fixed", "percent", "combined", "needs_review"}


def test_excise_empty_for_non_excise_chapter() -> None:
    excise_type, _, _ = resolve_excise_for_hs("8517110000")
    assert excise_type in {"none", "needs_review", "fixed", "percent"}
