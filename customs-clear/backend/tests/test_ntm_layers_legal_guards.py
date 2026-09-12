from __future__ import annotations

import pytest

from app.services.ntm_layers import get_phyto_requirement, get_vet_requirement


@pytest.mark.parametrize("hs_code", ["0508000000", "2305000000", "5104000000"])
def test_stale_broad_veterinary_prefixes_are_not_mandatory(hs_code: str) -> None:
    assert get_vet_requirement(hs_code) is None


def test_current_veterinary_0309_row_is_present() -> None:
    row = get_vet_requirement("0309900000")
    assert row is not None
    assert row["permit_type"] == "ВС"
    assert "КТС №317" in row["legal_ref"]


@pytest.mark.parametrize("hs_code", ["0710000000", "0711000000", "0811000000", "0812000000", "0814000000"])
def test_nonlisted_or_low_risk_phyto_rows_do_not_require_certificate(hs_code: str) -> None:
    assert get_phyto_requirement(hs_code) is None


def test_roasted_coffee_is_low_risk_and_does_not_require_phyto_certificate() -> None:
    assert get_phyto_requirement("0901210000") is None
    assert get_phyto_requirement("0901220000") is None


@pytest.mark.parametrize("hs_code", ["0901110000", "0901120000", "0712901100"])
def test_exact_high_risk_phyto_rows_require_certificate(hs_code: str) -> None:
    row = get_phyto_requirement(hs_code)
    assert row is not None
    assert row["permit_type"] == "ФСС"
    assert "КТС №318" in row["legal_ref"]
