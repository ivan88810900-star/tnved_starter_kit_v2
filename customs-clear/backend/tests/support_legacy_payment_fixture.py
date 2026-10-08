"""Deterministic rows for legacy calculator integration tests.

The application seed intentionally contains broad prefixes only.  API tests that
exercise concrete 10-digit goods must not depend on a developer's pre-populated
``customs.db``.  These rows are deliberately marked as test seeds: the payment
engine must keep their automatic totals in ``REVIEW_REQUIRED`` until a typed,
immutable source binding exists.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.db import SessionLocal
from app.models.core import HsRate
from app.models.tnved import Chapter, Commodity, Section, VatPreference
from app.services.normative_bundle import is_ett_test_hs


_BACKEND = Path(__file__).resolve().parents[1]


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
        "vat_rule_basis": "Synthetic test fixture for 10% reduced-rate contract coverage",
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


def ensure_committed_vat_fixture() -> None:
    """Load the retained VAT snapshot into a disposable test database.

    This deliberately assigns test-fixture provenance instead of claiming that
    the retained snapshot is current or production-admissible.  Coverage tests
    need deterministic representative rows; payment totals must continue to
    fail closed on these rows.
    """
    payload = json.loads(
        (_BACKEND / "data" / "raw_normative" / "eec_ett_vat.json").read_text(
            encoding="utf-8"
        )
    )
    by_code: dict[str, dict] = {}
    for item in payload.get("rates", []):
        code = re.sub(r"\D", "", str(item.get("hs_code") or ""))
        if len(code) == 10 and not is_ett_test_hs(code):
            by_code[code] = item

    with SessionLocal() as db:
        existing = {
            code
            for (code,) in db.query(HsRate.hs_code)
            .filter(HsRate.hs_code.in_(list(by_code)))
            .all()
        }
        rows = []
        for code, item in by_code.items():
            if code in existing:
                continue
            raw_rate = item.get("vat_import_rate")
            rows.append(
                HsRate(
                    hs_code=code,
                    hs_prefix=code,
                    duty_rate="0",
                    vat_import_rate=22.0 if raw_rate is None else float(raw_rate),
                    vat_rule=str(item.get("vat_rule") or "none"),
                    vat_rule_basis=str(item.get("vat_rule_basis") or ""),
                    source_url="fixture://committed-vat-snapshot",
                    source_revision="test-fixture:committed-vat-snapshot",
                )
            )
        db.bulk_save_objects(rows)

        preference_payload = json.loads(
            (_BACKEND / "data" / "vat_preferences_pp908_expansion.json").read_text(
                encoding="utf-8"
            )
        )
        for item in preference_payload.get("items", []):
            prefix = re.sub(r"\D", "", str(item.get("hs_code_prefix") or ""))[:10]
            rate = int(item.get("vat_rate") or 0)
            decree = str(item.get("decree_info") or "")
            if not prefix or rate not in {10, 22}:
                continue
            exists = (
                db.query(VatPreference)
                .filter(
                    VatPreference.hs_code_prefix == prefix,
                    VatPreference.vat_rate == rate,
                    VatPreference.decree_info == decree,
                )
                .first()
            )
            if exists is None:
                db.add(
                    VatPreference(
                        hs_code_prefix=prefix,
                        vat_rate=rate,
                        decree_info=decree,
                        comment=str(item.get("comment") or ""),
                    )
                )
        db.commit()


def ensure_specific_duty_fixture() -> None:
    """Create the minimum relational fixture for the EUR/kg backfill test."""
    code = "6303929000"
    with SessionLocal() as db:
        chapter = db.query(Chapter).filter(Chapter.code == "63").first()
        if chapter is None:
            section = db.query(Section).first()
            if section is None:
                section = Section(roman_number="XI", title="Test fixture")
                db.add(section)
                db.flush()
            chapter = Chapter(section_id=section.id, code="63", title="Test fixture")
            db.add(chapter)
            db.flush()
        if db.query(Commodity).filter(Commodity.code == code).first() is None:
            db.add(
                Commodity(
                    chapter_id=chapter.id,
                    code=code,
                    description="Synthetic curtain fixture",
                    unit="kg",
                    import_duty="0.61 EUR за 1 кг",
                )
            )
        rate = db.query(HsRate).filter(HsRate.hs_code == code).first()
        if rate is None:
            db.add(
                HsRate(
                    hs_code=code,
                    hs_prefix=code,
                    duty_rate="0.61 EUR за 1 кг",
                    vat_import_rate=22.0,
                    source_url="fixture://specific-duty-backfill",
                    source_revision="test-fixture:specific-duty-backfill",
                )
            )
        else:
            rate.duty_rate = "0.61 EUR за 1 кг"
        db.commit()
