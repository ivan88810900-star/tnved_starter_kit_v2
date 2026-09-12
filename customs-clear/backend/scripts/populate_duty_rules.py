#!/usr/bin/env python3
"""Blocked legacy maintenance entry point.

DB-derived hs_rates require reviewed originals before structured duty-rule admission.
The former application writer is retired; no database, download or deletion is
performed. There is no configuration switch that grants legal admission.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.official_payment_admission import blocked_payment_import


def main() -> dict:
    result = blocked_payment_import(source="populate_duty_rules", domain="import_duty")
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    main()
    raise SystemExit(2)
