#!/usr/bin/env python3
"""Restore hash-pinned retained capture objects without extracting TAR paths."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.ett_artifacts import LocalArtifactStore

MAX_COMPRESSED = 512 * 1024 * 1024
MAX_EXPANDED = 1024 * 1024 * 1024
MAX_OBJECT = 64 * 1024 * 1024
MAX_MEMBERS = 1000
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def restore_capture(archive: Path, expected_sha256: str, store: LocalArtifactStore) -> dict:
    if type(expected_sha256) is not str or not _SHA.fullmatch(expected_sha256):
        raise ValueError("invalid pinned archive digest")
    descriptor = os.open(archive, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_COMPRESSED:
            raise ValueError("invalid retained archive size or type")
        digest = hashlib.sha256()
        read = 0
        while chunk := source.read(1024 * 1024):
            read += len(chunk)
            if read > MAX_COMPRESSED:
                raise ValueError("retained archive exceeds its size bound")
            digest.update(chunk)
        if read != before.st_size or digest.hexdigest() != expected_sha256:
            raise ValueError("retained archive digest mismatch")
        source.seek(0)
        members, objects, expanded = 0, 0, 0
        seen = set()
        with tarfile.open(fileobj=source, mode="r|gz") as bundle:
            for item in bundle:
                members += 1
                if members > MAX_MEMBERS:
                    raise ValueError("retained archive has too many members")
                if item.isdir() and item.name in {"store", "store/"}:
                    continue
                match = re.fullmatch(r"store/([0-9a-f]{64})\.blob", item.name)
                if (not item.isfile() or item.issparse() or match is None
                        or not 0 < item.size <= MAX_OBJECT or item.name in seen):
                    raise ValueError("retained archive contains an invalid object")
                seen.add(item.name)
                expanded += item.size
                if expanded > MAX_EXPANDED:
                    raise ValueError("retained archive expansion limit")
                stream = bundle.extractfile(item)
                if stream is None:
                    raise ValueError("retained object body unavailable")
                data = stream.read(MAX_OBJECT + 1)
                if len(data) != item.size or hashlib.sha256(data).hexdigest() != match[1]:
                    raise ValueError("retained object digest mismatch")
                if store.put(data) != match[1]:
                    raise ValueError("restored object digest mismatch")
                objects += 1
        after = os.fstat(source.fileno())
        if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise ValueError("retained archive changed during restore")
    if not objects:
        raise ValueError("retained archive contains no objects")
    return {"kind": "ett_capture_objects_restored", "archive_sha256": expected_sha256,
            "restored_objects": objects, "restored_bytes": expanded,
            "legal_inventory_complete": False, "production_ready": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--store-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = restore_capture(args.archive, args.archive_sha256, LocalArtifactStore(args.store_root))
    except Exception:
        print(json.dumps({"status": "restore_failed", "production_ready": False}))
        return 2
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
