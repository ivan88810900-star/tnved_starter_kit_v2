#!/usr/bin/env python3
"""Валидация и отчёт качества official SGR seed (curated dataset)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.ntm_v2_official_sgr_dataset_report import (  # noqa: E402
    build_official_sgr_dataset_report_from_seed,
)


def main() -> None:
    run_sanity = "--no-sanity" not in sys.argv
    report = build_official_sgr_dataset_report_from_seed(run_sanity=run_sanity)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report.get("validation", {}).get("valid"):
        sys.exit(1)
    if run_sanity and not report.get("sanity_passed"):
        sys.exit(2)


if __name__ == "__main__":
    main()
