#!/usr/bin/env python3
"""
Синхронизация предварительных решений ФТС (FCS) — MVP на fixture.

Официальный контур: предварительные решения по классификации на customs.gov.ru.
В этом MVP используется детерминированный fixture; scheduled sync может подключить
официальный фид/API без смены broker/enforcement.

Запуск из ``customs-clear/backend``::

  PYTHONPATH=. python3 scripts/sync_fcs_predecisions.py
  PYTHONPATH=. python3 scripts/sync_fcs_predecisions.py --dry-run
  PYTHONPATH=. python3 scripts/sync_fcs_predecisions.py --fixture data/fixtures/fcs_preliminary_decisions.sample.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from app.services.fcs_preliminary_sync import (  # noqa: E402
    DEFAULT_FIXTURE_PATH,
    sync_fcs_preliminary_decisions,
)
from app.services.normative_store import init_db  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Импорт предварительных решений ФТС (FCS) из fixture → classification_decisions",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_FIXTURE_PATH,
        help=f"Путь к JSON-fixture (по умолчанию {DEFAULT_FIXTURE_PATH.name})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только парсинг и отчёт, без записи в БД и source_status",
    )
    args = parser.parse_args()

    init_db()
    result = sync_fcs_preliminary_decisions(fixture_path=args.fixture, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "OK":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
