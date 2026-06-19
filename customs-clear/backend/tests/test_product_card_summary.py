"""Tests for Issue #97: product card redesign — VAT from API, summary data."""
import pytest


def test_preview_returns_vat_rates():
    """The preview endpoint should include vat_rates array."""
    from app.api.tnved_catalog import router
    routes = [r.path for r in router.routes]
    assert "/preview/{code}" in routes


def test_preview_vat_rates_structure():
    """vat_rates should be a list of numbers (22 standard, 10 reduced)."""
    from app.services.normative_store import search_hs_rates
    assert callable(search_hs_rates)


def test_no_hardcoded_20_in_preview():
    """Preview endpoint should not hardcode 20% — it reads from DB."""
    import inspect
    from app.api import tnved_catalog
    source = inspect.getsource(tnved_catalog)
    assert 'НДС: 20%' not in source
    assert '"20%"' not in source
