"""Изоляция permits verify jobs по владельцу (JWT username); admin видит все."""
from __future__ import annotations

import importlib.util
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from app.datetime_util import utc_now_naive
from app.db import SessionLocal
from app.models import PermitsVerifyJob
from app.services.normative_store import init_db
from tests.support_auth import login_admin, login_declarant, login_viewer


def _insert_done_job(*, job_id: str, owner: str | None) -> None:
    with SessionLocal() as db:
        db.add(
            PermitsVerifyJob(
                id=job_id,
                created_by_username=owner,
                status="done",
                created_at=utc_now_naive(),
                finished_at=utc_now_naive(),
                error=None,
                summary={"total": 1, "valid": 0},
                items=[{"type": "ДС", "number": "TEST", "status": "UNKNOWN"}],
                request_payload={"rows": [{"type": "ДС", "number": "TEST"}], "hs_code": "", "enrich": True},
            )
        )
        db.commit()


def _delete_job(job_id: str) -> None:
    with SessionLocal() as db:
        row = db.get(PermitsVerifyJob, job_id)
        if row:
            db.delete(row)
            db.commit()


@unittest.skipUnless(importlib.util.find_spec("fastapi"), "fastapi")
class PermitsVerifyJobsOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        from fastapi.testclient import TestClient
        from app.main import app

        cls.client_decl = TestClient(app)
        cls.client_view = TestClient(app)
        cls.client_adm = TestClient(app)
        login_declarant(cls.client_decl)
        login_viewer(cls.client_view)
        login_admin(cls.client_adm)

    def tearDown(self) -> None:
        for jid in getattr(self, "_cleanup_ids", []):
            _delete_job(jid)

    def test_user_sees_only_own_jobs_in_list_and_detail(self) -> None:
        self._cleanup_ids = []
        jid_decl = uuid4().hex
        jid_view = uuid4().hex
        self._cleanup_ids.extend([jid_decl, jid_view])
        _insert_done_job(job_id=jid_decl, owner="declarant")
        _insert_done_job(job_id=jid_view, owner="viewer")

        lst_a = self.client_decl.get("/api/permits/verify/jobs?limit=50")
        self.assertEqual(lst_a.status_code, 200, lst_a.text)
        ids_a = {x.get("job_id") for x in (lst_a.json().get("items") or [])}
        self.assertIn(jid_decl, ids_a)
        self.assertNotIn(jid_view, ids_a)

        lst_b = self.client_view.get("/api/permits/verify/jobs?limit=50")
        self.assertEqual(lst_b.status_code, 200, lst_b.text)
        ids_b = {x.get("job_id") for x in (lst_b.json().get("items") or [])}
        self.assertIn(jid_view, ids_b)
        self.assertNotIn(jid_decl, ids_b)

        self.assertEqual(self.client_decl.get(f"/api/permits/verify/jobs/{jid_view}").status_code, 404)
        self.assertEqual(self.client_view.get(f"/api/permits/verify/jobs/{jid_decl}").status_code, 404)

        ok_a = self.client_decl.get(f"/api/permits/verify/jobs/{jid_decl}")
        self.assertEqual(ok_a.status_code, 200, ok_a.text)
        self.assertEqual(ok_a.json().get("job_id"), jid_decl)

    def test_admin_sees_all_jobs(self) -> None:
        self._cleanup_ids = []
        jid_decl = uuid4().hex
        jid_view = uuid4().hex
        self._cleanup_ids.extend([jid_decl, jid_view])
        _insert_done_job(job_id=jid_decl, owner="declarant")
        _insert_done_job(job_id=jid_view, owner="viewer")

        lst = self.client_adm.get("/api/permits/verify/jobs?limit=50")
        self.assertEqual(lst.status_code, 200, lst.text)
        ids = {x.get("job_id") for x in (lst.json().get("items") or [])}
        self.assertIn(jid_decl, ids)
        self.assertIn(jid_view, ids)

    def test_legacy_job_without_owner_hidden_from_non_admin(self) -> None:
        self._cleanup_ids = []
        jid = uuid4().hex
        self._cleanup_ids.append(jid)
        _insert_done_job(job_id=jid, owner=None)

        self.assertEqual(self.client_decl.get(f"/api/permits/verify/jobs/{jid}").status_code, 404)
        self.assertEqual(self.client_adm.get(f"/api/permits/verify/jobs/{jid}").status_code, 200)

    def test_export_with_admin_token_unaffected(self) -> None:
        self._cleanup_ids = []
        jid = uuid4().hex
        self._cleanup_ids.append(jid)
        _insert_done_job(job_id=jid, owner="declarant")
        with patch.dict(os.environ, {"ADMIN_API_TOKEN": "perm-export-secret"}):
            r = self.client_decl.get(
                f"/api/permits/verify/jobs/{jid}/export?format=json",
                headers={"X-Admin-Token": "perm-export-secret"},
            )
            self.assertEqual(r.status_code, 200, r.text)
            body = r.json()
            self.assertEqual(body.get("job_id"), jid)
            self.assertIn("items", body)


if __name__ == "__main__":
    unittest.main()
