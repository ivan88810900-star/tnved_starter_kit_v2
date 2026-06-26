"""Tests for mass regulatory document seed — validates coverage and integrity."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db import SessionLocal


class TestMassRegulatoryDocuments:
    @pytest.fixture(autouse=True)
    def _db(self):
        self.db = SessionLocal()
        yield
        self.db.close()

    def test_total_documents_exceeds_5000(self) -> None:
        count = self.db.execute(text("SELECT COUNT(*) FROM regulatory_documents")).scalar()
        assert count >= 5000, f"Expected >= 5000 documents, got {count}"

    def test_total_hs_mappings_exceeds_5000(self) -> None:
        count = self.db.execute(text("SELECT COUNT(*) FROM regulatory_doc_hs_mapping")).scalar()
        assert count >= 5000, f"Expected >= 5000 HS mappings, got {count}"

    def test_all_major_agencies_present(self) -> None:
        rows = self.db.execute(text(
            "SELECT DISTINCT agency FROM regulatory_documents"
        )).fetchall()
        agencies = {r[0] for r in rows}
        expected = {"FTS", "EEC", "MPT", "RPN", "RSN"}
        missing = expected - agencies
        assert not missing, f"Missing agencies: {missing}"

    def test_fts_has_most_documents(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM regulatory_documents WHERE agency = 'FTS'"
        )).scalar()
        assert count >= 1000, f"FTS should have >= 1000 docs, got {count}"

    def test_eec_has_substantial_coverage(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM regulatory_documents WHERE agency = 'EEC'"
        )).scalar()
        assert count >= 500, f"EEC should have >= 500 docs, got {count}"

    def test_all_97_chapters_have_hs_mappings(self) -> None:
        rows = self.db.execute(text(
            "SELECT DISTINCT SUBSTR(hs_prefix, 1, 2) FROM regulatory_doc_hs_mapping"
        )).fetchall()
        chapters = {r[0] for r in rows}
        for ch_num in range(1, 98):
            ch = f"{ch_num:02d}"
            if ch in ("77",):
                continue
            assert ch in chapters, f"Chapter {ch} has no HS mappings"

    def test_no_documents_with_empty_title(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM regulatory_documents WHERE title IS NULL OR title = ''"
        )).scalar()
        assert count == 0

    def test_all_mappings_have_valid_doc_id(self) -> None:
        orphans = self.db.execute(text("""
            SELECT COUNT(*) FROM regulatory_doc_hs_mapping m
            LEFT JOIN regulatory_documents d ON m.doc_id = d.id
            WHERE d.id IS NULL
        """)).scalar()
        assert orphans == 0, f"Found {orphans} orphaned HS mappings"

    def test_key_commodity_chapters_have_depth(self) -> None:
        critical = {"02": 10, "04": 10, "30": 5, "84": 20, "85": 20, "87": 10}
        for ch, min_count in critical.items():
            count = self.db.execute(text(
                "SELECT COUNT(*) FROM regulatory_doc_hs_mapping WHERE hs_prefix LIKE :pat"
            ), {"pat": f"{ch}%"}).scalar()
            assert count >= min_count, (
                f"Chapter {ch} should have >= {min_count} mappings, got {count}"
            )
