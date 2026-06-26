"""Unit- и контрактные тесты для ``app.services.hs_matching`` и потребителей."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.hs_matching import (
    get_hs_prefixes,
    match_hs_prefix,
    normalize_hs_code,
    specificity,
)


class TestNormalizeHsCode:
    def test_strips_non_digits(self) -> None:
        assert normalize_hs_code("85.17.62.00.00") == "8517620000"

    def test_spaces(self) -> None:
        assert normalize_hs_code("8517 6200 00") == "8517620000"

    def test_max_ten_digits(self) -> None:
        assert normalize_hs_code("85176200001234") == "8517620000"

    def test_empty(self) -> None:
        assert normalize_hs_code("") == ""
        assert normalize_hs_code("   ") == ""
        assert normalize_hs_code(None) == ""

    def test_no_side_effect_on_clean(self) -> None:
        assert normalize_hs_code("8517620000") == "8517620000"


class TestGetHsPrefixes:
    def test_ten_digit_example(self) -> None:
        assert get_hs_prefixes("8517620000") == [
            "8517620000",
            "85176200",
            "851762",
            "8517",
            "85",
        ]

    def test_custom_levels(self) -> None:
        assert get_hs_prefixes("8517620000", levels=(10, 8, 6, 4)) == [
            "8517620000",
            "85176200",
            "851762",
            "8517",
        ]

    def test_short_code(self) -> None:
        assert get_hs_prefixes("8517") == ["8517", "85"]


class TestMatchHsPrefix:
    def test_examples(self) -> None:
        assert match_hs_prefix("8517620000", "8517") is True
        assert match_hs_prefix("8517620000", "851762") is True
        assert match_hs_prefix("8517620000", "85") is True
        assert match_hs_prefix("8517620000", "8518") is False

    def test_spaced_code_same_as_plain(self) -> None:
        assert match_hs_prefix("85 17 62 00 00", "8517") is True
        assert match_hs_prefix("8517620000", "85 17") is True

    def test_empty_prefix_false(self) -> None:
        assert match_hs_prefix("8517", "") is False


class TestSpecificity:
    def test_lengths(self) -> None:
        assert specificity("8517") == 4
        assert specificity("85.17") == 4
        assert specificity("") == 0


class TestTrTsCatalogConsistency:
    def test_get_tr_ts_requirements_spaced_vs_plain(self) -> None:
        from app.services.tr_ts_catalog import get_tr_ts_requirements

        plain = "8517620000"
        spaced = "85 17 62 00 00"
        assert get_tr_ts_requirements(plain) == get_tr_ts_requirements(spaced)


class _FakeQueryChain:
    """Минимальная цепочка query().filter()…order_by().all() / join()…"""

    def join(self, *args: object, **kwargs: object) -> _FakeQueryChain:
        return self

    def filter(self, *args: object, **kwargs: object) -> _FakeQueryChain:
        return self

    def order_by(self, *args: object, **kwargs: object) -> _FakeQueryChain:
        return self

    def limit(self, *args: object, **kwargs: object) -> _FakeQueryChain:
        return self

    def all(self) -> list[object]:
        return []


class TestConsumersDoNotBreak:
    """Smoke: функции вызываются с «грязным» кодом и не падают."""

    def test_find_non_tariff_rules_empty(self) -> None:
        from app.services.normative_store import find_non_tariff_rules_for_hs

        assert find_non_tariff_rules_for_hs("") == []
        assert find_non_tariff_rules_for_hs("  ab  ") == []

    @patch("app.services.non_tariff_rules.SessionLocal")
    def test_find_measures_for_code_mock_db(self, mock_session: MagicMock) -> None:
        from app.services import non_tariff_rules

        fake_db = MagicMock()
        fake_db.query = lambda *_a, **_k: _FakeQueryChain()
        mock_session.return_value.__enter__.return_value = fake_db
        mock_session.return_value.__exit__.return_value = None

        assert non_tariff_rules.find_measures_for_code("85 17 62 00 00") == []

    @patch("app.services.regulatory_layer.SessionLocal")
    def test_get_regulatory_documents_mock_db(self, mock_session: MagicMock) -> None:
        from app.services import regulatory_layer

        fake_db = MagicMock()
        fake_db.query = lambda *_a, **_k: _FakeQueryChain()
        mock_session.return_value.__enter__.return_value = fake_db
        mock_session.return_value.__exit__.return_value = None

        assert regulatory_layer.get_regulatory_documents_for_hs("85 17 62 00 00") == []
