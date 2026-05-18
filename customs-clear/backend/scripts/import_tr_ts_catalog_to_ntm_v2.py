#!/usr/bin/env python3
"""Импорт ``tr_ts_catalog.ALL_REGULATIONS`` в NTM v2 (миграция должна быть применена)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Запуск из корня backend: python scripts/import_tr_ts_catalog_to_ntm_v2.py
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.ntm_v2_import import import_ntm_layers_to_ntm_v2, import_tr_ts_catalog_to_ntm_v2  # noqa: E402
from app.services.ntm_v2_legacy_measures_import import import_legacy_non_tariff_measures_to_ntm_v2  # noqa: E402
from app.services.ntm_v2_legacy_rules_import import import_legacy_non_tariff_rules_to_ntm_v2  # noqa: E402


def main() -> None:
    report_tr = import_tr_ts_catalog_to_ntm_v2()
    report_layers = import_ntm_layers_to_ntm_v2()
    report_rules = import_legacy_non_tariff_rules_to_ntm_v2()
    report_measures = import_legacy_non_tariff_measures_to_ntm_v2()
    print(
        json.dumps(
            {
                "tr_ts_catalog": report_tr,
                "ntm_layers": report_layers,
                "non_tariff_rules": report_rules,
                "non_tariff_measures": report_measures,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
