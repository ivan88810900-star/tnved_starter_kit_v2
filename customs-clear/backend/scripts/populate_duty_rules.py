from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal
from app.services.duty_rules_backfill import backfill_duty_rules_from_hs_rates


def main() -> None:
    with SessionLocal() as db:
        stats = backfill_duty_rules_from_hs_rates(db, only_missing=True)
        db.commit()
    print(
        "populate_duty_rules: "
        f"hs_rates backfill created={stats['created']}, "
        f"updated={stats['updated']}, skipped={stats['skipped']}"
    )


if __name__ == "__main__":
    main()
