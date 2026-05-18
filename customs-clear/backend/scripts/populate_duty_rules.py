from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal
from app.models.tnved import Commodity, HsDutyRule
from app.services.duty_parser import DutyParser


def main() -> None:
    created = 0
    updated = 0
    skipped = 0

    with SessionLocal() as db:
        commodities = db.query(Commodity).all()
        existing = {r.commodity_code: r for r in db.query(HsDutyRule).all()}

        for c in commodities:
            parsed = DutyParser.parse(c.import_duty or "")
            if parsed is None:
                skipped += 1
                continue

            row = existing.get(c.code)
            if row is None:
                db.add(
                    HsDutyRule(
                        commodity_code=c.code,
                        type=parsed.type,
                        ad_valorem_pct=parsed.ad_valorem_pct,
                        specific_amount=parsed.specific_amount,
                        specific_currency=parsed.specific_currency,
                        specific_uom=parsed.specific_uom,
                    ),
                )
                created += 1
            else:
                row.type = parsed.type
                row.ad_valorem_pct = parsed.ad_valorem_pct
                row.specific_amount = parsed.specific_amount
                row.specific_currency = parsed.specific_currency
                row.specific_uom = parsed.specific_uom
                updated += 1

        db.commit()

    print(f"populate_duty_rules: created={created}, updated={updated}, skipped={skipped}")


if __name__ == "__main__":
    main()
