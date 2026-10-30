#!/usr/bin/env python3
"""Generate, but never execute, a validated offline ETT staging plan."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.staging_ett_offline_plan import (  # noqa: E402
    PACKAGE_SCHEMA,
    EttOfflinePlanError,
    write_offline_artifacts,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--print-package-schema", action="store_true")
    args = parser.parse_args(argv)
    if args.print_package_schema:
        if args.package is not None or args.output_dir is not None:
            parser.error("--print-package-schema accepts no package or output")
        print(json.dumps(PACKAGE_SCHEMA, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    if args.package is None or args.output_dir is None:
        parser.error("--package and --output-dir are required")
    try:
        plan = write_offline_artifacts(args.package, args.output_dir)
    except EttOfflinePlanError as exc:
        print(f"ETT offline plan rejected: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "plan_sha256": plan["plan_sha256"],
                "normalization_digest": plan["normalization_digest"],
                "expected_counts": plan["expected_counts"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

