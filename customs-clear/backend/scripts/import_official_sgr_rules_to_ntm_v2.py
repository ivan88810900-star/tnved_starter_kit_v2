#!/usr/bin/env python3
"""Импорт official SGR rules (seed JSON) в NTM v2."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.ntm_v2_official_sgr_import import (  # noqa: E402
    DEFAULT_SEED_PATH,
    import_official_sgr_rules_to_ntm_v2,
    load_official_sgr_payload,
)


def main() -> None:
    path = DEFAULT_SEED_PATH
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
    payload = load_official_sgr_payload(path)
    report = import_official_sgr_rules_to_ntm_v2(payload)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
