#!/usr/bin/env python3
"""Матрица official SGR → advisory vs legacy (флаг ``NTM_V2_OFFICIAL_SGR_ADVISORY_ENABLED``)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.ntm_v2_official_sgr_advisory_diagnostics import (  # noqa: E402
    run_official_sgr_advisory_matrix_sync,
)


def main() -> None:
    enabled = "--off" not in sys.argv
    report = run_official_sgr_advisory_matrix_sync(official_advisory_enabled=enabled)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
