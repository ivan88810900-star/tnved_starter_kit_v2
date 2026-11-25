"""Offline rejection tests. No passwords, tokens or private records are created."""
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.local_pilot_profile import read_auth_file, restore_local_drafts


class LocalProfileTests(unittest.TestCase):
    def test_upgrade_keeps_old_drafts_and_new_clarifications(self):
        from app.services.local_pilot_invoice import PilotDrafts

        for legacy in (True, False):
            with self.subTest(legacy=legacy), TemporaryDirectory(prefix="tariff-invoice-handoff-") as old, TemporaryDirectory() as fresh:
                before = PilotDrafts(Path(old))
                draft = before.create("declarant", [{"line": 1, "description": "Посуда", "quantity": 6, "unit": "шт"}])
                before.choose("declarant", draft["draft_id"], 1, "7323940000", "кухонная посуда")
                if legacy:
                    with closing(sqlite3.connect(before.path)) as db, db:
                        db.execute("ALTER TABLE draft_lines DROP COLUMN clarification")
                after = PilotDrafts(Path(fresh))
                restore_local_drafts(before.path, after.path)
                line = after.read("declarant", draft["draft_id"])["lines"][0]
                self.assertEqual((line["quantity"], line["unit"], line["selected_code"]), (6, "шт", "7323940000"))
                self.assertEqual(line["clarification"], "" if legacy else "кухонная посуда")
                with self.assertRaisesRegex(ValueError, "Fresh pilot"):
                    restore_local_drafts(before.path, after.path)

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
