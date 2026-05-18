from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from app.db import SessionLocal  # noqa: E402
from app.models.tnved import Commodity, NonTariffMeasure  # noqa: E402


def import_raw() -> None:
    path = _ROOT / "downloads" / "raw_extracted.json"
    with path.open(encoding="utf-8") as f:
        data = json.load(f)

    with SessionLocal() as db:
        added = 0
        for item in data:
            hs_code = (item.get("hs_code") or "").strip()
            mtype = (item.get("measure_type") or "").strip()
            desc = (item.get("description") or "").strip()
            doc = (item.get("document_required") or "").strip()
            act = (item.get("regulatory_act") or "").strip()

            if not hs_code or not mtype:
                continue

            commodity_exists = (
                db.query(Commodity.code).filter(Commodity.code == hs_code).first() is not None
            )
            if not commodity_exists:
                continue

            exists = (
                db.query(NonTariffMeasure)
                .filter(
                    NonTariffMeasure.commodity_code == hs_code,
                    NonTariffMeasure.measure_type == mtype,
                    NonTariffMeasure.description == desc,
                )
                .first()
            )
            if exists:
                continue

            db.add(
                NonTariffMeasure(
                    commodity_code=hs_code,
                    measure_type=mtype,
                    description=desc,
                    document_required=doc,
                    regulatory_act=act,
                )
            )
            added += 1

        db.commit()
        print(f"Добавлено: {added}")


if __name__ == "__main__":
    import_raw()
