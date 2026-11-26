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
    return {"code": code, "kind": kind, "path": ["Учебная группа", *path], "label": path[-1]}


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

    def test_chapter_title_is_not_a_product_description(self):
        from app.services.local_pilot_invoice import find_candidates

        title = "Печатные книги, газеты и другие изделия полиграфической промышленности"
        book = row("4901990000", "coded", ["Печатные книги сброшюрованные:", "прочие"])
        notes = row("4904000000", "coded", ["Ноты, печатные или рукописные, в переплете"])
        binders = row("4820300000", "coded", ["Бухгалтерские книги, съемные переплеты:", "папки"])
        for item in (book, notes, binders):
            item["path"][0] = title
        with patch.object(SmallCatalog, "rows", [book, notes]):
            catalog = SmallCatalog()
            for description, clarification in (("Книги", ""), ("Издание", "Печатные книги")):
                matches, _, _ = find_candidates(catalog, description, clarification)
                self.assertEqual([item["code"] for item in matches], [book["code"]])
                self.assertEqual(matches[0]["path"][0], title)
            self.assertEqual(find_candidates(catalog, "Издание", "Книги в переплёте")[0], [])
            with patch.object(SmallCatalog, "rows", [binders]):
                self.assertEqual(find_candidates(catalog, "Издание", "Книги в переплёте")[0], [])
                matched = find_candidates(catalog, "Изделие", "Съёмные переплёты")[0]
                self.assertEqual([item["code"] for item in matched], [binders["code"]])
            own = find_candidates(catalog, "Издание", "Ноты в переплёте")[0]
            self.assertEqual([item["code"] for item in own], [notes["code"]])

    def test_child_book_audience_does_not_identify_content(self):
        rows = [row("4901990000", "coded", ["Печатные книги сброшюрованные", "прочие"]),
                row("4903000000", "coded", ["Книги-картинки, книги для рисования или раскрашивания, детские"])]
        login_declarant(self.client)
        with patch.object(SmallCatalog, "rows", rows):
            created = self.client.post(self.base, json={"description": "Детская книга"}).json()
            line = self.base + "/" + created["draft_id"] + "/lines/1"
            for clarification in ("", "Детские книги", "Бумажная книжка для детей от 4 лет", "Книги"):
                arguments = {"clarification": clarification}
                result = self.client.post(line + "/candidates", json=arguments).json()
                self.assertIn("текст для чтения", result["product_question"])
                self.assertIn("картинки", result["product_question"])
                self.assertIn("раскрашивания", result["product_question"])
                self.assertEqual(result["candidates"], [])
                self.assertIsNone(result["selected_code"])
                self.assertEqual(self.client.put(line + "/choice", json={**arguments, "code": "4903000000"}).status_code, 422)
            for term, expected in (("Печатные книги сброшюрованные", "4901990000"), ("Книги-картинки", "4903000000"),
                                   ("Книги для раскрашивания", "4903000000")):
                result = self.client.post(line + "/candidates", json={"clarification": term}).json()
                self.assertEqual([c["code"] for c in result["candidates"]], [expected])
                self.assertIsNone(result["selected_code"])
                self.assertIsNone(result["product_question"])

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

    def test_excluded_words_in_official_label_do_not_support_a_choice(self):
        from app.services.local_pilot_invoice import find_candidates

        for exclusion in ("кроме", "исключая", "за исключением"):
            with self.subTest(exclusion=exclusion):
                official = f"Посуда ({exclusion} сосудов для питья (в том числе кружек)) кухонная"
                rows = [row("7013491000", "coded", [official]),
                        row("7013371000", "coded", ["Сосуды для питья"])]
                with patch.object(SmallCatalog, "rows", rows):
                    catalog = SmallCatalog()
                    found, _, _ = find_candidates(catalog, "Сосуды", "Сосуды для питья")
                    self.assertEqual([item["code"] for item in found], ["7013371000"])
                    found, _, _ = find_candidates(catalog, "Кружек")
                    self.assertEqual(found, [])
                    found, _, _ = find_candidates(catalog, "Посуда кухонная")
                    self.assertEqual([item["label"] for item in found], [official])

    def test_unparenthesized_exception_cannot_make_an_ineligible_material_match(self):
        from app.services.local_pilot_invoice import find_candidates

        vessel = "Сосуды (бытовые) для питья, кроме изготовленных из стеклокерамики, из дерева:"
        plate = "Посуда (жаростойкая, кроме украшений) столовая"
        rows = [
            row("7013371000", "coded", [vessel, "из упрочненного стекла"]),
            row("7013491000", "coded", [plate]),
        ]
        with patch.object(SmallCatalog, "rows", rows):
            catalog = SmallCatalog()
            for excluded in ("стеклокерамики", "дерева"):
                self.assertEqual(find_candidates(catalog, "Сосуды", f"Сосуды для питья из {excluded}")[0], [])
            self.assertEqual(find_candidates(catalog, "Украшения")[0], [])
            for clarification, official in (("Бытовые из упрочнённого стекла", "7013371000"),
                                            ("Жаростойкая посуда столовая", "7013491000")):
                result = find_candidates(catalog, "Посуда", clarification)[0]
                self.assertEqual([item["code"] for item in result], [official])
            self.assertEqual(find_candidates(catalog, "Сосуды")[0][0]["path"][1], vessel)

    def test_two_xlsx_lines_keep_separate_confirmed_choices(self):
        login_declarant(self.client)
        book = Workbook()
        book.active.append(["Описание", "Количество", "Единица"])
        book.active.append(["Стулья", 8, "шт"])
        book.active.append(["Стулья", 6, "шт"])
        stream = io.BytesIO()
        book.save(stream)
        book.close()
        draft = self.client.post(self.base + "/upload", files={"file": ("two.xlsx", stream.getvalue())}).json()
        address = self.base + "/" + draft["draft_id"]
        for i, (label, code, wrong) in enumerate([
            ("деревянные", "9401000001", "9401000002"),
            ("металлические", "9401000002", "9401000001"),
        ], start=1):
            line = address + f"/lines/{i}"
            choices = self.client.post(line + "/candidates", json={}).json()
            answer = next(o["value"] for o in choices["question"]["options"] if o["label"] == label)
            self.assertEqual(self.client.put(line + "/choice", json={"answers": [answer], "code": wrong}).status_code, 422)
            self.assertIsNone(self.client.get(address).json()["lines"][i - 1]["selected_code"])
            self.assertEqual(self.client.put(line + "/choice", json={"answers": [answer], "code": code}).status_code, 200)
        restored = self.client.get(address).json()["lines"]
        self.assertEqual([(line["line"], line["description"], line["quantity"], line["unit"], line["selected_code"])
                          for line in restored], [(1, "Стулья", 8, "шт", "9401000001"), (2, "Стулья", 6, "шт", "9401000002")])

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
