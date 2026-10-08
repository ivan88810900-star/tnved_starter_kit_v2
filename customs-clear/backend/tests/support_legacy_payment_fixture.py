"""Deterministic rows for legacy calculator integration tests.

The application seed intentionally contains broad prefixes only.  API tests that
exercise concrete 10-digit goods must not depend on a developer's pre-populated
``customs.db``.  These rows are deliberately marked as test seeds: the payment
engine must keep their automatic totals in ``REVIEW_REQUIRED`` until a typed,
immutable source binding exists.
"""

from __future__ import annotations

from app.db import SessionLocal
from app.models.core import HsRate


_EXACT_RATES = (
    {
        "hs_code": "8509400000",
        "duty_rate": "8",
        "vat_import_rate": 22.0,
    },
    {
        "hs_code": "8516108008",
        "duty_rate": "8",
        "vat_import_rate": 22.0,
    },
    {
        "hs_code": "0201300000",
        "duty_rate": "15",
        "vat_import_rate": 10.0,
        "vat_rule": "reduced10",
        "vat_rule_basis": "Synthetic test fixture for reduced-rate contract coverage",
    },
    {
        "hs_code": "7214990000",
        "duty_rate": "10",
        "vat_import_rate": 22.0,
        "has_antidumping": True,
        "antidumping_type": "percent",
        "antidumping_value": 18.0,
        "antidumping_condition": "Synthetic test fixture requiring manual review",
        "antidumping_countries": "CN,UA",
    },
    {
        "hs_code": "8703231910",
        "duty_rate": "15",
        "vat_import_rate": 22.0,
    },
    {
        "hs_code": "8703231100",
        "duty_rate": "15",
        "vat_import_rate": 22.0,
    },
    {
        "hs_code": "8471300000",
        "duty_rate": "0",
        "vat_import_rate": 22.0,
    },
    {
        "hs_code": "8517110000",
        "duty_rate": "0",
        "vat_import_rate": 22.0,
    },
)


def ensure_legacy_payment_fixture() -> None:
    """Insert the exact-code rows used by API tests, without upgrading trust."""
    with SessionLocal() as db:
        existing = {
            code
            for (code,) in db.query(HsRate.hs_code)
            .filter(HsRate.hs_code.in_([row["hs_code"] for row in _EXACT_RATES]))
            .all()
        }
        for item in _EXACT_RATES:
            if item["hs_code"] in existing:
                continue
            db.add(
                HsRate(
                    hs_code=item["hs_code"],
                    hs_prefix=item["hs_code"],
                    duty_rate=item["duty_rate"],
                    vat_import_rate=item["vat_import_rate"],
                    vat_rule=item.get("vat_rule", "none"),
                    vat_rule_basis=item.get("vat_rule_basis", ""),
                    excise_type="none",
                    excise_value=0.0,
                    has_antidumping=item.get("has_antidumping", False),
                    antidumping_type=item.get("antidumping_type", "none"),
                    antidumping_value=item.get("antidumping_value", 0.0),
                    antidumping_condition=item.get("antidumping_condition", ""),
                    antidumping_countries=item.get("antidumping_countries", ""),
                    valid_from="2020-01-01",
                    valid_to="2099-12-31",
                    source_url="fixture://legacy-payment-tests",
                    source_revision="seed-test-fixture",
                )
            )
        db.commit()
