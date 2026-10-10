"""FSA opendata status must not upgrade an unverified row to VALID."""

from __future__ import annotations

import uuid

import pytest

from app.db import SessionLocal
from app.models.tnved import FsaCertificate
from app.services.normative_store import init_db
from app.services.opendata_registry import (
    _registry_status_to_verify,
    lookup_fsa_certificate,
)
from app.services.permits_service import normalize_number


@pytest.fixture(scope="module", autouse=True)
def _schema() -> None:
    init_db()


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("Действует", "VALID"),
        ("Зарегистрирован", "VALID"),
        ("active", "VALID"),
        ("valid", "VALID"),
        ("Аннулировано", "NOT_FOUND"),
        ("Не действует", "NOT_FOUND"),
        ("revoked", "NOT_FOUND"),
        ("not active", "NOT_FOUND"),
        ("not registered", "NOT_FOUND"),
        ("Не зарегистрирован", "NOT_FOUND"),
        ("Не зарегистрировано", "NOT_FOUND"),
        ("незарегистрирован", "NOT_FOUND"),
        ("Архив", "UNKNOWN"),
        ("Ожидает проверки", "UNKNOWN"),
        ("unknown-record", "UNKNOWN"),
        ("invalid", "UNKNOWN"),
        ("unregistered", "UNKNOWN"),
        ("", "UNKNOWN"),
    ],
)
def test_registry_status_classification_is_fail_closed(status: str, expected: str) -> None:
    assert _registry_status_to_verify(status, "") == expected


def test_expired_row_is_not_valid_even_with_active_status() -> None:
    assert _registry_status_to_verify("Действует", "2001-01-01") == "NOT_FOUND"


def test_lookup_preserves_unknown_status_as_manual_review_evidence() -> None:
    registry_number = f"TEST-FSA-STATUS-{uuid.uuid4().hex[:12]}"
    with SessionLocal() as db:
        db.add(
            FsaCertificate(
                registry_number=registry_number,
                doc_type="ДС",
                status="Ожидает проверки",
                applicant="TEST HOLDER",
                product_name="Тестовый товар",
            )
        )
        db.commit()

    try:
        found = lookup_fsa_certificate(registry_number, "ДС")
        assert found is not None
        assert found["status"] == "UNKNOWN"
        assert found["number"] == normalize_number(registry_number)
        assert found["holder"] == "TEST HOLDER"
        assert found["raw"]["fsa_status"] == "Ожидает проверки"
    finally:
        with SessionLocal() as db:
            db.query(FsaCertificate).filter(
                FsaCertificate.registry_number == registry_number
            ).delete()
            db.commit()
