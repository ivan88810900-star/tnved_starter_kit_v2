"""FSA JSON search results must prove identity and active status."""

from __future__ import annotations

import pytest

from app.services.permits_service import _extract_fsa_from_json


SEARCH_NUMBER = "ЕАЭС RU Д-RU.РА01.А.12345/26"


def _row(number: str = SEARCH_NUMBER, status: object = "Действует") -> dict[str, object]:
    return {
        "registryNumber": number,
        "status": status,
        "applicantName": "TEST HOLDER",
        "endDate": "31.12.2099",
        "products": [{"tnvedCode": "8504409500"}],
    }


def test_json_result_requires_exact_certificate_number() -> None:
    result = _extract_fsa_from_json(
        {"content": [_row("ЕАЭС RU Д-RU.РА01.А.99999/26")], "totalElements": 1},
        "ДС",
        SEARCH_NUMBER,
    )

    assert result is not None
    assert result["status"] == "NOT_FOUND"
    assert result["holder"] is None
    assert result["raw"]["identity_match"] is False


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("Действует", "VALID"),
        ({"name": "Действует"}, "VALID"),
        ("Аннулировано", "NOT_FOUND"),
        ({"name": "Приостановлено"}, "NOT_FOUND"),
        ("Ожидает проверки", "UNKNOWN"),
        (None, "UNKNOWN"),
    ],
)
def test_json_exact_result_uses_fail_closed_registry_status(
    status: object, expected: str
) -> None:
    result = _extract_fsa_from_json(
        {"content": [_row(status=status)], "totalElements": 1},
        "ДС",
        SEARCH_NUMBER,
    )

    assert result is not None
    assert result["status"] == expected
    assert result["holder"] == "TEST HOLDER"
    assert result["raw"]["identity_match"] is True
    assert result["raw"]["registry_status"] == (
        status.get("name") if isinstance(status, dict) else status
    )


def test_json_positive_count_without_rows_is_unknown() -> None:
    result = _extract_fsa_from_json(
        {"content": [], "totalElements": 3},
        "СС",
        SEARCH_NUMBER,
    )

    assert result is not None
    assert result["status"] == "UNKNOWN"
    assert result["raw"]["count"] == 3
    assert result["raw"]["identity_match"] is None


def test_json_rows_without_recognizable_number_are_unknown() -> None:
    result = _extract_fsa_from_json(
        {"content": [{"status": "Действует", "applicantName": "UNVERIFIED"}]},
        "СС",
        SEARCH_NUMBER,
    )

    assert result is not None
    assert result["status"] == "UNKNOWN"
    assert result["holder"] is None
    assert result["raw"]["identity_match"] is None


def test_json_exact_active_but_expired_result_is_not_found() -> None:
    row = _row()
    row["endDate"] = "01.01.2001"
    result = _extract_fsa_from_json(
        {"content": [row], "totalElements": 1},
        "ДС",
        SEARCH_NUMBER,
    )

    assert result is not None
    assert result["status"] == "NOT_FOUND"


@pytest.mark.parametrize(
    "rows",
    [
        [_row(status="Действует"), _row(status="Аннулировано")],
        [_row(status="Аннулировано"), _row(status="Действует")],
    ],
)
def test_json_duplicate_exact_records_fail_closed_regardless_of_order(
    rows: list[dict[str, object]],
) -> None:
    result = _extract_fsa_from_json(
        {"content": rows, "totalElements": 2},
        "ДС",
        SEARCH_NUMBER,
    )

    assert result is not None
    assert result["status"] == "NOT_FOUND"
    assert result["raw"]["identity_match"] is True
    assert result["raw"]["matched_count"] == 2


def test_json_duplicate_active_and_unknown_records_require_manual_review() -> None:
    result = _extract_fsa_from_json(
        {
            "content": [_row(status="Действует"), _row(status="Ожидает проверки")],
            "totalElements": 2,
        },
        "ДС",
        SEARCH_NUMBER,
    )

    assert result is not None
    assert result["status"] == "UNKNOWN"


def test_json_mixed_numbered_and_unnumbered_rows_cannot_prove_not_found() -> None:
    result = _extract_fsa_from_json(
        {
            "content": [
                _row("ЕАЭС RU Д-RU.РА01.А.99999/26"),
                {"status": "Действует", "applicantName": "UNVERIFIED"},
            ],
            "totalElements": 2,
        },
        "ДС",
        SEARCH_NUMBER,
    )

    assert result is not None
    assert result["status"] == "UNKNOWN"
    assert result["raw"]["identity_match"] is None


def test_json_generic_numeric_number_is_not_a_registry_identity() -> None:
    result = _extract_fsa_from_json(
        {"content": [{"number": 12345, "status": "Действует"}], "totalElements": 1},
        "СС",
        "12345",
    )

    assert result is not None
    assert result["status"] == "UNKNOWN"
    assert result["raw"]["identity_match"] is None


@pytest.mark.parametrize("internal_id", ["row-12345", "internal/id-987"])
def test_json_generic_string_number_is_not_a_registry_identity(
    internal_id: str,
) -> None:
    matching = _extract_fsa_from_json(
        {"content": [{"number": internal_id, "status": "Действует"}]},
        "СС",
        internal_id,
    )
    mismatching = _extract_fsa_from_json(
        {"content": [{"number": internal_id, "status": "Действует"}]},
        "СС",
        SEARCH_NUMBER,
    )

    assert matching is not None
    assert matching["status"] == "UNKNOWN"
    assert matching["raw"]["identity_match"] is None
    assert mismatching is not None
    assert mismatching["status"] == "UNKNOWN"
    assert mismatching["raw"]["identity_match"] is None
