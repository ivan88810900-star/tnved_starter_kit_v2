"""Tests for ROP chapter coverage audit (#144)."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db import Base
    from app.models.rop import RopGoodsRate
    from app.models.tnved import Chapter
    from app.services.rop_coverage_audit import build_rop_chapter_coverage, coverage_summary

    _OK = True
except ImportError:
    _OK = False


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = BACKEND_ROOT / "customs.db"
PINNED_CATALOGUE = BACKEND_ROOT / "customs.db.backup_before_pdf_import"
ROP_RATES = BACKEND_ROOT / "data/rop_rates_2024.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _protected_fingerprints() -> dict[Path, str | None]:
    paths = {
        ROP_RATES,
        *(
            candidate
            for path in (DEFAULT_DATABASE, PINNED_CATALOGUE)
            for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm"))
        ),
    }
    return {
        path: _sha256(path) if path.is_file() else None
        for path in paths
    }


def _load_2026_goods_rows() -> list[dict]:
    document = json.loads(ROP_RATES.read_text(encoding="utf-8"))
    legal_ref = str(document.get("legal_ref") or "")
    rows: list[dict] = []
    for item in document.get("goods") or []:
        rates = (item.get("rates_by_year") or {}).get("2026")
        assert rates is not None
        rows.append(
            {
                "category_code": item["category_code"],
                "pp2414_group": int(item["pp2414_group"]),
                "category_name": item["category_name"],
                "hs_prefixes_json": json.dumps(
                    item.get("hs_prefixes") or [],
                    ensure_ascii=False,
                ),
                "base_rate_per_ton": float(rates["base_rate_per_ton"]),
                "ke_coefficient": float(rates["ke_coefficient"]),
                "rate_per_ton": float(rates["rate_per_ton"]),
                "recycling_norm": float(rates["recycling_norm"]),
                "calendar_year": 2026,
                "legal_ref": legal_ref,
                "notes": str(item.get("notes") or ""),
                "needs_verification": bool(item.get("needs_verification")),
                "verification_note": str(item.get("verification_note") or ""),
            }
        )
    assert len(rows) == 16
    return rows


@unittest.skipIf(not _OK, "deps missing")
class RopCoverageAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._protected_hashes = _protected_fingerprints()
        cls._engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(
            bind=cls._engine,
            tables=[RopGoodsRate.__table__, Chapter.__table__],
        )
        cls._session_factory = sessionmaker(
            bind=cls._engine,
            autocommit=False,
            autoflush=False,
        )
        with cls._session_factory() as database:
            database.bulk_insert_mappings(RopGoodsRate, _load_2026_goods_rows())
            database.commit()
        cls.db = cls._session_factory()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.db.close()
        cls._engine.dispose()
        assert _protected_fingerprints() == cls._protected_hashes

    def test_matrix_has_97_chapters(self) -> None:
        matrix = build_rop_chapter_coverage(self.db, calendar_year=2026)
        self.assertGreaterEqual(len(matrix), 97)

    def test_chapter_61_subject(self) -> None:
        matrix = build_rop_chapter_coverage(self.db, calendar_year=2026)
        ch61 = next(r for r in matrix if r["chapter"] == "61")
        self.assertIn(ch61["subject_to_rop"], ("yes", "partial"))
        self.assertTrue(ch61["matched_groups"])

    def test_chapter_26_not_subject(self) -> None:
        matrix = build_rop_chapter_coverage(self.db, calendar_year=2026)
        ch26 = next(r for r in matrix if r["chapter"] == "26")
        self.assertTrue(ch26["not_subject"])

    def test_summary_counts(self) -> None:
        matrix = build_rop_chapter_coverage(self.db, calendar_year=2026)
        s = coverage_summary(matrix)
        self.assertEqual(s["total_chapters"], len(matrix))


if __name__ == "__main__":
    unittest.main()
