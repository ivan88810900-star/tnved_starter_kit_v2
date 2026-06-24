"""Backfill hs_duty_rules из текстовых ставок hs_rates."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models.core import HsRate
from ..models.tnved import Commodity, HsDutyRule
from .duty_parser import DutyParser


def backfill_duty_rules_from_hs_rates(db: Session, *, only_missing: bool = True) -> dict[str, int]:
    """Создаёт/обновляет hs_duty_rules по hs_rates.duty_rate через DutyParser."""
    existing = {r.commodity_code: r for r in db.query(HsDutyRule).all()}
    valid_codes = {code for (code,) in db.query(Commodity.code)}
    pending: set[str] = set()
    created = updated = skipped = 0

    for rate in db.query(HsRate).all():
        parsed = DutyParser.parse(rate.duty_rate or "")
        if parsed is None:
            skipped += 1
            continue

        if rate.hs_code not in valid_codes:
            skipped += 1
            continue

        if rate.hs_code in existing or rate.hs_code in pending:
            if only_missing:
                skipped += 1
                continue
            row = existing[rate.hs_code]
        else:
            row = None

        if row is None:
            db.add(
                HsDutyRule(
                    commodity_code=rate.hs_code,
                    type=parsed.type,
                    ad_valorem_pct=parsed.ad_valorem_pct,
                    specific_amount=parsed.specific_amount,
                    specific_currency=parsed.specific_currency,
                    specific_uom=parsed.specific_uom,
                )
            )
            pending.add(rate.hs_code)
            created += 1
            continue

        row.type = parsed.type
        row.ad_valorem_pct = parsed.ad_valorem_pct
        row.specific_amount = parsed.specific_amount
        row.specific_currency = parsed.specific_currency
        row.specific_uom = parsed.specific_uom
        updated += 1

    return {"created": created, "updated": updated, "skipped": skipped}
