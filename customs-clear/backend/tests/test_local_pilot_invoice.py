import io
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.api.auth import router as auth_router
from app.api.local_pilot_invoice import pilot_invoice_router
from tests.support_auth import login_admin, login_declarant, login_viewer


def row(code, kind, path):
    return {"code": code, "kind": kind, "path": path, "label": path[-1]}


class SmallCatalog:
    rows = [
        row(None, "codeless", ["Мебель", "Стулья:"]),
        row("9401000000", "coded", ["Мебель", "Стулья:"]),
        row("9401000001", "coded", ["Мебель", "Стулья:", "деревянные"]),
        row("9401000002", "coded", ["Мебель", "Стулья:", "металлические"]),
        row("9401999999", "reserved_marker", ["Мебель", "Стулья:", "зарезервировано"]),
        row("9999999999", "coded", ["Мебель", "Шкафы"]),
    ]

    def search_page(self, term, limit):
        hits = [r for r in self.rows if term in " ".join(r["path"]).casefold()]
        return {"results": hits, "total": len(hits), "limit": limit, "has_more": False}

    def has_children(self, code):
        return code == "9401000000"


@contextmanager
def catalog_reader(path, check):
    check()
    yield SmallCatalog()
    check()


class LocalInvoiceTests(unittest.TestCase):
    def setUp(self):
        scratch = self.enterContext(tempfile.TemporaryDirectory())
        app = FastAPI()
        app.include_router(auth_router, prefix="/api/auth")
        app.include_router(pilot_invoice_router(Path("unused"), lambda: None, Path(scratch)))
        self.enterContext(patch("app.api.local_pilot_invoice.pilot_catalog_reader", catalog_reader))
        self.client = self.enterContext(TestClient(app))
        self.base = "/api/local-invoice/drafts"

    def test_tree_answers_candidates_and_saved_explicit_choice(self):
        response = self.client.post(self.base, json={"description": "  Стулья "})
        self.assertEqual(response.status_code, 401)
        login_declarant(self.client)
        created = self.client.post(self.base, json={"description": "  Стулья "}).json()
        address = self.base + "/" + created["draft_id"]
        line = address + "/lines/1"
        self.assertEqual(created["lines"][0]["description"], "Стулья")
        self.assertIsNone(created["lines"][0]["selected_code"])
        initial = self.client.post(line + "/candidates", json={}).json()
        self.assertEqual([r["code"] for r in initial["candidates"]], ["9401000001", "9401000002"])
        self.assertFalse(initial["limited"])
        answer = next(o["value"] for o in initial["question"]["options"] if o["label"] == "деревянные")
        narrowed = self.client.post(line + "/candidates", json={"answers": [answer]}).json()
        self.assertIsNone(narrowed["question"])
        self.assertIsNone(narrowed["selected_code"])
        self.assertEqual([r["code"] for r in narrowed["candidates"]], ["9401000001"])
        for code in ("9401000000", "9401000002", "9401999999", "9999999999", "9401"):
            with self.subTest(code=code):
                self.assertEqual(self.client.put(line + "/choice", json={"code": code, "answers":[answer]}).status_code, 422)
        saved = self.client.put(line + "/choice", json={"code": "9401000001", "answers":[answer]})
        self.assertEqual(saved.json()["lines"][0]["selected_code"], "9401000001")
        self.assertEqual(self.client.get(address).json(), saved.json())
        login_admin(self.client)
        self.assertEqual(self.client.get(address).status_code, 404)
        self.assertEqual(self.client.put(line + "/choice", json={"code":"9401000001"}).status_code, 404)

    def test_unrecognized_name_requires_a_product_type_before_selecting(self):
        login_declarant(self.client)
        draft = self.client.post(self.base, json={"description": "Креслице деревянное"}).json()
        addr = self.base + "/" + draft["draft_id"]
        line = addr + "/lines/1"
        initial = self.client.post(line + "/candidates", json={}).json()
        self.assertTrue(initial["product_question"])
        self.assertEqual(initial["candidates"], [])
        self.assertIsNone(initial["selected_code"])
        self.assertEqual(self.client.put(line + "/choice", json={"code":"9401000001"}).status_code, 422)
        wrong_category = self.client.post(line + "/candidates", json={"clarification": "Стулья стеклянные"}).json()
        self.assertEqual(wrong_category["candidates"], [])
        clarified = self.client.post(line + "/candidates", json={"clarification":"Стулья"}).json()
        self.assertEqual([r["code"] for r in clarified["candidates"]], ["9401000001"])
        self.assertIsNone(clarified["selected_code"])
        self.assertIsNone(clarified["product_question"])
        self.assertEqual(self.client.put(line + "/choice", json={
            "code":"9999999999","clarification":"Стулья"}).status_code, 422)
        result = self.client.put(line + "/choice", json={"code":"9401000001","clarification":"Стулья"})
        self.assertEqual(result.status_code, 200)
        saved = self.client.get(addr).json()["lines"][0]
        self.assertEqual((saved["selected_code"], saved["clarification"]), ("9401000001", "Стулья"))

    def test_unknown_product_type_is_not_inferred_from_leading_modifiers(self):
        login_declarant(self.client)
        for description in ("Креслице деревянное", "Деревянное креслице"):
            with self.subTest(description=description):
                draft = self.client.post(self.base, json={"description":description}).json()
                line = self.base + "/" + draft["draft_id"] + "/lines/1"
                reply = self.client.post(line + "/candidates", json={}).json()
                self.assertTrue(reply["product_question"])
                self.assertEqual(reply["candidates"], [])
                reply = self.client.post(line + "/candidates", json={"clarification":"Стулья"}).json()
                self.assertEqual([c["code"] for c in reply["candidates"]], ["9401000001"])
                self.assertIsNone(reply["selected_code"])

    def test_yo_in_description_and_clarification_preserves_originals(self):
        entries = [
            row("7013491000", "coded", ["Посуда", "из упрочненного стекла"]),
            row("7013371000", "coded", ["Сосуды", "из упрочненного стекла"]),
        ]
        login_declarant(self.client)
        with patch.object(SmallCatalog, "rows", entries):
            for spelling in ("упрочненного", "упрочнённого", "упрочне\u0308нного"):
                with self.subTest(spelling=spelling):
                    text = "Тарелка из " + spelling + " стекла"
                    clarification = "Посуда из " + spelling + " стекла"
                    draft = self.client.post(self.base, json={"description":text}).json()
                    addr = self.base + "/" + draft["draft_id"]
                    line = addr + "/lines/1"
                    hit = self.client.post(line + "/candidates", json={"clarification":clarification}).json()
                    self.assertEqual([c["code"] for c in hit["candidates"]], ["7013491000"])
                    self.assertEqual(hit["candidates"][0]["label"], "из упрочненного стекла")
                    self.assertIsNone(hit["selected_code"])
                    self.assertEqual(self.client.put(line + "/choice",
                        json={"code":"7013491000","clarification":clarification}).status_code, 200)
                    saved = self.client.get(addr).json()["lines"][0]
                    self.assertEqual((saved["description"], saved["clarification"]), (text, clarification))

    def test_complete_category_page_covers_truncated_modifier_search(self):
        from app.services.local_pilot_invoice import find_candidates

        candidate = row("7013491000", "coded", ["Посуда", "из упрочненного стекла"])
        class Catalog(SmallCatalog):
            def search_page(self, term, limit):
                if term == "декор":
                    return {"results": [], "total": 250, "limit": limit, "has_more": True}
                return {"results": [candidate], "total": 1, "limit": limit, "has_more": False}

        found, limited, notice = find_candidates(Catalog(), "Декор", "Посуда")
        self.assertEqual([c["code"] for c in found], ["7013491000"])
        self.assertFalse(limited)
        self.assertIsNone(notice)

    def test_negated_property_is_not_a_positive_candidate(self):
        login_declarant(self.client)
        draft = self.client.post(self.base, json={"description": "Стулья без дерева"}).json()
        addr = self.base + "/" + draft["draft_id"] + "/lines/1"
        reply = self.client.post(addr + "/candidates", json={}).json()
        self.assertEqual(reply["candidates"], [])
        self.assertIsNone(reply["question"])
        self.assertIn("положительной форме", reply["notice"])
        self.assertEqual(self.client.put(addr + "/choice", json={"code":"9401000001"}).status_code, 422)

    def test_xlsx_lines_and_invalid_inputs(self):
        login_viewer(self.client)
        self.assertEqual(self.client.post(self.base, json={"description":"Стулья"}).status_code, 403)
        login_declarant(self.client)
        workbook = Workbook()
        workbook.active.append(["Description","Quantity","Unit"])
        workbook.active.append(["Стулья", 12, "шт"])
        workbook.active.append(["Неизвестныйтовар", 2, "шт"])
        stream = io.BytesIO()
        workbook.save(stream)
        workbook.close()
        upload = self.base + "/upload"
        created = self.client.post(upload, files={"file":("lines.xlsx", stream.getvalue())}).json()
        self.assertEqual([(l["quantity"], l["unit"]) for l in created["lines"]], [(12, "шт"), (2, "шт")])
        addr = self.base + "/" + created["draft_id"] + "/lines"
        self.assertEqual(self.client.post(addr + "/2/candidates", json={}).json()["candidates"], [])
        self.assertEqual(self.client.post(addr + "/1/candidates", json={"answers":["a"*24]}).status_code, 422)
        self.assertEqual(self.client.post(addr + "/3/candidates", json={}).status_code, 404)
        for filename in ("bad.xlsx","other.txt"):
            self.assertEqual(self.client.post(upload, files={"file":(filename,b"bad")}).status_code, 422)
