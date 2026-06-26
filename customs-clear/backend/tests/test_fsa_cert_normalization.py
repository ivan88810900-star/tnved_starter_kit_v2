"""Нормализация номеров FSA для lookup в opendata (префиксы ЕАЭС/РОСС/ВП)."""

from __future__ import annotations

import unittest
import uuid

from app.db import SessionLocal
from app.models.tnved import FsaCertificate
from app.services.normative_store import init_db
from app.services.opendata_registry import lookup_fsa_certificate
from app.services.permits_service import (
    canonical_cert_number,
    cert_number_search_variants,
    normalize_number,
)


class CertNumberVariantsTests(unittest.TestCase):
    def test_short_dt_form_generates_eaeu_variant(self) -> None:
        short = "RU С-CN.АД50.В.05226/22"
        variants = cert_number_search_variants(short)
        self.assertIn("RUС-CN.АД50.В.05226/22", variants)
        self.assertIn("ЕАЭСRUС-CN.АД50.В.05226/22", variants)

    def test_full_db_form_keeps_core(self) -> None:
        full = "ЕАЭСRU С-CN.АД50.В.04618/22"
        self.assertEqual(canonical_cert_number(full), "RUС-CN.АД50.В.04618/22")
        self.assertIn("ЕАЭСRUС-CN.АД50.В.04618/22", cert_number_search_variants(full))

    def test_ross_prefix(self) -> None:
        full = "РОССRUС-RU.НВ70.В.03706/25"
        self.assertEqual(canonical_cert_number(full), "RUС-RU.НВ70.В.03706/25")
        self.assertIn("РОССRUС-RU.НВ70.В.03706/25", cert_number_search_variants(full))


class FsaLookupNormalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def test_short_number_finds_row_with_eaeu_prefix(self) -> None:
        reg = f"ЕАЭСRUС-CN.ТЕ{uuid.uuid4().hex[:4].upper()}.В.00001/99"
        core = canonical_cert_number(reg)
        with SessionLocal() as db:
            db.add(
                FsaCertificate(
                    registry_number=reg,
                    doc_type="СС",
                    status="Действует",
                    applicant="TEST LOOKUP",
                    product_name="Тест",
                )
            )
            db.commit()

        short = core.replace("RUС-", "RU С-", 1)
        found = lookup_fsa_certificate(short, "СС")
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found["status"], "VALID")
        self.assertEqual(found["number"], normalize_number(reg))
        self.assertEqual(found["source_kind"], "opendata_local")
        self.assertEqual(found["holder"], "TEST LOOKUP")

        with SessionLocal() as db:
            db.query(FsaCertificate).filter(FsaCertificate.registry_number == reg).delete()
            db.commit()


if __name__ == "__main__":
    unittest.main()
