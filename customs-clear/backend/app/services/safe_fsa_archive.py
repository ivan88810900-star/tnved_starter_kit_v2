"""Fail-closed extraction of untrusted public FSA 7z snapshots."""

from __future__ import annotations

import os
import re
import stat
import unicodedata
from pathlib import Path

import py7zr

MAX_ARCHIVE_BYTES = 4 * 1024**3
MAX_EXPANDED_BYTES = 8 * 1024**3
MAX_MEMBER_BYTES = 4 * 1024**3
MAX_MEMBERS = 2048
MAX_CSV_FILES = 256


def _safe_name(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise RuntimeError("FSA archive has an invalid member name")
    parts = value.split("/")
    if len(parts) > 16 or any(
        not part or part in {".", ".."} or part[-1:] in {" ", "."}
        or any(ch in part for ch in "\\:\x00")
        or any(unicodedata.category(ch).startswith("C") for ch in part)
        or re.fullmatch(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part, re.I)
        for part in parts
    ):
        raise RuntimeError("FSA archive has an unsafe member path")
    normalized = unicodedata.normalize("NFKC", value)
    if normalized != value:
        # Avoid aliases of separators, dot segments and platform-dependent names.
        raise RuntimeError("FSA archive has a noncanonical Unicode member path")
    return value


def _validated_members(archive) -> dict[str, int]:
    if archive.needs_password():
        raise RuntimeError("FSA archive must not be encrypted")
    if len(archive.files) > MAX_MEMBERS:
        raise RuntimeError("FSA archive has too many members")
    names: dict[str, tuple[str, bool]] = {}
    csv_sizes: dict[str, int] = {}
    total = 0
    for member in archive.files:
        name = _safe_name(member.filename)
        key = name.casefold()
        if key in names:
            raise RuntimeError("FSA archive has colliding member paths")
        is_dir, is_file = member.is_directory, member.is_file
        if (type(is_dir) is not bool or type(is_file) is not bool or is_dir == is_file
                or member.is_symlink or member.is_junction or member.is_socket
                or member.st_fmt not in {None, stat.S_IFDIR if is_dir else stat.S_IFREG}):
            raise RuntimeError("FSA archive contains a non-regular member")
        size = member.uncompressed
        if type(size) is not int or size < 0 or size > MAX_MEMBER_BYTES or (is_dir and size):
            raise RuntimeError("FSA archive has an invalid member size")
        total += size
        # Count all members, including unselected predecessors in a solid block.
        if total > MAX_EXPANDED_BYTES:
            raise RuntimeError("FSA archive exceeds the expanded size limit")
        names[key] = (name, is_dir)
        if is_file and name.casefold().endswith(".csv"):
            if size == 0:
                raise RuntimeError("FSA archive contains an empty CSV")
            csv_sizes[name] = size
    for key in names:
        parts = key.split("/")
        for index in range(1, len(parts)):
            parent = "/".join(parts[:index])
            if parent in names and not names[parent][1]:
                raise RuntimeError("FSA archive has a file/directory path conflict")
    if not csv_sizes or len(csv_sizes) > MAX_CSV_FILES:
        raise RuntimeError("FSA archive must contain a bounded, nonempty CSV set")
    # Implicit directories must not alias each other with different casing.
    directory_names: dict[str, str] = {}
    for name in names.values():
        path, is_dir = name
        parts = path.split("/")
        for index in range(1, len(parts) + int(is_dir)):
            directory = "/".join(parts[:index])
            prior = directory_names.setdefault(directory.casefold(), directory)
            if prior != directory:
                raise RuntimeError("FSA archive has colliding directory paths")
    return csv_sizes


def extract_fsa_csvs(path: Path, root: Path) -> list[Path]:
    """Extract exactly the approved CSV files into a new private empty directory.

    py7zr 1.1.3 fixes symlink, header parsing and extraction-limit advisories.
    Never silently run with an older version lacking those protections.
    """
    version = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", py7zr.__version__)
    if version is None or tuple(map(int, version.groups())) < (1, 1, 3):
        raise RuntimeError("FSA requires patched py7zr >= 1.1.3")
    if not stat.S_ISREG(path.lstat().st_mode) or path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise RuntimeError("FSA archive exceeds the compressed size limit or is not regular")
    if root.is_symlink() or not root.is_dir() or any(root.iterdir()):
        raise RuntimeError("FSA extraction requires a private empty directory")
    root.chmod(0o700)
    with py7zr.SevenZipFile(path, mode="r", max_extract_size=MAX_EXPANDED_BYTES) as archive:
        sizes = _validated_members(archive)
        directories = {
            "/".join(name.split("/")[:i])
            for name in sizes for i in range(1, len(name.split("/")))
        }
        for directory in sorted(directories, key=lambda value: (value.count("/"), value)):
            (root / directory).mkdir(mode=0o700)
        archive.extract(path=root, targets=sorted(sizes), recursive=False)

    found: set[str] = set()
    pending = [root]
    while pending:
        parent = pending.pop()
        with os.scandir(parent) as entries:
            for entry in entries:
                relative = (parent / entry.name).relative_to(root).as_posix()
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode) and relative in directories:
                    pending.append(parent / entry.name)
                elif (stat.S_ISREG(info.st_mode) and relative in sizes
                      and info.st_nlink == 1 and info.st_size == sizes[relative]):
                    found.add(relative)
                else:
                    raise RuntimeError("FSA extraction produced an unexpected member/type/size")
    if found != set(sizes):
        raise RuntimeError("FSA extraction is missing expected CSV files")
    return [root / name for name in sorted(sizes)]
