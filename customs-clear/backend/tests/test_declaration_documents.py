"""Tests for declaration documents reference — Issue #87."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db import SessionLocal
from app.services.normative_store import find_declaration_documents


class TestDeclarationDocumentsData:
    @pytest.fixture(autouse=True)
    def _db(self):
        self.db = SessionLocal()
        yield
        self.db.close()

    def test_total_entries_above_50(self) -> None:
        total = self.db.execute(text("SELECT COUNT(*) FROM declaration_documents")).scalar()
        assert total >= 50, f"Expected >= 50, got {total}"

    def test_universal_docs_exist(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM declaration_documents WHERE hs_prefix = ''"
        )).scalar()
        assert count >= 10

    def test_conformity_docs_exist(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM declaration_documents WHERE category = 'conformity'"
        )).scalar()
        assert count >= 20

    def test_all_have_legal_ref(self) -> None:
        missing = self.db.execute(text(
            "SELECT COUNT(*) FROM declaration_documents WHERE legal_ref IS NULL OR legal_ref = ''"
        )).scalar()
        assert missing == 0

    def test_mandatory_docs_exist(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM declaration_documents WHERE is_mandatory = 1"
        )).scalar()
        assert count >= 30


class TestDeclarationDocumentsLookup:
    def test_universal_docs_for_any_code(self) -> None:
        docs = find_declaration_documents("8517120000")
        universal = [d for d in docs if d["hs_prefix"] == ""]
        assert len(universal) >= 10
        dt_found = any(d["doc_type"] == "ДТ" for d in universal)
        assert dt_found, "ДТ (декларация на товары) should be in universal docs"

    def test_electronics_has_conformity(self) -> None:
        docs = find_declaration_documents("8517120000")
        conformity = [d for d in docs if d["category"] == "conformity"]
        assert len(conformity) >= 2

    def test_meat_has_vet_cert(self) -> None:
        docs = find_declaration_documents("0201300000")
        vet = [d for d in docs if d["doc_type"] == "vet_cert"]
        assert len(vet) >= 1

    def test_pharma_has_registration(self) -> None:
        docs = find_declaration_documents("3004900000")
        reg = [d for d in docs if d["doc_type"] == "reg_cert"]
        assert len(reg) >= 1

    def test_vehicle_has_ottc_and_recycling(self) -> None:
        docs = find_declaration_documents("8703220000")
        doc_types = {d["doc_type"] for d in docs}
        assert "OTTC" in doc_types
        assert "recycling_fee" in doc_types

    def test_weapons_has_license(self) -> None:
        docs = find_declaration_documents("9302000000")
        lic = [d for d in docs if d["doc_type"] == "license_weapon"]
        assert len(lic) >= 1

    def test_mandatory_sorted_first(self) -> None:
        docs = find_declaration_documents("8517120000")
        if len(docs) > 1:
            mandatory_indices = [i for i, d in enumerate(docs) if d["is_mandatory"]]
            optional_indices = [i for i, d in enumerate(docs) if not d["is_mandatory"]]
            if mandatory_indices and optional_indices:
                assert max(mandatory_indices) < max(optional_indices) or min(mandatory_indices) < min(optional_indices)

    def test_crypto_notification_for_8517(self) -> None:
        docs = find_declaration_documents("8517120000")
        crypto = [d for d in docs if d["doc_type"] == "notification_crypto"]
        assert len(crypto) >= 1
        assert crypto[0]["condition"] != ""
