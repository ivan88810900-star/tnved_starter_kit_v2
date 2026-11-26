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
        self.assertNotIn("product_review", block)
        self.assertIn("Недостаточно данных", block["empty_message"])

    @patch("app.services.local_pilot_ntm.lookup_tr_ts_acts_by_codes", side_effect=OperationalError("lookup", {}, Exception()))
    def test_database_failure_is_not_reported_as_no_requirements(self, lookup):
        with self.assertRaises(HTTPException) as failure:
            archive_normative_block("3304100000", "")
        self.assertEqual(failure.exception.status_code, 503)

    @patch("app.services.local_pilot_ntm.lookup_tr_ts_acts_by_codes")
    def test_conditional_routes_require_article_six_and_leave_shipment_unassessed(self, lookup):
        lookup.return_value = [{"act_code": "009/2011", "in_registry": True, "short_name": "", "source_revision": "", "source_url": ""}]
        block = archive_normative_block("3304100000", "")["normative_block"]
        review = block["product_review"]
        self.assertEqual(review["status"], "NEEDS_CLARIFICATION")
        self.assertEqual({r["document_type"] for r in review["source_routes"]},
                         {"Государственная регистрация", "Декларация о соответствии"})
        for route in review["source_routes"]:
            self.assertIn("статья 6 с учётом статьи 1 пунктов 2 и 3", route["condition"])
            self.assertTrue(route["source_url"].startswith("https://docs.eaeunion.org/"))
        self.assertIn("ст. 5", review["edition"]["scope_limit"])
        self.assertTrue(any("на носителе" in q for q in review["questions"]))
        self.assertEqual(review["product_documents"]["status"], "NOT_PROVIDED")
        self.assertFalse(review["product_documents"]["shipment_verified"])
        self.assertTrue(any("артикул" in q for q in review["questions"]))
        supplied = archive_normative_block("3304100000", "косметика", country="RU")["normative_block"]["product_review"]
        self.assertFalse(any("страна происхождения" in q or "артикул" in q for q in supplied["questions"]))

    @patch("app.services.local_pilot_ntm.lookup_tr_ts_acts_by_codes")
    def test_lookup_is_limited_to_one_pinned_excerpt_and_exact_sgr_numbers(self, lookup):
        import hashlib
        import json
        import os
        from pathlib import Path
        from tempfile import TemporaryDirectory

        lookup.return_value = [{"act_code": "009/2011", "in_registry": True, "short_name": "", "source_revision": "", "source_url": ""}]
        synthetic = {"number": "EXAMPLE-1", "product": "Example", "issued_on": "2020-01-01",
                     "snapshot_date": "2026-11-25", "registry_status": "Example status"}
        raw = json.dumps(synthetic).encode()

        def check(documents):
            b = archive_normative_block("3304100000", "другой товар", permits=documents)["normative_block"]
            self.assertEqual(b["assessment"], "INSUFFICIENT_EVIDENCE")
            self.assertEqual(b["required_documents"], [])
            return b["product_review"]["product_documents"]

        with TemporaryDirectory() as tmp, patch("app.services.local_pilot_ntm._SGR_EXCERPT_SHA256", hashlib.sha256(raw).hexdigest()):
            path = Path(tmp) / "record.json"
            path.write_bytes(raw)
            with patch.dict(os.environ, {"TARIFF_PILOT_SGR_EVIDENCE": str(path)}):
                matched = check([{"type": "СГР", "number": "example-1"}])
                self.assertEqual(matched["comparison"], "NUMBER_MATCH_ONLY")
                self.assertEqual(matched["registry_matches"], 1)
                self.assertFalse(matched["shipment_verified"])
                self.assertEqual(matched["registered_product"], "Example")
                missing = check([{"type": "СГР", "number": "example-10"}])
                self.assertEqual(missing["comparison"], "NO_NUMBER_IN_LOCAL_EXCERPT")
                self.assertNotIn("registered_product", missing)
                self.assertFalse(check([{"type": "ДС", "number": "EXAMPLE-1"}])["registry_checked"])
                self.assertFalse(check([{"type": "СГР", "number": " "}])["registry_checked"])
                path.write_bytes(raw + b" ")
                with self.assertRaises(HTTPException) as failure:
                    check([{"type": "SGR", "number": "EXAMPLE-1"}])
                self.assertEqual(failure.exception.status_code, 503)
            with patch.dict(os.environ, {"TARIFF_PILOT_SGR_EVIDENCE": ""}):
                self.assertEqual(check([{"type": "СГР", "number": "EXAMPLE-1"}])["comparison"], "EXCERPT_NOT_CONFIGURED")


    @patch("app.services.local_pilot_ntm.lookup_tr_ts_acts_by_codes", return_value=[])
    def test_national_tableware_routes_are_scoped_by_product_and_code(self, lookup):
        cases = {
            "7323940000": ["2.1"],
            "7323930000": ["3.1", "4.1"],
            "8215201000": ["4.1"],
            "8215991000": ["4.1"],
            "7013420000": ["47.1"],
        }
        for code, expected in cases.items():
            with self.subTest(code=code):
                block = archive_normative_block(code, "товар")["normative_block"]
                review = block["product_review"]
                self.assertEqual(review["family"], "RF_TABLEWARE")
                self.assertEqual(len(review["source_routes"]), len(expected))
                for row, position in zip(review["source_routes"], expected, strict=True):
                    self.assertIn(f"п. {position},", row["locator"])
                    self.assertIn("?index=", row["source_url"])
                self.assertEqual(block["required_documents"], [])
                self.assertEqual(block["missing_documents"], [])
        for code in ("8205598099", "7323920000", "8215999000", "9403208009"):
            with self.subTest(code=code):
                self.assertNotIn("product_review", archive_normative_block(code, "кастрюля")["normative_block"])

    @patch("app.services.local_pilot_ntm.lookup_tr_ts_acts_by_codes", return_value=[])
    def test_child_intent_and_document_numbers_never_admit_a_shipment(self, lookup):
        permits = [{"type": "ДС", "number": "EXAMPLE-ONLY"}, {"type": "СГР", "number": "EXAMPLE-ONLY"}]
        with patch("app.services.local_pilot_ntm._product_documents", side_effect=AssertionError("unrelated certificate register")):
            result = archive_normative_block("7323940000", "Кастрюля для детей", permits=permits)
        block = result["normative_block"]
        review = block["product_review"]
        self.assertEqual(result["status"], "WARNING")
        self.assertEqual(block["assessment"], "INSUFFICIENT_EVIDENCE")
        self.assertIn("для взрослых", review["source_routes"][0]["condition"])
        self.assertTrue(any("детской" in q for q in review["questions"]))
        self.assertEqual(review["product_documents"]["submitted_count"], 2)
        self.assertFalse(review["product_documents"]["registry_checked"])
        self.assertFalse(review["product_documents"]["shipment_verified"])
        self.assertNotIn("EXAMPLE-ONLY", str(result))
        self.assertEqual(review["edition"]["status"], "PARTIALLY_RECONSTRUCTED")
        self.assertIn("Сноска 2", review["edition"]["scope_limit"])
        self.assertIn("заголовок", review["edition"]["scope_limit"])
        self.assertIn("01.09.2026", review["edition"]["limit"])

    @patch("app.services.local_pilot_ntm.lookup_tr_ts_acts_by_codes", return_value=[])
    def test_glass_plate_needs_explicit_use_and_manufacturer_age(self, lookup):
        code = "7013491000"
        permits = [{"type": "СС", "number": "EXAMPLE-ONLY"}]

        def check(use, age, code=code):
            block = archive_normative_block(
                code, "Тарелка для детей 4+", permits=permits,
                tableware_use=use, tableware_age=age,
            )["normative_block"]
            self.assertEqual(block["assessment"], "INSUFFICIENT_EVIDENCE")
            self.assertEqual((block["required_documents"], block["missing_documents"]), ([], []))
            rv = block["product_review"]
            self.assertEqual(rv["product_documents"]["submitted_count"], 1)
            self.assertFalse(rv["product_documents"]["registry_checked"])
            self.assertFalse(rv["product_documents"]["shipment_verified"])
            return rv

        self.assertEqual(check(None, None)["family"], "RF_TABLEWARE")
        self.assertEqual(check("unknown", "adult")["family"], "RF_TABLEWARE")
        types = {"under_3": ("Государственная регистрация с последующим декларированием соответствия", "ст. 12 п. 2"),
                 "over_3": ("Сертификат соответствия", "ст. 12 п. 4")}
        for age, (document, locator) in types.items():
            with self.subTest(age=age):
                rv = check("child_food_glass", age)
                self.assertEqual(rv["family"], "EAEU_CHILD_GLASS_TABLEWARE")
                self.assertEqual([r["document_type"] for r in rv["source_routes"]], [document])
                self.assertIn(locator, rv["source_routes"][0]["locator"])
                self.assertIn("/317/3175/", rv["source_routes"][0]["source_url"])
                self.assertIn("маркиров", " ".join(rv["questions"]) + rv["edition"]["scope_limit"])
                self.assertNotIn("ПП РФ № 2425", str(rv))
        for use, age, target, question in [
            ("child_food_glass", "unknown", code, "полный диапазон"),
            ("child_food_glass", "exactly_3", code, "одному указанию"),
            ("child_food_glass", "adult", code, "противоречат"),
            ("child_food_glass", "over_3", "7013990000", "выбранный код"),
            ("child_food_glass", "over_3", "7323940000", "выбранный код"),
            ("unknown", "over_3", code, "материал"),
        ]:
            with self.subTest(use=use, age=age, target=target):
                rv = check(use, age, target)
                self.assertEqual(rv["source_routes"], [])
                self.assertIn(question, rv["questions"][0])

    @patch("app.services.local_pilot_ntm.lookup_tr_ts_acts_by_codes", return_value=[])
    def test_drinking_vessel_requires_its_own_manufacturer_designation(self, lookup):
        def review(code, use, age):
            block = archive_normative_block(
                code, "Детский стакан для воды, 4+", tableware_use=use, tableware_age=age,
                permits=[{"type": "СС", "number": "EXAMPLE-ONLY"}],
            )["normative_block"]
            self.assertEqual(block["assessment"], "INSUFFICIENT_EVIDENCE")
            self.assertEqual((block["required_documents"], block["missing_documents"]), ([], []))
            item = block["product_review"]
            self.assertFalse(item["product_documents"]["shipment_verified"])
            return item

        code = "7013371000"
        for age, form, locator, url in [
            ("under_3", "Государственная регистрация с последующим декларированием соответствия", "поз. 6,", "/251/9400/"),
            ("over_3", "Сертификат соответствия", "поз. 6¹,", "/335/4893/"),
        ]:
            with self.subTest(age=age):
                (route,) = review(code, "child_drinking_cup", age)["source_routes"]
                self.assertEqual(route["document_type"], form)
                self.assertIn(locator, route["locator"])
                self.assertIn("из 7013", route["locator"])
                self.assertIn("аналогичный сосуд", route["condition"])
                self.assertTrue(route["source_url"].endswith(url))
        for target, use, age, question in [
            (code, "child_food_glass", "over_3", "поильник"),
            (code, "unknown", "under_3", "поильник"),
            (code, "child_drinking_cup", "exactly_3", "одному указанию"),
            (code, "child_drinking_cup", "unknown", "полный диапазон"),
            (code, "child_drinking_cup", "adult", "противоречат"),
            ("7013375100", "child_drinking_cup", "over_3", "выбранный код"),
            ("7013379900", "child_drinking_cup", "over_3", "выбранный код"),
            ("7013491000", "child_drinking_cup", "over_3", "выбранный код"),
        ]:
            with self.subTest(target=target, use=use, age=age):
                item = review(target, use, age)
                self.assertEqual(item["source_routes"], [])
                self.assertIn(question, item["questions"][0])

    @patch("app.services.local_pilot_ntm.lookup_tr_ts_acts_by_codes", return_value=[])
    def test_printed_publications_match_type_reader_and_alternative_document(self, lookup):
        def check(code, kind, age):
            block = archive_normative_block(
                code, "Книга для детей", publication_kind=kind, reader_age_years=age,
                permits=[{"type": "ДС", "number": "EXAMPLE-ONLY"}],
            )["normative_block"]
            self.assertEqual(block["assessment"], "INSUFFICIENT_EVIDENCE")
            self.assertEqual((block["required_documents"], block["missing_documents"]), ([], []))
            item = block["product_review"]
            self.assertFalse(item["product_documents"]["registry_checked"])
            self.assertFalse(item["product_documents"]["shipment_verified"])
            self.assertEqual(item["family"], "EAEU_CHILD_PRINTED_PUBLICATION")
            return item

        for code, kind, age in [
            ("4901990000", "child_printed_book", 7),
            ("4903000000", "child_coloring_book", 4),
            ("4903000000", "child_coloring_book", 8),
            ("4903000000", "child_picture_book", 3),
            ("4903000000", "child_picture_book", 0),
        ]:
            with self.subTest(code=code, kind=kind, age=age):
                review = check(code, kind, age)
                self.assertEqual([r["document_type"] for r in review["source_routes"]],
                                 ["Декларация о соответствии", "Сертификат соответствия по выбору заявителя"])
                self.assertIn("поз. 40", review["source_routes"][1]["locator"])
                self.assertIn("3д, 4д или 6д", review["source_routes"][0]["condition"])
                qs = " ".join(review["questions"])
                self.assertEqual("5 мм" in qs, kind == "child_coloring_book" and 3 <= age <= 6)
                self.assertEqual("массу бумаги раскраски" in qs, kind == "child_coloring_book")
                self.assertEqual("для графитного карандаша" in qs, kind == "child_coloring_book")
                self.assertEqual("многокрасочных иллюстрациях" in qs, kind == "child_picture_book")
                self.assertEqual("дистиллированной воде" in qs, age <= 3)

        for code, kind, age, text in [
            ("4901990000", "unknown", 7, "Укажите вид"),
            ("4901990000", "child_printed_book", None, "возрастную группу"),
            ("4901990000", "child_printed_book", 18, "читательскому адресу"),
            ("4903000000", "textbook", 7, "учебные пособия"),
            ("4903000000", "toy_book", 4, "издание с игрушкой"),
            ("4903000000", "child_printed_book", 7, "код расходятся"),
            ("4901990000", "child_picture_book", 7, "код расходятся"),
            ("4901910000", "child_printed_book", 7, "выходит за проверенные"),
        ]:
            with self.subTest(code=code, kind=kind, age=age):
                review = check(code, kind, age)
                self.assertEqual(review["source_routes"], [])
                self.assertIn(text, review["questions"][0])

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
