"""Content-addressed ETT artifacts for local development, not legal retention.

This store deliberately has no cloud credentials, network access, or database
dependencies. Local file permissions and atomic publication protect ordinary
development runs; they cannot supply production Object Lock or durable archival
evidence. An approved production snapshot needs a separate retention-capable
storage implementation and verification of that provider's actual retention.
"""

from __future__ import annotations

from contextlib import contextmanager
try:
    import fcntl
except ImportError:  # The optional local store must not break Windows app startup.
    fcntl = None  # type: ignore[assignment]
import hashlib
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Iterator, Literal


class ArtifactIntegrityError(ValueError):
    """An artifact or its storage boundary cannot be verified safely."""


class LocalArtifactStore:
    """Private, immutable-by-convention development artifacts, keyed by SHA-256.

    Only ``root`` itself may be created. Existing ancestors must be directories,
    never symlinks; an existing root must be owned by this process's user and
    have mode 0700. Files are published without replacing existing paths and
    are checked on every read, including deduplication. POSIX directory locks
    serialize publication with readers and other cooperating writers.

    ``create=False`` verifies an existing store without writing anything. It is
    suitable for read-only consumers and ``put`` rejects this mode. This
    convenience restriction does not replace filesystem access controls.
    """

    __slots__ = ("_root", "_max_bytes", "_identity", "_writable")

    def __init__(
        self,
        root: Path,
        max_bytes: int = 64 * 1024 * 1024,
        *,
        create: bool = True,
    ) -> None:
        if fcntl is None:
            raise ArtifactIntegrityError("Local ETT artifacts require a POSIX storage host")
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        if type(create) is not bool:
            raise ValueError("create must be a boolean")
        path = Path(root)
        if ".." in path.parts or "\x00" in str(path):
            raise ArtifactIntegrityError("Unsafe artifact root")
        self._root = path.absolute()
        if self._root == Path(self._root.anchor):
            raise ArtifactIntegrityError("Filesystem root cannot be an artifact store")
        self._max_bytes = max_bytes
        self._writable = create
        self._identity: tuple[int, int] | None = None
        with self._directory(create=create) as directory:
            metadata = os.fstat(directory)
            self._identity = (metadata.st_dev, metadata.st_ino)

    @property
    def storage_kind(self) -> Literal["local_development"]:
        return "local_development"

    @property
    def production_ready(self) -> Literal[False]:
        return False

    @contextmanager
    def _directory(self, *, create: bool = False) -> Iterator[int]:
        """Walk from / with no-follow dirfds; never resolve an untrusted link."""
        descriptor: int | None = None
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            descriptor = os.open(self._root.anchor, flags)
            components = self._root.parts[1:]
            for index, component in enumerate(components):
                if create and index == len(components) - 1:
                    try:
                        os.mkdir(component, 0o700, dir_fd=descriptor)
                        os.fsync(descriptor)
                    except FileExistsError:
                        pass
                following = os.open(component, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = following
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o700
                or metadata.st_uid != os.geteuid()
                or metadata.st_nlink == 0
            ):
                raise ArtifactIntegrityError("Artifact root must be an owned private directory")
            if self._identity is not None and self._identity != (
                metadata.st_dev,
                metadata.st_ino,
            ):
                raise ArtifactIntegrityError("Artifact root has been replaced")
            yield descriptor
        except OSError as exc:
            raise ArtifactIntegrityError("Unsafe or unavailable artifact storage") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)

    @staticmethod
    def _name(sha256: str) -> str:
        if not isinstance(sha256, str) or re.fullmatch(r"[0-9a-f]{64}", sha256) is None:
            raise ArtifactIntegrityError("Artifact digest must be lowercase SHA-256")
        return sha256 + ".blob"

    @staticmethod
    def _file_identity(metadata: os.stat_result) -> tuple[int, ...]:
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
            metadata.st_mode,
            metadata.st_nlink,
            metadata.st_uid,
        )

    def _read(self, directory: int, sha256: str, *, missing_ok: bool = False) -> bytes | None:
        name = self._name(sha256)
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
        try:
            descriptor = os.open(name, flags, dir_fd=directory)
        except FileNotFoundError:
            if missing_ok:
                return None
            raise ArtifactIntegrityError("Artifact is missing") from None
        try:
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or stat.S_IMODE(before.st_mode) != 0o400
                or before.st_uid != os.geteuid()
                or before.st_nlink != 1
                or before.st_size > self._max_bytes
            ):
                raise ArtifactIntegrityError("Unsafe artifact file or artifact exceeds byte limit")
            chunks: list[bytes] = []
            total = 0
            digest = hashlib.sha256()
            while True:
                chunk = os.read(descriptor, min(1024 * 1024, self._max_bytes + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > self._max_bytes:
                    raise ArtifactIntegrityError("Artifact exceeds byte limit")
                chunks.append(chunk)
                digest.update(chunk)
            after = os.fstat(descriptor)
            if (
                self._file_identity(before) != self._file_identity(after)
                or total != before.st_size
                or digest.hexdigest() != sha256
            ):
                raise ArtifactIntegrityError("Artifact integrity mismatch")
            return b"".join(chunks)
        finally:
            os.close(descriptor)

    def read(self, sha256: str) -> bytes:
        self._name(sha256)
        with self._directory() as directory:
            fcntl.flock(directory, fcntl.LOCK_SH)
            result = self._read(directory, sha256)
            assert result is not None
            return result

    def verify(self, sha256: str, size_bytes: int) -> None:
        if type(size_bytes) is not int or not 0 <= size_bytes <= self._max_bytes:
            raise ArtifactIntegrityError("Artifact size must be a bounded nonnegative integer")
        if len(self.read(sha256)) != size_bytes:
            raise ArtifactIntegrityError("Artifact size mismatch")

    def put(self, data: bytes) -> str:
        if not self._writable:
            raise ArtifactIntegrityError("Artifact store was opened read-only")
        if not isinstance(data, bytes):
            raise TypeError("Artifact data must be bytes")
        if len(data) > self._max_bytes:
            raise ArtifactIntegrityError("Artifact exceeds byte limit")
        sha256 = hashlib.sha256(data).hexdigest()
        name = self._name(sha256)
        with self._directory() as directory:
            fcntl.flock(directory, fcntl.LOCK_EX)
            if self._read(directory, sha256, missing_ok=True) is not None:
                return sha256
            temporary = ".pending-" + secrets.token_hex(24)
            descriptor: int | None = None
            created = False
            try:
                descriptor = os.open(
                    temporary,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600,
                    dir_fd=directory,
                )
                created = True
                remaining = memoryview(data)
                while remaining:
                    written = os.write(descriptor, remaining)
                    if written <= 0:
                        raise ArtifactIntegrityError("Artifact write made no progress")
                    remaining = remaining[written:]
                os.fchmod(descriptor, 0o400)
                os.fsync(descriptor)
                os.close(descriptor)
                descriptor = None
                # link() publishes atomically and refuses to overwrite any target,
                # including a concurrently inserted symlink. Readers share the lock
                # so they cannot observe the transient two-link state.
                os.link(
                    temporary,
                    name,
                    src_dir_fd=directory,
                    dst_dir_fd=directory,
                    follow_symlinks=False,
                )
                os.unlink(temporary, dir_fd=directory)
                created = False
                os.fsync(directory)
                self._read(directory, sha256)
                return sha256
            finally:
                if descriptor is not None:
                    os.close(descriptor)
                if created:
                    os.unlink(temporary, dir_fd=directory)
                    os.fsync(directory)
