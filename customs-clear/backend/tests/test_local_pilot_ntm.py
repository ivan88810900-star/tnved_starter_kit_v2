import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.services.local_pilot_ntm import archive_normative_block


class LocalNormativeBlockTests(unittest.TestCase):
    @patch("app.services.local_pilot_ntm.lookup_tr_ts_acts_by_codes")
    def test_archived_match_is_a_reference_only(self, lookup):
        lookup.return_value = [{"act_code": "009/2011", "short_name": "ТР", "source_revision": "archive",
                                "source_url": "", "in_registry": True}]
        response = archive_normative_block("3304100000", "товар")
        self.assertIn("009/2011", lookup.call_args.args[0])
        self.assertEqual(response["status"], "WARNING")
        block = response["normative_block"]
        self.assertEqual(block["assessment"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual([act["act_code"] for act in block["archive_acts"]], ["009/2011"])
        self.assertEqual([block[k] for k in ("required_documents", "missing_documents", "advisory_requirements")], [[], [], []])

    @patch("app.services.local_pilot_ntm.lookup_tr_ts_acts_by_codes")
    def test_missing_registry_card_is_not_presented_as_a_source(self, lookup):
        lookup.return_value = [{"act_code": "009/2011", "in_registry": False}]
        block = archive_normative_block("3304100000", "")["normative_block"]
        self.assertEqual(block["archive_acts"], [])
        self.assertIn("Недостаточно данных", block["empty_message"])

    @patch("app.services.local_pilot_ntm.lookup_tr_ts_acts_by_codes", side_effect=OperationalError("lookup", {}, Exception()))
    def test_database_failure_is_not_reported_as_no_requirements(self, lookup):
        with self.assertRaises(HTTPException) as failure:
            archive_normative_block("3304100000", "")
        self.assertEqual(failure.exception.status_code, 503)

    def test_standard_route_keeps_authenticated_default_checker(self):
        from app.api import auth, non_tariff
        from tests.support_auth import login_declarant

        app = FastAPI()
        app.include_router(auth.router, prefix="/api/auth")
        app.include_router(non_tariff.router, prefix="/api/non_tariff")
        body = {"items": [{"hs_code": "3304100000", "description": "описание", "country": "FR"}]}
        result = {"status": "OK", "normative_block": {"status": "OK"}}
        with TestClient(app) as client, patch.object(non_tariff, "check_position_non_tariff", new_callable=AsyncMock) as checker:
            checker.return_value = result
            self.assertEqual(client.post("/api/non_tariff/normative-block", json=body).status_code, 401)
            checker.assert_not_awaited()
            login_declarant(client)
            reply = client.post("/api/non_tariff/normative-block", json=body)
            self.assertEqual(reply.status_code, 200)
            self.assertEqual(reply.json()["items"][0]["normative_block"], result["normative_block"])
            checker.assert_awaited_once_with("3304100000", "описание", "FR", [])
