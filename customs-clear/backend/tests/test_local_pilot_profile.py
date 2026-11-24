"""Offline rejection tests. No passwords, tokens or private records are created."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.local_pilot_profile import read_auth_file


class LocalProfileTests(unittest.TestCase):
    def test_empty_owner_file_is_incomplete(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile"
            path.write_text("{}")
            path.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "field set"):
                read_auth_file(path)

    def test_world_readable_file_is_rejected_before_parsing(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile"
            path.touch(mode=0o600)
            path.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "owner-only"):
                read_auth_file(path)

    def test_git_worktree_is_rejected(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / ".git").touch()
            with self.assertRaisesRegex(ValueError, "outside Git"):
                read_auth_file(folder / "absent")

    def test_symlink_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile"
            original = path.with_suffix(".original")
            original.touch(mode=0o600)
            os.symlink(original, path)
            with self.assertRaises(OSError):
                read_auth_file(path)
