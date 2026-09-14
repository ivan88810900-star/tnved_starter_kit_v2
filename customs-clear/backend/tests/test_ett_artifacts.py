"""Local artifact integrity and publication boundaries, without cloud access."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import stat

import pytest

from app.services.ett_artifacts import ArtifactIntegrityError, LocalArtifactStore


def artifact_path(root: Path, data: bytes) -> Path:
    return root / (hashlib.sha256(data).hexdigest() + ".blob")


def test_put_read_verify_deduplicates_without_replacing(tmp_path):
    root = tmp_path / "artifacts"
    store = LocalArtifactStore(root)
    digest = store.put(b"official document bytes")
    path = artifact_path(root, b"official document bytes")
    original = path.stat()
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE(original.st_mode) == 0o400
    assert store.put(b"official document bytes") == digest
    assert (path.stat().st_ino, path.stat().st_mtime_ns) == (
        original.st_ino,
        original.st_mtime_ns,
    )
    assert store.read(digest) == b"official document bytes"
    assert store.verify(digest, 23) is None
    assert store.storage_kind == "local_development"
    assert store.production_ready is False
    with pytest.raises(AttributeError):
        store.production_ready = True
    assert list(root.iterdir()) == [path]


def test_zero_length_is_valid_content_not_a_missing_artifact(tmp_path):
    store = LocalArtifactStore(tmp_path / "artifacts")
    digest = store.put(b"")
    assert store.read(digest) == b""
    store.verify(digest, 0)


def test_read_only_constructor_and_reads_do_not_write(tmp_path, monkeypatch):
    root = tmp_path / "artifacts"
    digest = LocalArtifactStore(root).put(b"document")

    def reject_write(*args, **kwargs):
        pytest.fail("read-only store attempted a filesystem mutation")

    for method in ("mkdir", "chmod", "fchmod", "write", "fsync", "link", "unlink"):
        monkeypatch.setattr(os, method, reject_write)
    store = LocalArtifactStore(root, create=False)
    assert store.read(digest) == b"document"
    store.verify(digest, 8)
    with pytest.raises(ArtifactIntegrityError, match="read-only"):
        store.put(b"document")


def test_read_only_missing_root_is_not_created(tmp_path):
    root = tmp_path / "missing"
    with pytest.raises(ArtifactIntegrityError):
        LocalArtifactStore(root, create=False)
    assert not root.exists()


@pytest.mark.parametrize("digest", ["../a", "a/" + "b" * 64, "A" * 64, "a" * 63, None, "a" * 64 + "\n"])
def test_digest_rejects_traversal_and_noncanonical_values(tmp_path, digest):
    store = LocalArtifactStore(tmp_path / "artifacts")
    with pytest.raises(ArtifactIntegrityError):
        store.read(digest)


@pytest.mark.parametrize("limit", [0, -1, True, 3.5])
def test_invalid_limits_rejected_before_creating_root(tmp_path, limit):
    root = tmp_path / "artifacts"
    with pytest.raises(ValueError):
        LocalArtifactStore(root, max_bytes=limit)
    assert not root.exists()


def test_put_and_verify_bounds(tmp_path):
    root = tmp_path / "artifacts"
    store = LocalArtifactStore(root, max_bytes=4)
    with pytest.raises(ArtifactIntegrityError, match="byte limit"):
        store.put(b"12345")
    assert list(root.iterdir()) == []
    digest = store.put(b"1234")
    for size in (3, 5, -1, True, 4.0):
        with pytest.raises(ArtifactIntegrityError):
            store.verify(digest, size)
    with pytest.raises(TypeError):
        store.put(bytearray(b"1234"))


def test_oversized_existing_file_rejected_before_read(tmp_path, monkeypatch):
    root = tmp_path / "artifacts"
    store = LocalArtifactStore(root, max_bytes=4)
    data = b"12345"
    path = artifact_path(root, data)
    path.write_bytes(data)
    path.chmod(0o400)

    def forbidden_read(*args, **kwargs):
        pytest.fail("oversized file must not be read")

    monkeypatch.setattr(os, "read", forbidden_read)
    with pytest.raises(ArtifactIntegrityError, match="byte limit"):
        store.read(hashlib.sha256(data).hexdigest())


@pytest.mark.parametrize("location", ["root", "parent"])
def test_symlink_root_or_ancestor_rejected(tmp_path, location):
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    root = link if location == "root" else link / "artifacts"
    with pytest.raises(ArtifactIntegrityError):
        LocalArtifactStore(root)
    assert list(target.iterdir()) == []


def test_parent_traversal_and_missing_parent_rejected(tmp_path):
    with pytest.raises(ArtifactIntegrityError):
        LocalArtifactStore(tmp_path / "unused" / ".." / "artifacts")
    with pytest.raises(ArtifactIntegrityError):
        LocalArtifactStore(tmp_path / "missing" / "artifacts")
    assert not (tmp_path / "missing").exists()


def test_existing_nonprivate_root_is_rejected_without_chmod(tmp_path):
    root = tmp_path / "shared"
    root.mkdir(mode=0o755)
    with pytest.raises(ArtifactIntegrityError, match="private"):
        LocalArtifactStore(root)
    assert stat.S_IMODE(root.stat().st_mode) == 0o755


def test_root_replacement_rejected(tmp_path):
    root = tmp_path / "artifacts"
    store = LocalArtifactStore(root)
    root.rename(tmp_path / "original")
    root.mkdir(mode=0o700)
    with pytest.raises(ArtifactIntegrityError, match="replaced"):
        store.put(b"document")
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("target_kind", ["symlink", "dangling", "hardlink", "directory", "fifo"])
def test_unsafe_target_cannot_be_read_or_overwritten(tmp_path, target_kind):
    root = tmp_path / "artifacts"
    store = LocalArtifactStore(root)
    data = b"document"
    target = artifact_path(root, data)
    outside = tmp_path / "outside"
    outside.write_bytes(data)
    outside.chmod(0o400)
    if target_kind == "symlink":
        target.symlink_to(outside)
    elif target_kind == "dangling":
        target.symlink_to(tmp_path / "absent")
    elif target_kind == "hardlink":
        os.link(outside, target)
    elif target_kind == "directory":
        target.mkdir()
    else:
        os.mkfifo(target, 0o400)
    inode = target.lstat().st_ino
    for operation in (lambda: store.put(data), lambda: store.read(hashlib.sha256(data).hexdigest())):
        with pytest.raises(ArtifactIntegrityError):
            operation()
    assert target.lstat().st_ino == inode
    assert outside.read_bytes() == data
    assert not list(root.glob(".pending-*"))


def test_tampered_existing_artifact_not_silently_repaired(tmp_path):
    root = tmp_path / "artifacts"
    store = LocalArtifactStore(root)
    data = b"document"
    digest = store.put(data)
    target = artifact_path(root, data)
    target.chmod(0o600)
    target.write_bytes(b"tampered")
    target.chmod(0o400)
    for operation in (lambda: store.put(data), lambda: store.read(digest)):
        with pytest.raises(ArtifactIntegrityError, match="integrity"):
            operation()
    assert target.read_bytes() == b"tampered"


def test_concurrent_puts_deduplicate_and_read_consistently(tmp_path):
    root = tmp_path / "artifacts"
    data = b"document" * 1024

    def write_and_read(_):
        store = LocalArtifactStore(root)
        digest = store.put(data)
        assert store.read(digest) == data
        return digest

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(write_and_read, range(36)))
    assert len(set(results)) == 1
    assert list(root.iterdir()) == [artifact_path(root, data)]


def test_short_writes_are_completed(tmp_path, monkeypatch):
    store = LocalArtifactStore(tmp_path / "artifacts")
    original_write = os.write

    def short_write(descriptor, data):
        return original_write(descriptor, data[:3])

    monkeypatch.setattr(os, "write", short_write)
    data = b"document bytes"
    assert store.read(store.put(data)) == data


def test_uncooperative_target_insertion_is_never_overwritten(tmp_path, monkeypatch):
    root = tmp_path / "artifacts"
    store = LocalArtifactStore(root)
    data = b"document"
    target = artifact_path(root, data)
    original_link = os.link

    def insert_target_before_publish(*args, **kwargs):
        target.write_bytes(b"concurrent insertion")
        target.chmod(0o400)
        return original_link(*args, **kwargs)

    monkeypatch.setattr(os, "link", insert_target_before_publish)
    with pytest.raises(ArtifactIntegrityError):
        store.put(data)
    assert target.read_bytes() == b"concurrent insertion"
    assert not list(root.glob(".pending-*"))


def test_concurrent_file_change_is_detected_even_if_read_bytes_match(tmp_path, monkeypatch):
    root = tmp_path / "artifacts"
    store = LocalArtifactStore(root)
    data = b"document"
    digest = store.put(data)
    target = artifact_path(root, data)
    original_read = os.read
    altered = False

    def read_then_mutate(descriptor, size):
        nonlocal altered
        chunk = original_read(descriptor, size)
        if chunk and not altered:
            altered = True
            target.chmod(0o600)
            target.write_bytes(b"tampered")
            target.chmod(0o400)
        return chunk

    monkeypatch.setattr(os, "read", read_then_mutate)
    with pytest.raises(ArtifactIntegrityError, match="integrity"):
        store.read(digest)


@pytest.mark.parametrize("failure", ["write", "zero_write", "fsync"])
def test_partial_write_failure_cleans_private_staging(tmp_path, monkeypatch, failure):
    root = tmp_path / "artifacts"
    store = LocalArtifactStore(root)
    original_write = os.write
    original_fsync = os.fsync
    writes = 0

    def failing_write(descriptor, data):
        nonlocal writes
        writes += 1
        if failure == "zero_write":
            return 0
        if writes == 1:
            return original_write(descriptor, data[:3])
        raise OSError("simulated disk failure")

    def failing_file_fsync(descriptor):
        if stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError("simulated fsync failure")
        return original_fsync(descriptor)

    if failure == "fsync":
        monkeypatch.setattr(os, "fsync", failing_file_fsync)
    else:
        monkeypatch.setattr(os, "write", failing_write)
    with pytest.raises(ArtifactIntegrityError):
        store.put(b"document bytes")
    assert list(root.iterdir()) == []
