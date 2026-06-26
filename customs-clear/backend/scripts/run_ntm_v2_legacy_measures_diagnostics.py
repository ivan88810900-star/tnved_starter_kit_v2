#!/usr/bin/env python3
"""Диагностика imported legacy non_tariff_measures (без enforcement)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import inspect  # noqa: E402

from app.db import engine  # noqa: E402
from app.services.ntm_v2_legacy_measures_diagnostics import (  # noqa: E402
    run_full_legacy_measures_diagnostics_report,
)


def main() -> None:
    insp = inspect(engine)
    if not insp.has_table("ntm_measures_v2"):
        print(json.dumps({"error": "ntm_measures_v2 table missing — run alembic migration first"}, indent=2))
        sys.exit(1)

    report = asyncio.run(run_full_legacy_measures_diagnostics_report())
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
