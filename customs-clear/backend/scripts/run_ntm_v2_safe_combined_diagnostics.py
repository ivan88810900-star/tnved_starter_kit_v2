#!/usr/bin/env python3
"""Combined legacy vs safe v2 NTM runtime (все четыре flags ON в safe-режиме)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.ntm_v2_combined_runtime_diagnostics import (  # noqa: E402
    build_safe_v2_matrix_cases,
    run_safe_v2_combined_impact_matrix,
)


async def _main() -> dict:
    cases = build_safe_v2_matrix_cases()
    return await run_safe_v2_combined_impact_matrix(cases)


def main() -> None:
    report = asyncio.run(_main())
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
