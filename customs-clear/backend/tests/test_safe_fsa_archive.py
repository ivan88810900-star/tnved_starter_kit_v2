"""Real 7z round trips and adversarial metadata for FSA's extraction boundary."""

from __future__ import annotations

import stat
from types import SimpleNamespace

import py7zr
import pytest

from app.services import safe_fsa_archive as safe


def _member(name="snapshot.csv", **kwargs):
    return SimpleNamespace(filename=name, uncompressed=20, is_directory=False,
        is_file=True, is_symlink=False, is_junction=False, is_socket=False,
        st_fmt=stat.S_IFREG, **kwargs)


def _archive(members):
    return SimpleNamespace(files=members, needs_password=lambda: False)


@pytest.mark.parametrize("name", ["../escape.csv", "/escape.csv", "C:/escape.csv",
    "dir\\escape.csv", "dir/../escape.csv", "dir//x.csv", "x.csv ", "x.csv.",
    "x\x00.csv", "x\n.csv", "dir/./x.csv", "Ｃ.csv", "AUX.csv"])
def test_rejects_unsafe_names(name):
    with pytest.raises(RuntimeError):
        safe._validated_members(_archive([_member(name)]))


@pytest.mark.parametrize("changes", [
    {"uncompressed": -1}, {"uncompressed": True}, {"uncompressed": "10"},
    {"is_symlink": True}, {"is_junction": True}, {"is_socket": True},
    {"is_file": False}, {"st_fmt": stat.S_IFIFO}, {"st_fmt": stat.S_IFCHR},
    {"uncompressed": 0},
])
def test_rejects_bad_types_and_sizes(changes):
    member = _member()
    for key, value in changes.items():
        setattr(member, key, value)
    with pytest.raises(RuntimeError):
        safe._validated_members(_archive([member]))


@pytest.mark.parametrize("names", [["a.csv", "A.csv"], ["dir", "dir/a.csv"],
    ["dir/a.csv", "DIR/b.csv"]])
def test_rejects_collisions_and_file_ancestor_conflicts(names):
    with pytest.raises(RuntimeError):
        safe._validated_members(_archive([_member(name) for name in names]))


def test_expansion_limit_counts_unselected_solid_predecessors(monkeypatch):
    monkeypatch.setattr(safe, "MAX_EXPANDED_BYTES", 30)
    with pytest.raises(RuntimeError, match="expanded size"):
        safe._validated_members(_archive([_member("unused.bin"), _member()]))


def test_real_7z_extracts_only_exact_nested_csv_set(tmp_path):
    path = tmp_path / "snapshot.7z"
    with py7zr.SevenZipFile(path, "w") as archive:
        archive.writestr("not imported", "notes.txt")
        archive.writestr("reg_number;product_name\n1;one\n", "data/snapshot.csv")
    root = tmp_path / "extract"
    root.mkdir()
    files = safe.extract_fsa_csvs(path, root)
    assert [file.relative_to(root).as_posix() for file in files] == ["data/snapshot.csv"]
    assert "1;one" in files[0].read_text()
    assert not (root / "notes.txt").exists()


def test_real_7z_encryption_is_rejected(tmp_path):
    path = tmp_path / "encrypted.7z"
    with py7zr.SevenZipFile(path, "w", password="fixture-only") as archive:
        archive.writestr("a;b\n1;2\n", "snapshot.csv")
    root = tmp_path / "extract"
    root.mkdir()
    with pytest.raises(RuntimeError, match="encrypted"):
        safe.extract_fsa_csvs(path, root)
    assert not list(root.iterdir())


def test_real_7z_symlink_is_rejected(tmp_path):
    target = tmp_path / "target.csv"
    target.write_text("a;b\n1;2\n")
    link = tmp_path / "link.csv"
    link.symlink_to(target)
    path = tmp_path / "links.7z"
    with py7zr.SevenZipFile(path, "w", dereference=False) as archive:
        archive.write(link, "link.csv")
    root = tmp_path / "extract"
    root.mkdir()
    with pytest.raises(RuntimeError, match="non-regular"):
        safe.extract_fsa_csvs(path, root)
    assert not list(root.iterdir())


def test_real_7z_bomb_metadata_fails_before_extraction(monkeypatch, tmp_path):
    path = tmp_path / "bomb.7z"
    with py7zr.SevenZipFile(path, "w") as archive:
        archive.writestr("x" * 100_000, "snapshot.csv")
    root = tmp_path / "extract"
    root.mkdir()
    monkeypatch.setattr(safe, "MAX_MEMBER_BYTES", 500)
    with pytest.raises(RuntimeError, match="member size"):
        safe.extract_fsa_csvs(path, root)
    assert not list(root.iterdir())
