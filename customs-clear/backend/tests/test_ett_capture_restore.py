import hashlib
import io
import tarfile

import pytest

from app.services.ett_artifacts import LocalArtifactStore
from scripts.restore_ett_capture import restore_capture


def bundle(path, name, data):
    with tarfile.open(path, "w:gz") as archive:
        member = tarfile.TarInfo(name)
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_original_objects_restore_by_digest_without_tar_paths(tmp_path):
    data = b"synthetic retained object"
    digest = hashlib.sha256(data).hexdigest()
    archive = tmp_path / "objects.tar.gz"
    pinned = bundle(archive, f"store/{digest}.blob", data)
    store = LocalArtifactStore(tmp_path / "objects")
    result = restore_capture(archive, pinned, store)
    assert result["restored_objects"] == 1
    assert store.read(digest) == data
    assert result["production_ready"] is False


def test_changed_archive_is_rejected_before_publishing_objects(tmp_path):
    archive = tmp_path / "objects.tar.gz"
    bundle(archive, "store/" + "a" * 64 + ".blob", b"body")
    store = LocalArtifactStore(tmp_path / "objects")
    with pytest.raises(ValueError, match="archive digest mismatch"):
        restore_capture(archive, "b" * 64, store)
    assert list((tmp_path / "objects").iterdir()) == []


@pytest.mark.parametrize("name", ["../escape", "store/" + "a" * 64 + ".blob"])
def test_invalid_member_name_or_object_digest_never_becomes_a_source(tmp_path, name):
    archive = tmp_path / "objects.tar.gz"
    pinned = bundle(archive, name, b"wrong object")
    store = LocalArtifactStore(tmp_path / "objects")
    with pytest.raises(ValueError):
        restore_capture(archive, pinned, store)
    assert list((tmp_path / "objects").iterdir()) == []
