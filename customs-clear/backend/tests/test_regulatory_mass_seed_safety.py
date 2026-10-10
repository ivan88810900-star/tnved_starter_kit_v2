"""Synthetic mass seed must never become regulatory product evidence."""

from __future__ import annotations

from app.db import SessionLocal
from app.models.regulatory import (
    REGULATORY_QUALITY_SYNTHETIC_SEED,
    REGULATORY_STATUS_REFERENCE_ONLY,
    RegulatoryDocHsMapping,
    RegulatoryDocument,
)
from app.services.regulatory_layer import get_regulatory_documents_for_hs
from app.services.regulatory_source_completeness import _count_db_probe
from scripts import seed_regulatory_mass


_DOC = {
    "agency": "FTS",
    "doc_type": "letter",
    "num": "SYNTHETIC-SAFETY-8517",
    "date": "2024-01-01",
    "title": "Синтетический шаблон для проверки границы источников",
    "hs": ["8517"],
    "confidence": 1.0,
    "relevance": "direct",
}


def test_mass_seed_is_reference_only_and_repairs_legacy_labels(monkeypatch) -> None:
    source_url = seed_regulatory_mass._url(_DOC["agency"], _DOC["num"])
    doc_id = seed_regulatory_mass._doc_id(source_url)
    monkeypatch.setattr(seed_regulatory_mass, "_generate_all_docs", lambda: [_DOC])

    with SessionLocal() as db:
        db.query(RegulatoryDocHsMapping).filter(
            RegulatoryDocHsMapping.doc_id == doc_id
        ).delete(synchronize_session=False)
        db.query(RegulatoryDocument).filter(RegulatoryDocument.id == doc_id).delete(
            synchronize_session=False
        )
        db.commit()

    admitted_before = _count_db_probe("regulatory_documents")
    try:
        seed_regulatory_mass.run()

        with SessionLocal() as db:
            doc = db.get(RegulatoryDocument, doc_id)
            assert doc is not None
            assert doc.status == REGULATORY_STATUS_REFERENCE_ONLY
            assert doc.quality == REGULATORY_QUALITY_SYNTHETIC_SEED
            mapping = db.query(RegulatoryDocHsMapping).filter_by(doc_id=doc_id).one()
            assert mapping.source == "synthetic_seed"
            assert mapping.relevance == "reference"
            assert mapping.confidence == 0.0
            assert mapping.approved is False

            # Reproduce the unsafe labels from the historical seed, then prove
            # an idempotent rerun repairs both the document and its mapping.
            doc.status = "active"
            doc.quality = "verified"
            mapping.source = "seed"
            mapping.relevance = "direct"
            mapping.confidence = 1.0
            db.commit()

        seed_regulatory_mass.run()

        with SessionLocal() as db:
            repaired = db.get(RegulatoryDocument, doc_id)
            assert repaired is not None
            assert repaired.status == REGULATORY_STATUS_REFERENCE_ONLY
            assert repaired.quality == REGULATORY_QUALITY_SYNTHETIC_SEED
            repaired_mapping = db.query(RegulatoryDocHsMapping).filter_by(doc_id=doc_id).one()
            assert repaired_mapping.source == "synthetic_seed"
            assert repaired_mapping.confidence == 0.0

        assert get_regulatory_documents_for_hs("8517620000") == []
        assert _count_db_probe("regulatory_documents") == admitted_before
    finally:
        with SessionLocal() as db:
            db.query(RegulatoryDocHsMapping).filter(
                RegulatoryDocHsMapping.doc_id == doc_id
            ).delete(synchronize_session=False)
            db.query(RegulatoryDocument).filter(RegulatoryDocument.id == doc_id).delete(
                synchronize_session=False
            )
            db.commit()


def test_pravo_probe_uses_product_evidence_admission() -> None:
    docs = (
        ("active-pravo-source-probe", "active", "normal"),
        (
            "synthetic-pravo-source-probe",
            REGULATORY_STATUS_REFERENCE_ONLY,
            REGULATORY_QUALITY_SYNTHETIC_SEED,
        ),
        ("noise-pravo-source-probe", "active", "noise"),
        ("reference-pravo-source-probe", REGULATORY_STATUS_REFERENCE_ONLY, "normal"),
    )
    doc_ids = [doc_id for doc_id, _, _ in docs]
    with SessionLocal() as db:
        db.query(RegulatoryDocument).filter(RegulatoryDocument.id.in_(doc_ids)).delete(
            synchronize_session=False
        )
        db.commit()

    admitted_before = _count_db_probe("regulatory_documents_pravo")
    with SessionLocal() as db:
        db.add_all(
            [
                RegulatoryDocument(
                    id=doc_id,
                    agency="PRAVO_GOV",
                    doc_type="law",
                    title=f"Проверка admission официальной публикации: {doc_id}",
                    source_url=f"https://synthetic.invalid/{doc_id}",
                    status=status,
                    quality=quality,
                )
                for doc_id, status, quality in docs
            ]
        )
        db.commit()

    try:
        assert _count_db_probe("regulatory_documents_pravo") == admitted_before + 1
    finally:
        with SessionLocal() as db:
            db.query(RegulatoryDocument).filter(RegulatoryDocument.id.in_(doc_ids)).delete(
                synchronize_session=False
            )
            db.commit()
