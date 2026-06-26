"""Метаданные аудита из HTTP-запроса."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from app.services.audit_log import request_audit_meta


class RequestAuditMetaTests(unittest.TestCase):
    def test_none(self):
        self.assertEqual(request_audit_meta(None), {})

    def test_headers(self):
        req = MagicMock()
        req.headers = {
            "x-client-id": "user-1",
            "x-audit-subject": "декларация 123",
        }
        m = request_audit_meta(req)
        self.assertEqual(m["client_id"], "user-1")
        self.assertEqual(m["audit_subject"], "декларация 123")


if __name__ == "__main__":
    unittest.main()
