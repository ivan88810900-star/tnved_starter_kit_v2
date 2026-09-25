"""Fail-closed parsing of legacy ``required_permits`` labels."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.core import NonTariffRule
from app.services.compliance_resolver import (
    _permit_doc_types,
    _requirements_from_non_tariff_rules,
)


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Ветеринарный сертификат", {"Ветконтроль"}),
        ("Фитосанитарный сертификат", {"Фитоконтроль"}),
        ("Сертификат соответствия", {"СС"}),
        ("Сертификат о соответствии требованиям", {"СС"}),
        ("Сертификат на соответствие требованиям", {"СС"}),
        ("СС", {"СС"}),
        ("СС, ветеринарный сертификат", {"СС", "Ветконтроль"}),
    ],
)
def test_permit_parser_separates_conformity_from_control_certificates(
    label: str,
    expected: set[str],
) -> None:
    assert _permit_doc_types(label) == expected


@pytest.mark.parametrize(
    "label",
    [
        "Разрешение Россельхознадзора",
        "Сведения Росстандарта",
        "Сертификат соответствующего образца",
        "Сертификат соответствующих документов",
        "Ответ заявителю",
        "Цвет и свет изделия",
    ],
)
def test_permit_parser_does_not_match_embedded_abbreviations(label: str) -> None:
    assert "СС" not in _permit_doc_types(label)
    assert "Ветконтроль" not in _permit_doc_types(label)


def test_rule_resolution_does_not_add_conformity_certificate_for_vet_certificate() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[NonTariffRule.__table__])
    sm = sessionmaker(bind=engine)
    with sm() as session:
        session.add(
            NonTariffRule(
                name="Мясо",
                hs_prefix="0201",
                required_permits="Ветеринарный сертификат",
                tr_ts="",
                tr_ts_edition="",
                exception_note="",
                priority=5,
                valid_from="",
                valid_to="",
                source_url="https://example.invalid/vet",
                source_revision="test",
            )
        )
        session.commit()

        doc_types = {
            req.doc_type
            for req in _requirements_from_non_tariff_rules("0201100000", session)
        }

    assert doc_types == {"Ветконтроль"}
