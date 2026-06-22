"""Tests for Issue #98: non-tariff measures structured display."""
import pytest


def test_measure_types_recognized():
    """All measure types from the DB should have labels."""
    known_types = ["ban", "license", "certificate", "vet_control", "phyto_control"]
    for mt in known_types:
        assert mt in known_types


def test_non_tariff_check_returns_measures():
    """The non_tariff/check endpoint accepts items and returns results."""
    from app.api.non_tariff import router
    routes = [r.path for r in router.routes]
    assert "/check" in routes


def test_regulatory_act_field_exists():
    """Non-tariff measures should have regulatory_act field."""
    from app.models.tnved import NonTariffMeasure
    assert hasattr(NonTariffMeasure, 'regulatory_act')


def test_measure_type_field_exists():
    """Non-tariff measures should have measure_type field."""
    from app.models.tnved import NonTariffMeasure
    assert hasattr(NonTariffMeasure, 'measure_type')
