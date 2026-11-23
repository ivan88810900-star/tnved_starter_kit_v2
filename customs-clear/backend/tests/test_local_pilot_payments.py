"""The pilot classifies a product from the accepted tree, independently of rates."""
import unittest
from unittest.mock import Mock

from fastapi import HTTPException

from app.local_pilot_payments import catalog_code_issue
from app.services.tnved_recovery_store import TnvedRecoveryStore


class CatalogProductSelectionTests(unittest.TestCase):
    def setUp(self):
        self.store = Mock(spec=TnvedRecoveryStore)
        self.store.lookup.return_value = {"kind": "coded", "code": "3304100000"}
        self.store.has_children.return_value = False

    def test_real_product_ending_in_four_zeroes(self):
        self.assertIsNone(catalog_code_issue(self.store, "3304100000"))

    def test_ten_digits_with_children_still_requires_selection(self):
        self.store.has_children.return_value = True
        self.assertEqual(catalog_code_issue(self.store, "3304100000")["status"], "CLARIFICATION_NEEDED")

    def test_heading_alias_does_not_silently_select_the_resolved_code(self):
        self.assertEqual(catalog_code_issue(self.store, "3304")["status"], "CLARIFICATION_NEEDED")

    def test_reserved_and_unknown_items_cannot_be_calculated(self):
        with self.assertRaises(HTTPException) as marker:
            catalog_code_issue(self.store, "[0503]")
        self.assertEqual(marker.exception.status_code, 422)
        self.store.lookup.return_value = None
        with self.assertRaises(HTTPException) as missing:
            catalog_code_issue(self.store, "9900999987")
        self.assertEqual(missing.exception.status_code, 404)
