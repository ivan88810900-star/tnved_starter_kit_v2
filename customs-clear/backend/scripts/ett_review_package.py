#!/usr/bin/env python3
"""Build or replay an offline ETT review dossier; never approve or promote rates."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ett_artifacts import LocalArtifactStore
from app.services.ett_manifest import MAX_MANIFEST_BYTES
from app.services.ett_review_package import (
    MAX_PACKAGE_BYTES, ReviewPackageError, build_review_package, verify_review_package,
)


def _read(path: Path, maximum: int) -> bytes:
    # The CLI's own input reads precede the service deadline. A FIFO/device
    # must therefore fail before it can block on open or unbounded I/O.
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= maximum:
            raise ReviewPackageError("input_file_type_or_size_limit")
        with os.fdopen(descriptor, "rb") as source:
            descriptor = None
            raw = source.read(maximum + 1)
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not 0 < len(raw) <= maximum:
        raise ReviewPackageError("input_size_limit")
    return raw


def _publish_exclusive(path: Path, raw: bytes) -> None:
    """Publish complete bytes without replacing an existing file or symlink."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", prefix=".ett-review-", dir=path.parent, delete=False) as target:
            temporary = Path(target.name)
            target.write(raw)
            target.flush()
            os.fsync(target.fileno())
        os.link(temporary, path, follow_symlinks=False)
    finally:
        if temporary is not None:
            temporary.unlink()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="Recompute every check from retained source objects")
    build.add_argument("manifest", type=Path)
    build.add_argument("--acquisition-receipt-sha256", required=True)
    build.add_argument("--supplemental-capture-report-sha256")
    prior = build.add_mutually_exclusive_group(required=True)
    prior.add_argument("--initial", action="store_true", help="Explicitly declare that no prior manifest exists")
    prior.add_argument("--prior-manifest", type=Path)
    build.add_argument("--assumption", action="append", default=[], help="Unverified text for review; may be repeated")
    build.add_argument("--output", required=True, type=Path, help="New canonical package file; existing paths are never replaced")
    verify = commands.add_parser("verify", help="Rebuild a canonical package and compare every byte")
    verify.add_argument("package", type=Path)
    for command in (build, verify):
        command.add_argument("--store-root", required=True, type=Path, help="Existing source object store, opened read-only")
    args = parser.parse_args(argv)
    try:
        store = LocalArtifactStore(args.store_root, create=False)
        if args.command == "build":
            if os.path.lexists(args.output):
                raise ReviewPackageError("output_already_exists")
            package = build_review_package(
                _read(args.manifest, MAX_MANIFEST_BYTES), store,
                acquisition_receipt_sha256=args.acquisition_receipt_sha256,
                supplemental_capture_report_sha256=args.supplemental_capture_report_sha256,
                prior_manifest=_read(args.prior_manifest, MAX_MANIFEST_BYTES) if args.prior_manifest else None,
                assumptions=tuple(args.assumption),
            )
        else:
            package = verify_review_package(_read(args.package, MAX_PACKAGE_BYTES), store)
        report = package.as_dict()
        if not report["assembly_ready"]:
            raise ReviewPackageError("review_package_assembly_not_ready")
        if args.command == "build":
            _publish_exclusive(args.output, package.canonical_bytes)
        print(json.dumps({"status": "review_package_built" if args.command == "build" else "review_package_verified",
                          "package_sha256": package.sha256,
                          "candidate_manifest_sha256": report["candidate"]["manifest_sha256"],
                          "package_size_bytes": len(package.canonical_bytes),
                          "assembly_ready": True, "source_complete": False, "legal_ready": False,
                          "retention_attested": False, "production_ready": False, "can_promote": False}, sort_keys=True))
        return 0
    except Exception:
        # Do not emit local paths, object contents, source text or tracebacks.
        print(json.dumps({"status": "ERROR", "reason": "review_package_input_assembly_or_replay_failed",
                          "production_ready": False, "can_promote": False}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
