"""Tests for customs procedures database."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db import SessionLocal


class TestCustomsProcedures:
    @pytest.fixture(autouse=True)
    def _db(self):
        self.db = SessionLocal()
        yield
        self.db.close()

    def test_total_procedures_above_20(self) -> None:
        count = self.db.execute(
            text("SELECT COUNT(*) FROM customs_procedures")
        ).scalar()
        assert count >= 20, f"Expected >= 20 procedures, got {count}"

    def test_im40_exists_and_is_main_import(self) -> None:
        row = self.db.execute(text(
            "SELECT name_ru, duty_applies, vat_applies, direction "
            "FROM customs_procedures WHERE procedure_code = 'ИМ40'"
        )).fetchone()
        assert row is not None, "ИМ40 (release for domestic consumption) must exist"
        assert row[1] == 1, "ИМ40 should have duty_applies=True"
        assert row[2] == 1, "ИМ40 should have vat_applies=True"
        assert row[3] == "import"

    def test_ek10_exists_and_is_export(self) -> None:
        row = self.db.execute(text(
            "SELECT direction, duty_applies, vat_applies "
            "FROM customs_procedures WHERE procedure_code = 'ЭК10'"
        )).fetchone()
        assert row is not None, "ЭК10 (export) must exist"
        assert row[0] == "export"
        assert row[2] == 0, "ЭК10 should have vat_applies=False (0% VAT on export)"

    def test_im53_temporary_import_no_duty(self) -> None:
        row = self.db.execute(text(
            "SELECT duty_applies, vat_applies, time_limit_months "
            "FROM customs_procedures WHERE procedure_code = 'ИМ53'"
        )).fetchone()
        assert row is not None, "ИМ53 (temporary import) must exist"
        assert row[0] == 0, "ИМ53 should be duty-free"
        assert row[1] == 0, "ИМ53 should be VAT-free"
        assert row[2] is not None and row[2] > 0, "ИМ53 should have time limit"

    def test_tt80_transit_no_payments(self) -> None:
        row = self.db.execute(text(
            "SELECT duty_applies, vat_applies, excise_applies, direction "
            "FROM customs_procedures WHERE procedure_code = 'ТТ80'"
        )).fetchone()
        assert row is not None, "ТТ80 (transit) must exist"
        assert row[0] == 0 and row[1] == 0 and row[2] == 0
        assert row[3] == "transit"

    def test_all_directions_present(self) -> None:
        rows = self.db.execute(text(
            "SELECT DISTINCT direction FROM customs_procedures"
        )).fetchall()
        dirs = {r[0] for r in rows}
        expected = {"import", "export", "transit", "special"}
        missing = expected - dirs
        assert not missing, f"Missing directions: {missing}"

    def test_all_procedures_have_legal_ref(self) -> None:
        missing = self.db.execute(text(
            "SELECT COUNT(*) FROM customs_procedures "
            "WHERE legal_ref IS NULL OR legal_ref = ''"
        )).scalar()
        assert missing == 0, f"Found {missing} procedures without legal_ref"

    def test_all_procedures_have_description(self) -> None:
        missing = self.db.execute(text(
            "SELECT COUNT(*) FROM customs_procedures "
            "WHERE description IS NULL OR description = ''"
        )).scalar()
        assert missing == 0, f"Found {missing} procedures without description"

    def test_all_procedures_have_documents_required(self) -> None:
        missing = self.db.execute(text(
            "SELECT COUNT(*) FROM customs_procedures "
            "WHERE documents_required IS NULL OR documents_required = ''"
        )).scalar()
        assert missing == 0, f"Found {missing} procedures without documents_required"

    def test_import_procedures_majority(self) -> None:
        import_count = self.db.execute(text(
            "SELECT COUNT(*) FROM customs_procedures WHERE direction = 'import'"
        )).scalar()
        total = self.db.execute(text(
            "SELECT COUNT(*) FROM customs_procedures"
        )).scalar()
        assert import_count > total / 2, "Import procedures should be majority"

    def test_im51_processing_no_duty(self) -> None:
        row = self.db.execute(text(
            "SELECT duty_applies, time_limit_months "
            "FROM customs_procedures WHERE procedure_code = 'ИМ51'"
        )).fetchone()
        assert row is not None, "ИМ51 (inward processing) must exist"
        assert row[0] == 0, "ИМ51 should be duty-free"
        assert row[1] == 36, "ИМ51 should have 36-month time limit"

    def test_unique_procedure_codes(self) -> None:
        total = self.db.execute(text(
            "SELECT COUNT(*) FROM customs_procedures"
        )).scalar()
        unique = self.db.execute(text(
            "SELECT COUNT(DISTINCT procedure_code) FROM customs_procedures"
        )).scalar()
        assert total == unique, f"Duplicate procedure codes found: {total} vs {unique}"
