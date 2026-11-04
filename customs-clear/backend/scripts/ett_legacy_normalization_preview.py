#!/usr/bin/env python3
"""Build a deterministic JSON preview from exact legacy ETT evidence."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.staging_ett_legacy_normalization_preview import (  # noqa: E402
    EttLegacyPreviewError,
    build_legacy_normalization_preview,
)
from app.services.staging_ett_normalization_core import canonical_json  # noqa: E402


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def _read_envelope(path: Path) -> dict[str, Any]:
    decoded = path.read_bytes().decode("utf-8", errors="strict")
    value = json.loads(
        decoded,
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
    )
    if not isinstance(value, dict):
        raise ValueError("recovery envelope must be a JSON object")
    return value


def _write_new_file(path: Path, content: bytes) -> None:
    parent = path.parent
    if not parent.is_dir():
        raise FileNotFoundError(f"output parent directory does not exist: {parent}")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recovery-envelope", type=Path, required=True)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--source-text", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        envelope = _read_envelope(args.recovery_envelope)
        preview = build_legacy_normalization_preview(
            envelope,
            original_bytes=args.original.read_bytes(),
            source_text_bytes=args.source_text.read_bytes(),
        )
        _write_new_file(
            args.output,
            (canonical_json(preview) + "\n").encode("utf-8"),
        )
    except (EttLegacyPreviewError, OSError, UnicodeError, ValueError) as exc:
        print(f"ETT legacy preview rejected: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "output": str(args.output),
                "preview_sha256": preview["preview_sha256"],
                "counts": preview["counts"],
                "legal_status": preview["legal_status"],
                "verified": preview["verified"],
                "admitted": preview["admitted"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
