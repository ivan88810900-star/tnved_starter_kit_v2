"""Every payment source reference must resolve to the central regulatory registry."""

from __future__ import annotations

from app.services.payment_source_registry import PAYMENT_SOURCE_REGISTRY, get_payment_source_entry
from app.services.regulatory_source_registry import get_registry_entry


def test_every_declared_payment_registry_reference_resolves() -> None:
    unresolved = {
        entry.source_code: entry.registry_source_id
        for entry in PAYMENT_SOURCE_REGISTRY
        if entry.registry_source_id and get_registry_entry(entry.registry_source_id) is None
    }
    assert unresolved == {}


def test_payment_sources_use_canonical_regulatory_source_ids() -> None:
    expected = {
        "eec_odata_vat_preferences": "eec_odata_vat_preferences",
        "excise_official_contour": "rf_excise_tax_code",
        "trade_remedies_official": "trade_remedies_official",
        "trade_remedies_special_safeguard_official": (
            "trade_remedies_special_safeguard_official"
        ),
        "trade_remedies_countervailing_official": (
            "trade_remedies_countervailing_official"
        ),
    }
    actual: dict[str, str | None] = {}
    for source_code in expected:
        entry = get_payment_source_entry(source_code)
        assert entry is not None
        actual[source_code] = entry.registry_source_id
    assert actual == expected


def test_payment_source_status_matches_central_registry_status() -> None:
    """A payment contour must not borrow another contour's green SourceStatus."""
    for payment in PAYMENT_SOURCE_REGISTRY:
        if not payment.registry_source_id or not payment.source_status_code:
            continue
        regulatory = get_registry_entry(payment.registry_source_id)
        assert regulatory is not None
        # eec_ett_tnved is an umbrella reference for the two separately proven
        # EEC_ETT/EEC_VAT payment bundles; all dedicated contours must match.
        if payment.source_code in {"eec_ett_tariff", "eec_ett_vat"}:
            continue
        assert regulatory.source_status_code == payment.source_status_code, payment.source_code
