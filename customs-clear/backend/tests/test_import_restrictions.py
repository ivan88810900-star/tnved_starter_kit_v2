"""Tests for import restrictions database — Issue #86."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db import SessionLocal
from app.services.normative_store import find_import_restrictions


class TestImportRestrictionsData:
    @pytest.fixture(autouse=True)
    def _db(self):
        self.db = SessionLocal()
        yield
        self.db.close()

    def test_total_entries_above_70(self) -> None:
        total = self.db.execute(text("SELECT COUNT(*) FROM import_restrictions")).scalar()
        assert total >= 70, f"Expected >= 70, got {total}"

    def test_ban_entries(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM import_restrictions WHERE restriction_type = 'ban'"
        )).scalar()
        assert count >= 15

    def test_dual_use_entries(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM import_restrictions WHERE restriction_type = 'dual_use'"
        )).scalar()
        assert count >= 20

    def test_licensing_entries(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM import_restrictions WHERE restriction_type = 'licensing'"
        )).scalar()
        assert count >= 10

    def test_quota_entries(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM import_restrictions WHERE restriction_type = 'quota'"
        )).scalar()
        assert count >= 5

    def test_all_have_legal_ref(self) -> None:
        missing = self.db.execute(text(
            "SELECT COUNT(*) FROM import_restrictions WHERE legal_ref IS NULL OR legal_ref = ''"
        )).scalar()
        assert missing == 0

    def test_all_have_severity(self) -> None:
        invalid = self.db.execute(text(
            "SELECT COUNT(*) FROM import_restrictions WHERE severity NOT IN ('block', 'warning')"
        )).scalar()
        assert invalid == 0


class TestImportRestrictionsLookup:
    def test_cheese_ban_from_eu(self) -> None:
        results = find_import_restrictions("0406000000", country="EU")
        bans = [r for r in results if r["restriction_type"] == "ban"]
        assert len(bans) >= 1
        assert bans[0]["severity"] == "block"

    def test_cheese_no_ban_from_turkey(self) -> None:
        results = find_import_restrictions("0406000000", country="TR")
        bans = [r for r in results if r["restriction_type"] == "ban"]
        assert len(bans) == 0

    def test_nuclear_reactor_dual_use(self) -> None:
        results = find_import_restrictions("8401200000")
        dual = [r for r in results if r["restriction_type"] == "dual_use"]
        assert len(dual) >= 1
        assert dual[0]["severity"] == "block"

    def test_weapons_licensing(self) -> None:
        results = find_import_restrictions("9302000000")
        lic = [r for r in results if r["restriction_type"] == "licensing"]
        assert len(lic) >= 1
        assert lic[0]["severity"] == "block"

    def test_quota_beef(self) -> None:
        results = find_import_restrictions("0201300000")
        quotas = [r for r in results if r["restriction_type"] == "quota"]
        assert len(quotas) >= 1

    def test_crypto_equipment_dual_use(self) -> None:
        results = find_import_restrictions("8517120000")
        dual = [r for r in results if r["restriction_type"] == "dual_use"]
        assert len(dual) >= 1

    def test_no_restrictions_for_safe_goods(self) -> None:
        results = find_import_restrictions("6109100000")
        assert len(results) == 0

    def test_country_filter_blocks_irrelevant(self) -> None:
        all_results = find_import_restrictions("0201000000")
        us_results = find_import_restrictions("0201000000", country="US")
        cn_only = find_import_restrictions("0201000000", country="CN")
        assert len(us_results) >= 1
        us_bans = [r for r in us_results if r["restriction_type"] == "ban"]
        assert len(us_bans) >= 1
