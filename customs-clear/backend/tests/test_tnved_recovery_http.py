"""Local read-only HTTP contract; real-byte/browser acceptance is recorded separately."""
from __future__ import annotations

import hashlib
import sqlite3
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.recovery_main import create_recovery_app
from tests.test_tnved_recovery_ci import _builder, _fixture, CHAPTERS, COUNTS


class RecoveryHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        catalog, index, catalog_sha, index_sha = _fixture(root)
        self.database = root / "snapshot.sqlite"
        _builder()._build_with_pins(
            catalog, index, self.database, None,
            catalog_sha256=catalog_sha, index_sha256=index_sha,
            expected_counts=COUNTS, expected_chapters=CHAPTERS, expected_section_count=21,
        )
        # Russian uppercase regression: SQLite lower() alone cannot find this.
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE recovery_nodes SET label=? WHERE code=?", ("ЛОШАДИ племенные", "0100000000"))
        self.pin = hashlib.sha256(self.database.read_bytes()).hexdigest()
        self.client = TestClient(create_recovery_app(self.database, self.pin))

    def tearDown(self):
        self.client.close()

    def test_search_card_hierarchy_use_same_snapshot_without_writes(self):
        def blocked(*args, **kwargs):
            raise AssertionError("external connection forbidden")
        with patch("socket.socket.connect", blocked), patch("socket.getaddrinfo", blocked):
            health = self.client.get("/api/health/ready").json()
            self.assertEqual(health["recovered_catalog"]["snapshot_sha256"], self.pin)
            self.assertFalse(health["recovered_catalog"]["rates_present"])
            for query in ("0100000000", "01 00 000 000", "лошади", "ЛОШАДИ"):
                response = self.client.get("/api/v1/tnved/search", params={"q": query})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["results"][0]["code"], "0100000000")
                self.assertEqual(response.json()["snapshot_sha256"], self.pin)
            card = self.client.get("/api/v1/tnved/0100000000").json()
            self.assertEqual(card["name"], "ЛОШАДИ племенные")
            self.assertEqual([r["hs_code"] for r in card["breadcrumb"]], ["I", "01", "0100000000"])
            self.assertEqual(card["path"], ["Synthetic chapter 01", "Synthetic leaf 01"])
            self.assertEqual(card["legal_status"], "unverified")
            self.assertIsNone(card["rates"])
            self.assertIsNone(card["valid_from"])
            self.assertFalse(card["complete"])
            self.assertEqual(self.client.get("/api/tnved/children/01").json()["items"][0]["code"], card["code"])
            self.assertEqual(self.client.get("/api/tnved/children/0100000000").json()["items"], [])
            self.assertEqual(self.client.get("/api/tnved/children/I").json()["items"][0]["code"], "01")
            sections = self.client.get("/api/tnved/children").json()["items"]
            self.assertEqual([r["code"] for r in sections], "I II III IV V VI VII VIII IX X XI XII XIII XIV XV XVI XVII XVIII XIX XX XXI".split())
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(), self.pin)
        self.assertNotIn("app.main", sys.modules)
        self.assertNotIn("app.db", sys.modules)

    def test_missing_changed_or_unpinned_snapshot_never_falls_back(self):
        with self.assertRaises(FileNotFoundError):
            create_recovery_app(self.database.with_name("missing.sqlite"), self.pin)
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            create_recovery_app(self.database, "0" * 64)
        self.database.write_bytes(self.database.read_bytes() + b" ")
        for path in ("/api/health/ready", "/api/v1/tnved/search?q=01", "/api/v1/tnved/0100000000"):
            self.assertEqual(self.client.get(path).status_code, 503)

    def test_invalid_unknown_and_write_requests_fail_closed(self):
        for path in ("/api/v1/tnved/9999999999", "/api/tnved/children/9999999999", "/api/tnved/breadcrumb/9999999999"):
            self.assertEqual(self.client.get(path).status_code, 404)
        for path in ("/api/v1/tnved/bad", "/api/tnved/children/01?depth=all"):
            self.assertEqual(self.client.get(path).status_code, 422)
        for method in ("post", "put", "delete"):
            self.assertEqual(getattr(self.client, method)("/api/v1/tnved/0100000000").status_code, 405)
        Path(str(self.database) + "-wal").touch()
        self.assertEqual(self.client.get("/api/health/ready").status_code, 503)


if __name__ == "__main__":
    unittest.main()
